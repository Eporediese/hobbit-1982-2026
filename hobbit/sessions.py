"""One game per player, held in memory and persisted to disk.

Each player gets their own Middle-earth and their own company of dwarves --
Bilbo is one hobbit, and the game was designed around that. A session is
therefore just a `Game` plus who it belongs to and when it was last touched.

Persistence is per-player rather than one savegame file: the terminal game
keeps a single `savegame.json` beside the code, which is exactly wrong for a
server where four relatives are mid-journey at once. Sessions are named files
in one directory, so a save can be inspected, backed up, or deleted by hand.

Structured so a shared world can be added later without a rewrite: nothing
outside this module knows how a game is stored or found, and `SessionStore`
is the only thing that maps a player to a `Game`. A future shared world is a
second store with the same three methods, not a change to the server.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .game import Game
from .save import load_game, save_game

# What a name may NOT contain. The real constraint is that the name becomes a
# filename, so this blocks the path-dangerous characters and the dot (which
# would collide with the .json / .transcript.json suffixes), rather than
# restricting to ASCII -- a family has O'Briens, Josés and Renées in it, and
# an accented letter is a perfectly good filename.
_NAME_BAD = re.compile(r"[^\w '’.-]|[.]", re.UNICODE)


def normalise_name(raw: str) -> str | None:
    """Fold a typed name to its canonical form, or None if unusable.

    'Duncan', 'duncan' and '  Duncan  ' are the same player -- a relative who
    capitalises differently on their phone should not find a new empty game
    waiting for them. Real names are welcome: apostrophes and accented letters
    pass; only characters that would be unsafe or ambiguous in a filename are
    turned away.
    """
    # Compose accents to one canonical form, so "José" typed two different ways
    # (é as one code point or e + combining accent) is one player, not two.
    name = unicodedata.normalize("NFC", " ".join((raw or "").split()))
    if not name or len(name) > 32:
        return None
    if _NAME_BAD.search(name):
        return None
    return name.lower()


@dataclass
class Session:
    name: str
    game: Game
    last_seen: float = field(default_factory=time.monotonic)
    # Everything the player has been shown, so a reconnecting browser can be
    # handed back its scrollback instead of an empty screen.
    transcript: list[str] = field(default_factory=list)

    def touch(self) -> None:
        self.last_seen = time.monotonic()


class SessionStore:
    """The only thing that maps a player to a game.

    Thread-safe: the stdlib HTTP server handles requests on separate threads,
    and two tabs open on the same game would otherwise interleave turns
    half-applied. One lock around the whole store is ample at family scale and
    leaves no room for a subtle interleaving bug.
    """

    def __init__(self, directory: Path, llm=None, llm_fast=None,
                 authentic: bool = False, max_transcript: int = 400):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.llm = llm
        self.llm_fast = llm_fast
        self.authentic = authentic
        self.max_transcript = max_transcript
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    # -- storage --------------------------------------------------------

    def path_for(self, name: str) -> Path:
        return self.directory / f"{name}.json"

    def _transcript_path(self, name: str) -> Path:
        # A sibling of the game save. Kept separate on purpose: the game save
        # is engine state that the terminal build shares, while the transcript
        # is the web layer's scrollback (rendered HTML). Loading one must not
        # depend on the other, and a corrupt transcript must never endanger a
        # good game.
        return self.directory / f"{name}.transcript.json"

    def _load_transcript(self, name: str) -> list[str]:
        path = self._transcript_path(name)
        if not path.exists():
            return []
        try:
            lines = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []               # cosmetic; a bad file just means no history
        if not isinstance(lines, list):
            return []
        return [str(x) for x in lines][-self.max_transcript:]

    def _new_game(self, authentic: bool | None = None) -> Game:
        return Game(authentic=self.authentic if authentic is None else authentic,
                    llm=self.llm, llm_fast=self.llm_fast)

    def has(self, name: str) -> bool:
        """Is there already a game for this player, in memory or on disk?

        Lets a caller offer a first-time choice (which mode to play) to a new
        player without accidentally creating the game first -- get() would
        create it eagerly in the default mode, and the mode can't change once
        the journey has begun."""
        with self._lock:
            return name in self._sessions or self.path_for(name).exists()

    def _load_from_disk(self, name: str) -> Game | None:
        path = self.path_for(name)
        if not path.exists():
            return None
        game = self._new_game()
        try:
            load_game(game, path)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            # A truncated or outdated save must not take the server down, and
            # must not silently erase the player's journey either: move it
            # aside so it can be looked at, and start them fresh.
            path.replace(path.with_suffix(".corrupt.json"))
            return None
        # Fold in anything the save predates -- the same reconciliation the
        # terminal game does on load.
        game.reconcile_after_load()
        return game

    # -- public API -----------------------------------------------------

    def get(self, name: str, authentic: bool | None = None) -> Session:
        """The player's session: resumed from memory, then disk, else new.

        `authentic` only bites when a game is created here for the first time
        -- once a journey exists, its mode is fixed and the argument is
        ignored, so passing it on a returning player is harmless."""
        with self._lock:
            session = self._sessions.get(name)
            if session is not None:
                session.touch()
                return session
            game = self._load_from_disk(name)
            # Only restore scrollback for a game that actually loaded -- a
            # fresh start with a leftover transcript file would show history
            # from a game that no longer exists.
            transcript = self._load_transcript(name) if game is not None else []
            session = Session(name=name,
                              game=game or self._new_game(authentic),
                              transcript=transcript)
            self._sessions[name] = session
            return session

    def save(self, name: str) -> None:
        with self._lock:
            session = self._sessions.get(name)
            if session is None:
                return
            save_game(session.game, self.path_for(name))
            # And the scrollback, so a restart (every deploy is one) hands the
            # player back their history, not just their position.
            self._transcript_path(name).write_text(
                json.dumps(session.transcript), encoding="utf-8")

    # -- manual checkpoints (a bookmark you can return to) --------------
    #
    # Separate from the per-turn save above, which faithfully records wherever
    # you are -- including your death. A checkpoint is a point the player chose,
    # so `load` can bring them back to it after a bad end. It deliberately
    # survives `restart`, so even a fresh start can be undone.

    def _checkpoint_path(self, name: str) -> Path:
        return self.directory / f"{name}.checkpoint.json"

    def save_checkpoint(self, name: str) -> bool:
        with self._lock:
            session = self._sessions.get(name)
            if session is None:
                return False
            save_game(session.game, self._checkpoint_path(name))
            return True

    def load_checkpoint(self, name: str) -> bool:
        """Restore the player's checkpoint into their live game, in place.
        False if there is nothing saved, or the file is unreadable."""
        with self._lock:
            session = self._sessions.get(name)
            path = self._checkpoint_path(name)
            if session is None or not path.exists():
                return False
            try:
                load_game(session.game, path)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                return False
            session.game.reconcile_after_load()
            return True

    def restart(self, name: str) -> Session:
        """Begin the journey again, keeping the old save as a record.

        Never deletes: a relative who types 'restart' by accident on turn 400
        should be able to get their game back, and the file is a few dozen
        kilobytes.
        """
        with self._lock:
            stamp = int(time.time())
            path = self.path_for(name)
            if path.exists():
                path.replace(path.with_name(f"{name}.{stamp}.bak"))
            # The old scrollback goes with the old save, or a restarted game
            # would resume showing the previous journey's history.
            tpath = self._transcript_path(name)
            if tpath.exists():
                tpath.replace(tpath.with_name(f"{name}.{stamp}.transcript.bak"))
            session = Session(name=name, game=self._new_game())
            self._sessions[name] = session
            return session

    def record(self, session: Session, lines: list[str]) -> None:
        """Append to the scrollback, bounded so a long journey can't grow
        without limit in memory."""
        with self._lock:
            session.transcript.extend(lines)
            if len(session.transcript) > self.max_transcript:
                del session.transcript[:-self.max_transcript]

    def evict_idle(self, older_than: float = 3600.0) -> int:
        """Drop sessions nobody has touched lately, saving them first.

        A family server holds a handful of games, but a process that never
        forgets anything is a leak waiting for a long weekend.
        """
        with self._lock:
            stale = [n for n, s in self._sessions.items()
                     if time.monotonic() - s.last_seen > older_than]
            for name in stale:
                self.save(name)
                del self._sessions[name]
            return len(stale)

    def save_all(self) -> None:
        """Persist every live session -- called on shutdown, so a deploy or a
        restart doesn't cost anyone their journey."""
        with self._lock:
            for name in list(self._sessions):
                self.save(name)

    def known_players(self) -> list[str]:
        """Everyone with a game on disk or in memory, for an admin glance."""
        with self._lock:
            on_disk = {p.stem for p in self.directory.glob("*.json")
                       if not p.name.endswith((".corrupt.json", ".bak",
                                               ".transcript.json",
                                               ".checkpoint.json"))}
            return sorted(on_disk | set(self._sessions))
