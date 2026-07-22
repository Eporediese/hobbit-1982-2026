"""Tests for party quality-of-life: free info commands, message collapsing,
healing, and desynchronised needs."""
from hobbit.game import Game, _collapse_company_messages
from hobbit.ui import Note


def test_info_commands_cost_no_game_time():
    game = Game(seed=1)
    turn0 = game.turn
    hunger0 = game.player.hunger
    for cmd in ("status", "party", "inventory", "look", "help", "examine map"):
        game.process_player_input(cmd)
    assert game.turn == turn0
    assert game.player.hunger == hunger0  # nobody got hungrier from reading


def test_action_commands_do_cost_game_time():
    game = Game(seed=1)
    turn0 = game.turn
    game.process_player_input("go east")
    assert game.turn == turn0 + 1


def test_company_movement_lines_collapse():
    msgs = [f"{n} goes east." for n in
            ("Thorin Oakenshield", "Balin", "Dwalin", "Fili", "Kili")]
    out = _collapse_company_messages(msgs)
    assert out == ["The company heads east."]


def test_company_catchup_lines_collapse():
    msgs = [f"{n} catches up." for n in ("Balin", "Dwalin", "Fili", "Kili")]
    assert _collapse_company_messages(msgs) == ["The company catches up."]


def test_companions_arriving_at_bilbo_read_as_catching_up():
    """A companion entering Bilbo's room 'catches up' -- it shouldn't read as
    'heads east' (direction of travel) when they're actually rejoining him."""
    game = Game(seed=1)
    here = "lone_lands_2"
    behind = "lone_lands_1"
    game.player.location_id = here
    balin = game.characters["balin"]
    game.world.get(balin.location_id).npcs.remove("balin")
    balin.location_id = behind
    game.world.get(behind).npcs.append("balin")
    # let cohesion pull Balin forward until he reaches Bilbo
    saw_catchup = False
    for _ in range(4):
        msgs = [getattr(m, "text", m) for m in game._advance_world_turn()]
        if any("Balin catches up." == m for m in msgs):
            saw_catchup = True
        if balin.location_id == here:
            break
    assert balin.location_id == here
    assert saw_catchup


def test_company_eating_lines_collapse():
    msgs = [f"{n} pauses to eat some loaf of bread." for n in
            ("Balin", "Dwalin", "Fili", "Kili")]
    out = _collapse_company_messages(msgs)
    assert out == ["The company pauses to eat."]


def test_two_movers_are_not_collapsed():
    msgs = ["Balin goes east.", "Dwalin goes east."]
    assert _collapse_company_messages(msgs) == msgs


def test_mixed_lines_keep_order_and_notes_pass_through():
    msgs = ["You take the iron key.",
            "Balin goes east.", "Dwalin goes east.", "Fili goes east.",
            Note("a note line"),
            'Thorin Oakenshield says: "Onward!"']
    out = _collapse_company_messages(msgs)
    assert out[0] == "You take the iron key."
    assert "The company heads east." in out
    assert any(isinstance(m, Note) for m in out)
    assert out[-1] == 'Thorin Oakenshield says: "Onward!"'


def test_wounded_characters_heal_when_fed_and_rested():
    game = Game(seed=1)
    thorin = game.characters["thorin"]
    thorin.health = thorin.max_health - 5
    thorin.hunger = 0
    thorin.fatigue = 0
    before = thorin.health
    game._advance_world_turn()
    assert thorin.health > before


def test_party_gives_distance_and_direction_for_absent_members():
    """Regression: three rooms are all named 'The Lone-lands', so 'at The
    Lone-lands' was ambiguous when Bilbo was standing in another of them."""
    game = Game(seed=1)
    game.player.location_id = "lone_lands_3"
    gandalf = game.characters["gandalf"]
    game.world.get("bag_end").npcs.remove("gandalf")
    gandalf.location_id = "lone_lands_1"  # same name, different room
    game.world.get("lone_lands_1").npcs.append("gandalf")
    msgs = game.process_player_input("party")
    gline = next(m for m in msgs if "Gandalf" in m)
    assert "2 rooms" in gline and "west" in gline


def test_travel_works_up_an_appetite():
    game = Game(seed=1)
    h0 = game.player.hunger
    game.process_player_input("go east")
    # base tick (2) plus travel appetite (1)
    assert game.player.hunger == h0 + 3


def test_company_needs_are_staggered_at_start():
    game = Game(seed=1)
    hungers = {c.hunger for cid, c in game.characters.items()
               if cid != "bilbo" and getattr(c, "def_", None) and c.def_.is_party}
    assert len(hungers) > 3  # not everyone identical


# -- wording -------------------------------------------------------------

def test_single_characters_are_not_given_plural_pronouns():
    """'Dwalin stops to catch their breath' -- one dwarf, plural pronoun. The
    lines about a single character are phrased without a pronoun at all."""
    game = Game(seed=1)
    balin = game.characters["balin"]
    balin.fatigue = 50
    msgs = [str(getattr(m, "text", m)) for m in game._npc_upkeep(balin)[0]]
    assert any("stops for breath" in m for m in msgs)
    assert not any("their" in m for m in msgs)

    thorin = game.characters["thorin"]
    thorin.wield_weapon("orcrist", 8, 1)
    msgs = [str(getattr(m, "text", m)) for m in game._npc_upkeep(thorin)[0]]
    assert not any("their" in m for m in msgs)


def test_the_company_keeps_its_plural_pronoun_when_collapsed():
    out = _collapse_company_messages(
        [f"{n} stops for breath." for n in ("Balin", "Dwalin", "Fili")])
    assert out == ["The company stops for breath."]


def test_proper_named_items_take_no_article():
    """You wield Sting, not 'the Sting'; and never 'the the Arkenstone'."""
    from hobbit.ui import with_article
    assert with_article("Sting") == "Sting"
    assert with_article("Orcrist") == "Orcrist"
    assert with_article("the Arkenstone") == "the Arkenstone"
    assert with_article("torch") == "the torch"
    assert with_article("loaf of bread") == "the loaf of bread"
