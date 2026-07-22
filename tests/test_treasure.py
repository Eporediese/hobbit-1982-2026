"""Treasure and burden: packs hold a weight rather than a count, the haul is
reckoned across the whole company, and the Arkenstone means something to
Thorin."""
from hobbit.game import Game


def _place(game, cid, room):
    char = game.characters[cid]
    old = game.world.get(char.location_id)
    if cid in old.npcs:
        old.npcs.remove(cid)
    char.location_id = room
    if cid not in game.world.get(room).npcs:
        game.world.get(room).npcs.append(cid)


# -- weight ---------------------------------------------------------------

def test_pack_holds_a_weight_not_a_count():
    game = Game(seed=1)
    bilbo = game.player
    bilbo.inventory = []
    # six light loaves fit; a single heavy heap (7) does not
    assert game.add_food(bilbo, "bread", 6) == 6
    assert game.carried_weight(bilbo) == 6
    bilbo.inventory = []
    assert not game.can_carry(bilbo, game.items.get("treasure_hoard"))


def test_a_hobbit_cannot_shift_a_dragons_hoard_but_a_dwarf_can():
    game = Game(seed=1)
    hoard = game.items.get("treasure_hoard")
    for c in (game.player, game.characters["thorin"], game.characters["bombur"]):
        c.inventory = []
    assert not game.can_carry(game.player, hoard)       # Bilbo, capacity 6
    assert game.can_carry(game.characters["thorin"], hoard)   # a dwarf, 8
    assert game.can_carry(game.characters["bombur"], hoard)   # Bombur, 12


def test_heavy_load_costs_extra_march_fatigue():
    game = Game(seed=1)
    bilbo = game.player
    bilbo.inventory = []
    assert game.load_burden(bilbo) == 0
    bilbo.inventory = ["bread"] * 8  # 8/12 -- a good stock of bread, no burden
    assert game.load_burden(bilbo) == 0
    bilbo.inventory = ["bread"] * 9  # 9/12
    assert game.load_burden(bilbo) == 1
    bilbo.inventory = ["gold_coins_small", "gold_coins_small"]  # 12/12, brimful
    assert game.load_burden(bilbo) == 2
    # and that burden really does tire you faster on the road
    bilbo.fatigue = 0
    bilbo.add_travel_fatigue(game.load_burden(bilbo))
    laden = bilbo.fatigue
    bilbo.inventory, bilbo.fatigue = [], 0
    bilbo.add_travel_fatigue(game.load_burden(bilbo))
    assert laden > bilbo.fatigue


def test_a_heavily_laden_companion_sometimes_pauses():
    game = Game(seed=1)
    balin = game.characters["balin"]
    balin.inventory = ["treasure_hoard", "bread"]  # 8/8 -- fully burdened
    balin.hunger = balin.fatigue = 0
    game.rng.random = lambda: 0.0  # force the pause
    _msgs, skip = game._npc_upkeep(balin)
    assert game.is_heavily_laden(balin)
    assert skip  # spends the turn shifting the load instead of marching


def test_companions_keep_headroom_when_restocking():
    game = Game(seed=1)
    balin = game.characters["balin"]
    balin.inventory = []
    _place(game, "balin", "green_dragon_inn")
    game._npc_upkeep(balin)
    assert game.load_burden(balin) == 0  # never laden just from provisioning


# -- the company's haul ---------------------------------------------------

def test_treasure_is_reckoned_across_the_whole_company():
    game = Game(seed=1)
    game.player.inventory = ["arkenstone"]
    game.characters["bombur"].inventory = ["treasure_hoard"]
    game.characters["thorin"].inventory = ["gold_goblet"]
    bearers = {b for b, _, _ in game.company_treasure()}
    assert bearers == {"Bilbo Baggins", "Bombur", "Thorin Oakenshield"}
    assert game.treasure_total() == 1000 + 900 + 120
    text = " ".join(getattr(m, "text", m) for m in game.treasure_reckoning())
    assert "Bombur" in text and "heap of treasure" in text


def test_treasure_lost_with_the_dead_is_not_counted():
    game = Game(seed=1)
    thorin = game.characters["thorin"]
    thorin.inventory = ["gold_goblet"]
    assert game.treasure_total() == 120
    thorin.alive = False
    assert game.treasure_total() == 0


def test_ordinary_gear_is_worth_nothing_in_the_reckoning():
    game = Game(seed=1)
    game.player.inventory = ["bread", "torch", "sting"]
    assert game.treasure_total() == 0


# -- the Arkenstone -------------------------------------------------------

def test_giving_the_arkenstone_to_thorin_delights_him():
    game = Game(seed=1)
    game.player.inventory = ["arkenstone"]
    _place(game, "thorin", game.player.location_id)
    game.characters["thorin"].inventory = []
    msgs = " ".join(getattr(m, "text", m)
                    for m in game.process_player_input("give arkenstone to thorin"))
    assert "arkenstone" in game.characters["thorin"].inventory
    assert "king's gift" in msgs
    assert any("Arkenstone" in n for n in game.company_lore)


