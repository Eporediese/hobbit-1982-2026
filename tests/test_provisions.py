"""Tests for food (carried as real, stackable items), food sources, status
readouts, NPC self-care, and party cohesion."""
from hobbit.game import Game
from hobbit.entities import HUNGER_WEAK


def _food(game, character):
    return game.food_count(character)


def _place(game, cid, room):
    char = game.characters[cid]
    old = game.world.get(char.location_id)
    if cid in old.npcs:
        old.npcs.remove(cid)
    char.location_id = room
    if cid not in game.world.get(room).npcs:
        game.world.get(room).npcs.append(cid)


def test_everyone_starts_with_a_single_loaf():
    """Provisioning at the bakery is the first order of business -- nobody
    sets out already stocked."""
    game = Game(seed=1)
    assert _food(game, game.player) == 1
    bombur = game.characters["bombur"]
    assert _food(game, bombur) == 1
    assert bombur.max_carry > game.player.max_carry  # Bombur can lug more


def test_food_source_clause_shows_in_enhanced_and_reverts_in_purist():
    from hobbit import ui
    game = Game(seed=1)
    game.player.location_id = "green_dragon_inn"
    block = ui.present(game.describe_location(game.player), game.annotation_level)[0]
    assert "Baskets of fresh loaves" in block
    assert "\033[" not in block           # shown, but no longer tinted
    assert "cheerful inn" in block

    pure = Game(seed=1, authentic=True)
    pure.player.location_id = "green_dragon_inn"
    pblock = ui.present(pure.describe_location(pure.player), pure.annotation_level)[0]
    assert "Baskets of fresh loaves" not in pblock
    assert "cheerful inn" in pblock


def test_food_is_carried_as_a_real_stackable_item():
    game = Game(seed=1)
    game.add_food(game.player, game.STAPLE_FOOD, 2)  # now carrying 3 loaves
    msgs = game.process_player_input("inventory")
    assert any("loaf of bread (x3)" in m.lower() for m in msgs)


def test_grabbing_a_loaf_at_a_settlement_adds_a_real_loaf():
    game = Game(seed=1)
    game.player.location_id = "green_dragon_inn"
    # empty the pack, then grab loaves one at a time
    game.player.inventory = [i for i in game.player.inventory
                             if not game.items.get(i).is_food]
    assert _food(game, game.player) == 0
    game.process_player_input("take loaf")
    assert _food(game, game.player) == 1
    assert game.items.get(game.player.inventory[-1]).is_food


def test_take_food_is_capped_by_total_carry_limit():
    game = Game(seed=1)
    game.player.location_id = "green_dragon_inn"
    game.player.inventory = []
    game.fill_food(game.player)  # fill all carrying space with loaves
    assert len(game.player.inventory) == game.player.max_carry
    msgs = game.process_player_input("take loaf")
    assert any("full" in m.lower() or "carry only" in m.lower() for m in msgs)


def test_world_food_like_mutton_is_carried_as_an_item():
    game = Game(seed=1)
    game.player.location_id = "troll_cave"
    game.player.light_remaining = 20
    game.player.inventory = []  # make room
    game.process_player_input("take mutton")
    assert "mutton" in game.player.inventory


def test_stock_up_only_at_food_sources():
    game = Game(seed=1)
    game.player.inventory = []  # empty pack
    msgs = game.process_player_input("stock up")
    assert _food(game, game.player) == 0
    assert any("nowhere" in m.lower() for m in msgs)
    game.player.location_id = "green_dragon_inn"
    game.process_player_input("stock up")
    assert _food(game, game.player) == game.player.max_carry


def test_food_line_names_the_actual_food_not_just_loaves():
    """Regression: 'Food: 2 loaves' when the pack held a loaf and a leg of
    mutton."""
    game = Game(seed=1)
    game.player.inventory = ["bread", "mutton"]
    msgs = game.process_player_input("status")
    food_line = next(m for m in msgs if "Food:" in m)
    assert "loaf of bread" in food_line and "leg of mutton" in food_line
    assert "loaves" not in food_line


def test_give_respects_receivers_carry_capacity():
    game = Game(seed=1)
    bombur = game.characters["bombur"]
    bombur.location_id = game.player.location_id
    if "bombur" not in game.world.get(game.player.location_id).npcs:
        game.world.get(game.player.location_id).npcs.append("bombur")
    bombur.inventory = ["bread"] * bombur.max_carry  # loaded to his weight limit
    game.player.inventory = ["gold_coins_small"]
    msgs = " ".join(game.process_player_input("give coins to bombur"))
    # Rather than refuse, he sets down lighter loaves to take the gold.
    assert "sets down" in msgs
    assert "gold_coins_small" in bombur.inventory
    assert "gold_coins_small" not in game.player.inventory
    assert game.carried_weight(bombur) <= bombur.max_carry
    assert "bread" in game.world.get(game.player.location_id).items


def test_give_refuses_when_nothing_lighter_can_be_spared():
    game = Game(seed=1)
    thorin = game.characters["thorin"]
    thorin.location_id = game.player.location_id
    if "thorin" not in game.world.get(game.player.location_id).npcs:
        game.world.get(game.player.location_id).npcs.append("thorin")
    # full of things all heavier than a loaf, so there is nothing light to shed
    thorin.inventory = ["treasure_hoard", "torch"]  # 14 + 2 = 16, his limit
    game.player.inventory = ["bread"]
    msgs = " ".join(game.process_player_input("give bread to thorin"))
    assert "no room" in msgs.lower()
    assert "bread" in game.player.inventory  # nothing was lost


