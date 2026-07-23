"""One game per player, and a journey that survives a closed tab."""
import json
import time

import pytest

from hobbit.sessions import SessionStore, normalise_name


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "saves")


def test_a_name_is_the_same_player_however_it_is_typed():
    """A relative who capitalises differently on their phone must not find a
    new empty game waiting for them."""
    assert normalise_name("Duncan") == normalise_name("duncan") == "duncan"
    assert normalise_name("  Duncan  ") == "duncan"
    assert normalise_name("Great Aunt Mabel") == "great aunt mabel"


def test_unusable_names_are_refused():
    for bad in ("", "   ", "../etc/passwd", "a" * 40, "bob/../bob", "<script>"):
        assert normalise_name(bad) is None


def test_each_player_gets_their_own_middle_earth(store):
    alice, bob = store.get("alice"), store.get("bob")
    assert alice.game is not bob.game
    alice.game.process_player_input("east")
    assert alice.game.player.location_id != bob.game.player.location_id


def test_a_journey_survives_a_closed_tab(store):
    session = store.get("alice")
    for _ in range(3):
        session.game.process_player_input("east")
    where, turn = session.game.player.location_id, session.game.turn
    store.save("alice")

    fresh = SessionStore(store.directory)          # as if the server restarted
    resumed = fresh.get("alice")
    assert resumed.game.player.location_id == where
    assert resumed.game.turn == turn


def test_the_same_player_twice_is_the_same_game(store):
    """Two tabs must not be two journeys."""
    assert store.get("alice") is store.get("alice")


def test_a_corrupt_save_is_set_aside_not_silently_erased(store):
    store.get("alice").game.process_player_input("east")
    store.save("alice")
    store.path_for("alice").write_text("{ this is not json", encoding="utf-8")

    fresh = SessionStore(store.directory)
    session = fresh.get("alice")            # starts over rather than crashing
    assert session.game.turn == 0
    # ...but the damaged file is still there to look at
    assert (store.directory / "alice.corrupt.json").exists()


def test_restart_keeps_the_old_journey_as_a_record(store):
    session = store.get("alice")
    for _ in range(4):
        session.game.process_player_input("east")
    store.save("alice")

    restarted = store.restart("alice")
    assert restarted.game.turn == 0
    # The game backup, specifically -- restart now also keeps the old
    # transcript as its own .transcript.bak, so filter that out.
    backups = [b for b in store.directory.glob("alice.*.bak")
               if "transcript" not in b.name]
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["turn"] > 0


def test_the_scrollback_is_bounded(store):
    small = SessionStore(store.directory, max_transcript=10)
    session = small.get("alice")
    small.record(session, [f"line {i}" for i in range(50)])
    assert len(session.transcript) == 10
    assert session.transcript[-1] == "line 49"   # the newest is kept


def test_idle_sessions_are_saved_before_they_are_dropped(store):
    session = store.get("alice")
    session.game.process_player_input("east")
    where = session.game.player.location_id
    session.last_seen = time.monotonic() - 9999

    assert store.evict_idle(older_than=60) == 1
    assert store.path_for("alice").exists()      # saved on the way out
    assert store.get("alice").game.player.location_id == where


def test_an_active_session_is_not_evicted(store):
    store.get("alice")
    assert store.evict_idle(older_than=60) == 0


def test_shutdown_persists_every_live_game(store):
    for who in ("alice", "bob", "carol"):
        store.get(who).game.process_player_input("east")
    store.save_all()
    for who in ("alice", "bob", "carol"):
        assert store.path_for(who).exists()


def test_known_players_ignores_backups_and_wreckage(store):
    store.get("alice"); store.save("alice")
    (store.directory / "alice.corrupt.json").write_text("{}", encoding="utf-8")
    (store.directory / "alice.123.bak").write_text("{}", encoding="utf-8")
    assert store.known_players() == ["alice"]


