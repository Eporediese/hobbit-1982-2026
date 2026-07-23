"""The HTTP layer: no game logic here, only the plumbing around it -- the
gate, the ANSI-to-HTML translation, and that concurrent players don't collide.
"""
import json
import threading
import urllib.request
import urllib.error

import pytest

from hobbit.web import Gate, to_html, render, serve


# -- ANSI -> HTML ----------------------------------------------------------

def test_a_plain_line_is_escaped_not_marked_up():
    assert to_html("You go north.") == "You go north."
    assert to_html("<not a tag>") == "&lt;not a tag&gt;"


def test_any_stray_colour_escape_is_stripped_not_rendered():
    """The game no longer emits colour, and any leftover ANSI escape must be
    removed rather than shown or turned into a span."""
    assert to_html("\033[96mold map\033[0m") == "old map"
    assert to_html("\033[96m== Bag End ==") == "== Bag End =="


def test_render_splits_multiline_blocks_into_rows():
    # A room block is one message with newlines in it (title, prose, exits).
    # present() capitalises the opening letter, so "one" comes back "One".
    out = render(["one line\ntwo line\nthree line"], "standard")
    assert out == ["One line", "two line", "three line"]


# -- the gate --------------------------------------------------------------

def test_an_open_gate_lets_everyone_in():
    gate = Gate(password=None)
    assert gate.open
    assert gate.allows(None)


def test_a_closed_gate_needs_the_word():
    gate = Gate(password="mellon", secret="s")
    assert not gate.open
    assert gate.issue("speak friend") is None
    token = gate.issue("mellon")
    assert token and gate.allows(token)


def test_a_forged_token_is_refused():
    gate = Gate(password="mellon", secret="s")
    assert not gate.allows("9999999999.deadbeef")
    assert not gate.allows("not-even-close")
    assert not gate.allows(None)


def test_a_token_from_a_different_secret_is_refused():
    """Two servers with different secrets must not honour each other's
    tokens."""
    real = Gate(password="mellon", secret="one")
    token = real.issue("mellon")
    impostor = Gate(password="mellon", secret="two")
    assert not impostor.allows(token)


def test_an_expired_token_is_refused():
    gate = Gate(password="mellon", secret="s", days=0)
    token = gate.issue("mellon")
    assert not gate.allows(token)          # expired the instant it was made


# -- the server, end to end ------------------------------------------------

@pytest.fixture
def server(tmp_path):
    httpd = serve(host="127.0.0.1", port=0, saves=tmp_path / "saves",
                  password=None)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _post(base, path, payload):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return json.loads(r.read())


def test_the_page_is_served(server):
    with urllib.request.urlopen(server + "/", timeout=5) as r:
        body = r.read().decode()
    assert "<title>The Hobbit</title>" in body


def test_a_command_takes_a_turn(server):
    data = _post(server, "/api/command", {"name": "alice", "text": "look"})
    joined = " ".join(data["lines"])
    assert "Bag End" in joined
    assert not data["over"]


def test_the_command_is_echoed(server):
    data = _post(server, "/api/command", {"name": "alice", "text": "look"})
    assert any("&gt; look" in line for line in data["lines"])


def test_a_closed_tab_resumes_where_it_left_off(server):
    _post(server, "/api/command", {"name": "alice", "text": "east"})
    state = _get(server, "/api/state?name=alice")
    assert any("east" in line.lower() or "road" in line.lower()
               for line in state["lines"])


def test_two_players_have_two_journeys(server):
    _post(server, "/api/command", {"name": "alice", "text": "east"})
    a = _get(server, "/api/state?name=alice")
    b = _get(server, "/api/state?name=bob")
    assert len(a["lines"]) > len(b["lines"])   # bob hasn't moved


