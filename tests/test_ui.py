from hobbit.game import Game
from hobbit.ui import Note, present


def test_present_keeps_note_text_as_plain_content():
    """Note text is real content, just newly written -- it is shown, not
    hidden. It used to be tinted cyan; now it reads like any other line."""
    assert present([Note("Added feature")], level="purist") == ["Added feature"]
    assert present([Note("Added feature")], level="standard") == ["Added feature"]


def test_additions_are_no_longer_coloured():
    """The cyan marking of additions was removed, so no output carries an ANSI
    escape at either level."""
    for level in ("purist", "standard"):
        out = present([Note("Added feature")], level=level)
        assert out == ["Added feature"]
        assert "\033[" not in out[0]


def test_present_leaves_plain_messages_alone_but_for_the_opening_letter():
    for level in ("purist", "standard"):
        assert present(["Plain narrative"], level=level) == ["Plain narrative"]


def test_present_capitalises_lines_that_open_with_a_lower_case_name():
    """Several characters are named in lower case on purpose ('wood-elf guard',
    'giant spider'), which reads right mid-line but not at the start of one.
    The level no longer changes the output."""
    for level in ("purist", "standard"):
        assert present(["giant spider looms here."], level=level) == \
            ["Giant spider looms here."]
        assert present([Note("wood-elf guard bars the way.")], level=level) == \
            ["Wood-elf guard bars the way."]


def test_the_mode_cannot_be_changed_mid_journey():
    """Purist and enhanced are different worlds, not two views of one -- the map
    is a real item in one and wall flavour in the other, the Elvenking's gate is
    barred in one and open in the other. Switching halfway would rearrange the
    world around a company already standing in it."""
    game = Game(seed=1)
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("purist"))
    assert game.annotation_level == "standard"        # unchanged
    assert "cannot be changed" in msgs


def test_there_is_no_annotate_command_any_more():
    """The verbose/amber commentary layer was removed: keeping it accurate
    meant re-documenting the whole game on every change, and a player who
    wants the unimproved article can just play purist."""
    game = Game(seed=1)
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("annotate verbose")).lower()
    assert "don't know how" in msgs or "didn't understand" in msgs
    assert game.annotation_level == "standard"


def test_mode_reports_which_game_you_are_in():
    game = Game(seed=1)
    assert any("ENHANCED" in str(m) for m in game.process_player_input("mode"))
    pure = Game(seed=1, authentic=True)
    assert any("PURIST" in str(m) for m in pure.process_player_input("mode"))


def test_examine_map_by_game():
    from hobbit import ui
    game = Game(seed=1)

    # purist == authentic: the map is unexaminable wall flavour, as in 1982
    game.annotation_level = "purist"
    shown = ui.present(game.process_player_input("examine map"), "purist")
    assert any("no map" in m.lower() for m in shown)
    assert not any("moon-letters" in m.lower() for m in shown)

    # standard: real item with a full description -- and, now, no colour
    game.annotation_level = "standard"
    shown = ui.present(game.process_player_input("examine map"), "standard")
    assert any("moon-letters" in m.lower() for m in shown)
    assert not any("\033[" in m for m in shown)


def test_no_message_carries_a_colour_escape():
    """Nothing anywhere is tinted now -- a sweep of the common commands finds no
    ANSI escape in any line."""
    from hobbit import ui
    game = Game(seed=1)
    game.player.inventory = ["sting", "thorin_map"]
    for cmd in ("look", "examine map", "examine torch", "inventory", "take map",
                "mode", "help", "status", "open door", "close door"):
        for m in ui.present(game.process_player_input(cmd), "standard"):
            assert "\033[" not in m, f"{cmd!r} still emits a colour escape: {m!r}"


def test_previously_unreachable_room_still_describes_itself():
    """The room used to carry amber commentary about having been unreachable.
    The commentary is gone; the room, and its description, must not be."""
    from hobbit import ui
    game = Game(seed=1)
    game.player.location_id = "troll_cave"
    game.player.light_remaining = 10  # room is dark; needs light to see it

    for level in ("purist", "standard"):
        game.annotation_level = level
        shown = ui.present(game.process_player_input("look"), level)
        assert any("trolls' cave" in m.lower() for m in shown)
        assert not any("bugfix" in m.lower() for m in shown)


def test_nothing_narrates_its_own_changelog_at_the_player():
    """A sweep: with the amber layer gone, no message anywhere should still be
    explaining to the player which defect it fixed."""
    from hobbit import ui
    game = Game(seed=1)
    game.player.inventory = ["sting", "thorin_map"]
    for cmd in ("look", "examine map", "examine sting", "inventory",
                "mode", "help", "status", "open door", "close door"):
        for m in ui.present(game.process_player_input(cmd), "standard"):
            assert "bugfix" not in m.lower(), f"{cmd!r} still mentions a bugfix: {m}"


def test_inventory_listing_is_the_same_at_both_levels():
    from hobbit import ui
    game = Game(seed=1)
    game.player.inventory = ["thorin_map", "torch"]  # gear only, no loaves

    line = game.process_player_input("inventory")[0]

    for level in ("purist", "standard"):
        shown = ui.present([line], level)[0]
        assert shown.startswith("You are carrying: old map, torch.")
        assert "\033[" not in shown


def test_you_see_line_lists_the_added_item_without_colour():
    from hobbit import ui
    game = Game(seed=1)
    line = next(m for m in game.process_player_input("look") if "You see" in m)

    for level in ("purist", "standard"):
        shown = ui.present([line], level)[0]
        assert "old map" in shown and "walking stick" in shown
        assert "\033[" not in shown


def test_take_messages_name_the_item_without_colour():
    from hobbit import ui
    game = Game(seed=1)

    shown = ui.present(game.process_player_input("take map"), "standard")
    assert any("old map" in m for m in shown)
    assert not any("\033[" in m for m in shown)

    shown = ui.present(game.process_player_input("take torch"), "standard")
    assert not any("\033[" in m for m in shown)
