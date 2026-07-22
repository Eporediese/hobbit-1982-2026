"""The Elvenking's halls: a guarded door, a stolen key, a larder, and the
barrel escape. The gate is barred as in the book -- the river is the way out,
and it takes only those standing at the barrels."""
from hobbit.game import Game


def _gather(game, room, **kw):
    """Put Bilbo and the whole company in one room."""
    game.player.location_id = room
    game.player.light_remaining = 500
    for cid, char in game.characters.items():
        if getattr(char, "def_", None) and char.def_.is_party:
            old = game.world.get(char.location_id)
            if cid in old.npcs:
                old.npcs.remove(cid)
            char.location_id = room
            game.world.get(room).npcs.append(cid)
            for key, val in kw.items():
                setattr(char, key, val)
    return game


# -- the guarded door -----------------------------------------------------

def test_the_guard_turns_back_anyone_he_can_see():
    game = Game(seed=1)
    game.player.location_id = "elvenking_halls_gate"
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("north"))
    assert "bars the way" in msgs
    assert game.player.location_id == "elvenking_halls_gate"


def test_the_ring_gets_him_past_the_guard():
    game = Game(seed=1)
    game.player.location_id = "elvenking_halls_gate"
    game.player.inventory = ["ring"]
    game.process_player_input("wear ring")
    game.process_player_input("north")
    assert game.player.location_id == "elvenking_halls"
    game.process_player_input("take key")
    assert "elven_cellar_key" in game.player.inventory


def test_the_guard_is_not_a_monster_to_be_brawled_with_by_accident():
    game = Game(seed=1)
    guard = game.characters["elf_guard"]
    assert not guard.def_.is_monster
    assert not game.is_hostile_pair(guard, game.player)
    assert guard.def_.stationary


# -- the barred gate ------------------------------------------------------

def test_the_east_gate_is_barred():
    game = Game(seed=1)
    game.player.location_id = "elvenking_halls_gate"
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("east"))
    assert "barred" in msgs
    assert game.player.location_id == "elvenking_halls_gate"


def test_the_eastern_eaves_stay_reachable_from_the_other_side():
    """Barring one exit must not seal the room off from the rest of the map."""
    game = Game(seed=1)
    game.player.location_id = "forest_river"
    game.process_player_input("west")
    assert game.player.location_id == "mirkwood_east_eaves"


# -- the larder -----------------------------------------------------------

def test_the_cellars_are_locked_until_the_key_is_found():
    game = Game(seed=1)
    game.player.location_id = "elvenking_dungeon"
    game.player.light_remaining = 500
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("down"))
    assert "locked" in msgs
    assert game.player.location_id == "elvenking_dungeon"


def test_the_company_provisions_itself_from_the_larder():
    game = Game(seed=1)
    game.world.get("elvenking_cellars").locked = False
    _gather(game, "elvenking_cellars", inventory=[], hunger=80)
    game._advance_world_turn()
    fed = [c for c in game.characters.values()
           if getattr(c, "def_", None) and c.def_.is_party
           and game.food_count(c) > 0]
    assert len(fed) >= 10                       # they help themselves
    assert game.staple_at("elvenking_cellars") == "elven_cake"


# -- the barrels ----------------------------------------------------------

def test_barrels_refuse_to_leave_anyone_behind():
    game = Game(seed=1)
    game.world.get("elvenking_cellars").locked = False
    _gather(game, "elvenking_cellars")
    bombur = game.characters["bombur"]
    game.world.get("elvenking_cellars").npcs.remove("bombur")
    bombur.location_id = "mirkwood_path_4"
    game.world.get("mirkwood_path_4").npcs.append("bombur")
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("barrel"))
    assert "Bombur" in msgs
    assert game.player.location_id == "elvenking_cellars"   # didn't cast off


def test_barrels_carry_the_whole_company_east():
    game = Game(seed=1)
    game.world.get("elvenking_cellars").locked = False
    _gather(game, "elvenking_cellars")
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("barrel"))
    assert "rapids" in msgs
    assert game.player.location_id == "mirkwood_east_eaves"
    left = [c.name for c in game.characters.values()
            if getattr(c, "def_", None) and c.def_.is_party and c.alive
            and c.location_id == "elvenking_cellars"]
    assert not left


def test_no_barrels_anywhere_else():
    game = Game(seed=1)
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("barrel"))
    assert "no barrels here" in msgs


# -- mustering ------------------------------------------------------------

