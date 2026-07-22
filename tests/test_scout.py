"""Tests for the scout role: Gandalf ranges ahead, learns the road, and
reports back to Bilbo."""
from hobbit.game import Game
from hobbit.npc import SCOUT_RANGE
from hobbit.ui import Note


def _put_scout_with_player(game, room):
    gandalf = game.characters["gandalf"]
    game.world.get(gandalf.location_id).npcs.remove("gandalf")
    gandalf.location_id = room
    game.world.get(room).npcs.append("gandalf")
    game.player.location_id = room
    return gandalf


def test_scout_does_not_report_a_skirmish_in_bilbos_own_room():
    game = Game(seed=1)
    room = "trolls_clearing"
    name = game.world.get(room).name
    gandalf = _put_scout_with_player(game, room)
    # a skirmish trace here, queued as scout news -- but Bilbo is standing in it
    gandalf.scout_unreported = [{"text": f"signs of a recent skirmish at {name}",
                                 "concern": None}]
    joined = " ".join(getattr(m, "text", m) for m in game._scout_report())
    assert "skirmish" not in joined


def test_scout_still_reports_a_skirmish_elsewhere():
    game = Game(seed=1)
    here = "trolls_clearing"
    elsewhere = game.world.get(here).exits["east"]
    far_name = game.world.get(elsewhere).name
    gandalf = _put_scout_with_player(game, here)
    gandalf.scout_unreported = [{"text": f"signs of a recent skirmish at {far_name}",
                                 "concern": None}]
    joined = " ".join(getattr(m, "text", m) for m in game._scout_report())
    assert "skirmish" in joined


def test_gandalf_is_the_scout():
    game = Game(seed=1)
    assert game.characters["gandalf"].def_.is_scout
    assert not game.characters["thorin"].def_.is_scout


def test_scout_ranges_ahead_beyond_the_party_leash():
    game = Game(seed=1)
    gandalf = game.characters["gandalf"]
    reached = 0
    for _ in range(8):
        game._advance_world_turn()
        reached = max(reached, game.world.distance(gandalf.location_id,
                                                    game.player.location_id))
    assert reached >= 3  # well beyond the 2-room escort leash
    assert reached <= SCOUT_RANGE + 1


def test_scout_records_observations_and_reports_to_bilbo():
    game = Game(seed=1)
    gandalf = game.characters["gandalf"]
    report_lines = []
    for _ in range(30):
        msgs = game._advance_world_turn()
        report_lines += [m for m in msgs if isinstance(m, Note) and "scouting" in m]
        if report_lines:
            break
    assert gandalf.scout_memory, "the scout should have learned something"
    assert report_lines, "the scout should have reported back to Bilbo"
    # ranging from Bag End he learns of the inn (a food source) up the road
    assert any("food and shelter" in m for m in gandalf.scout_memory)


def test_scout_does_not_walk_into_a_monster_room_alone():
    game = Game(seed=3)
    gandalf = game.characters["gandalf"]
    # place scout + Bilbo right before the trolls' clearing
    game.player.location_id = "trollshaws_approach"
    game.world.get("bag_end").npcs.remove("gandalf")
    gandalf.location_id = "trollshaws_approach"
    game.world.get("trollshaws_approach").npcs.append("gandalf")
    gandalf.scout_phase = "ranging"
    for _ in range(6):
        game._advance_world_turn()
        assert gandalf.location_id != "trolls_clearing", \
            "the scout should peek at the trolls, not stroll in alone"
    # and the peek itself was recorded
    assert any("lurk" in m for m in gandalf.scout_memory)


def test_follow_me_suspends_scouting():
    game = Game(seed=1)
    game.process_player_input("gandalf, follow me")
    gandalf = game.characters["gandalf"]
    for _ in range(6):
        game._advance_world_turn()
        assert game.world.distance(gandalf.location_id,
                                    game.player.location_id) <= 1


def test_no_scouting_in_purist_mode():
    game = Game(seed=1, authentic=True)
    gandalf = game.characters["gandalf"]
    for _ in range(12):
        game._advance_world_turn()
    assert gandalf.scout_memory == []


