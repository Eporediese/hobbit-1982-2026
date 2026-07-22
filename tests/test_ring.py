"""The ring. It used to do almost nothing -- a 60% chance an attacker missed.
Now it makes Bilbo genuinely unseen: nothing will attack him, the company
cannot follow what they cannot see, and a blow struck from nowhere gives him
away (or he could kill Smaug in perfect safety)."""
from hobbit.game import Game


def _place(game, cid, room):
    char = game.characters[cid]
    old = game.world.get(char.location_id)
    if cid in old.npcs:
        old.npcs.remove(cid)
    char.location_id = room
    if cid not in game.world.get(room).npcs:
        game.world.get(room).npcs.append(cid)


def _among_trolls(game, wear):
    room = "trolls_clearing"
    game.player.location_id = room
    game.player.inventory = ["ring", "sting"]
    for troll in ("troll_tom", "troll_bert", "troll_william"):
        _place(game, troll, room)
        game.characters[troll].alive = True
    if wear:
        game.process_player_input("wear ring")
    struck = 0
    for _ in range(10):
        for msg in game._advance_world_turn():
            text = str(getattr(msg, "text", msg))
            if "Bilbo" in text and ("hits" in text or "attacks" in text):
                struck += 1
    return struck


def test_nothing_attacks_him_while_he_wears_it():
    assert _among_trolls(Game(seed=3), wear=False) > 0   # mobbed without it
    assert _among_trolls(Game(seed=3), wear=True) == 0   # untouched with it


def test_the_company_cannot_follow_what_they_cannot_see():
    game = Game(seed=1)
    game.player.inventory = ["ring"]
    game.process_player_input("wear ring")
    vanished = game.player.location_id
    for _ in range(6):
        game.process_player_input("east")
    party = [c for c in game.characters.values()
             if getattr(c, "def_", None) and c.def_.is_party]
    assert not any(c.location_id == game.player.location_id for c in party)
    assert any(c.location_id == vanished for c in party)  # waiting where he vanished


def test_taking_it_off_lets_them_gather_to_him_again():
    game = Game(seed=1)
    game.player.inventory = ["ring"]
    game.process_player_input("wear ring")
    for _ in range(6):
        game.process_player_input("east")
    game.process_player_input("remove ring")
    for _ in range(10):
        game._advance_world_turn()
    party = [c for c in game.characters.values()
             if getattr(c, "def_", None) and c.def_.is_party]
    assert any(c.location_id == game.player.location_id for c in party)


def test_he_may_still_follow_a_companion_while_unseen():
    game = Game(seed=1)
    game.player.inventory = ["ring"]
    game.process_player_input("wear ring")
    game.process_player_input("follow thorin")
    before = game.world.distance(game.player.location_id, "front_gate")
    for _ in range(8):
        game.process_player_input("wait")
    after = game.world.distance(game.player.location_id, "front_gate")
    assert after < before  # he can follow, even though he can't be followed


def test_striking_a_blow_gives_him_away():
    game = Game(seed=3)
    _among_trolls(game, wear=True)
    assert game.player.invisible
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("attack tom"))
    assert not game.player.invisible
    assert "ring" not in game.player.worn
    assert "see you now" in msgs


def test_the_ring_really_falls_and_must_be_picked_up():
    """It says it slips from his finger, so it had better be on the ground --
    not tucked safely back in his pocket."""
    game = Game(seed=3)
    _among_trolls(game, wear=True)
    room = game.player.location_id
    game.process_player_input("attack tom")
    assert "ring" not in game.player.inventory     # genuinely lost hold of it
    assert "ring" in game.world.get(room).items    # lying where he stood
    game.process_player_input("take ring")
    assert "ring" in game.player.inventory         # and recoverable


class _FakeLLM:
    def chat(self, system, user):
        return "Well met, Mr. Baggins!"


def test_status_tells_you_that_you_are_unseen():
    game = Game(seed=1)
    game.player.inventory = ["ring"]
    plain = " ".join(str(getattr(m, "text", m))
                     for m in game.process_player_input("status"))
    assert "unseen" not in plain
    game.process_player_input("wear ring")
    worn = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("status"))
    assert "plain gold ring" in worn   # what he's wearing
    assert "unseen" in worn            # and what it means


def test_companions_do_not_chatter_at_a_hobbit_they_cannot_see():
    game = Game(seed=1, llm=_FakeLLM())
    game.rng.random = lambda: 0.0  # force the ambient chance every turn
    assert game._maybe_ambient_remark()          # they speak to a visible Bilbo
    game.player.inventory = ["ring"]
    game.process_player_input("wear ring")
    assert game._maybe_ambient_remark() == []    # but not to an unseen one


