from hobbit.commands import _find_character
from hobbit.game import Game
from hobbit.ui import Note


def test_a_character_is_found_by_a_name_with_a_stripped_article():
    """The parser strips articles, so 'attack William the troll' reaches the
    matcher as 'william troll' -- which is not a substring of the name
    'William the troll'. Matching whole words instead finds it."""
    game = Game(seed=1)
    trolls = ["troll_bert", "troll_william", "troll_tom"]
    assert _find_character(game, "william troll", trolls) == "troll_william"
    assert _find_character(game, "william the troll", trolls) == "troll_william"
    assert _find_character(game, "william", trolls) == "troll_william"
    assert _find_character(game, "bert", trolls) == "troll_bert"
    assert _find_character(game, "troll", trolls) in trolls   # any of them
    assert _find_character(game, "smaug", trolls) is None


def test_attacking_a_troll_by_its_full_name_lands_the_blow():
    """Regression: 'attack William the troll' answered 'There is no william
    troll here to attack' while the dwarves were fighting it by name."""
    game = Game(seed=1)
    game.player.location_id = "trolls_clearing"
    msgs = game.process_player_input("attack william the troll")
    assert not any("here to attack" in str(m).lower() for m in msgs)
    # the player's own blow (hit or miss) resolved against William, by name
    assert any(game.player.name in str(m) and "William the troll" in str(m)
               for m in msgs)


def test_look_marks_locked_exits_in_enhanced_mode():
    from hobbit import ui
    game = Game(seed=1)
    game.player.location_id = "trolls_clearing"
    shown = ui.present(game.describe_location(game.player), "standard")
    exits_row = next(r for r in shown[0].split("\n") if r.startswith("Exits:"))
    assert "down" in exits_row and "(locked)" in exits_row  # the courtesy marker
    assert "\033[" not in exits_row                          # but no longer tinted
    # and once opened, the marker goes away
    game.world.get("troll_cave").locked = False
    shown = ui.present(game.describe_location(game.player), "standard")
    exits_row = next(r for r in shown[0].split("\n") if r.startswith("Exits:"))
    assert "(locked)" not in exits_row


def test_purist_look_does_not_mark_locked_exits():
    game = Game(seed=1, authentic=True)
    game.player.location_id = "trolls_clearing"
    block = game.describe_location(game.player)[0]
    assert "(locked)" not in block


def test_companion_bumping_locked_door_is_silent():
    game = Game(seed=1)
    game.player.location_id = "trolls_clearing"
    thorin = game.characters["thorin"]
    game.world.get("bag_end").npcs.remove("thorin")
    thorin.location_id = "trolls_clearing"
    game.world.get("trolls_clearing").npcs.append("thorin")
    for tid in ("troll_tom", "troll_bert", "troll_william"):
        game.characters[tid].alive = False
    # aim Thorin at the locked cave so he bumps the door
    thorin.goal_target, thorin.goal_kind, thorin.goal_age = "troll_cave", "roam", 0
    msgs = game._advance_world_turn()
    assert not any("locked" in m.lower() for m in msgs)


def test_locked_way_hints_to_open_when_you_hold_the_key():
    game = Game(seed=1)
    game.player.location_id = "trolls_clearing"
    for tid in ("troll_tom", "troll_bert", "troll_william"):
        game.characters[tid].alive = False
    # without the key: just says locked
    plain = game.process_player_input("go down")
    assert any("locked" in m.lower() and "open" not in m.lower() for m in plain)
    # with the key: nudges toward 'open'
    game.player.inventory.append("key_troll_cave")
    hinted = game.process_player_input("go down")
    assert any("open door" in m.lower() for m in hinted)


def test_examine_scenery_returns_a_tagged_note():
    game = Game(seed=1)
    game.player.location_id = "bag_end_garden"
    messages = game.process_player_input("examine gate")
    scenery_messages = [m for m in messages if isinstance(m, Note)]
    assert scenery_messages, "expected the scenery description to be present and tagged as a Note"
    assert "north" in scenery_messages[0].lower()


def test_examine_map_finds_the_real_item():
    game = Game(seed=1)
    messages = game.process_player_input("examine map")
    assert any("moon-letters" in m.lower() for m in messages)


def test_bag_end_description_does_not_claim_map_after_taking_it():
    """Regression: the room prose used to hardcode 'a well-worn map hangs
    by the door', so it still said so once the map had been taken."""
    game = Game(seed=1)
    game.process_player_input("take map")
    room_block = game.describe_location(game.player)[0].lower()
    assert "map" not in room_block  # neither the prose nor the item list mentions it now
    assert "thorin_map" not in game.world.get("bag_end").items


def test_examine_unknown_noun_still_fails_gracefully():
    game = Game(seed=1)
    messages = game.process_player_input("examine nonexistent_thing")
    assert any("you see no" in m.lower() for m in messages)


def test_close_cannot_softlock_a_room_with_no_lock():
    """Regression: 'close' used to set loc.locked = True unconditionally,
    even in rooms with no key_item, permanently sealing an exit."""
    game = Game(seed=1)
    game.process_player_input("close door")
    assert game.world.get("bag_end").locked is False
    # still able to leave and come back
    game.process_player_input("go east")
    game.process_player_input("go west")
    assert game.player.location_id == "bag_end"


def test_close_requires_an_object():
    game = Game(seed=1)
    messages = game.process_player_input("close")
    assert any("close what" in m.lower() for m in messages)


def test_close_works_on_a_real_locked_room_and_reopening_still_works():
    game = Game(seed=1)
    game.player.location_id = "trolls_clearing"
    game.player.inventory.append("key_troll_cave")
    game.process_player_input("open door")
    assert game.world.get("troll_cave").locked is False
    game.process_player_input("close door")
    assert game.world.get("troll_cave").locked is True
    game.process_player_input("open door")
    assert game.world.get("troll_cave").locked is False


def test_unlocking_names_the_key_that_turned():
    """By the Lonely Mountain you may be carrying four keys, and a key hauled
    the length of the world deserves its moment."""
    from hobbit.game import Game
    cases = [
        ("secret_door_path", "moon_key", "moon-letter key"),
        ("trolls_clearing", "key_troll_cave", "iron key"),
        ("goblin_throne_room", "key_goblin_cell", "goblin cell key"),
        ("elvenking_dungeon", "elven_cellar_key", "carved elven key"),
    ]
    for room, key, name in cases:
        game = Game(seed=1)
        game.player.location_id = room
        game.player.light_remaining = 999
        game.player.inventory = [key]
        msgs = " ".join(str(getattr(m, "text", m))
                        for m in game.process_player_input("open door"))
        assert "unlock and open it" in msgs, room
        assert name in msgs, room


def test_a_door_with_no_key_still_opens_plainly():
    """Not every openable thing has a key to name."""
    from hobbit.commands import _open_locked_room
    from hobbit.game import Game
    game = Game(seed=1)
    room = game.world.get("troll_cave")
    room.locked, room.key_item = True, None
    msgs = _open_locked_room(game.player, room, game)
    assert msgs[0] == "You unlock and open it."
