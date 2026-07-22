from pathlib import Path

from hobbit.game import Game


def test_weak_player_loses_health_over_time():
    game = Game(seed=1)
    game.player.fatigue = 65  # already weak from fatigue
    game.player.health = 25
    game._advance_world_turn()
    assert game.player.health < 25  # being weak wears health down


def test_well_fed_player_keeps_full_health():
    game = Game(seed=1)
    game.player.hunger = 0
    game.player.fatigue = 0
    game.player.health = 25
    game._advance_world_turn()
    assert game.player.health == 25  # no drain when not weak


def test_captured_npc_does_not_starve_to_death():
    game = Game(seed=1)
    balin = game.characters["balin"]
    # held far from Bilbo (a captive in Bilbo's own room would just be freed)
    game.world.get("bag_end").npcs.remove("balin")
    balin.location_id = "goblin_dungeon"
    game.world.get("goblin_dungeon").npcs.append("balin")
    balin.captured = True
    balin.hunger = 100
    balin.fatigue = 100
    balin.health = 5
    for _ in range(10):
        game._advance_world_turn()
    assert balin.alive  # imprisoned, not worn down -- rescuable


def test_status_shows_hunger_and_fatigue_levels():
    game = Game(seed=1)
    game.player.hunger = 50
    game.player.fatigue = 30
    msgs = game.process_player_input("status")
    joined = " ".join(msgs).lower()
    assert "hunger:" in joined and "fatigue:" in joined


def test_load_reports_missing_save_cleanly(tmp_path, capsys):
    # do_load must not claim success; the host loop decides. Simulate the
    # host loop's contract: do_load only sets the request flag, no message.
    game = Game(seed=1)
    msgs = game.process_player_input("load")
    assert msgs == [] or all("loaded" not in m.lower() for m in msgs)
    assert game.request_load is True


def test_save_then_load_roundtrip_preserves_state(tmp_path):
    save = tmp_path / "s.json"
    game = Game(seed=1)
    game.player.location_id = "rivendell_hall"
    game.player.inventory = ["bread", "bread", "torch"]  # 2 loaves + gear
    game.save(save)

    fresh = Game(seed=1)
    fresh.load(save)
    assert fresh.player.location_id == "rivendell_hall"
    assert fresh.food_count(fresh.player) == 2
    assert "torch" in fresh.player.inventory


# -- the collapse death spiral --------------------------------------------

def _collapsed(authentic=False):
    game = Game(seed=1, authentic=authentic)
    game.player.hunger = 100
    game.player.fatigue = 100
    game.player.inventory = ["bread"]
    assert game.player.is_fainted()
    return game


def test_a_collapsed_hobbit_can_still_eat_and_rest():
    """The original told you to eat, then refused every command -- including
    eating. Collapsing was an unwinnable state."""
    game = _collapsed()
    before = game.player.hunger
    game.process_player_input("eat")
    assert game.player.hunger < before          # he can save himself
    tired = game.player.fatigue
    game.process_player_input("rest")
    assert game.player.fatigue < tired


def test_a_collapsed_hobbit_still_cannot_fight_or_march():
    game = _collapsed()
    room = game.player.location_id
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("east"))
    assert "too weak" in msgs
    assert game.player.location_id == room


def test_purist_keeps_the_original_death_spiral():
    game = _collapsed(authentic=True)
    before = game.player.hunger
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("eat"))
    assert "too weak" in msgs
    assert game.player.hunger == before  # refused: no way out but death


def test_reporting_commands_work_even_collapsed_in_purist():
    """Being unable to save or look at death's door would be hostile, not
    authentic."""
    game = _collapsed(authentic=True)
    for cmd in ("status", "look", "inventory"):
        msgs = " ".join(str(getattr(m, "text", m))
                        for m in game.process_player_input(cmd))
        assert "too weak" not in msgs, cmd