def test_thorin_claims_the_arkenstone_if_he_is_there_when_it_is_lifted():
    game = Game(seed=1)
    room = game.player.location_id
    game.world.get(room).items.append("arkenstone")
    _place(game, "thorin", room)
    game.characters["thorin"].inventory = []
    msgs = " ".join(getattr(m, "text", m)
                    for m in game.process_player_input("take arkenstone"))
    assert "arkenstone" in game.characters["thorin"].inventory
    assert "arkenstone" not in game.player.inventory
    assert "It is mine" in msgs


def test_bilbo_keeps_the_arkenstone_when_thorin_is_absent():
    game = Game(seed=1)
    room = game.player.location_id
    game.world.get(room).items.append("arkenstone")
    _place(game, "thorin", "rivendell_hall")
    game.process_player_input("take arkenstone")
    assert "arkenstone" in game.player.inventory


def test_gold_coins_answer_to_gold_and_to_gold_coins():
    game = Game(seed=1)
    coins = game.items.get("gold_coins_small")
    for phrase in ("gold", "coins", "gold coins", "pile", "small pile of gold coins"):
        assert coins.matches(phrase), phrase


def test_multi_word_matching_did_not_loosen_other_items():
    game = Game(seed=1)
    coins = game.items.get("gold_coins_small")
    assert not coins.matches("silver coins")
    assert not coins.matches("gold ring")


def test_a_laden_companion_sheds_lighter_things_to_take_a_gift():
    game = Game(seed=1)
    bombur = game.characters["bombur"]
    _place(game, "bombur", game.player.location_id)
    bombur.inventory = ["bread"] * bombur.max_carry  # brimful of loaves
    game.player.inventory = ["gold_coins_small"]
    msgs = " ".join(game.process_player_input("give gold coins to bombur"))
    assert "sets down" in msgs
    assert "(x" in msgs  # repeats are stacked, not listed one by one
    assert "gold_coins_small" in bombur.inventory
    assert game.food_count(bombur) >= 2  # never stripped of his last meals


def test_shedding_never_drops_the_weapon_in_hand():
    game = Game(seed=1)
    thorin = game.characters["thorin"]
    _place(game, "thorin", game.player.location_id)
    thorin.inventory = ["orcrist"] + ["bread"] * 11  # 5 + 11 = 16, his limit
    thorin.wield_weapon("orcrist", 8, 1)
    game.player.inventory = ["gold_coins_small"]
    room = game.player.location_id
    game.process_player_input("give gold to thorin")
    # He sheds loaves, never the blade in his hand (he may sheathe it later,
    # on a quiet road, but he does not set it down).
    assert "orcrist" in thorin.inventory
    assert "orcrist" not in game.world.get(room).items


def test_party_shows_who_bears_what():
    game = Game(seed=1)
    game.characters["bombur"].inventory = ["treasure_hoard"]
    game.characters["balin"].inventory = ["key_goblin_cell", "bread"]
    game.characters["fili"].inventory = ["torch"]
    game.characters["dwalin"].inventory = ["orcrist"]
    game.player.inventory = ["gold_coins_small"]
    lines = " ".join(getattr(m, "text", m) for m in game.process_player_input("party"))
    assert "heap of treasure" in lines          # treasure
    assert "goblin cell key" in lines           # keys
    assert "torch" in lines                     # a light is life in the deep places
    assert "Orcrist" in lines                   # weapons, carried or drawn
    assert "loaf of bread" not in lines         # ordinary rations are not
    assert "small pile of gold coins" in lines  # including Bilbo's own share


def test_party_reports_bilbos_own_condition():
    game = Game(seed=1)
    game.player.hunger = 70
    game.player.fatigue = 45
    lines = [getattr(m, "text", m) for m in game.process_player_input("party")]
    mine = next(l for l in lines if "(you)" in l)
    assert game.player.condition_word() in mine
    # and he's listed even when carrying nothing of note
    game.player.inventory = []
    lines = [getattr(m, "text", m) for m in game.process_player_input("party")]
    assert any("(you)" in l for l in lines)


def test_named_items_do_not_get_a_doubled_article():
    game = Game(seed=1)
    room = game.player.location_id
    game.world.get(room).items.append("arkenstone")
    _place(game, "thorin", "rivendell_hall")
    msgs = " ".join(getattr(m, "text", m)
                    for m in game.process_player_input("take arkenstone"))
    assert "the the" not in msgs


def _lair_showdown(seed=11, present=("dwalin", "bifur", "bofur", "dori")):
    from hobbit.game import Game
    game = Game(seed=seed)
    game.player.location_id = "treasure_chamber"
    game.player.light_remaining = 99999
    for d in present:
        game.characters[d].location_id = "treasure_chamber"
        game.world.get("treasure_chamber").npcs.append(d)
    return game