def test_bilbo_at_the_barrels_calls_the_company_in():
    """A hungry dwarf with an empty pack would otherwise wander off foraging
    and never come back, and the barrels could never cast off."""
    game = Game(seed=1)
    game.world.get("elvenking_cellars").locked = False
    game.player.location_id = "elvenking_cellars"
    game.player.light_remaining = 500
    assert game.mustering_room() == "elvenking_cellars"
    balin = game.characters["balin"]
    old = game.world.get(balin.location_id)
    old.npcs.remove("balin")
    balin.location_id = "elvenking_halls_gate"
    game.world.get("elvenking_halls_gate").npcs.append("balin")
    balin.inventory, balin.hunger = [], 90       # would otherwise forage
    target, _desc, _kind = balin.brain._scripted_goal(balin, game)
    assert target == "elvenking_cellars"


def test_the_scout_answers_the_muster_too():
    """Gandalf keeps his own rhythm and would range off mid-embarkation."""
    game = Game(seed=1)
    game.world.get("elvenking_cellars").locked = False
    game.player.location_id = "elvenking_cellars"
    game.player.light_remaining = 500
    gandalf = game.characters["gandalf"]
    old = game.world.get(gandalf.location_id)
    old.npcs.remove("gandalf")
    gandalf.location_id = "elvenking_halls_gate"
    game.world.get("elvenking_halls_gate").npcs.append("gandalf")
    for _ in range(6):
        game._advance_world_turn()
        if gandalf.location_id == "elvenking_cellars":
            break
    assert gandalf.location_id == "elvenking_cellars"


def test_nobody_sets_off_for_food_through_the_barred_gate():
    """Lake-town lies east of a gate no one can open; a forager who set out
    for it would stall against the bars and be lost to the company."""
    game = Game(seed=1)
    found = game.world.nearest_food_source("elvenking_halls_gate")
    assert found != "lake_town_market"
    assert found == "elvenking_cellars"


# -- saves written before the chapter existed -----------------------------

def _round_trip(game, tmp_path):
    path = tmp_path / "s.json"
    game.save(path)
    fresh = Game(seed=1)
    fresh.load(path)
    return fresh


def test_an_older_save_still_gets_the_new_content(tmp_path):
    """A save records the world as it stood, so loading one written before the
    Elvenking chapter existed came back with 'npcs: []' and 'items: []' --
    silently deleting the guard, his key, and the lock on the cellars from a
    game in progress."""
    stale = Game(seed=1)
    # simulate a save from before any of it existed
    stale.world.get("elvenking_halls").npcs = []
    stale.world.get("elvenking_halls").items = []
    stale.world.get("elvenking_cellars").locked = False
    fresh = _round_trip(stale, tmp_path)

    assert fresh.guard_at("elvenking_halls") is not None
    assert "elven_cellar_key" in fresh.world.get("elvenking_halls").items
    assert fresh.world.get("elvenking_cellars").locked


def test_reconciling_does_not_resurrect_what_you_already_took(tmp_path):
    game = Game(seed=1)
    game.player.inventory = ["elven_cellar_key"]
    game.world.get("elvenking_halls").items = []
    fresh = _round_trip(game, tmp_path)
    assert "elven_cellar_key" in fresh.player.inventory
    assert "elven_cellar_key" not in fresh.world.get("elvenking_halls").items


def test_reconciling_does_not_duplicate_anyone(tmp_path):
    game = Game(seed=1)
    fresh = _round_trip(game, tmp_path)
    for loc in fresh.world.locations.values():
        assert len(loc.npcs) == len(set(loc.npcs)), loc.id


def test_a_door_you_opened_stays_open(tmp_path):
    """Only rooms the player has never entered get their lock restored."""
    game = Game(seed=1)
    cellars = game.world.get("elvenking_cellars")
    cellars.locked = False
    cellars.visited = True          # he has been inside
    fresh = _round_trip(game, tmp_path)
    assert not fresh.world.get("elvenking_cellars").locked


# -- taking the local fare ------------------------------------------------

def test_you_can_ask_for_the_larder_fare_by_its_own_name():
    """Bilbo starved amid a full larder: the take-food shortcut only knew
    'loaf' and 'bread', so 'take cake' failed in the Elvenking's cellars."""
    game = Game(seed=1)
    game.world.get("elvenking_cellars").locked = False
    game.player.location_id = "elvenking_cellars"
    game.player.light_remaining = 500
    game.player.inventory = []
    for phrase in ("cake", "honey-cake", "honey cake", "elven cake", "food"):
        game.player.inventory = []
        msgs = " ".join(str(getattr(m, "text", m))
                        for m in game.process_player_input(f"take {phrase}"))
        assert "elven_cake" in game.player.inventory, phrase
        assert "elven cake" in msgs, phrase


def test_and_can_then_eat_it():
    game = Game(seed=1)
    game.world.get("elvenking_cellars").locked = False
    game.player.location_id = "elvenking_cellars"
    game.player.light_remaining = 500
    game.player.inventory = []
    game.player.hunger = 80
    game.process_player_input("take cake")
    game.process_player_input("eat")
    assert game.player.hunger < 80


