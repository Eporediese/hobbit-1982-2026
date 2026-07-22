from hobbit.game import Game


def test_game_initializes_party_at_bag_end():
    game = Game(seed=1)
    bag_end = game.world.get("bag_end")
    assert "thorin" in bag_end.npcs
    assert "gandalf" in bag_end.npcs
    assert len([n for n in bag_end.npcs]) == 14  # gandalf + thorin + 12 dwarves


def test_monsters_do_not_attack_each_other():
    game = Game(seed=3)
    game.player.location_id = "front_gate"  # keep bilbo out of the clearing
    # Freeze the party so their goal-directed marching can't wander in and
    # fight the trolls -- we're isolating the monster-vs-monster invariant.
    for c in game.characters.values():
        if getattr(c, "captured", None) is not None:
            c.captured = True
    for _ in range(30):
        game._advance_world_turn()
    tom = game.characters["troll_tom"]
    bert = game.characters["troll_bert"]
    william = game.characters["troll_william"]
    # trolls have no hostile targets in their own clearing, so none should be dead
    assert tom.alive and bert.alive and william.alive


def test_direct_command_overrides_wander_and_attacks_target():
    game = Game(seed=5)
    game.characters["thorin"].location_id = "trolls_clearing"
    game.world.get("bag_end").npcs.remove("thorin")
    game.world.get("trolls_clearing").npcs.append("thorin")
    tom = game.characters["troll_tom"]
    start_health = tom.health
    game.process_player_input("thorin, attack tom")
    assert tom.health < start_health or not tom.alive


def test_npc_can_be_captured_in_goblin_tunnels():
    # The capture (trouble) mechanic fires for an unaccompanied NPC in the
    # dark goblin tunnels. Raise the chance so it triggers promptly instead
    # of relying on a rare roll.
    game = Game(seed=2)
    balin = game.characters["balin"]
    balin.def_.trouble_chance = 0.95
    game.world.get("bag_end").npcs.remove("balin")
    balin.location_id = "goblin_tunnel_1"
    game.world.get("goblin_tunnel_1").npcs.append("balin")
    game.player.location_id = "front_gate"
    captured = False
    for _ in range(20):
        game._advance_world_turn()
        if balin.captured:
            captured = True
            break
    assert captured
    assert balin.location_id == "goblin_dungeon"


def test_hunger_and_fatigue_eventually_kill_the_player():
    # The player must manage their own hunger; ignoring it long enough is
    # fatal -- starvation and exhaustion wear health away to nothing.
    game = Game(seed=4)
    for _ in range(140):
        game._advance_world_turn()
        if game.lost:
            break
    assert game.lost
    assert not game.player.alive
    assert game.player.is_weak()  # they were worn down by need, not combat
