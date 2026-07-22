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
from dataclasses import dataclass, field
from pathlib import Path

from .game import Game
from .save import load_game, save_game

# A player name has to be safe as a filename and readable in a URL. Family
# members type these, so keep it forgiving but bounded.
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,31}$")


def normalise_name(raw: str) -> str | None:
    """Fold a typed name to its canonical form, or None if unusable.

    'Duncan', 'duncan' and '  Duncan  ' are the same player -- a relative
    who capitalises differently on their phone should not find a new empty
    game waiting for them.
    """
    name = " ".join((raw or "").split())
    if not _NAME_OK.match(name):
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

    def _new_game(self) -> Game:
        return Game(authentic=self.authentic, llm=self.llm,
                    llm_fast=self.llm_fast)

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

    def get(self, name: str) -> Session:
        """The player's session: resumed from memory, then disk, else new."""
        with self._lock:
            session = self._sessions.get(name)
            if session is not None:
                session.touch()
                return session
            game = self._load_from_disk(name) or self._new_game()
            session = Session(name=name, game=game)
            self._sessions[name] = session
            return session

    def save(self, name: str) -> None:
        with self._lock:
            session = self._sessions.get(name)
            if session is not None:
                save_game(session.game, self.path_for(name))

    def restart(self, name: str) -> Session:
        """Begin the journey again, keeping the old save as a record.

        Never deletes: a relative who types 'restart' by accident on turn 400
        should be able to get their game back, and the file is a few dozen
        kilobytes.
        """
        with self._lock:
            path = self.path_for(name)
            if path.exists():
                path.replace(path.with_name(f"{name}.{int(time.time())}.bak"))
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
                       if not p.name.endswith((".corrupt.json", ".bak"))}
            return sorted(on_disk | set(self._sessions))
