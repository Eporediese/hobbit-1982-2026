"""Goblin abductions and what a kill leaves behind.

Companions used to be seized regardless of company, so a dwarf could be
freed and re-taken in the very cell he stood in, with Bilbo watching. And
loot dropped in total silence, so the key the goblin chapter turns on could
lie unnoticed on the floor forever.
"""
from hobbit.game import Game


def _place(game, cid, room):
    char = game.characters[cid]
    old = game.world.get(char.location_id)
    if cid in old.npcs:
        old.npcs.remove(cid)
    char.location_id = room
    if cid not in game.world.get(room).npcs:
        game.world.get(room).npcs.append(cid)


# -- abductions -----------------------------------------------------------

def test_a_lone_companion_in_the_dark_can_still_be_taken():
    game = Game(seed=1)
    _place(game, "balin", "goblin_tunnel_1")
    game.player.location_id = "bag_end"  # far away
    assert game.can_be_seized(game.characters["balin"])


def test_bilbos_presence_is_protection_not_immunity():
    """In the tale the tunnels take the whole company, so a snatch at Bilbo's
    side is harder -- not impossible."""
    game = Game(seed=1)
    balin = game.characters["balin"]
    _place(game, "balin", "goblin_tunnel_1")
    game.player.location_id = "bag_end"
    adrift = game.seizure_chance(balin)
    game.player.location_id = "goblin_tunnel_1"
    beside = game.seizure_chance(balin)
    assert 0 < beside < adrift


def test_stragglers_are_fair_game_even_in_company():
    """Goblins take the ones who drift. Requiring total solitude made captures
    impossible once the company travelled together properly -- what protects
    you is being at Bilbo's side, not merely having a dwarf nearby."""
    game = Game(seed=1)
    for cid in ("balin", "dwalin"):
        _place(game, cid, "goblin_tunnel_1")
    game.player.location_id = "bag_end"  # they have drifted away from Bilbo
    assert game.can_be_seized(game.characters["balin"])


def test_no_one_is_dragged_to_the_cell_they_are_already_in():
    """The rescue/recapture loop: freed in the dungeon, seized again on the
    spot, 'taken' to the room they were standing in."""
    game = Game(seed=1)
    _place(game, "balin", "goblin_dungeon")
    game.player.location_id = "bag_end"
    assert not game.can_be_seized(game.characters["balin"])


def test_abductions_end_once_the_great_goblin_falls():
    game = Game(seed=1)
    _place(game, "balin", "goblin_tunnel_1")
    game.player.location_id = "bag_end"
    balin = game.characters["balin"]
    assert game.can_be_seized(balin)          # captain still rules the tunnels
    game.characters["goblin_captain"].alive = False
    assert game.goblins_routed()
    assert not game.can_be_seized(balin)      # leaderless goblins take no one


def test_rescued_company_is_not_re_taken_in_the_dungeon():
    """End to end: free the captives and nobody gets snatched back."""
    game = Game(seed=3)
    cell = "goblin_dungeon"
    game.player.location_id = cell
    game.player.light_remaining = 200
    for cid in ("balin", "dwalin", "bifur", "bofur"):
        _place(game, cid, cell)
        game.characters[cid].captured = True
    for _ in range(15):
        game._advance_world_turn()
    assert not any(game.characters[c].captured
                   for c in ("balin", "dwalin", "bifur", "bofur"))


# -- loot -----------------------------------------------------------------

def _seize(game, cid, from_room="goblin_tunnel_2"):
    """Force the goblins to take a companion, and return their cell."""
    npc = game.characters[cid]
    _place(game, cid, from_room)
    game.player.location_id = "bag_end"
    game.rng.random = lambda: 0.0
    npc.brain.decide(npc, game)
    return npc.location_id


def test_goblins_rob_their_prisoners():
    game = Game(seed=1)
    bombur = game.characters["bombur"]
    bombur.inventory = ["treasure_hoard", "gold_coins_small", "bread"]
    cell = _seize(game, "bombur")
    assert bombur.captured
    assert "treasure_hoard" not in bombur.inventory   # stripped of the gold
    assert "bread" in bombur.inventory                # but keeps his supper
    spoils = [i for i in game.world.get(cell).items if game.items.get(i).value > 0]
    assert set(spoils) == {"treasure_hoard", "gold_coins_small"}