def test_the_scout_cannot_report_to_someone_he_cannot_see():
    game = Game(seed=1)
    gandalf = game.characters["gandalf"]
    _place(game, "gandalf", game.player.location_id)
    news = [{"text": "wolves gather at the ford", "concern": None}]

    gandalf.scout_unreported = list(news)
    game.player.invisible = True
    assert game._scout_report() == []      # nothing to report TO

    gandalf.scout_unreported = list(news)
    game.player.invisible = False
    assert game._scout_report()            # reports once he can see him again


def test_speaking_aloud_gives_you_away():
    game = Game(seed=1, llm=_FakeLLM())
    game.player.inventory = ["ring"]
    game.process_player_input("wear ring")
    assert game.player.invisible
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("talk to thorin"))
    assert not game.player.invisible
    assert "ring" not in game.player.worn
    assert "voice out of thin air" in msgs


def test_the_ring_counts_in_the_reckoning():
    game = Game(seed=1)
    game.player.inventory = ["ring"]
    assert game.treasure_total() > 0
    text = " ".join(str(getattr(m, "text", m)) for m in game.treasure_reckoning())
    assert "plain gold ring" in text


def test_a_ring_left_on_the_floor_is_worth_nothing():
    game = Game(seed=1)
    game.player.inventory = ["ring"]
    worth = game.treasure_total()
    game.player.inventory = []
    game.world.get(game.player.location_id).items.append("ring")
    assert game.treasure_total() == 0 < worth


def test_the_ring_shows_in_party_so_you_know_who_holds_it():
    game = Game(seed=1)
    game.player.inventory = ["ring"]
    lines = " ".join(str(getattr(m, "text", m))
                     for m in game.process_player_input("party"))
    assert "plain gold ring" in lines


def test_no_one_sheds_treasure_to_make_room():
    """The ring weighs nothing, so it would otherwise be first out of the pack
    when a companion made space for a gift."""
    game = Game(seed=1)
    bombur = game.characters["bombur"]
    _place(game, "bombur", game.player.location_id)
    bombur.inventory = ["ring"] + ["bread"] * bombur.max_carry
    game.player.inventory = ["gold_coins_small"]
    game.process_player_input("give coins to bombur")
    assert "ring" in bombur.inventory
    assert "bread" in game.world.get(game.player.location_id).items


def test_a_dropped_ring_can_be_left_behind():
    game = Game(seed=3)
    _among_trolls(game, wear=True)
    room = game.player.location_id
    game.process_player_input("attack tom")
    game.process_player_input("west")  # flee without stooping for it
    assert "ring" in game.world.get(room).items
    assert "ring" not in game.player.inventory


def test_the_ring_lets_him_walk_in_the_dark():
    """Gollum kept his sight in the deep places while he bore it, and so does
    Bilbo -- it's what makes a stealth rescue possible at all."""
    game = Game(seed=1)
    game.player.location_id = "spiders_web_clearing"
    game.player.inventory = ["ring"]
    blocked = " ".join(str(getattr(m, "text", m))
                       for m in game.process_player_input("north"))
    assert "pitch dark" in blocked
    assert game.player.location_id == "spiders_web_clearing"

    game.process_player_input("wear ring")
    game.process_player_input("north")
    assert game.player.location_id == "spiders_nest"


def test_he_can_free_the_webbed_without_ever_fighting():
    game = Game(seed=1)
    for cid in ("balin", "ori", "bofur"):
        _place(game, cid, "spiders_nest")
        game.characters[cid].captured = True
    _place(game, "giant_spider", "spiders_nest")
    game.characters["giant_spider"].alive = True
    game.player.location_id = "spiders_web_clearing"
    game.player.inventory = ["ring", "sting"]
    game.process_player_input("wear ring")
    game.process_player_input("north")
    assert not any(game.characters[c].captured for c in ("balin", "ori", "bofur"))
    assert game.characters["giant_spider"].alive     # never had to fight it
    assert game.player.health == game.player.max_health  # and took no hurt


def test_the_ring_is_no_substitute_for_a_torch_for_the_company():
    """It lights nothing for anyone but him: the dwarves still cannot fight."""
    game = Game(seed=1)
    game.player.location_id = "spiders_nest"
    game.player.inventory = ["ring"]
    game.process_player_input("wear ring")
    assert game.player_can_see_in_dark(game.player)
    assert not game.room_is_lit("spiders_nest")
    assert not game.can_fight_here("spiders_nest")


def test_taking_the_ring_off_leaves_him_in_the_dark_again():
    game = Game(seed=1)
    game.player.location_id = "spiders_nest"
    game.player.inventory = ["ring"]
    game.process_player_input("wear ring")
    assert game.player_can_see_in_dark(game.player)
    game.process_player_input("remove ring")
    assert not game.player_can_see_in_dark(game.player)