def test_the_hoard_is_carried_out_after_the_dragon_falls():
    """The hoard used to go uncounted: the only way to pick it up was to break
    off mid-battle and loot the floor while Smaug still breathed."""
    game = _lair_showdown()
    game.characters["smaug"].health = 1
    for _ in range(40):
        game.process_player_input("attack smaug")
        if game.won:
            break
    assert game.won
    before = game.treasure_total()
    game.gather_the_hoard()
    after = game.treasure_total()
    assert after > before
    assert after >= 2270  # Arkenstone, heap, mithril coat and goblet


def test_the_arkenstone_goes_to_thorin_if_he_lives_to_claim_it():
    game = _lair_showdown(present=("thorin", "dwalin", "bifur", "bofur"))
    game.characters["smaug"].alive = False
    game.gather_the_hoard()
    assert "arkenstone" in game.characters["thorin"].inventory


def test_bilbo_pockets_the_arkenstone_when_thorin_has_fallen():
    game = _lair_showdown()
    game.characters["smaug"].alive = False
    thorin = game.characters["thorin"]
    thorin.alive, thorin.health = False, 0
    game.gather_the_hoard()
    assert "arkenstone" in game.player.inventory


def test_the_hoard_is_bounded_by_what_the_survivors_can_bear():
    """Weight has to still mean something at the climax -- a lone hobbit
    cannot walk out with the whole Mountain."""
    game = _lair_showdown(present=())
    game.characters["smaug"].alive = False
    game.player.inventory = ["sting"]
    lines = " ".join(str(getattr(m, "text", m)) for m in game.gather_the_hoard())
    assert "Left behind" in lines
    assert game.carried_weight(game.player) <= game.player.max_carry


def test_nothing_is_taken_twice_from_the_hoard():
    game = _lair_showdown()
    game.characters["smaug"].alive = False
    game.gather_the_hoard()
    first = game.treasure_total()
    game.gather_the_hoard()
    assert game.treasure_total() == first


def test_the_victory_line_is_the_last_word_of_the_game():
    """It reads as a verdict on the burials, the hoard and the reckoning --
    not as an interruption of them."""
    game = _lair_showdown()
    game.characters["smaug"].alive = False
    lines = [str(getattr(m, "text", m)) for m in game.ending_lines()]
    assert lines[-1].strip() == "You have won!"
    joined = "\n".join(lines)
    assert joined.index("stood, at the end of it") < joined.index("reckoning of what")
    assert joined.index("reckoning of what") < joined.index("You have won!")


def test_no_one_is_buried_twice_even_if_the_graves_are_rebuilt():
    """Regression: two cairns rose over Fili. A room's grave list is rebuilt
    by a load and by reconcile_after_load, so it can't be the only memory."""
    game = _lair_showdown()
    game.characters["smaug"].alive = False
    fili = game.characters["fili"]
    fili.location_id, fili.alive, fili.health = "treasure_chamber", False, 0
    game._pending_burials = [("treasure_chamber", "Fili")]
    first = game._resolve_burials()
    assert len(first) == 1
    game.world.get("treasure_chamber").graves = []   # as a load would
    game._pending_burials = [("treasure_chamber", "Fili")]
    assert game._resolve_burials() == []


def test_the_company_sets_down_bread_to_make_room_for_treasure():
    """The road is walked. Without this the heap -- 14 of a dwarf's 16, the
    biggest prize in the Mountain -- was left behind in every single run by a
    company that had eaten well."""
    game = _lair_showdown(present=("dwalin", "kili", "gloin", "bifur", "bofur"))
    for d in ("dwalin", "kili", "gloin", "bifur", "bofur"):
        game.fill_food(game.characters[d])
    game.characters["smaug"].alive = False
    lines = " ".join(str(getattr(m, "text", m)) for m in game.gather_the_hoard())
    assert "setting down the last of their bread" in lines
    assert "Left behind" not in lines
    assert game.treasure_total() >= 2270


def test_a_broken_company_still_cannot_carry_the_heap():
    """Setting down bread must not make the haul a formality -- what comes out
    still depends on who survived to bear it."""
    game = _lair_showdown(present=("dwalin",))
    game.characters["dwalin"].inventory = ["orcrist", "torch"]
    game.characters["smaug"].alive = False
    lines = " ".join(str(getattr(m, "text", m)) for m in game.gather_the_hoard())
    assert "heap of treasure" in lines  # named as left behind


def test_thorin_thanks_the_company_over_the_arkenstone():
    game = _lair_showdown(present=("thorin", "dwalin"))
    game.characters["smaug"].alive = False
    lines = " ".join(str(getattr(m, "text", m)) for m in game.ending_lines())
    assert "arkenstone" in game.characters["thorin"].inventory
    assert "Thorin holds the Arkenstone up" in lines
    assert "we would not be standing here without you" in lines


def test_no_thanks_from_a_dead_king():
    game = _lair_showdown(present=("dwalin",))
    thorin = game.characters["thorin"]
    thorin.alive, thorin.health = False, 0
    game.characters["smaug"].alive = False
    lines = " ".join(str(getattr(m, "text", m)) for m in game.ending_lines())
    assert "Thorin holds the Arkenstone up" not in lines
    assert "arkenstone" in game.player.inventory
