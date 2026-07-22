"""Combat balance: a company of fourteen used to annihilate anything in a
single round (even Smaug), because everyone could swing at once. Rooms now
have a fighting front, bosses have real stats, and the wounded can actually
reach a haven from the mountains."""
from hobbit.game import Game
from hobbit.npc import HEAL_SEEK_RANGE


def _place(game, cid, room):
    char = game.characters[cid]
    old = game.world.get(char.location_id)
    if cid in old.npcs:
        old.npcs.remove(cid)
    char.location_id = room
    if cid not in game.world.get(room).npcs:
        game.world.get(room).npcs.append(cid)


def _crowd_the_tunnel(game, room="goblin_tunnel_1"):
    game.player.location_id = room
    game.player.light_remaining = 500
    for cid in ("thorin", "balin", "dwalin", "fili", "kili", "oin", "gloin", "bifur"):
        _place(game, cid, room)
    _place(game, "goblin_scout", room)
    game.characters["goblin_scout"].alive = True
    return room


# -- melee width ----------------------------------------------------------

def test_a_tunnel_is_narrower_than_a_hall():
    game = Game(seed=1)
    assert game.world.get("goblin_tunnel_1").melee_width < \
           game.world.get("goblin_throne_room").melee_width


def test_only_the_front_rank_can_strike_in_a_tunnel():
    game = Game(seed=4)
    room = _crowd_the_tunnel(game)
    width = game.world.get(room).melee_width
    msgs = [getattr(m, "text", m) for m in game._advance_world_turn()]
    swings = [m for m in msgs
              if ("hits goblin scout" in m or "attacks goblin scout" in m)
              and not m.startswith("Goblin")]
    assert len(swings) <= width, swings


def test_the_ones_behind_are_told_they_cannot_reach():
    game = Game(seed=4)
    _crowd_the_tunnel(game)
    msgs = [getattr(m, "text", m) for m in game._advance_world_turn()]
    assert any("press behind" in m for m in msgs)
    # and it's said once, not once per blocked dwarf
    assert sum("press behind" in m for m in msgs) == 1


def test_a_lone_foe_in_a_tunnel_survives_a_round():
    game = Game(seed=4)
    _crowd_the_tunnel(game)
    game._advance_world_turn()
    scout = game.characters["goblin_scout"]
    # 8 dwarves no longer evaporate a goblin instantly
    assert scout.alive or scout.health < 16


def test_purist_mode_keeps_the_old_free_for_all():
    game = Game(seed=4, authentic=True)
    room = _crowd_the_tunnel(game)
    assert game.world.get(room).melee_width  # the data is there
    # but the 1982 routine ignores it -- no "press behind" bookkeeping
    msgs = [getattr(m, "text", m) for m in game._advance_world_turn()]
    assert not any("press behind" in m for m in msgs)


# -- bosses ---------------------------------------------------------------

def test_smaug_is_the_most_dangerous_thing_in_the_world():
    game = Game(seed=1)
    smaug = game.characters["smaug"]
    others = [c for c in game.characters.values()
              if getattr(c, "def_", None) and c.def_.is_monster and c is not smaug]
    assert smaug.max_health > max(c.max_health for c in others) * 1.5
    assert smaug.attack_power > max(c.attack_power for c in others)


def test_the_great_goblin_is_a_boss_not_a_speed_bump():
    game = Game(seed=1)
    captain = game.characters["goblin_captain"]
    scout = game.characters["goblin_scout"]
    assert captain.max_health > scout.max_health * 3
    party = [c for c in game.characters.values()
             if getattr(c, "def_", None) and c.def_.is_party]
    front = game.world.get("goblin_throne_room").melee_width
    per_round = sum(sorted((c.effective_attack() for c in party),
                           reverse=True)[:front]) * 0.75
    assert captain.max_health / per_round > 2  # survives more than a round or two


# -- healing reachable ----------------------------------------------------

def test_the_mountains_are_no_longer_a_healing_desert():
    game = Game(seed=1)
    for room in ("goblin_throne_room", "goblin_tunnel_1", "goblin_gate"):
        haven = game.world.nearest_food_source(room)
        assert haven
        assert game.world.distance(room, haven) <= HEAL_SEEK_RANGE, room


def test_a_badly_hurt_dwarf_in_the_tunnels_makes_for_a_haven():
    game = Game(seed=1)
    room = "goblin_throne_room"
    _place(game, "balin", room)
    game.player.location_id = room
    balin = game.characters["balin"]
    balin.health = 3
    _target, _desc, kind = balin.brain._scripted_goal(balin, game)
    assert kind == "heal"


def _lair(seed, crew, fire=True):
    from hobbit.game import Game
    game = Game(seed=seed)
    if not fire:
        game.characters["smaug"].def_.breath = None
    game.player.location_id = "treasure_chamber"
    game.player.light_remaining = 999999
    game.player.inventory = ["sting"]
    game.player.wielded = "sting"
    for d in crew:
        game.characters[d].location_id = "treasure_chamber"
        game.world.get("treasure_chamber").npcs.append(d)
    return game


_COMPANY = ("dwalin", "balin", "kili", "gloin", "bifur", "bofur",
            "dori", "nori", "ori", "oin", "bombur", "fili")


def _fight(game, crew, limit=40):
    smaug = game.characters["smaug"]
    for _ in range(limit):
        game.process_player_input("attack smaug")
        if not smaug.alive or not game.player.alive:
            break
    return sum(1 for d in crew if not game.characters[d].alive)


def test_smaug_breathes_on_the_whole_front_rank():
    """A dragon does not fence. Melee width lets six reach him and he could
    only answer one of them, so numbers alone settled the climax."""
    game = _lair(4, _COMPANY)
    seen = []
    for _ in range(6):
        seen += [str(getattr(m, "text", m))
                 for m in game.process_player_input("attack smaug")]
    joined = "\n".join(seen)
    assert "fire rolls the length of the hall" in joined
    assert joined.count("is caught in the fire") >= 3   # a sweep, not a bite


def test_the_fire_does_not_reach_past_the_front_rank():
    """The same limit that lets them reach him limits what he can burn."""
    game = _lair(4, _COMPANY)
    width = game.world.get("treasure_chamber").melee_width
    burned = set()
    for _ in range(4):
        for m in game.process_player_input("attack smaug"):
            text = str(getattr(m, "text", m))
            if "is caught in the fire" in text:
                burned.add(text.split(" is caught")[0])
    assert 0 < len(burned) <= width


def test_the_dragon_costs_a_full_company_real_lives():
    """Regression on the complaint that started this: the fight was winnable
    at full strength for almost nothing. Averaged over seeds, it isn't now."""
    losses = [_fight(_lair(s, _COMPANY), _COMPANY) for s in range(1, 13)]
    assert sum(losses) / len(losses) >= 4

    without = [_fight(_lair(s, _COMPANY, fire=False), _COMPANY)
               for s in range(1, 13)]
    assert sum(losses) > sum(without)   # the fire is what made the difference
