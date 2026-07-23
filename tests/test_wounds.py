"""Tests for wounds: combat penalty, healing at havens, rest mending,
wounded companions seeking a haven, and graves/bodies for the fallen."""
from hobbit.game import Game


def test_wounds_weaken_attack():
    game = Game(seed=1)
    thorin = game.characters["thorin"]
    thorin.attack_power = 8
    thorin.health = thorin.max_health
    full = thorin.effective_attack()
    thorin.health = thorin.max_health // 4  # badly hurt
    assert thorin.effective_attack() < full


def test_wounds_mend_slowly_on_the_road_and_fast_at_a_haven():
    road = Game(seed=1)
    road.player.location_id = "lone_lands_1"  # not a food source
    road.player.health = 10
    road._advance_world_turn()
    on_road = road.player.health - 10

    haven = Game(seed=1)
    haven.player.location_id = "rivendell_hall"  # a haven
    haven.player.health = 10
    haven._advance_world_turn()
    at_haven = haven.player.health - 10

    assert 0 < on_road < at_haven


def test_resting_mends_a_little():
    game = Game(seed=1)
    game.player.health = 10
    game.player.fatigue = 50
    game.process_player_input("rest")
    assert game.player.health > 10


def test_no_healing_while_weak():
    game = Game(seed=1)
    game.player.location_id = "lone_lands_1"
    game.player.health = 10
    game.player.fatigue = 90  # weak -> wearing down, not mending
    game._advance_world_turn()
    assert game.player.health <= 10


def test_badly_hurt_companion_seeks_a_nearby_haven():
    game = Game(seed=1)
    balin = game.characters["balin"]
    # near Rivendell, badly hurt
    game.player.location_id = "rivendell_bridge"
    game.world.get("bag_end").npcs.remove("balin")
    balin.location_id = "rivendell_bridge"
    game.world.get("rivendell_bridge").npcs.append("balin")
    balin.health = 3
    target, desc, kind = balin.brain._scripted_goal(balin, game)
    assert kind == "heal"
    assert game.world.get(target).food_source


def test_slain_monster_leaves_a_body():
    game = Game(seed=1)
    tom = game.characters["troll_tom"]
    tom.alive = False
    game.handle_death(tom)
    assert "Tom the troll" in game.world.get("trolls_clearing").slain
    game.player.location_id = "trolls_clearing"
    block = game.describe_location(game.player)[0]
    assert "The body of Tom the troll lies where it fell" in block


def test_the_fallen_are_counted_and_given_their_articles():
    """'The bodies of goblin scout lie where they fell' -- one corpse, plural
    verb, no article."""
    game = Game(seed=1)
    loc = game.world.get("trolls_clearing")
    game.player.location_id = "trolls_clearing"

    loc.slain = ["goblin scout"]
    assert "The body of the goblin scout lies where it fell" in \
        game.describe_location(game.player)[0]

    loc.slain = ["goblin scout", "goblin scout", "warg"]
    block = game.describe_location(game.player)[0]
    assert "The bodies of two goblin scouts and the warg lie where they fell" in block

    loc.slain = ["Tom the troll"]  # a proper name takes no article
    assert "The body of Tom the troll lies where it fell" in \
        game.describe_location(game.player)[0]


def test_fallen_companion_is_buried_once_the_battle_is_won():
    game = Game(seed=1)
    game.player.location_id = "trolls_clearing"
    thorin = game.characters["thorin"]
    game.world.get("bag_end").npcs.remove("thorin")
    thorin.location_id = "trolls_clearing"
    game.world.get("trolls_clearing").npcs.append("thorin")
    # another companion present to do the digging
    balin = game.characters["balin"]
    game.world.get("bag_end").npcs.remove("balin")
    balin.location_id = "trolls_clearing"
    game.world.get("trolls_clearing").npcs.append("balin")
    thorin.alive = False
    game.handle_death(thorin)
    # trolls still alive -> no burial yet
    game._advance_world_turn()
    assert "Thorin Oakenshield" not in game.world.get("trolls_clearing").graves
    # clear the foes; now the cairn is raised
    for tid in ("troll_tom", "troll_bert", "troll_william"):
        game.characters[tid].alive = False
    msgs = game._advance_world_turn()
    assert "Thorin Oakenshield" in game.world.get("trolls_clearing").graves
    assert any("cairn" in m.lower() for m in msgs)


def test_a_burial_pending_across_a_reload_is_not_lost(tmp_path):
    """A companion who fell while foes still stood was queued for burial only in
    memory. A save + reload before the fight ended (every deploy restarts the
    server) used to leave them dead but never given a cairn. reconcile_after_load
    re-derives the burial from who is dead and where they fell."""
    game = Game(seed=1)
    game.player.location_id = "trolls_clearing"
    for cid in ("balin", "oin", "dwalin"):        # gather them at the clearing
        game.world.get("bag_end").npcs.remove(cid)
        game.characters[cid].location_id = "trolls_clearing"
        game.world.get("trolls_clearing").npcs.append(cid)
    dwalin = game.characters["dwalin"]
    dwalin.alive = False
    game.handle_death(dwalin)                     # trolls alive -> burial pending
    assert game._pending_burials                  # queued, but only in memory

    save = tmp_path / "s.json"
    game.save(save)                               # ...and the queue is not saved
    reloaded = Game(seed=1)
    reloaded.load(save)
    reloaded.reconcile_after_load()
    assert any(name == "Dwalin" for _, name in reloaded._pending_burials)

    # clear the foes; the cairn is raised, just as if the fight had only ended
    for tid in ("troll_tom", "troll_bert", "troll_william"):
        reloaded.characters[tid].alive = False
    reloaded._advance_world_turn()
    assert "Dwalin" in reloaded.world.get("trolls_clearing").graves


def test_battle_marks_survive_save_load(tmp_path):
    save = tmp_path / "s.json"
    game = Game(seed=1)
    game.world.get("trolls_clearing").slain = ["Tom the troll"]
    game.world.get("trolls_clearing").graves = ["Thorin Oakenshield"]
    game.save(save)
    fresh = Game(seed=1)
    fresh.load(save)
    assert fresh.world.get("trolls_clearing").slain == ["Tom the troll"]
    assert fresh.world.get("trolls_clearing").graves == ["Thorin Oakenshield"]