def test_a_captives_treasure_counts_for_nothing():
    """He is still in a cell -- he carried nothing out."""
    game = Game(seed=1)
    game.characters["bombur"].inventory = ["treasure_hoard", "gold_coins_small"]
    assert game.treasure_total() > 0
    _seize(game, "bombur")
    assert game.treasure_total() == 0


def test_a_still_captive_companion_is_left_out_of_the_reckoning():
    """Belt and braces: even if a captive somehow holds something of worth,
    it never counts while he's imprisoned."""
    game = Game(seed=1)
    balin = game.characters["balin"]
    balin.captured = True
    balin.inventory = ["gold_goblet"]
    assert game.treasure_total() == 0


def test_freeing_him_wins_back_the_plunder():
    game = Game(seed=1)
    game.characters["bombur"].inventory = ["gold_coins_small"]
    cell = _seize(game, "bombur")
    game.player.location_id = cell
    game.player.light_remaining = 200
    game._resolve_rescues()
    assert not game.characters["bombur"].captured
    game.process_player_input("take coins")
    assert game.treasure_total() > 0  # recovered along with the prisoner


def test_the_robbery_is_never_narrated():
    """It happens in the deeps, far from Bilbo -- he cannot see or hear it.
    Finding the hoard in the cell is how he learns of it."""
    game = Game(seed=1)
    game.characters["bombur"].inventory = ["gold_coins_small"]
    _seize(game, "bombur")
    news = " ".join(str(getattr(m, "text", m)) for m in game._deliver_company_news())
    assert "strip" not in news
    assert "gold coins" not in news
    # the capture itself is still heard -- that's a cry down the tunnels
    assert "taken by goblins" in news


def test_a_kill_announces_what_it_leaves_behind():
    game = Game(seed=2)
    room = "goblin_throne_room"
    game.player.location_id = room
    game.player.light_remaining = 50
    _place(game, "goblin_captain", room)
    captain = game.characters["goblin_captain"]
    captain.health = 1
    game.rng.random = lambda: 0.0  # never miss
    msgs = " ".join(getattr(m, "text", m)
                    for m in game.process_player_input("attack goblin"))
    assert "goblin cell key" in msgs          # the drop is announced
    assert "key_goblin_cell" in game.world.get(room).items


def test_a_fallen_companions_gear_is_announced_too():
    game = Game(seed=1)
    thorin = game.characters["thorin"]
    thorin.inventory = ["gold_goblet"]
    thorin.alive = False
    msgs = " ".join(getattr(m, "text", m) for m in game.handle_death(thorin))
    assert "golden goblet" in msgs


def test_sentences_do_not_open_in_lower_case():
    from hobbit.ui import sentence
    assert sentence("the Great Goblin has been defeated!").startswith("The")
    assert sentence("goblin scout hits Bilbo.").startswith("Goblin")
    assert sentence("Bilbo hits.").startswith("Bilbo")


# -- locked doors ---------------------------------------------------------

def test_a_locked_door_names_the_key_you_need():
    game = Game(seed=1)
    door_room = next(rid for rid, loc in game.world.locations.items()
                     if "goblin_dungeon" in loc.exits.values())
    game.player.location_id = door_room
    game.player.light_remaining = 50
    msgs = " ".join(getattr(m, "text", m)
                    for m in game.process_player_input("open door"))
    assert "goblin cell key" in msgs


# -- Mirkwood: the spiders take those who blunder in the dark --------------

def test_spiders_web_a_dwarf_who_wanders_mirkwood_unlit():
    game = Game(seed=1)
    balin = game.characters["balin"]
    _place(game, "balin", "mirkwood_path_2")
    game.player.location_id = "bag_end"
    balin.inventory = []                    # no light
    game.rng.random = lambda: 0.0
    balin.brain.decide(balin, game)
    assert balin.captured
    assert balin.location_id == "spiders_nest"
    news = " ".join(str(getattr(m, "text", m)) for m in game._deliver_company_news())
    assert "webs" in news or "webbed" in news
    assert "goblins" not in news            # the right captor's flavour


