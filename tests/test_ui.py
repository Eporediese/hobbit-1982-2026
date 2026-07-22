from hobbit.game import Game
from hobbit.ui import BugfixNote, Note, present


def test_present_purist_strips_color_but_keeps_note_text():
    out = present([Note("Added feature")], level="purist")
    assert out == ["Added feature"]


def test_present_standard_colors_note_but_hides_bugfix():
    out = present([Note("Added feature"), BugfixNote("fixed thing")], level="standard")
    assert len(out) == 1
    assert "Added feature" in out[0]
    assert "\033[96m" in out[0]


def test_present_verbose_shows_both_colored():
    out = present([Note("added feature"), BugfixNote("fixed thing")], level="verbose")
    assert len(out) == 2
    assert "\033[96m" in out[0]
    assert "\033[93m" in out[1]


def test_present_leaves_plain_messages_alone_but_for_the_opening_letter():
    for level in ("purist", "standard", "verbose"):
        assert present(["Plain narrative"], level=level) == ["Plain narrative"]


def test_present_capitalises_lines_that_open_with_a_lower_case_name():
    """Several characters are named in lower case on purpose ('wood-elf guard',
    'giant spider'), which reads right mid-line but not at the start of one."""
    for level in ("purist", "standard", "verbose"):
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

    pure = Game(seed=1, authentic=True)
    pure.process_player_input("annotate standard")
    assert pure.annotation_level == "purist"          # and no way back out


def test_annotate_command_sets_and_reports_level():
    game = Game(seed=1)
    game.process_player_input("annotate verbose")
    assert game.annotation_level == "verbose"
    messages = game.process_player_input("annotate")
    assert any("verbose" in m for m in messages)


def test_annotate_rejects_unknown_level():
    game = Game(seed=1)
    messages = game.process_player_input("annotate nonsense")
    assert any("unknown annotation level" in m.lower() for m in messages)
    assert game.annotation_level == "standard"


def test_bugfix_note_only_surfaces_at_verbose_for_the_garden_gate():
    game = Game(seed=1)
    game.player.location_id = "bag_end_garden"
    for level, expect_bugfix in (("purist", False), ("standard", False), ("verbose", True)):
        game.annotation_level = level
        from hobbit import ui
        raw = game.process_player_input("examine gate")
        shown = ui.present(raw, level)
        has_bugfix_text = any("bugfix" in m.lower() for m in shown)
        assert has_bugfix_text is expect_bugfix


def test_examine_map_by_level():
    from hobbit import ui
    game = Game(seed=1)

    # purist == authentic: the map is unexaminable wall flavor, as in 1982
    game.annotation_level = "purist"
    raw = game.process_player_input("examine map")
    shown = ui.present(raw, "purist")
    assert any("no map" in m.lower() for m in shown)
    assert not any("moon-letters" in m.lower() for m in shown)

    # standard: real item, description colored cyan, no bugfix commentary
    game.annotation_level = "standard"
    raw = game.process_player_input("examine map")
    shown = ui.present(raw, "standard")
    assert any("\033[96m" in m and "moon-letters" in m.lower() for m in shown)
    assert not any("bugfix" in m.lower() for m in shown)

    # verbose: cyan description plus amber bugfix note
    game.annotation_level = "verbose"
    raw = game.process_player_input("examine map")
    shown = ui.present(raw, "verbose")
    assert any("\033[93m" in m and "bugfix" in m.lower() for m in shown)


def test_plain_items_stay_uncolored_when_examined():
    from hobbit import ui
    game = Game(seed=1)
    raw = game.process_player_input("examine torch")
    shown = ui.present(raw, "verbose")
    assert not any("\033[" in m for m in shown)


def test_previously_unreachable_room_shows_bugfix_note_only_at_verbose():
    from hobbit import ui
    game = Game(seed=1)
    game.player.location_id = "troll_cave"
    game.player.light_remaining = 10  # room is dark; needs light to see description

    for level, expect_bugfix in (("purist", False), ("standard", False), ("verbose", True)):
        game.annotation_level = level
        raw = game.process_player_input("look")
        shown = ui.present(raw, level)
        has_bugfix = any("bugfix" in m.lower() for m in shown)
        assert has_bugfix is expect_bugfix
        # the room description itself must always be visible regardless of level
        assert any("trolls' cave" in m.lower() for m in shown)


def test_room_without_bugfix_note_never_shows_one():
    from hobbit import ui
    game = Game(seed=1)
    game.player.location_id = "hobbiton_road"  # a room with no bugfix_note
    for level in ("purist", "standard", "verbose"):
        game.annotation_level = level
        raw = game.process_player_input("look")
        shown = ui.present(raw, level)
        assert not any("bugfix" in m.lower() for m in shown)


def test_troll_cave_items_get_bugfix_note_but_stay_uncolored_as_notes():
    from hobbit import ui
    game = Game(seed=1)
    game.player.location_id = "troll_cave"
    game.player.light_remaining = 10
    game.player.inventory.append("sting")

    game.annotation_level = "standard"
    raw = game.process_player_input("examine sting")
    shown = ui.present(raw, "standard")
    # not a "new feature" (Note) -- Sting is faithful content, so no cyan
    assert not any("\033[96m" in m for m in shown)
    assert not any("bugfix" in m.lower() for m in shown)

    game.annotation_level = "verbose"
    raw = game.process_player_input("examine sting")
    shown = ui.present(raw, "verbose")
    assert any("\033[93m" in m and "bugfix" in m.lower() for m in shown)


def test_inventory_listing_colors_only_the_added_item_name():
    from hobbit import ui
    game = Game(seed=1)
    game.player.inventory = ["thorin_map", "torch"]  # gear only, no loaves

    raw = game.process_player_input("inventory")
    line = raw[0]

    purist = ui.present([line], "purist")[0]
    assert purist.startswith("You are carrying: old map, torch.")

    standard = ui.present([line], "standard")[0]
    assert f"{ui.ADDITION_COLOR}old map{ui.RESET}" in standard
    assert ", torch." in standard  # torch itself stays uncolored
    assert standard.count(ui.ADDITION_COLOR) == 1  # only the map, not the whole line


def test_you_see_line_colors_only_the_added_item_name():
    from hobbit import ui
    game = Game(seed=1)
    raw = game.process_player_input("look")
    line = next(m for m in raw if "You see" in m)

    purist = ui.present([line], "purist")[0]
    assert "old map" in purist and "\033[" not in purist

    standard = ui.present([line], "standard")[0]
    assert f"{ui.ADDITION_COLOR}old map{ui.RESET}" in standard
    assert "walking stick" in standard and f"{ui.ADDITION_COLOR}walking stick" not in standard


def test_take_and_wield_messages_color_only_added_item_names():
    from hobbit import ui
    game = Game(seed=1)

    raw = game.process_player_input("take map")
    shown_standard = ui.present(raw, "standard")
    assert any(f"{ui.ADDITION_COLOR}old map{ui.RESET}" in m for m in shown_standard)

    raw = game.process_player_input("take torch")
    shown_standard = ui.present(raw, "standard")
    assert not any(ui.ADDITION_COLOR in m for m in shown_standard)