def test_the_article_agrees_with_the_fare():
    from hobbit.ui import an
    assert an("elven cake") == "an elven cake"
    assert an("loaf of bread") == "a loaf of bread"
    assert an("Sting") == "Sting"           # proper names take none


# -- the scout must eat too -----------------------------------------------

def _strand_gandalf(game, hunger):
    gandalf = game.characters["gandalf"]
    old = game.world.get(gandalf.location_id)
    old.npcs.remove("gandalf")
    gandalf.location_id = "forest_river"
    game.world.get("forest_river").npcs.append("gandalf")
    gandalf.hunger, gandalf.health, gandalf.inventory = hunger, 17, ["glamdring"]
    game.player.location_id = "elvenking_halls_gate"
    return gandalf


def test_a_hungry_scout_breaks_off_for_food():
    """Gandalf's scouting loop never consulted the survival goals, so he ranged
    on with an empty pack until he starved three rooms from Lake-town."""
    game = Game(seed=1)
    gandalf = _strand_gandalf(game, hunger=80)
    _target, _desc, kind = gandalf.brain._scripted_goal(gandalf, game)
    assert kind == "forage"
    for _ in range(20):
        game._advance_world_turn()
        if gandalf.hunger < 40:
            break
    assert gandalf.alive
    assert gandalf.hunger < 40          # he reached food and ate


def test_a_scout_who_already_collapsed_is_past_saving():
    """Collapse still means collapse -- he cannot march, so provisioning him
    in time is the player's job."""
    game = Game(seed=1)
    gandalf = _strand_gandalf(game, hunger=100)
    assert gandalf.is_fainted()
    for _ in range(20):
        game._advance_world_turn()
        if not gandalf.alive:
            break
    assert not gandalf.alive


# -- finding the way out --------------------------------------------------

def test_the_barrels_are_listed_as_a_way_out():
    """A way out nobody can find is no way out -- so it belongs in the exits
    line beside the other directions, not in a paragraph explaining itself."""
    from hobbit import ui
    game = Game(seed=1)
    game.world.get("elvenking_cellars").locked = False
    game.player.location_id = "elvenking_cellars"
    game.player.light_remaining = 500
    block = ui.present(game.describe_location(game.player), "standard")[0]
    exits = next(l for l in block.split("\n") if l.startswith("Exits:"))
    assert "barrel" in exits and "up" in exits


def test_a_barred_way_is_shown_as_barred():
    from hobbit import ui
    game = Game(seed=1)
    game.player.location_id = "elvenking_halls_gate"
    block = ui.present(game.describe_location(game.player), "standard")[0]
    exits = next(l for l in block.split("\n") if l.startswith("Exits:"))
    assert "east" in exits and "barred" in exits


def test_purist_has_neither_barrels_nor_a_barred_gate():
    """The whole chapter is an addition; the raw 1982 experience must not be
    left with a barred gate and no river to leave by."""
    from hobbit import ui
    game = Game(seed=1, authentic=True)
    game.player.location_id = "elvenking_cellars"
    game.player.light_remaining = 500
    block = ui.present(game.describe_location(game.player), "purist")[0]
    exits = next(l for l in block.split("\n") if l.startswith("Exits:"))
    assert "barrel" not in exits
    game.player.location_id = "elvenking_halls_gate"
    game.process_player_input("east")
    assert game.player.location_id == "mirkwood_east_eaves"   # walks out as before


def test_the_trap_door_is_examinable():
    """Described-but-not-implemented: the prose mentioned a trap-door that
    'examine trap-door' could not find."""
    game = Game(seed=1)
    game.world.get("elvenking_cellars").locked = False
    game.player.location_id = "elvenking_cellars"
    game.player.light_remaining = 500
    for noun in ("trap-door", "trapdoor", "trap door", "barrels", "shelves"):
        msgs = " ".join(str(getattr(m, "text", m))
                        for m in game.process_player_input(f"examine {noun}"))
        assert "you see no" not in msgs.lower(), noun


def test_every_natural_phrasing_boards_the_barrels():
    for phrase in ("barrel", "barrels", "go barrel", "take barrel",
                   "enter barrel", "get in barrel", "go trapdoor"):
        game = Game(seed=1)
        game.world.get("elvenking_cellars").locked = False
        _gather(game, "elvenking_cellars")
        game.process_player_input(phrase)
        assert game.player.location_id == "mirkwood_east_eaves", phrase


def test_barrel_words_do_nothing_elsewhere():
    """'take barrel' in a room with no barrels shouldn't teleport anyone."""
    game = Game(seed=1)
    before = game.player.location_id
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("take barrel"))
    assert game.player.location_id == before
    assert "no barrel" in msgs.lower()
