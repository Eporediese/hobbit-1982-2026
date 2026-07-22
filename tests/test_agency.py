"""Companions acting on what they can see, rather than walking past it."""
from hobbit.game import Game
from hobbit.parser import Command


def _put(game, who, room):
    c = game.characters[who]
    old = game.world.get(c.location_id)
    if who in old.npcs:
        old.npcs.remove(who)
    c.location_id = room
    game.world.get(room).npcs.append(who)


def _with_bilbo(game, who, room):
    """Companions only act on a room they share with the company."""
    game.player.location_id = room
    game.player.light_remaining = 9999
    _put(game, who, room)


def test_a_dwarf_takes_up_a_better_blade_than_the_one_in_hand():
    """A fallen friend's sword lying on the floor is the clearest case: it
    used to need the player to notice and hand it over."""
    game = Game(seed=1)
    _with_bilbo(game, "dwalin", "hobbiton_road")
    dwalin = game.characters["dwalin"]
    dwalin.inventory = []
    dwalin.wielded = None
    game.world.get("hobbiton_road").items.append("orcrist")

    cmd = dwalin.decide(game)
    assert cmd and cmd.verb == "take" and "orcrist" in cmd.obj.lower()


def test_a_dwarf_leaves_a_worse_blade_alone():
    game = Game(seed=1)
    _with_bilbo(game, "dwalin", "hobbiton_road")
    dwalin = game.characters["dwalin"]
    dwalin.inventory = ["orcrist"]
    dwalin.wield_weapon("orcrist", game.items.get("orcrist").damage, 1)
    game.world.get("hobbiton_road").items.append("walking_stick")

    cmd = dwalin.decide(game)
    assert not (cmd and cmd.verb == "take"
                and "walking" in (cmd.obj or "").lower())


def test_a_companion_opens_a_door_he_holds_the_key_to():
    """A quiet room on purpose: a foe in the room is dealt with first, and
    rightly so."""
    game = Game(seed=1)
    _with_bilbo(game, "dwalin", "secret_door_path")
    dwalin = game.characters["dwalin"]
    dwalin.inventory = ["moon_key"]

    cmd = dwalin.decide(game)
    assert cmd and cmd.verb == "open"


def test_a_foe_in_the_room_outranks_anything_lying_in_it():
    game = Game(seed=1)
    _with_bilbo(game, "dwalin", "trolls_clearing")
    dwalin = game.characters["dwalin"]
    dwalin.inventory = ["key_troll_cave"]

    cmd = dwalin.decide(game)
    assert cmd and cmd.verb == "attack"


def test_a_companion_shares_food_with_one_who_has_none():
    """Left to the upkeep rules a foodless dwarf walks off to forage; sharing
    keeps the company together, which is what a company is for."""
    game = Game(seed=1)
    _with_bilbo(game, "dwalin", "hobbiton_road")
    _put(game, "bofur", "hobbiton_road")
    dwalin, bofur = game.characters["dwalin"], game.characters["bofur"]
    dwalin.inventory = ["bread", "bread", "bread", "bread"]
    bofur.inventory = []
    bofur.hunger = 40

    cmd = dwalin.decide(game)
    assert cmd and cmd.verb == "give" and cmd.indirect == bofur.name


def test_nobody_dawdles_while_the_company_marches_on():
    """Acting costs the actor their turn, so a dwarf who stops for a coin
    while the company moves is left behind -- one room becomes two."""
    game = Game(seed=1)
    game.player.location_id = "bag_end"
    _put(game, "dwalin", "hobbiton_road")          # not with the player
    dwalin = game.characters["dwalin"]
    dwalin.inventory = []
    dwalin.wielded = None
    game.world.get("hobbiton_road").items.append("orcrist")

    cmd = dwalin.decide(game)
    assert not (cmd and cmd.verb == "take")


def test_a_companion_cuts_a_captive_loose():
    """Rescue used to be Bilbo's alone -- so a dwarf could walk into the cell
    where his cousin was chained and step over him to look at the gold."""
    game = Game(seed=1)
    game.player.location_id = "bag_end"            # the player is far away
    dwalin, bofur = game.characters["dwalin"], game.characters["bofur"]
    _put(game, "bofur", "goblin_dungeon")
    bofur.captured = True
    _put(game, "dwalin", "goblin_dungeon")

    msgs = " ".join(str(getattr(m, "text", m)) for m in game._resolve_rescues())
    assert not bofur.captured
    assert "cuts" in msgs and "Bofur" in msgs


def test_the_player_still_rescues_in_their_own_words():
    game = Game(seed=1)
    bofur = game.characters["bofur"]
    _put(game, "bofur", "goblin_dungeon")
    bofur.captured = True
    game.player.location_id = "goblin_dungeon"

    msgs = " ".join(str(getattr(m, "text", m)) for m in game._resolve_rescues())
    assert not bofur.captured
    assert "You strike off" in msgs


def test_purist_companions_notice_nothing():
    """The 1982 characters walked past everything, and that is the point of
    the mode."""
    game = Game(seed=1, authentic=True)
    _with_bilbo(game, "dwalin", "hobbiton_road")
    dwalin = game.characters["dwalin"]
    dwalin.inventory = []
    dwalin.wielded = None
    game.world.get("hobbiton_road").items.append("orcrist")

    cmd = dwalin.decide(game)
    assert not (cmd and cmd.verb == "take")


def test_no_companion_pockets_the_ring():
    """A soft-lock this feature created and the soak caught: only Bilbo can
    walk past the wood-elf guard unseen, so a helpful dwarf picking up the
    ring makes the Elvenking's halls impassable and the game unfinishable."""
    game = Game(seed=1)
    _with_bilbo(game, "dwalin", "gollum_lake_shore")
    dwalin = game.characters["dwalin"]
    dwalin.inventory = []
    if "ring" not in game.world.get("gollum_lake_shore").items:
        game.world.get("gollum_lake_shore").items.append("ring")

    for _ in range(5):
        cmd = dwalin.decide(game)
        assert not (cmd and cmd.verb == "take" and "ring" in (cmd.obj or "").lower())


def test_no_companion_pockets_a_key():
    """Also caught by the soak: a dwarf took the moon-letter key off the
    library table, so the player walked back for a key already in Dwalin's
    coat -- for ever. The puzzles a key opens are the player's."""
    game = Game(seed=1)
    _with_bilbo(game, "dwalin", "rivendell_library")
    dwalin = game.characters["dwalin"]
    dwalin.inventory = []

    assert "moon_key" in game.world.get("rivendell_library").items
    for _ in range(5):
        cmd = dwalin.decide(game)
        assert not (cmd and cmd.verb == "take" and "key" in (cmd.obj or "").lower())


def test_a_companion_still_picks_up_plain_treasure():
    """The reckoning counts the company's haul, not Bilbo's, so this is worth
    having -- the restriction is only on what the story turns on."""
    game = Game(seed=1)
    _with_bilbo(game, "dwalin", "hobbiton_road")
    dwalin = game.characters["dwalin"]
    dwalin.inventory = []
    game.world.get("hobbiton_road").items.append("gold_goblet")

    cmd = dwalin.decide(game)
    assert cmd and cmd.verb == "take" and "goblet" in cmd.obj.lower()
