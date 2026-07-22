"""Tests for company awareness of deaths/captures and the rescue mechanic."""
from hobbit.game import Game


def _kill_in_battle(game, cid):
    npc = game.characters[cid]
    npc.alive = False
    return game.handle_death(npc)


def test_death_is_announced_to_the_player():
    game = Game(seed=1)
    _kill_in_battle(game, "thorin")
    msgs = game._advance_world_turn()
    assert any("Thorin Oakenshield has fallen" in m for m in msgs)


def test_death_enters_company_lore_and_party_shows_where():
    game = Game(seed=1)
    thorin = game.characters["thorin"]
    thorin.location_id = "trolls_clearing"
    _kill_in_battle(game, "thorin")
    assert any("fell in battle at The Trolls' Clearing" in t
               for t in game.company_lore)
    msgs = game.process_player_input("party")
    tline = next(m for m in msgs if "Thorin" in m)
    assert "fell at The Trolls' Clearing" in tline


def test_capture_is_announced_and_remembered():
    game = Game(seed=1)
    game.company_news("Ori was taken by goblins near A Goblin Tunnel",
                       announce="A cry echoes down the tunnels -- Ori has been taken by goblins!")
    msgs = game._advance_world_turn()
    assert any("Ori has been taken" in m for m in msgs)
    assert any("taken by goblins" in t for t in game.company_lore)


def test_reaching_a_captive_frees_them():
    game = Game(seed=1)
    balin = game.characters["balin"]
    game.world.get("bag_end").npcs.remove("balin")
    balin.location_id = "goblin_dungeon"
    game.world.get("goblin_dungeon").npcs.append("balin")
    balin.captured = True
    # Bilbo fights his way to the cell
    game.player.location_id = "goblin_dungeon"
    msgs = game._advance_world_turn()
    assert balin.captured is False
    assert any("free" in m.lower() for m in msgs)
    assert any("rescued" in t for t in game.company_lore)


def test_freed_companion_rejoins_the_company():
    game = Game(seed=1)
    balin = game.characters["balin"]
    game.world.get("bag_end").npcs.remove("balin")
    balin.location_id = "goblin_dungeon"
    game.world.get("goblin_dungeon").npcs.append("balin")
    balin.captured = True
    game.player.location_id = "goblin_dungeon"
    game._advance_world_turn()
    # walk out; Balin should start moving again (escort goal resumes)
    game.player.location_id = "goblin_throne_room"
    moved = False
    for _ in range(6):
        game._advance_world_turn()
        if balin.location_id != "goblin_dungeon":
            moved = True
            break
    assert moved


def test_company_lore_reaches_dialogue_context():
    class FakeLLM:
        def __init__(self):
            self.prompts = []

        def chat(self, system, user):
            self.prompts.append(user)
            return "Alas, poor Thorin."

    fake = FakeLLM()
    game = Game(seed=1, llm=fake)
    game.characters["thorin"].location_id = "trolls_clearing"
    _kill_in_battle(game, "thorin")
    game.process_player_input("talk to balin")
    assert any("fell in battle at The Trolls' Clearing" in p for p in fake.prompts)


def test_grief_is_spoken_in_ai_mode():
    class FakeLLM:
        def chat(self, system, user):
            return "He was our king, and we will finish what he began."

    game = Game(seed=1, llm=FakeLLM())
    _kill_in_battle(game, "thorin")
    msgs = game._advance_world_turn()
    assert any("finish what he began" in m for m in msgs)


def test_company_lore_survives_save_load(tmp_path):
    save = tmp_path / "s.json"
    game = Game(seed=1)
    game.characters["thorin"].location_id = "trolls_clearing"
    _kill_in_battle(game, "thorin")
    game.save(save)
    fresh = Game(seed=1)
    fresh.load(save)
    assert any("fell in battle" in t for t in fresh.company_lore)
    assert fresh.characters["thorin"].death_place == "The Trolls' Clearing"