def test_the_store_survives_concurrent_players(store):
    """The stdlib server answers on threads; two relatives playing at once
    must not interleave into each other's games."""
    import threading
    errors = []

    def play(who):
        try:
            for _ in range(20):
                s = store.get(who)
                s.game.process_player_input("look")
                store.record(s, ["a line"])
        except Exception as exc:      # pragma: no cover - only on a real bug
            errors.append(exc)

    threads = [threading.Thread(target=play, args=(f"player{i}",))
               for i in range(6)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors
    assert len(store.known_players()) == 6


def test_scrollback_survives_a_server_restart(store):
    """Every deploy restarts the process. The game state already survived;
    now the visible history does too, so an update doesn't blank the family's
    screens."""
    session = store.get("alice")
    session.game.process_player_input("east")
    store.record(session, ["<div>== Hobbiton Road ==</div>", "You go east."])
    store.save("alice")

    fresh = SessionStore(store.directory)          # as if redeployed
    resumed = fresh.get("alice")
    assert resumed.transcript == ["<div>== Hobbiton Road ==</div>",
                                   "You go east."]
    assert resumed.game.player.location_id == session.game.player.location_id


def test_a_fresh_player_gets_no_leftover_scrollback(store):
    """A transcript file must never attach to a game that didn't load -- that
    would show history from a game that no longer exists."""
    store.get("alice")
    store.record(store.get("alice"), ["old history"])
    store.save("alice")
    # remove only the game save, leaving the transcript behind
    store.path_for("alice").unlink()

    fresh = SessionStore(store.directory)
    assert fresh.get("alice").transcript == []      # no game -> no history


def test_restart_does_not_carry_the_old_scrollback(store):
    session = store.get("alice")
    store.record(session, ["a line from the first journey"])
    store.save("alice")

    restarted = store.restart("alice")
    assert restarted.transcript == []
    # and the old scrollback is kept as a record, not destroyed
    assert list(store.directory.glob("alice.*.transcript.bak"))


def test_a_corrupt_transcript_does_not_endanger_the_game(store):
    session = store.get("alice")
    session.game.process_player_input("east")
    store.record(session, ["some history"])
    store.save("alice")
    store._transcript_path("alice").write_text("{ not json", encoding="utf-8")

    fresh = SessionStore(store.directory)
    resumed = fresh.get("alice")
    assert resumed.transcript == []                       # history lost
    assert resumed.game.player.location_id != "bag_end"   # but the game is fine


def test_known_players_ignores_transcript_files(store):
    store.get("alice")
    store.record(store.get("alice"), ["x"])
    store.save("alice")
    assert store.known_players() == ["alice"]      # not "alice.transcript"


def test_real_names_with_apostrophes_and_accents_are_welcome():
    """A family has O'Briens, Josés and Renées in it. The old ASCII-only
    rule turned their real names away."""
    for good in ("O'Brien", "José", "Zoë", "Søren", "Renée", "Anne-Marie",
                 "Mary Jane", "田中"):
        assert normalise_name(good) is not None, good


def test_names_that_are_unsafe_as_a_filename_are_still_refused():
    for bad in ("", "   ", "../etc/passwd", "bob/../bob", "<script>",
                "a" * 40, "a.json", "night\x00day", "St. John"):
        assert normalise_name(bad) is None, bad


def test_an_accented_name_round_trips_through_a_unicode_save(tmp_path):
    store = SessionStore(tmp_path)
    name = normalise_name("José")
    session = store.get(name)
    session.game.process_player_input("east")
    store.record(session, ["a line"])
    store.save(name)

    fresh = SessionStore(tmp_path)
    resumed = fresh.get(name)
    assert resumed.game.player.location_id == session.game.player.location_id
    assert resumed.transcript == ["a line"]


def test_a_player_named_after_a_companion_still_plays_as_bilbo(tmp_path):
    """The session name and the in-game character are independent, so a
    relative called Gandalf gets their own journey as the hobbit, not a
    collision with the wizard."""
    store = SessionStore(tmp_path)
    session = store.get(normalise_name("Gandalf"))
    assert session.game.player.id == "bilbo"
    assert "gandalf" in session.game.characters   # the real wizard is still there
    assert session.game.characters["gandalf"] is not session.game.player
