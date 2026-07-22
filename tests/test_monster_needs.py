"""Monsters don't hunger or tire, so they can't starve to death in place --
which previously handed the player a free 'win' when Smaug quietly starved
in his lair over a long game."""
from hobbit.game import Game


def test_monsters_do_not_accumulate_hunger_or_fatigue():
    game = Game(seed=1)
    smaug = game.characters["smaug"]
    for _ in range(300):
        smaug.tick_needs()
    assert smaug.hunger == 0
    assert smaug.fatigue == 0
    assert not smaug.is_weak()
    assert smaug.needs_health_drain() == 0


def test_idle_dragon_never_dies_and_never_grants_a_win():
    game = Game(seed=1)
    smaug = game.characters["smaug"]
    for _ in range(300):
        # keep Bilbo fed so his own starvation doesn't end the run early
        game.player.hunger = 0
        game.player.fatigue = 0
        game._advance_world_turn()
    assert smaug.alive
    assert not game.won


def test_travellers_still_feel_needs():
    game = Game(seed=1)
    assert game.player.feels_needs
    thorin = game.characters["thorin"]
    assert thorin.feels_needs  # a companion, not a monster


def _place(game, cid, room):
    char = game.characters[cid]
    old = game.world.get(char.location_id)
    if cid in old.npcs:
        old.npcs.remove(cid)
    char.location_id = room
    if cid not in game.world.get(room).npcs:
        game.world.get(room).npcs.append(cid)


def test_monsters_do_tire_from_a_real_fight():
    """A long battle wears a beast down, so persistence pays."""
    game = Game(seed=1)
    spider = game.characters["giant_spider"]
    for _ in range(5):
        spider.add_combat_fatigue()
    assert spider.fatigue > 0


def test_monsters_get_their_wind_back_in_the_lull():
    """Otherwise fatigue only ever climbs and a beast eventually faints in its
    own lair, having never eaten or slept in its life."""
    game = Game(seed=1)
    spider = game.characters["giant_spider"]
    spider.fatigue = 40
    for _ in range(20):
        game._advance_world_turn()      # nothing to fight
    assert spider.fatigue == 0


def test_monsters_do_not_tire_from_travelling():
    game = Game(seed=1)
    warg = game.characters["warg"]
    for _ in range(50):
        warg.add_travel_fatigue()
    assert warg.fatigue == 0 and warg.hunger == 0


def test_a_monster_never_tires_from_penning_prisoners():
    """Webbing is not fighting. The spider used to stand over its own captives
    beating them round after round -- they cannot strike back or flee -- which
    both killed them in the larder and wore it out for nothing."""
    game = Game(seed=1)
    room = "spiders_nest"
    spider = game.characters["giant_spider"]
    _place(game, "giant_spider", room)
    spider.alive = True
    for cid in ("balin", "dwalin"):
        _place(game, cid, room)
        game.characters[cid].captured = True
    game.player.location_id = "bag_end"
    attacks = 0
    for _ in range(30):
        cmd = spider.brain.decide(spider, game)
        if cmd and cmd.verb == "attack":
            attacks += 1
    assert attacks == 0                       # larder, not foes
    assert spider.fatigue == 0                # and so it costs nothing
    assert game.characters["balin"].health == game.characters["balin"].max_health


def test_captives_are_not_killed_while_helpless():
    game = Game(seed=1)
    room = "spiders_nest"
    _place(game, "giant_spider", room)
    game.characters["giant_spider"].alive = True
    balin = game.characters["balin"]
    _place(game, "balin", room)
    balin.captured = True
    game.player.location_id = "bag_end"
    for _ in range(40):
        game._advance_world_turn()
    assert balin.alive
    assert balin.health == balin.max_health


def test_the_too_weak_line_opens_with_a_capital():
    """'giant spider is too weak from hunger and fatigue to act.'"""
    game = Game(seed=1)
    game.player.hunger = 100
    game.player.fatigue = 100
    line = str(getattr(game.process_player_input("east")[0], "text",
                       game.process_player_input("east")[0]))
    assert line[0].isupper()


def test_residents_do_not_starve_in_their_own_halls():
    """Elrond and the Elvenking's guard aren't monsters, so they felt hunger --
    but nothing feeds anyone outside the travelling company, so they starved to
    death at home. Elrond died amid his own feast."""
    game = Game(seed=1)
    for cid in ("elrond", "elf_guard"):
        resident = game.characters[cid]
        assert not resident.feels_needs
        for _ in range(200):
            resident.tick_needs()
        assert resident.hunger == 0
        assert resident.needs_health_drain() == 0


def test_the_company_still_feels_hunger():
    game = Game(seed=1)
    assert game.player.feels_needs
    for cid in ("thorin", "balin", "gandalf"):
        assert game.characters[cid].feels_needs


def test_a_long_idle_game_leaves_the_residents_alive():
    game = Game(seed=1)
    for _ in range(300):
        game.player.hunger = 0        # keep Bilbo going; we're watching them
        game.player.fatigue = 0
        game._advance_world_turn()
    assert game.characters["elrond"].alive
    assert game.characters["elf_guard"].alive


# -- nobody falls twice ---------------------------------------------------

def test_a_death_is_only_processed_once():
    """'Cairns stand here, raised over Gandalf and Gandalf.'"""
    game = Game(seed=1)
    gandalf = game.characters["gandalf"]
    _place(game, "gandalf", "forest_river")
    _place(game, "balin", "forest_river")
    game.player.location_id = "forest_river"
    gandalf.alive = False
    gandalf.inventory = ["glamdring"]
    game.handle_death(gandalf)
    game.handle_death(gandalf)          # twice
    game._resolve_burials()
    game._resolve_burials()
    room = game.world.get("forest_river")
    assert room.graves == ["Gandalf"]
    assert room.items.count("glamdring") == 1
    news = [str(getattr(m, "text", m)) for m in game._deliver_company_news()]
    assert sum("has fallen" in n for n in news) == 1


def test_loading_tidies_a_double_burial_already_in_a_save(tmp_path):
    game = Game(seed=1)
    game.world.get("forest_river").graves = ["Gandalf", "Gandalf"]
    path = tmp_path / "s.json"
    game.save(path)
    fresh = Game(seed=1)
    fresh.load(path)
    assert fresh.world.get("forest_river").graves == ["Gandalf"]
