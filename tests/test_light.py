"""A torch that burns down, and a dark that can't trap you."""
from hobbit.game import Game


def test_an_unlit_torch_is_not_a_light():
    """It used to be: merely carrying one counted, which made the fuel
    decorative and the dark a formality."""
    game = Game(seed=1)
    game.player.inventory = ["torch"]
    assert not game.carries_light(game.player)
    game.process_player_input("light torch")
    assert game.carries_light(game.player)


def test_the_torch_actually_burns_down():
    """light_remaining was set when you lit it and then never decremented
    anywhere, so one torch lasted the whole journey."""
    game = Game(seed=1)
    game.player.inventory = ["torch"]
    game.process_player_input("light torch")
    before = game.player.light_remaining
    game.process_player_input("wait")
    assert game.player.light_remaining == before - 1


def test_a_torch_burns_for_an_uncertain_number_of_turns():
    """You know roughly how long a brand lasts; never how long this one will."""
    lives = set()
    for seed in range(1, 25):
        game = Game(seed=seed)
        game.player.inventory = ["torch"]
        game.process_player_input("light torch")
        lives.add(game.player.light_remaining)
    assert len(lives) > 3, f"always the same life: {lives}"


def test_it_flickers_before_it_dies():
    """The warning is the point -- the dark should be seen coming, not fall
    between one turn and the next."""
    game = Game(seed=3)
    game.player.inventory = ["torch"]
    game.process_player_input("light torch")
    game.player.light_remaining = 11
    seen = []
    for _ in range(12):
        seen += [str(getattr(m, "text", m))
                 for m in game.process_player_input("wait")]
    joined = "\n".join(seen)
    assert "burns low and flickers" in joined
    assert "goes out" in joined
    assert joined.index("flickers") < joined.index("goes out")


def test_a_burnt_out_torch_can_be_lit_again():
    """The brand is not consumed. What a dark stretch costs you is the turns
    spent stopping to relight -- not a fuel gauge counting down to a dead end
    in the middle of the goblin tunnels."""
    game = Game(seed=1)
    game.player.inventory = ["torch"]
    game.process_player_input("light torch")
    game.player.light_remaining = 1
    game.process_player_input("wait")

    assert not game.carries_light(game.player)     # it went out
    assert "torch" in game.player.inventory        # but it is still yours
    game.process_player_input("light torch")
    assert game.carries_light(game.player)         # and lights again


def test_one_torch_burns_at_one_torch_a_turn():
    """Regression: `characters` already contains the player, so listing them
    separately burned every torch twice as fast as it should."""
    game = Game(seed=1)
    game.player.inventory = ["torch"]
    game.process_player_input("light torch")
    life = game.player.light_remaining
    turns = 0
    while game.player.light_remaining > 0 and turns < life * 3:
        game.process_player_input("wait")
        turns += 1
    assert turns == life


def test_a_brand_burns_for_a_few_turns_not_a_chapter():
    """Short enough that a dark stretch means stopping to relight more than
    once, long enough that it is not a nuisance every other turn."""
    game = Game(seed=1)
    game.player.inventory = ["torch"]
    game.process_player_input("light torch")
    assert 5 <= game.player.light_remaining <= 20


def test_the_dark_can_always_be_retraced():
    """A torch that gutters three rooms into the tunnels would otherwise
    strand you: every way on is dark, so you could not move at all and would
    starve where you stood."""
    game = Game(seed=5)
    player = game.player
    player.location_id = "goblin_gate"        # the mouth of the tunnels
    player.inventory = ["torch"]
    game.process_player_input("light torch")
    for _ in range(3):
        game.process_player_input("east")
    deep = player.location_id
    assert game.world.get(deep).dark
    player.light_remaining = 0

    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("west"))
    assert player.location_id != deep, msgs
    assert "feel your way back" in msgs


def test_the_dark_still_stops_you_going_somewhere_new():
    """The mercy is a way back, not a free pass onward."""
    game = Game(seed=5)
    player = game.player
    player.location_id = "goblin_gate"
    player.inventory = ["torch"]
    game.process_player_input("light torch")
    game.process_player_input("east")
    here = player.location_id
    player.light_remaining = 0
    player.trail = []                      # nothing remembered: no way back
    onward = [d for d, dest in game.world.get(here).exits.items()
              if game.world.get(dest).dark]
    if onward:
        msgs = " ".join(str(getattr(m, "text", m))
                        for m in game.process_player_input(onward[0]))
        assert "pitch dark" in msgs
        assert player.location_id == here


def _cleared_clearing(game):
    """The Trolls' Clearing with the trolls dead and the cave below unlocked,
    Bilbo standing there carrying no light of his own."""
    clearing = game.world.get("trolls_clearing")
    game.player.location_id = "trolls_clearing"
    for t in ("troll_tom", "troll_bert", "troll_william"):
        game.characters[t].alive = False
        if t in clearing.npcs:
            clearing.npcs.remove(t)
    game.world.get("troll_cave").locked = False
    game.player.inventory = []
    game.player.trail = []
    return clearing