def test_report_framing_ranged_vs_roadside():
    from hobbit import ui
    # ranged: he really went off scouting
    game = Game(seed=1)
    gandalf = game.characters["gandalf"]
    gandalf.scout_ranged = 3
    gandalf.scout_unreported = [{"text": "food and shelter can be had at The Green Dragon Inn",
                                  "concern": None}]
    msg = ui.present(game._scout_report(), "standard")[0]
    assert "returns from scouting ahead" in msg
    assert gandalf.scout_ranged == 0  # reset after reporting

    # roadside: he spied it from the road while marching with the company
    gandalf.scout_ranged = 1
    gandalf.scout_unreported = [{"text": "Tom the troll lurks at The Trolls' Clearing",
                                  "concern": None}]
    msg = ui.present(game._scout_report(), "standard")[0]
    assert "keeping pace with the company" in msg
    assert "returns from scouting ahead" not in msg


def test_stale_finding_about_a_now_visited_room_is_not_reported():
    """Regression: Gandalf reported 'food at the Green Dragon Inn' while
    Bilbo was standing in it."""
    game = Game(seed=1)
    gandalf = game.characters["gandalf"]
    gandalf.scout_unreported = [
        {"text": "food and shelter can be had at The Green Dragon Inn",
         "concern": "green_dragon_inn"}]
    game.player.location_id = "green_dragon_inn"
    game.world.get("green_dragon_inn").visited = True  # Bilbo is standing here
    assert game._scout_report() == []  # nothing worth saying


def _capture_balin(game):
    balin = game.characters["balin"]
    game.world.get("bag_end").npcs.remove("balin")
    balin.location_id = "goblin_dungeon"
    game.world.get("goblin_dungeon").npcs.append("balin")
    balin.captured = True
    return balin


def test_scout_spots_a_captured_companion_from_the_adjacent_room():
    game = Game(seed=1)
    _capture_balin(game)
    gandalf = game.characters["gandalf"]
    # Gandalf passes the throne room; the dungeon lies just below it.
    game.scout_observe(gandalf, "goblin_throne_room")
    assert any("Balin is held captive at The Goblin Dungeon" in m
               for m in gandalf.scout_memory)
    # a friend in chains is urgent -- reported before other findings
    assert gandalf.scout_unreported[0]["text"].startswith("Balin is held captive")


def test_captives_are_news_even_in_visited_rooms():
    game = Game(seed=1)
    _capture_balin(game)
    game.world.get("goblin_dungeon").visited = True  # Bilbo has been here before
    gandalf = game.characters["gandalf"]
    game.scout_observe(gandalf, "goblin_dungeon")
    assert any("held captive" in m for m in gandalf.scout_memory)


def test_free_companions_are_not_reported_as_sightings():
    game = Game(seed=1)
    balin = game.characters["balin"]
    game.world.get("bag_end").npcs.remove("balin")
    balin.location_id = "rivendell_hall"  # far off, but free
    game.world.get("rivendell_hall").npcs.append("balin")
    gandalf = game.characters["gandalf"]
    game.scout_observe(gandalf, "rivendell_hall")
    assert not any("Balin" in m for m in gandalf.scout_memory)


def test_captive_report_reaches_bilbo():
    game = Game(seed=1)
    _capture_balin(game)
    gandalf = game.characters["gandalf"]
    game.scout_observe(gandalf, "goblin_throne_room")
    # scout back at Bilbo's side -> report is delivered
    gandalf.location_id = game.player.location_id
    msgs = game._scout_report()
    assert any("held captive" in m for m in msgs)


def test_discoveries_reach_dialogue_context():
    class FakeLLM:
        def __init__(self):
            self.prompts = []

        def chat(self, system, user):
            self.prompts.append(user)
            return "The road ahead holds trolls, my dear Bilbo."

    fake = FakeLLM()
    game = Game(seed=1, llm=fake)
    gandalf = game.characters["gandalf"]
    gandalf.scout_memory.append("trolls lurk at The Trolls' Clearing")
    game.process_player_input("talk to gandalf")
    assert any("trolls lurk at The Trolls' Clearing" in p for p in fake.prompts)


def test_scout_state_survives_save_load(tmp_path):
    save = tmp_path / "s.json"
    game = Game(seed=1)
    gandalf = game.characters["gandalf"]
    gandalf.scout_memory.append("a locked way bars passage down of The Trolls' Clearing")
    gandalf.scout_unreported.append(
        {"text": "a locked way bars passage down of The Trolls' Clearing", "concern": "trolls_clearing"})
    gandalf.scout_seen.add("trolls_clearing:locked:troll_cave")
    game.save(save)
    fresh = Game(seed=1)
    fresh.load(save)
    g2 = fresh.characters["gandalf"]
    assert g2.scout_memory == gandalf.scout_memory
    assert g2.scout_unreported == gandalf.scout_unreported
    assert "trolls_clearing:locked:troll_cave" in g2.scout_seen


