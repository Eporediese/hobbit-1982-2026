from hobbit.game import Game
from hobbit.ui import Note, present


def test_present_purist_strips_color_but_keeps_note_text():
    """Note text is real content, just newly written -- purist shows it
    unflagged rather than hiding it."""
    out = present([Note("Added feature")], level="purist")
    assert out == ["Added feature"]


def test_present_standard_colors_notes():
    out = present([Note("Added feature")], level="standard")
    assert len(out) == 1
    assert "Added feature" in out[0]
    assert "\033[96m" in out[0]


def test_present_leaves_plain_messages_alone_but_for_the_opening_letter():
    for level in ("purist", "standard"):
        assert present(["Plain narrative"], level=level) == ["Plain narrative"]


def test_present_capitalises_lines_that_open_with_a_lower_case_name():
    """Several characters are named in lower case on purpose ('wood-elf guard',
    'giant spider'), which reads right mid-line but not at the start of one."""
    for level in ("purist", "standard"):
        assert present(["giant spider looms here."], level=level) == \
            ["Giant spider looms here."]
        assert present([Note("wood-elf guard bars the way.")], level=level)[0] \
            .endswith("Wood-elf guard bars the way.\033[0m"
                      if level != "purist" else "Wood-elf guard bars the way.")


def test_capitalising_does_not_reach_inside_a_colour_escape():
    """Regression: the first *letter* of '\\033[96m== Room ==' is the 'm' of
    the escape sequence itself."""
    out = present([f"{'\033[96m'}== Hobbiton Road ==\033[0m"], level="standard")
    assert "\033[96m== Hobbiton Road ==" in out[0]


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

    # standard: real item, description coloured cyan
    game.annotation_level = "standard"
    shown = ui.present(game.process_player_input("examine map"), "standard")
    assert any("\033[96m" in m and "moon-letters" in m.lower() for m in shown)


def test_plain_items_stay_uncolored_when_examined():
    from hobbit import ui
    game = Game(seed=1)
    shown = ui.present(game.process_player_input("examine torch"), "standard")
    assert not any("\033[" in m for m in shown)


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


def test_inventory_listing_colors_only_the_added_item_name():
    from hobbit import ui
    game = Game(seed=1)
    game.player.inventory = ["thorin_map", "torch"]  # gear only, no loaves

    line = game.process_player_input("inventory")[0]

    purist = ui.present([line], "purist")[0]
    assert purist.startswith("You are carrying: old map, torch.")

    standard = ui.present([line], "standard")[0]
    assert f"{ui.ADDITION_COLOR}old map{ui.RESET}" in standard
    assert ", torch." in standard  # torch itself stays uncoloured
    assert standard.count(ui.ADDITION_COLOR) == 1  # only the map, not the line


def test_you_see_line_colors_only_the_added_item_name():
    from hobbit import ui
    game = Game(seed=1)
    line = next(m for m in game.process_player_input("look") if "You see" in m)

    purist = ui.present([line], "purist")[0]
    assert "old map" in purist and "\033[" not in purist

    standard = ui.present([line], "standard")[0]
    assert f"{ui.ADDITION_COLOR}old map{ui.RESET}" in standard
    assert "walking stick" in standard and f"{ui.ADDITION_COLOR}walking stick" not in standard


def test_take_and_wield_messages_color_only_added_item_names():
    from hobbit import ui
    game = Game(seed=1)

    shown = ui.present(game.process_player_input("take map"), "standard")
    assert any(f"{ui.ADDITION_COLOR}old map{ui.RESET}" in m for m in shown)

    shown = ui.present(game.process_player_input("take torch"), "standard")
    assert not any(ui.ADDITION_COLOR in m for m in shown)