def test_a_companions_torch_lights_the_way_down_for_bilbo():
    """The one torch serves the whole party. Bilbo, carrying none himself, can
    go down into the dark when a companion holds the lit brand -- whether at his
    side to come down with him, or already gone ahead into the dark below."""
    # Balin beside Bilbo with the lit torch -> down together
    game = Game(seed=1)
    clearing = _cleared_clearing(game)
    balin = game.characters["balin"]
    game.world.get(balin.location_id).npcs.remove("balin")
    balin.location_id = "trolls_clearing"
    clearing.npcs.append("balin")
    balin.light_remaining = 10
    game.process_player_input("down")
    assert game.player.location_id == "troll_cave"

    # Balin already below, holding the torch -> Bilbo follows the light down
    game = Game(seed=1)
    _cleared_clearing(game)
    balin = game.characters["balin"]
    game.world.get(balin.location_id).npcs.remove("balin")
    balin.location_id = "troll_cave"
    game.world.get("troll_cave").npcs.append("balin")
    balin.light_remaining = 10
    game.process_player_input("down")
    assert game.player.location_id == "troll_cave"


def test_the_dark_still_stops_bilbo_when_no_one_carries_a_light():
    """The shared torch is the mercy; a party with no lit brand at all still
    cannot walk into the black."""
    game = Game(seed=1)
    _cleared_clearing(game)      # nobody here has lit anything
    msgs = " ".join(str(m) for m in game.process_player_input("down"))
    assert "pitch dark" in msgs
    assert game.player.location_id == "trolls_clearing"


def test_you_can_take_things_by_a_companions_torch():
    """The room the torch lights is a room you can act in, not just see. Taking
    an item used to check Bilbo's own light, so in a cave lit only by Balin's
    torch 'take sting' failed with 'too dark' -- while Balin walked off with
    it."""
    game = Game(seed=1)
    cave = game.world.get("troll_cave")
    game.player.location_id = "troll_cave"
    balin = game.characters["balin"]
    game.world.get(balin.location_id).npcs.remove("balin")
    balin.location_id = "troll_cave"
    cave.npcs.append("balin")
    balin.light_remaining = 10
    if "sting" not in cave.items:
        cave.items.append("sting")
    out = game.process_player_input("take sting")
    assert "sting" in game.player.inventory
    assert not any("too dark" in str(m).lower() for m in out)


def test_a_torchless_companion_does_not_narrate_its_fumbling():
    """When the room really is dark, a dwarf who can't see to loot fails in
    silence -- the 'you need a light' hint is for the player, and one per
    companion was a wall of it."""
    from hobbit.commands import do_take
    from hobbit.parser import Command
    game = Game(seed=1)
    cave = game.world.get("troll_cave")
    assert cave.dark and not game.room_is_lit("troll_cave")
    kili = game.characters["kili"]
    kili.location_id = "troll_cave"
    assert do_take(game, kili, Command(verb="take", obj="sting")) == []
    # ...but Bilbo, in the same dark, still gets told how to fix it
    game.player.location_id = "troll_cave"
    out = do_take(game, game.player, Command(verb="take", obj="sting"))
    assert any("need a light" in str(m).lower() for m in out)


def test_a_companion_strikes_a_light_when_the_room_is_black():
    """The torch is no use in a pack, and nobody can strike a blow in the
    dark of Mirkwood."""
    game = Game(seed=1)
    dwalin = game.characters["dwalin"]
    old = game.world.get(dwalin.location_id)
    if "dwalin" in old.npcs:
        old.npcs.remove("dwalin")
    dwalin.location_id = "mirkwood_path_2"
    game.world.get("mirkwood_path_2").npcs.append("dwalin")
    dwalin.inventory = ["torch"]
    game.player.location_id = "mirkwood_path_2"

    cmd = dwalin.decide(game)
    assert cmd is not None and cmd.verb == "light"


def test_no_companion_pockets_the_torch():
    """Only the player's own light lets them walk into a dark room, so a
    helpful dwarf picking the brand up off the floor at Bag End left Bilbo
    unable to enter the goblin tunnels at all. Caught by soak-testing: the
    journey stopped dead at the cave mouth."""
    game = Game(seed=1)
    dwalin = game.characters["dwalin"]
    game.player.location_id = "bag_end"
    dwalin.location_id = "bag_end"
    if "dwalin" not in game.world.get("bag_end").npcs:
        game.world.get("bag_end").npcs.append("dwalin")
    dwalin.inventory = []
    assert "torch" in game.world.get("bag_end").items

    for _ in range(5):
        cmd = dwalin.decide(game)
        assert not (cmd and cmd.verb == "take"
                    and "torch" in (cmd.obj or "").lower())


def test_a_companion_who_has_a_torch_still_lights_it():
    """They don't pick one up, but one handed to them is used."""
    game = Game(seed=1)
    dwalin = game.characters["dwalin"]
    old = game.world.get(dwalin.location_id)
    if "dwalin" in old.npcs:
        old.npcs.remove("dwalin")
    dwalin.location_id = "mirkwood_path_2"
    game.world.get("mirkwood_path_2").npcs.append("dwalin")
    dwalin.inventory = ["torch"]
    game.player.location_id = "mirkwood_path_2"

    cmd = dwalin.decide(game)
    assert cmd is not None and cmd.verb == "light"
