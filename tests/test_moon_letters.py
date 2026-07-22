"""The map's moon-letters: reading them at the moonlit table in Elrond's
Library reveals what the silver key is for."""
from hobbit.game import Game


def _examine_map(game):
    return [getattr(m, "text", m) for m in game.process_player_input("examine map")]


def test_map_reveals_key_purpose_at_the_moonlit_table():
    game = Game(seed=1)
    game.player.inventory.append("thorin_map")
    game.player.location_id = "rivendell_library"  # moonlit
    lines = " ".join(_examine_map(game)).lower()
    assert game.moon_letters_read
    assert "moon-letters" in lines
    assert "key" in lines and "door" in lines


def test_map_stays_flavor_away_from_moonlight():
    game = Game(seed=1)
    game.player.inventory.append("thorin_map")
    game.player.location_id = "lone_lands_1"  # not moonlit
    lines = " ".join(_examine_map(game)).lower()
    assert not game.moon_letters_read
    # only the standing hint that you'd need moonlight, not the deciphered text
    assert "durin's day" not in lines


def test_once_read_the_map_reminds_you_elsewhere():
    game = Game(seed=1)
    game.player.inventory.append("thorin_map")
    game.player.location_id = "rivendell_library"
    _examine_map(game)  # read them under the moon
    game.player.location_id = "lone_lands_1"
    lines = " ".join(_examine_map(game)).lower()
    assert "moon-letter key" in lines


def test_moon_letters_read_survives_save_load(tmp_path):
    save = tmp_path / "s.json"
    game = Game(seed=1)
    game.moon_letters_read = True
    game.save(save)
    fresh = Game(seed=1)
    assert not fresh.moon_letters_read
    fresh.load(save)
    assert fresh.moon_letters_read


def test_purist_leaves_the_map_as_wall_flavor():
    game = Game(seed=1, authentic=True)
    game.player.inventory.append("thorin_map")
    game.player.location_id = "rivendell_library"
    _examine_map(game)
    # no moon-letters puzzle in the raw 1982 experience
    assert not game.moon_letters_read


def test_the_keyhole_stops_posing_a_riddle_once_the_key_has_turned():
    """You can only stand at the Secret Door after unlocking it, so a
    future-tense 'whatever opens it will need to be...' would always be read
    by someone already holding the answer -- and reads like a second lock."""
    from hobbit.game import Game
    game = Game(seed=1)
    room = game.world.get("secret_door")

    locked = " ".join(str(getattr(m, "text", m))
                      for m in _examine_keyhole(game))
    assert "will need to be" in locked

    game.player.inventory = ["moon_key"]
    game.player.location_id = "secret_door_path"
    game.process_player_input("open door")
    assert not room.locked
    opened = " ".join(str(getattr(m, "text", m)) for m in _examine_keyhole(game))
    assert "moon-letter key" in opened
    assert "will need to be" not in opened


def _examine_keyhole(game):
    game.player.location_id = "secret_door"
    return game.process_player_input("examine keyhole")


def test_scenery_without_a_second_reading_is_unaffected():
    from hobbit.game import Game
    game = Game(seed=1)
    scenery = game.world.get("secret_door").scenery[0]
    plain = game.world.get("bag_end").scenery[0]
    assert plain.opened_description == plain.description
    assert scenery.opened_description != scenery.description