def test_one_torch_lights_the_room_for_everyone_in_it():
    """There is a single torch in all the world, so it must serve the party:
    whoever holds it lets the whole room fight -- and nobody in the next one."""
    game = Game(seed=1)
    balin, dwalin = game.characters["balin"], game.characters["dwalin"]
    for cid in ("balin", "dwalin"):
        _place(game, cid, "mirkwood_path_2")
        game.characters[cid].inventory = []
    game.player.location_id = "bag_end"
    assert game.seizure_chance(balin) > 0 and game.seizure_chance(dwalin) > 0

    dwalin.inventory = ["torch"]           # one torch, held by one dwarf
    assert game.room_is_lit("mirkwood_path_2")
    assert game.seizure_chance(balin) == 0.0   # protects his companion too
    assert game.seizure_chance(dwalin) == 0.0

    _place(game, "ori", "mirkwood_path_3")     # a straggler, a room behind
    game.characters["ori"].inventory = []
    assert game.seizure_chance(game.characters["ori"]) > 0


def test_the_torch_does_not_save_them_it_lets_them_fight():
    """Light isn't a ward against spiders -- it's the difference between
    swinging a blade and groping blindly while you're wrapped up."""
    game = Game(seed=1)
    balin = game.characters["balin"]
    _place(game, "balin", "spiders_nest")
    _place(game, "giant_spider", "spiders_nest")
    game.characters["giant_spider"].alive = True
    game.player.location_id = "bag_end"

    balin.inventory = []                       # blind: no blow to be struck
    assert not game.can_fight_here("spiders_nest")
    assert balin.brain.decide(balin, game) is None or True
    loc = game.world.get("spiders_nest")
    assert game.choose_combat_target(balin, loc)      # the foe is right there
    cmd = balin.brain.decide(balin, game)
    assert cmd is None or cmd.verb != "attack"        # yet he cannot strike

    balin.captured = False
    balin.inventory = ["torch"]                # a light, and now he fights
    assert game.can_fight_here("spiders_nest")
    cmd = balin.brain.decide(balin, game)
    assert cmd is not None and cmd.verb == "attack"


def test_goblins_are_not_deterred_by_torchlight():
    """They know their own tunnels blind -- a lamp only helps in the forest."""
    game = Game(seed=1)
    balin = game.characters["balin"]
    _place(game, "balin", "goblin_tunnel_1")
    game.player.location_id = "bag_end"
    balin.inventory = ["torch"]
    assert game.seizure_chance(balin) > 0


def test_spiders_have_no_use_for_gold():
    game = Game(seed=1)
    balin = game.characters["balin"]
    _place(game, "balin", "mirkwood_path_2")
    game.player.location_id = "bag_end"
    balin.inventory = ["gold_coins_small"]
    game.rng.random = lambda: 0.0
    balin.brain.decide(balin, game)
    assert balin.captured
    assert "gold_coins_small" in balin.inventory  # unlike the goblins


def test_webbing_stops_once_the_great_spider_is_slain():
    game = Game(seed=1)
    balin = game.characters["balin"]
    _place(game, "balin", "mirkwood_path_2")
    game.player.location_id = "bag_end"
    balin.inventory = []
    assert game.seizure_chance(balin) > 0
    game.characters["giant_spider"].alive = False
    assert game.captors_routed("mirkwood")
    assert game.seizure_chance(balin) == 0.0


def test_no_one_is_webbed_inside_the_nest_itself():
    game = Game(seed=1)
    balin = game.characters["balin"]
    _place(game, "balin", "spiders_nest")
    game.player.location_id = "bag_end"
    balin.inventory = []
    assert game.seizure_chance(balin) == 0.0


def test_cutting_the_webbed_free_works_like_any_rescue():
    game = Game(seed=1)
    for cid in ("balin", "ori"):
        _place(game, cid, "mirkwood_path_2")
        game.characters[cid].inventory = []
    game.player.location_id = "bag_end"
    game.rng.random = lambda: 0.0
    for cid in ("balin", "ori"):
        game.characters[cid].brain.decide(game.characters[cid], game)
    assert all(game.characters[c].captured for c in ("balin", "ori"))
    game.player.location_id = "spiders_nest"
    game.player.light_remaining = 200
    game._resolve_rescues()
    assert not any(game.characters[c].captured for c in ("balin", "ori"))
