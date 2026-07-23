"""Combat coordination: spread melee by default, a leader's call for aid
focuses the company's fire, nearby dwarves rush to the call, and off-screen
fights are heard (a cue) and later remarked on."""
from hobbit.game import Game
from hobbit.entities import FATIGUE_WEAK


def _place(game, cid, room):
    """Move an existing character to a room, fixing up the room npc lists."""
    char = game.characters[cid]
    old = game.world.get(char.location_id)
    if cid in old.npcs:
        old.npcs.remove(cid)
    char.location_id = room
    if char is not game.player and cid not in game.world.get(room).npcs:
        game.world.get(room).npcs.append(cid)


def _two_monsters_room(game):
    """A room with two live troll foes for the company to fight."""
    room = "trolls_clearing"
    for tid in ("troll_tom", "troll_bert", "troll_william"):
        if tid in game.characters:
            _place(game, tid, room)
            game.characters[tid].alive = True
    return room


def test_company_spreads_across_multiple_foes():
    game = Game(seed=3)
    room = _two_monsters_room(game)
    foes = game.combat_hostiles(game.player, game.world.get(room))
    # three dwarves choosing targets should not all land on the same foe
    picks = []
    for cid in ("balin", "dwalin", "fili"):
        _place(game, cid, room)
        picks.append(game.choose_combat_target(game.characters[cid], game.world.get(room)))
    assert set(picks) - {None}
    assert len(set(picks)) > 1  # spread, not a pile-on
    assert set(picks) <= set(foes)


def test_monsters_spread_across_the_company_too():
    """The trolls used to all pin the same dwarf and kill him in a round while
    the rest died one by one -- the spread logic only counted the company's
    load, so every troll fell through to the first defender. Both sides spread
    now: three trolls take three different members of the company."""
    game = Game(seed=3)
    room = _two_monsters_room(game)
    defenders = ("balin", "dwalin", "fili", "kili", "oin")
    for cid in defenders:
        _place(game, cid, room)
    picks = []
    for tid in ("troll_tom", "troll_bert", "troll_william"):
        game.characters[tid].combat_target = None
        picks.append(game.choose_combat_target(game.characters[tid],
                                                game.world.get(room)))
    assert len(set(picks)) == 3            # three trolls, three different dwarves
    assert set(picks) <= set(defenders)


def test_a_fighter_keeps_to_its_target_until_it_dies():
    game = Game(seed=3)
    room = _two_monsters_room(game)
    _place(game, "balin", room)
    balin = game.characters["balin"]
    first = game.choose_combat_target(balin, game.world.get(room))
    again = game.choose_combat_target(balin, game.world.get(room))
    assert first == again  # sticks to the same foe round to round


def test_leader_calls_for_help_and_company_focus_fires():
    game = Game(seed=3)
    room = _two_monsters_room(game)
    _place(game, "thorin", room)
    thorin = game.characters["thorin"]
    thorin.health = 3  # badly hurt -> should call for aid
    msgs = game._maybe_call_for_help(thorin)
    assert room in game.rally_targets
    focus = game.rally_targets[room]
    # every companion now piles onto the rally target
    for cid in ("balin", "dwalin"):
        _place(game, cid, room)
        assert game.choose_combat_target(game.characters[cid], game.world.get(room)) == focus


def test_nearby_dwarf_rushes_to_a_rally():
    game = Game(seed=3)
    room = _two_monsters_room(game)
    _place(game, "thorin", room)
    thorin = game.characters["thorin"]
    thorin.fatigue = FATIGUE_WEAK  # weary -> calls for aid
    game._maybe_call_for_help(thorin)
    # a dwarf one room away should be drawn toward the fight
    adj_room = next(iter(game.world.get(room).exits.values()))
    _place(game, "balin", adj_room)
    assert game.fight_needing_aid(game.characters["balin"]) == room


def test_distant_dwarf_does_not_hear_the_call():
    game = Game(seed=3)
    room = _two_monsters_room(game)
    _place(game, "thorin", room)
    game.characters["thorin"].health = 2
    game._maybe_call_for_help(game.characters["thorin"])
    _place(game, "balin", "bag_end")  # far away
    assert game.fight_needing_aid(game.characters["balin"]) is None


def test_rally_clears_when_the_foe_falls():
    game = Game(seed=3)
    room = _two_monsters_room(game)
    _place(game, "thorin", room)
    game.characters["thorin"].health = 2
    game._maybe_call_for_help(game.characters["thorin"])
    foe = game.characters[game.rally_targets[room]]
    foe.alive = False
    game._clear_stale_rallies()
    assert room not in game.rally_targets


def test_a_fight_one_room_away_is_heard():
    game = Game(seed=4)
    here = "lone_lands_1"
    east = game.world.get(here).exits["east"]
    game.player.location_id = here
    place_foe = "troll_tom"
    _place(game, place_foe, east)
    game.characters[place_foe].alive = True
    game.characters[place_foe].health = 50
    _place(game, "dwalin", east)  # a dwarf fighting next door
    msgs = [getattr(m, "text", m) for m in game._advance_world_turn()]
    assert any("clash of steel" in m for m in msgs)


def test_a_companion_boasts_of_an_unseen_victory():
    game = Game(seed=4)
    balin = game.characters["balin"]
    balin.pending_warcry = "warg"  # won a fight the player didn't see
    _place(game, "balin", game.player.location_id)  # now back at Bilbo's side
    line = " ".join(getattr(m, "text", m) for m in game._deliver_warcries())
    assert "warg" in line


def test_authentic_mode_keeps_the_original_pile_on():
    game = Game(seed=3, authentic=True)
    room = _two_monsters_room(game)
    _place(game, "thorin", room)
    game.characters["thorin"].health = 2
    # no rallies are raised in the raw 1982 experience
    game._advance_world_turn()
    assert not game.rally_targets