def test_a_bad_name_is_refused(server):
    req = urllib.request.Request(
        server + "/api/command",
        data=json.dumps({"name": "../etc", "text": "look"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)
        assert False, "should have been refused"
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_restart_begins_again(server):
    for _ in range(3):
        _post(server, "/api/command", {"name": "alice", "text": "east"})
    data = _post(server, "/api/command", {"name": "alice", "text": "restart"})
    assert any("Bag End" in line for line in data["lines"])


def test_the_gate_blocks_a_command_without_a_token(tmp_path):
    httpd = serve(host="127.0.0.1", port=0, saves=tmp_path / "s",
                  password="mellon")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        req = urllib.request.Request(
            base + "/api/command",
            data=json.dumps({"name": "alice", "text": "look"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "should be locked"
        except urllib.error.HTTPError as e:
            assert e.code == 401
    finally:
        httpd.shutdown()


def test_concurrent_players_do_not_collide(server):
    """The whole reason for the lock: many relatives at once, each in their
    own game, no turn half-applied into another's."""
    errors = []

    def play(who):
        try:
            for _ in range(15):
                _post(server, "/api/command", {"name": who, "text": "look"})
        except Exception as exc:      # pragma: no cover - only on a real bug
            errors.append(exc)

    threads = [threading.Thread(target=play, args=(f"p{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


# -- the serve entry point -------------------------------------------------

def test_serve_reads_its_config_from_the_environment(tmp_path, monkeypatch):
    """python -m hobbit.serve must come up from environment alone, with no
    model configured, and still be a playable server."""
    import threading
    import urllib.request
    from hobbit import serve as serve_module

    monkeypatch.setenv("HOBBIT_SAVES", str(tmp_path / "s"))
    monkeypatch.delenv("HOBBIT_LLM_URL", raising=False)
    monkeypatch.delenv("HOBBIT_LLM_MODEL", raising=False)

    llm, fast = serve_module._make_llm()
    assert llm is None and fast is None          # nothing configured, no crash

    httpd = serve(host="127.0.0.1", port=0, saves=tmp_path / "s")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{httpd.server_address[1]}/", timeout=5) as r:
            assert "The Hobbit" in r.read().decode()
    finally:
        httpd.store.save_all()      # the shutdown path
        httpd.shutdown()


def test_the_dockerfile_installs_nothing():
    """The whole point of standard-library-only: the container needs no pip
    step, and a stray 'pip install' would mean a dependency crept in
    unnoticed."""
    from pathlib import Path
    dockerfile = Path(__file__).resolve().parent.parent / "Dockerfile"
    if not dockerfile.exists():
        return
    # Look at instruction lines only, so a comment explaining *why* there's no
    # pip step doesn't trip the check that there's no pip step.
    instructions = "\n".join(
        line for line in dockerfile.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#"))
    assert "pip" not in instructions
    assert "requirements" not in instructions.lower()
    assert "hobbit.serve" in instructions


def test_quit_and_exit_guide_rather_than_stranding(server):
    """On a web page there is no process to quit. A player typed 'exit'
    hoping to restart and got 'Farewell!' with nowhere to go."""
    for word in ("quit", "exit", "bye"):
        data = _post(server, "/api/command", {"name": "q", "text": word})
        joined = " ".join(data["lines"])
        assert "Farewell" not in joined
        assert "restart" in joined
        assert not data["over"]          # the game is not over, just idling


def test_restart_shows_the_opening_room(server):
    """Restart has to land you somewhere, not on a bare confirmation."""
    _post(server, "/api/command", {"name": "r", "text": "east"})
    data = _post(server, "/api/command", {"name": "r", "text": "restart"})
    joined = " ".join(data["lines"])
    assert "set out again" in joined
    assert "Bag End" in joined


def test_a_new_player_is_flagged_new_without_a_game_being_made(server, tmp_path):
    """The mode choice must come before the game exists -- checking state
    can't quietly create it in the default mode."""
    state = _get(server, "/api/state?name=freshfish")
    assert state["new"] is True
    assert state["lines"] == []


def test_choosing_purist_starts_a_purist_game(server):
    data = _post(server, "/api/command",
                 {"name": "purist_pat", "text": "look", "mode": "purist"})
    # the map is wall-flavour in purist -- 'examine map' finds nothing
    m = _post(server, "/api/command", {"name": "purist_pat", "text": "examine map"})
    assert any("no map" in line.lower() for line in m["lines"])
    assert not any("added" in line for line in m["lines"])   # no cyan additions


def test_the_default_choice_is_the_enhanced_game(server):
    _post(server, "/api/command",
          {"name": "enh", "text": "look", "mode": "enhanced"})
    m = _post(server, "/api/command", {"name": "enh", "text": "examine map"})
    assert any("moon-letters" in line.lower() for line in m["lines"])


def test_mode_is_fixed_after_the_game_exists(server):
    """A returning player keeps their tale -- a later mode hint is ignored."""
    _post(server, "/api/command",
          {"name": "steady", "text": "look", "mode": "purist"})
    # a subsequent command claiming 'enhanced' must not flip an existing game
    _post(server, "/api/command",
          {"name": "steady", "text": "look", "mode": "enhanced"})
    m = _post(server, "/api/command", {"name": "steady", "text": "examine map"})
    assert any("no map" in line.lower() for line in m["lines"])   # still purist


def test_a_returning_player_is_not_flagged_new(server):
    _post(server, "/api/command", {"name": "back", "text": "look"})
    state = _get(server, "/api/state?name=back")
    assert state["new"] is False
    assert state["lines"]
