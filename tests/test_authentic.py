"""Tests for authenticity mode: the 1982-flavored revert of this
recreation's additions and fixes."""
from hobbit.game import Game


def test_added_map_hidden_and_not_takeable_in_authentic_mode():
    authentic = Game(seed=1, authentic=True)
    bag_end = authentic.world.get("bag_end")
    # the item still exists in world data, but is hidden from view + interaction
    assert "thorin_map" in bag_end.items
    assert "thorin_map" not in authentic.visible_items(bag_end)
    block = authentic.describe_location(authentic.player)[0].lower()
    assert "old map" not in block
    assert "you see: walking stick, torch" in block
    assert any("no map" in m.lower() for m in authentic.process_player_input("take map"))
    # enhanced still exposes it as a real, takeable item
    enhanced = Game(seed=1)
    assert "thorin_map" in enhanced.visible_items(enhanced.world.get("bag_end"))


def test_examine_map_fails_in_authentic_mode():
    game = Game(seed=1, authentic=True)
    messages = game.process_player_input("examine map")
    assert any("no map" in m.lower() or "you see no" in m.lower() for m in messages)


def test_garden_description_reverts_to_buggy_original():
    enhanced = Game(seed=1)
    authentic = Game(seed=1, authentic=True)
    enhanced.player.location_id = "bag_end_garden"
    authentic.player.location_id = "bag_end_garden"

    enh = enhanced.describe_location(enhanced.player)[0]
    aut = authentic.describe_location(authentic.player)[0]

    assert "onto the lane" in aut          # the buggy original affordance is back
    assert "hedge-trimming" not in aut     # the corrected phrasing is gone
    assert "hedge-trimming" in enh         # enhanced still has the fix


def test_scenery_examine_disabled_in_authentic_mode():
    game = Game(seed=1, authentic=True)
    game.player.location_id = "bag_end_garden"
    messages = game.process_player_input("examine gate")
    assert any("you see no" in m.lower() for m in messages)


def test_purist_shows_no_meta_commentary():
    """purist == authentic: the raw article, with nothing of this recreation
    talking over it."""
    from hobbit import ui
    game = Game(seed=1, authentic=True)  # purist
    game.player.location_id = "bag_end_garden"
    shown = ui.present(game.process_player_input("look"), game.annotation_level)
    assert not any("bugfix" in m.lower() for m in shown)


def test_locked_room_unreachable_in_authentic_mode():
    """The core of the 'broken mechanics' revert: standing in the clearing
    with the key, 'open' can't unlock the cave below (it only checks the
    room you're in), so the Trolls' Cave is unreachable."""
    game = Game(seed=1, authentic=True)
    game.player.location_id = "trolls_clearing"
    game.player.inventory.append("key_troll_cave")
    game.process_player_input("open door")
    assert game.world.get("troll_cave").locked is True
    # and the enhanced game, same setup, CAN open it
    enhanced = Game(seed=1)
    enhanced.player.location_id = "trolls_clearing"
    enhanced.player.inventory.append("key_troll_cave")
    enhanced.process_player_input("open door")
    assert enhanced.world.get("troll_cave").locked is False


def test_parser_conveniences_still_work_in_authentic_mode():
    """The chosen setting keeps chaining + direct address (faithful to the
    real 1982 parser)."""
    game = Game(seed=1, authentic=True)
    game.player.location_id = "bag_end"
    # chaining: take stick then go east
    game.process_player_input("take stick and go east")
    assert game.player.location_id == "hobbiton_road"
    assert "walking_stick" in game.player.inventory


def test_mode_command_reports_current_mode():
    pure = " ".join(str(getattr(m, "text", m))
                    for m in Game(seed=1, authentic=True).process_player_input("mode"))
    assert "purist" in pure.lower()
    rich = " ".join(str(getattr(m, "text", m))
                    for m in Game(seed=1).process_player_input("mode"))
    assert "enhanced" in rich.lower()
    # and both say the choice is fixed
    assert "cannot be changed" in pure and "cannot be changed" in rich


def test_authentic_flag_survives_save_load(tmp_path):
    save = tmp_path / "s.json"
    game = Game(seed=1, authentic=True)
    game.save(save)
    # load into a default (enhanced) game -- the saved flag should win
    fresh = Game(seed=1)
    fresh.load(save)
    assert fresh.authentic is True