def test_eat_consumes_one_loaf_and_restores_hunger():
    game = Game(seed=1)
    game.player.hunger = 50
    before = _food(game, game.player)
    game.process_player_input("eat")
    assert _food(game, game.player) == before - 1
    assert game.player.hunger < 50


def test_eat_with_no_food_is_graceful():
    game = Game(seed=1)
    game.player.inventory = []
    msgs = game.process_player_input("eat")
    assert any("no food" in m.lower() for m in msgs)


def test_status_and_party_readouts():
    game = Game(seed=1)
    status = game.process_player_input("status")
    joined = " ".join(status).lower()
    assert "bilbo" in joined and "food:" in joined
    party = game.process_player_input("party")
    assert any("thorin" in m.lower() for m in party)


def test_npc_auto_eats_when_hungry():
    game = Game(seed=1)
    thorin = game.characters["thorin"]
    thorin.hunger = HUNGER_WEAK
    before = _food(game, thorin)
    game._npc_upkeep(thorin)
    assert _food(game, thorin) == before - 1
    assert thorin.hunger < HUNGER_WEAK


def test_npc_restocks_at_food_source():
    game = Game(seed=1)
    balin = game.characters["balin"]
    balin.inventory = []  # out of food
    game.world.get("bag_end").npcs.remove("balin")
    balin.location_id = "green_dragon_inn"
    game.world.get("green_dragon_inn").npcs.append("balin")
    game._npc_upkeep(balin)
    # Companions provision sensibly rather than cramming the pack: a brimful
    # pack would leave them permanently laden and forever stopping to shift it.
    assert _food(game, balin) > 0
    assert game.carried_weight(balin) <= balin.max_carry * game.NPC_PACK_TARGET
    assert game.load_burden(balin) == 0  # able to march unencumbered


def test_hungry_npc_with_empty_pack_forages():
    game = Game(seed=1)
    balin = game.characters["balin"]
    balin.inventory = []
    balin.hunger = HUNGER_WEAK
    target, desc, kind = balin.brain._scripted_goal(balin, game)
    assert target == "green_dragon_inn"
    assert kind == "forage"


def test_party_stays_near_bilbo_when_he_dawdles():
    game = Game(seed=1)
    for _ in range(40):
        game._advance_world_turn()  # Bilbo never moves from Bag End
    thorin = game.characters["thorin"]
    assert game.world.distance("bag_end", thorin.location_id) <= 2  # stays with him


def test_party_travels_with_bilbo_when_he_moves():
    game = Game(seed=1)
    for _ in range(6):
        game.process_player_input("go east")  # Bilbo journeys east
    for cid in ("thorin", "balin"):
        d = game.world.distance(game.characters[cid].location_id, game.player.location_id)
        assert d <= 3, f"{cid} lagged {d} rooms behind"


# -- havens: local fare, real meals, and visible mending -------------------

def test_each_haven_supplies_its_own_fare():
    game = Game(seed=1)
    assert game.staple_at("rivendell_hall") == "elvish_bread"
    assert game.staple_at("green_dragon_inn") == "bread"
    assert game.staple_at("lake_town_market") == "cram"
    assert game.staple_at("bag_end") == game.STAPLE_FOOD  # nowhere special


def test_waybread_is_worth_more_than_a_loaf_and_still_carryable():
    game = Game(seed=1)
    waybread, loaf = game.items.get("elvish_bread"), game.items.get("bread")
    assert waybread.food_value > loaf.food_value
    assert waybread.takeable and waybread.weight <= loaf.weight


def test_stocking_up_at_rivendell_yields_waybread():
    game = Game(seed=1)
    game.player.location_id = "rivendell_hall"
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("stock up"))
    assert "waybread" in msgs
    assert "elvish_bread" in game.player.inventory


def test_a_haven_meal_fully_sates_and_costs_no_rations():
    """The hosts do the feeding -- 'a hearty meal' should mean one."""
    game = Game(seed=1)
    balin = game.characters["balin"]
    _place(game, "balin", "rivendell_hall")
    balin.hunger = 100
    balin.inventory = []           # nothing of his own to eat
    game._npc_upkeep(balin)
    assert balin.hunger == 0       # properly fed by the house


def test_a_wounded_companion_mends_at_rivendell_and_it_is_announced():
    game = Game(seed=1)
    game.player.location_id = "rivendell_hall"
    balin = game.characters["balin"]
    _place(game, "balin", "rivendell_hall")
    balin.hunger, balin.fatigue, balin.health = 100, 100, 5
    seen = []
    for _ in range(4):
        seen += [str(getattr(m, "text", m)) for m in game._advance_world_turn()]
    assert balin.health > 5
    assert any("mend" in m for m in seen)


def test_elrond_keeps_his_house_and_speaks_of_healing():
    game = Game(seed=1)
    elrond = game.characters["elrond"]
    assert elrond.location_id == "rivendell_hall"
    assert not elrond.def_.is_party      # not a companion
    assert not game.is_hostile_pair(elrond, game.player)
    start = elrond.location_id
    for _ in range(20):
        game._advance_world_turn()
    assert elrond.location_id == start   # he never leaves
    game.player.location_id = "rivendell_hall"
    said = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("talk to elrond"))
    assert "mends" in said or "rest" in said.lower()
