from hobbit.game import Game
from hobbit.ui import Note, present


def test_examine_key_by_short_name():
    """Regression: 'iron key' shown in the room could not be examined as
    'key'."""
    game = Game(seed=1)
    game.player.location_id = "trolls_clearing"
    game.player.inventory.append("key_troll_cave")
    messages = game.process_player_input("examine key")
    assert any("rusty iron key" in m.lower() for m in messages)


def test_take_item_by_head_noun():
    game = Game(seed=1)
    game.player.location_id = "trolls_clearing"
    game.world.get("trolls_clearing").items.append("gold_coins_small")
    messages = game.process_player_input("take coins")
    assert "gold_coins_small" in game.player.inventory
    assert any("take" in m.lower() for m in messages)


def test_autolook_shows_room_after_move_with_only_the_title_colored():
    game = Game(seed=1)  # enhanced/standard
    msgs = game.process_player_input("go east")
    shown = present(msgs, game.annotation_level)
    block = next(m for m in shown if "Hobbiton Road" in m)
    # the title line is coloured...
    assert "\033[96m== Hobbiton Road ==\033[0m" in block
    # ...but the description body is plain (no colour code on that line)
    desc_row = next(r for r in block.split("\n") if "dusty lane" in r)
    assert "\033[" not in desc_row


def test_no_autolook_without_moving():
    game = Game(seed=1)
    msgs = game.process_player_input("look")
    # a plain look shows the room but with no coloured title
    assert not any("\033[96m== Bag End ==" in m for m in present(msgs, game.annotation_level))


def test_no_autolook_in_purist_mode():
    game = Game(seed=1, authentic=True)
    msgs = game.process_player_input("go east")
    # purist stays faithful: no room block appears automatically after a move
    assert not any("Hobbiton Road" in m for m in msgs)
