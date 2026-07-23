"""HTTP server: the game, reachable by a link.

Standard library only, like everything else here -- `ThreadingHTTPServer` is
ample for a family. Each request is answered on its own thread, so one
player's turn (which may be waiting on a model for a couple of seconds) never
blocks another's.

The API is deliberately small:

    GET  /                  the page
    POST /api/login         swap the shared word for a token, if a gate is set
    GET  /api/state         resume: scrollback and where you stand
    POST /api/command       take a turn

Everything the game prints comes back as HTML fragments, escaped so the browser
renders text as text.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import ui
from .sessions import SessionStore, normalise_name

PAGE = Path(__file__).resolve().parent / "static" / "index.html"

# The game no longer emits colour (the cyan marking of additions was removed),
# so any stray ANSI escape is simply stripped before the line is escaped.
_ANSI = re.compile(r"\033\[([0-9;]*)m")


def to_html(line: str) -> str:
    """One printed line as safe HTML."""
    return html.escape(_ANSI.sub("", line))


def render(messages, level: str) -> list[str]:
    """A batch of game messages as HTML lines, one per printed line."""
    lines: list[str] = []
    for shown in ui.present(messages, level):
        for row in str(shown).split("\n"):
            lines.append(to_html(row))
    return lines


class Gate:
    """An optional shared word, and the tokens it buys.

    A family server on the open internet is a public server. Without this,
    anyone who finds the URL plays on your model credit -- and a crawler that
    finds it plays continuously. Set HOBBIT_PASSWORD to close it.

    Tokens are signed rather than stored, so a restart doesn't log anyone out
    provided HOBBIT_SECRET is set (and if it isn't, a restart logging everyone
    out is the safe failure).
    """

    def __init__(self, password: str | None, secret: str | None = None,
                 days: int = 30):
        self.password = password or None
        self.secret = (secret or os.environ.get("HOBBIT_SECRET")
                       or secrets.token_hex(32)).encode()
        self.ttl = days * 86400

    @property
    def open(self) -> bool:
        return self.password is None

    def issue(self, offered: str) -> str | None:
        if self.open:
            return "open"
        if not hmac.compare_digest(offered or "", self.password):
            return None
        expires = str(int(time.time()) + self.ttl)
        sig = hmac.new(self.secret, expires.encode(), hashlib.sha256).hexdigest()
        return f"{expires}.{sig}"

    def allows(self, token: str | None) -> bool:
        if self.open:
            return True
        if not token or "." not in token:
            return False
        expires, _, sig = token.partition(".")
        expected = hmac.new(self.secret, expires.encode(),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        try:
            return int(expires) > time.time()
        except ValueError:
            return False


class Handler(BaseHTTPRequestHandler):
    server_version = "Hobbit"
    store: SessionStore
    gate: Gate

    # -- plumbing -------------------------------------------------------

    def log_message(self, fmt, *args):
        pass  # the default logs every request to stderr; nobody wants that

    def _send(self, code: int, body: bytes, ctype: str,
              cookie: str | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # The page is one file and talks only to itself.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict, cookie: str | None = None) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json", cookie)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 64_000:
                return {}
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def _token(self) -> str | None:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "hobbit":
                return value
        return None

    def _player(self, data: dict) -> str | None:
        return normalise_name(str(data.get("name", "")))

    # -- routes ---------------------------------------------------------

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                page = PAGE.read_bytes()
            except OSError:
                page = b"<h1>The page is missing.</h1>"
            return self._send(200, page, "text/html; charset=utf-8")
        if path == "/api/state":
            if not self.gate.allows(self._token()):
                return self._json(401, {"error": "locked"})
            query = parse_qs(urlparse(self.path).query)
            name = normalise_name((query.get("name") or [""])[0])
            if not name:
                return self._json(400, {"error": "bad name"})
            # Don't create the game here: a brand-new player is offered the
            # choice of mode first, and get() would create it in the default
            # mode before they could choose. So report existence, and only
            # touch the session when there is already one.
            if not self.store.has(name):
                return self._json(200, {"name": name, "new": True, "lines": []})
            session = self.store.get(name)
            return self._json(200, {
                "name": name,
                "new": False,
                "lines": session.transcript,
                "over": session.game.won or session.game.lost,
            })
        return self._json(404, {"error": "no such thing"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        data = self._body()

        if path == "/api/login":
            token = self.gate.issue(str(data.get("password", "")))
            if token is None:
                # Not a timing oracle worth worrying about, but the delay also
                # takes the shine off guessing at speed.
                time.sleep(0.5)
                return self._json(401, {"error": "that is not the word"})
            cookie = (f"hobbit={token}; Path=/; HttpOnly; SameSite=Strict; "
                      f"Max-Age={self.gate.ttl}")
            return self._json(200, {"ok": True}, cookie)

        if not self.gate.allows(self._token()):
            return self._json(401, {"error": "locked"})

        if path == "/api/command":
            name = self._player(data)
            if not name:
                return self._json(400, {"error":
                                        "A name, please -- letters and spaces."})
            text = str(data.get("text", ""))[:200]
            word = text.strip().lower()
            # The chosen mode only matters when this player's game is created
            # here for the first time; get() ignores it for a game that already
            # exists, so a returning player is unaffected.
            authentic = True if data.get("mode") == "purist" else None
            session = self.store.get(name, authentic=authentic)
            game = session.game

            if word in ("restart", "start again", "begin again", "new game"):
                session = self.store.restart(name)
                game = session.game
                lines = [to_html("You set out again from the beginning."),
                         ""]
                lines += render(game.describe_location(game.player),
                                game.annotation_level)
            elif word in ("quit", "exit", "q", "bye"):
                # There is no process to quit in a browser, and "Farewell!"
                # left the player stranded -- one of them typed 'exit' hoping
                # to start over. Say what actually works here.
                lines = [f'<span class="echo">&gt; {html.escape(text)}</span>',
                         to_html("There's no need to leave -- close the tab "
                                 "whenever you like and your journey waits for "
                                 "you. To begin again from Bag End, type "
                                 "'restart'.")]
            elif word in ("save", "load", "restore"):
                # These belong to the terminal game, which has a save file and a
                # host loop to load it. Here every turn is written to the
                # player's own save automatically -- do_load would just set a
                # flag nothing reads, leaving the player staring at a blank
                # reply (as one did after 'restart' + 'load'). Say what's true.
                lines = [f'<span class="echo">&gt; {html.escape(text)}</span>',
                         to_html("Your journey saves itself after every turn -- "
                                 "there's nothing to save or load by hand. Close "
                                 "the tab whenever you like and you'll pick up "
                                 "right where you left off. To start over from "
                                 "Bag End, type 'restart'.")]
            elif game.won or game.lost:
                lines = [to_html("The journey is over. Type 'restart' to "
                                 "begin again.")]
            else:
                lines = [f'<span class="echo">&gt; {html.escape(text)}</span>']
                lines += render(game.process_player_input(text),
                                game.annotation_level)
                if game.won:
                    lines += render(game.ending_lines(), game.annotation_level)
                    lines.append(to_html("*** THE END ***"))
                elif game.lost:
                    lines.append(to_html(game.lose_reason or "You have died."))
                    lines.append(to_html("*** GAME OVER ***"))
            self.store.record(session, lines)
            self.store.save(name)      # every turn: a closed tab loses nothing
            return self._json(200, {
                "lines": lines,
                "over": game.won or game.lost,
            })

        return self._json(404, {"error": "no such thing"})


def serve(host: str = "0.0.0.0", port: int = 8080, saves: Path | None = None,
          llm=None, llm_fast=None, authentic: bool = False,
          password: str | None = None) -> ThreadingHTTPServer:
    """Build the server. Caller runs serve_forever()."""
    store = SessionStore(saves or Path("saves"), llm=llm, llm_fast=llm_fast,
                         authentic=authentic)
    gate = Gate(password if password is not None
                else os.environ.get("HOBBIT_PASSWORD"))

    handler = type("BoundHandler", (Handler,), {"store": store, "gate": gate})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    httpd.store = store
    httpd.gate = gate
    return httpd
