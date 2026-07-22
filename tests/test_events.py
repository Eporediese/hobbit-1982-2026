"""Tests for the world-event layer: located traces of things that happened,
which the scout reads and reports."""
from hobbit.game import Game


def test_record_event_rate_limits_per_room_and_kind():
    game = Game(seed=1)
    for _ in range(3):  # a three-round brawl leaves one trace
        game.record_event("lone_lands_1", "fight", "signs of a recent skirmish")
    assert len(game.fresh_events_at("lone_lands_1")) == 1
    game.turn += 5  # later, another fight is a new trace
    game.record_event("lone_lands_1", "fight", "signs of a recent skirmish")
    assert len(game.fresh_events_at("lone_lands_1")) == 2


def test_events_go_cold_after_a_while():
    game = Game(seed=1)
    game.record_event("lone_lands_1", "fight", "signs of a recent skirmish")
    game.turn += game.EVENT_FRESH + 1
    assert game.fresh_events_at("lone_lands_1") == []


def test_combat_records_a_skirmish_trace():
    game = Game(seed=1)
    game.player.location_id = "trolls_clearing"
    game.process_player_input("attack tom")
    assert any(e["kind"] == "fight" for e in game.fresh_events_at("trolls_clearing"))


def test_death_records_a_slain_trace():
    game = Game(seed=1)
    tom = game.characters["troll_tom"]
    tom.alive = False
    game.handle_death(tom)
    assert any(e["kind"] == "slain" and "Tom the troll" in e["text"]
               for e in game.fresh_events_at("trolls_clearing"))


def test_scout_reads_traces_and_reports_them():
    game = Game(seed=1)
    gandalf = game.characters["gandalf"]
    # a fight happened up the road, out of Bilbo's sight
    game.record_event("lone_lands_1", "fight",
                       "signs of a recent skirmish at The Lone-lands")
    game.scout_observe(gandalf, "lone_lands_1")
    assert any("skirmish" in m for m in gandalf.scout_memory)
    # delivered when he stands with Bilbo
    gandalf.location_id = game.player.location_id
    msgs = game._scout_report()
    assert any("skirmish" in m for m in msgs)


def test_abduction_event_is_urgent_news():
    game = Game(seed=1)
    game.record_event("goblin_tunnel_1", "captured",
                       "Balin was seized by goblins near A Goblin Tunnel "
                       "-- drag-marks lead into the deeps", urgent=True)
    game.record_event("goblin_tunnel_1", "fight", "signs of a skirmish")
    gandalf = game.characters["gandalf"]
    game.scout_observe(gandalf, "goblin_tunnel_1")
    assert gandalf.scout_unreported[0]["text"].startswith("Balin was seized")


def test_events_bilbo_witnessed_are_not_reported():
    game = Game(seed=1)
    # the fight happens in Bilbo's own room
    game.record_event(game.player.location_id, "fight",
                       "signs of a recent skirmish at Bag End")
    gandalf = game.characters["gandalf"]
    game.scout_observe(gandalf, game.player.location_id)
    assert not any("skirmish" in m for m in gandalf.scout_memory)


def test_events_survive_save_load(tmp_path):
    save = tmp_path / "s.json"
    game = Game(seed=1)
    game.record_event("lone_lands_1", "fight", "signs of a recent skirmish")
    game.save(save)
    fresh = Game(seed=1)
    fresh.load(save)
    assert any(e["kind"] == "fight" for e in fresh.fresh_events_at("lone_lands_1"))