def _put(game, cid, room):
    char = game.characters[cid]
    old = game.world.get(char.location_id)
    if cid in old.npcs:
        old.npcs.remove(cid)
    char.location_id = room
    if cid not in game.world.get(room).npcs:
        game.world.get(room).npcs.append(cid)


def test_captive_news_expires_when_they_are_freed():
    """Gandalf solemnly reported four dwarves 'held captive at The Spiders'
    Nest' while all four stood beside Bilbo, rescued. Captive findings carry
    no `concern` room by design, so the visited-room filter never caught them."""
    game = Game(seed=1)
    held = ("fili", "bofur", "dori", "bifur")
    for cid in held:
        _put(game, cid, "spiders_nest")
        game.characters[cid].captured = True
    gandalf = game.characters["gandalf"]
    _put(game, "gandalf", "spiders_nest")
    game.scout_observe(gandalf, "spiders_nest")

    # while they really are held, it's news worth carrying
    _put(game, "gandalf", game.player.location_id)
    said = " ".join(str(getattr(m, "text", m)) for m in game._scout_report())
    assert "held captive" in said

    # free them, and the same finding must not be repeated
    game.scout_observe(gandalf, "spiders_nest")
    for cid in held:
        game.characters[cid].captured = False
        _put(game, cid, game.player.location_id)
    _put(game, "gandalf", game.player.location_id)
    said = " ".join(str(getattr(m, "text", m)) for m in game._scout_report())
    assert "held captive" not in said


def test_a_capture_trace_expires_with_the_rescue_too():
    game = Game(seed=1)
    balin = game.characters["balin"]
    game.record_event("mirkwood_path_2", "captured",
                      "Balin was taken by spiders near A Path Through Mirkwood",
                      urgent=True, subject="balin")
    balin.captured = True
    gandalf = game.characters["gandalf"]
    _put(game, "gandalf", "mirkwood_path_2")
    game.scout_observe(gandalf, "mirkwood_path_2")
    _put(game, "gandalf", game.player.location_id)
    assert any("taken by spiders" in str(getattr(m, "text", m))
               for m in game._scout_report())

    game.scout_observe(gandalf, "mirkwood_path_2")
    balin.captured = False
    _put(game, "gandalf", game.player.location_id)
    assert not any("taken by spiders" in str(getattr(m, "text", m))
                   for m in game._scout_report())


def test_findings_about_nobody_in_particular_are_unaffected():
    game = Game(seed=1)
    gandalf = game.characters["gandalf"]
    gandalf.scout_unreported = [{"text": "wolves gather at the ford",
                                 "concern": None, "subjects": None}]
    _put(game, "gandalf", game.player.location_id)
    assert game._scout_report()


def test_captive_news_from_an_older_save_also_expires():
    """The first fix only tagged findings created after it, so news already
    queued -- in a running game or restored from a save -- still leaked. These
    have no 'subjects' key at all, so the names are read from the prose."""
    game = Game(seed=1)
    legacy = [
        {"text": "Fili, Bofur, Dori and Bifur are held captive at The Spiders' Nest",
         "concern": None},
        {"text": "Bifur was taken by spiders near A Path Through Mirkwood "
                 "-- a silk-wrapped shape was hauled up into the branches",
         "concern": None},
    ]
    assert set(game._captives_named_in(legacy[0]["text"])) == \
        {"fili", "bofur", "dori", "bifur"}

    gandalf = game.characters["gandalf"]
    gandalf.scout_unreported = list(legacy)
    _put(game, "gandalf", game.player.location_id)
    assert game._scout_report() == []      # nobody is captive; say nothing

    game.characters["bifur"].captured = True   # but if one still is, it's news
    gandalf.scout_unreported = list(legacy)
    assert game._scout_report()


def test_name_matching_is_whole_word():
    """'Ori' must not match inside 'Dori' or 'Nori'."""
    game = Game(seed=1)
    named = game._captives_named_in("Dori and Nori are held captive at X")
    assert set(named) == {"dori", "nori"}
    assert "ori" not in named


def test_ordinary_findings_are_not_treated_as_captivity_news():
    game = Game(seed=1)
    assert game._captives_named_in("food and shelter can be had at Beorn's Hall") == []
    assert game._captives_named_in("Balin walks the road near the ford") == []
