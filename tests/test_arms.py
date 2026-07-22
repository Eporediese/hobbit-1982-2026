"""Tests for weapons: NPCs draw when danger is near (and sheathe at peace),
the walking stick as a walking aid + weak weapon, and travel fatigue."""
from hobbit.game import Game


def _at_the_trolls(game, cid):
    """Put a companion in the trolls' clearing (danger present) with Bilbo."""
    game.player.location_id = "trolls_clearing"
    npc = game.characters[cid]
    game.world.get("bag_end").npcs.remove(cid)
    npc.location_id = "trolls_clearing"
    game.world.get("trolls_clearing").npcs.append(cid)
    return npc


def test_gifted_weapon_is_drawn_when_danger_is_near():
    game = Game(seed=1)
    dwalin = _at_the_trolls(game, "dwalin")
    game.player.inventory.append("orcrist")
    game.process_player_input("give orcrist to dwalin")  # costs a turn -> upkeep
    assert dwalin.wielded == "orcrist"
    assert dwalin.attack_power == 8


def test_npcs_draw_their_own_blades_facing_danger():
    game = Game(seed=1)
    thorin = _at_the_trolls(game, "thorin")  # carries Orcrist from the start
    game._advance_world_turn()
    assert thorin.wielded == "orcrist"
    assert thorin.attack_power == 8


def test_npcs_sheathe_when_the_road_is_quiet():
    game = Game(seed=1)
    thorin = _at_the_trolls(game, "thorin")
    game._advance_world_turn()
    assert thorin.wielded == "orcrist"
    # peace returns (trolls gone); Thorin puts up his blade
    for tid in ("troll_tom", "troll_bert", "troll_william"):
        game.characters[tid].alive = False
    game._advance_world_turn()
    assert thorin.wielded is None
    assert thorin.attack_power == thorin.base_attack


def test_npc_does_not_downgrade_to_a_worse_weapon():
    game = Game(seed=1)
    dwalin = _at_the_trolls(game, "dwalin")
    dwalin.inventory.append("orcrist")
    game._advance_world_turn()
    assert dwalin.wielded == "orcrist"
    dwalin.inventory.append("walking_stick")  # weaker; no downgrade
    game._advance_world_turn()
    assert dwalin.wielded == "orcrist"


def test_walking_stick_beats_bare_hands_but_is_crummy():
    game = Game(seed=1)
    stick = game.items.get("walking_stick")
    assert stick.is_weapon and stick.walking_aid
    assert stick.damage > game.player.base_attack  # better than fists
    assert stick.damage < game.items.get("sting").damage  # but a poor blade


def _fatigue_of_one_march(weapon: str | None) -> int:
    game = Game(seed=1)
    if weapon:
        game.player.inventory.append(weapon)
        game.process_player_input(f"wield {weapon.split('_')[0]}")
    game.player.fatigue = 10  # a fixed, mid-range starting point
    before = game.player.fatigue
    game.process_player_input("go east")
    return game.player.fatigue - before


def test_stick_eases_and_sword_wearies_the_march():
    bare = _fatigue_of_one_march(None)
    stick = _fatigue_of_one_march("walking_stick")
    sword = _fatigue_of_one_march("sting")
    assert stick < bare < sword


def test_sheathe_returns_to_bare_hands():
    game = Game(seed=1)
    game.player.inventory.append("sting")
    game.process_player_input("wield sting")
    assert game.player.attack_power == 7
    msgs = game.process_player_input("sheathe")
    assert game.player.wielded is None
    assert game.player.attack_power == game.player.base_attack
    assert any("put away" in m.lower() for m in msgs)


def test_giving_away_wielded_weapon_disarms_the_giver():
    game = Game(seed=1)
    game.player.inventory.append("sting")
    game.process_player_input("wield sting")
    game.process_player_input("give sting to dwalin")
    assert game.player.wielded is None
    assert game.player.attack_power == game.player.base_attack
    assert game.player.travel_mod == 0


def test_status_shows_what_is_in_hand():
    game = Game(seed=1)
    game.player.inventory.append("sting")
    game.process_player_input("wield sting")
    msgs = game.process_player_input("status")
    assert any("wielding Sting" in m for m in msgs)


def test_giving_to_the_player_names_the_absent_companion_not_bilbo():
    """A scout ranged a room ahead can still be commanded, but he can't hand
    anything to Bilbo from there. The old message -- 'there is no bilbo here'
    -- blamed the player, who is Bilbo."""
    from hobbit.game import Game
    game = Game(seed=1)
    gandalf = game.characters["gandalf"]
    game.world.get("bag_end").npcs.remove("gandalf")
    gandalf.location_id = "hobbiton_road"
    game.world.get("hobbiton_road").npcs.append("gandalf")
    gandalf.inventory = ["walking_stick"]

    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("gandalf, give stick to bilbo"))
    assert "Gandalf isn't here" in msgs
    assert "no bilbo" not in msgs.lower()
    assert "walking_stick" in gandalf.inventory   # he still holds it


def test_giving_to_the_player_works_when_together():
    from hobbit.game import Game
    game = Game(seed=1)
    game.characters["gandalf"].inventory = ["walking_stick"]
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("gandalf, give stick to bilbo"))
    assert "gives the walking stick to Bilbo" in msgs
    assert "walking_stick" in game.player.inventory


def test_a_genuinely_absent_recipient_still_reads_plainly():
    """The reworded message is only for the player-as-target case; asking to
    give to someone who really isn't in the room keeps the plain wording."""
    from hobbit.game import Game
    game = Game(seed=1)
    game.player.inventory = ["walking_stick"]
    # thorin is here at the start; move him away
    game.world.get("bag_end").npcs.remove("thorin")
    game.characters["thorin"].location_id = "hobbiton_road"
    game.world.get("hobbiton_road").npcs.append("thorin")
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("give stick to thorin"))
    assert "no thorin here" in msgs.lower()
