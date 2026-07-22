"""Tests for goal-directed NPC agency and the follow command."""
from hobbit.game import Game
from hobbit.npc import GoalBrain, LLMGoalBrain, LLMBrain


class FakeLLM:
    def __init__(self, reply="ADVANCE"):
        self.reply = reply
        self.calls = 0

    def chat(self, system, user):
        self.calls += 1
        return self.reply


def _step_toward(game, npc_id, target, max_turns=40):
    npc = game.characters[npc_id]
    start_dist = _dist(game, npc.location_id, target)
    for _ in range(max_turns):
        game._advance_world_turn()
        if npc.location_id == target:
            return True
    return _dist(game, npc.location_id, target) < start_dist


def _dist(game, a, b):
    # crude BFS distance for assertions
    from collections import deque
    seen = {a}
    q = deque([(a, 0)])
    while q:
        cur, d = q.popleft()
        if cur == b:
            return d
        for nb in game.world.get(cur).exits.values():
            if nb not in seen:
                seen.add(nb)
                q.append((nb, d + 1))
    return 999


def test_company_travels_with_bilbo_not_off_on_its_own():
    game = Game(seed=1)  # standard mode, no LLM -> scripted escort goals
    assert isinstance(game.characters["thorin"].brain, GoalBrain)
    # Bilbo journeys east; the company should come with him, not lag behind
    # nor race ahead -- staying within the leash.
    for step in ("go east", "go east", "go east", "go east"):
        game.process_player_input(step)
    for _ in range(6):
        game._advance_world_turn()
    for cid in ("thorin", "balin"):
        d = game.world.distance(game.characters[cid].location_id, game.player.location_id)
        assert d <= 3, f"{cid} strayed {d} rooms from Bilbo"
    # Gandalf is the scout: he may range further ahead, but never beyond
    # his scouting range.
    from hobbit.npc import SCOUT_RANGE
    d = game.world.distance(game.characters["gandalf"].location_id, game.player.location_id)
    assert d <= SCOUT_RANGE + 1, f"gandalf strayed {d} rooms from Bilbo"


def test_stranded_companion_returns_to_bilbo():
    game = Game(seed=2)
    balin = game.characters["balin"]
    game.world.get("bag_end").npcs.remove("balin")
    balin.location_id = "rivendell_hall"  # far from Bilbo at Bag End
    game.world.get("rivendell_hall").npcs.append("balin")
    before = game.world.distance(balin.location_id, game.player.location_id)
    for _ in range(30):
        game._advance_world_turn()
    after = game.world.distance(balin.location_id, game.player.location_id)
    assert after < before  # heads back toward Bilbo


def test_llm_chooses_goal_when_available_then_scripted_fallback():
    fake = FakeLLM(reply="GUARD_BILBO")
    game = Game(seed=1, llm=fake)
    gandalf = game.characters["gandalf"]
    assert isinstance(gandalf.brain, LLMBrain)
    assert isinstance(gandalf.brain.base, LLMGoalBrain)
    game._goal_budget = 5
    gandalf.brain.base._assign_goal(gandalf, game)
    assert gandalf.goal_target == game.player.location_id  # GUARD_BILBO resolved
    assert fake.calls == 1


def test_goal_budget_caps_llm_calls_per_turn():
    fake = FakeLLM(reply="ADVANCE")
    game = Game(seed=1, llm=fake)
    game._goal_budget = 1
    assert game.take_goal_budget() is True
    assert game.take_goal_budget() is False  # budget exhausted


def test_player_can_follow_a_companion():
    game = Game(seed=1)
    # move Thorin somewhere and have the player follow
    game.process_player_input("follow thorin")
    assert game.player_follow == "thorin"
    # advance until Thorin moves; player should track to his room
    for _ in range(10):
        game._advance_world_turn()
        if game.player.location_id == game.characters["thorin"].location_id:
            break
    assert game.player.location_id == game.characters["thorin"].location_id


def test_following_a_companion_makes_them_lead_the_march():
    """Follow Thorin and the deadlock is broken: he takes the lead toward the
    Mountain and draws Bilbo (and the company) east, instead of both waiting
    on each other forever."""
    game = Game(seed=1)
    front = "front_gate"
    before = game.world.distance(game.player.location_id, front)
    game.process_player_input("follow thorin")
    for _ in range(12):
        game.process_player_input("wait")  # keep pace -- Thorin leads
    thorin = game.characters["thorin"]
    after = game.world.distance(game.player.location_id, front)
    assert thorin.goal_kind == "lead"
    assert after < before  # the march actually progressed
    assert game.world.distance(game.player.location_id, thorin.location_id) <= 1


def test_company_stays_with_bilbo_while_he_follows_a_leader():
    """'The company catches up' must mean they're actually here. The follow
    move used to resolve after everyone else acted, so the dwarves escorted
    Bilbo to the room he was about to leave and trailed a room behind forever."""
    game = Game(seed=1)
    game.process_player_input("follow thorin")
    for _ in range(10):
        game.process_player_input("wait")
    here = game.player.location_id
    strays = [c.name for c in game.characters.values()
              if c is not game.player and getattr(c, "def_", None)
              and c.def_.is_party and c.alive and c.location_id != here]
    assert not strays, f"companions left behind: {strays}"


def test_leader_returns_to_the_ranks_when_you_stop_following():
    game = Game(seed=1)
    game.process_player_input("follow thorin")
    for _ in range(4):
        game.process_player_input("wait")
    assert game.characters["thorin"].goal_kind == "lead"
    game.process_player_input("follow")  # stop
    for _ in range(2):
        game.process_player_input("wait")
    assert game.characters["thorin"].goal_kind == "escort"


def test_a_badly_hurt_followed_leader_still_breaks_off_to_heal():
    game = Game(seed=1)
    game.player.location_id = "rivendell_bridge"  # a haven is in range
    thorin = game.characters["thorin"]
    game.world.get("bag_end").npcs.remove("thorin")
    thorin.location_id = "rivendell_bridge"
    game.world.get("rivendell_bridge").npcs.append("thorin")
    thorin.health = 3  # grievously wounded
    game.player_follow = "thorin"
    thorin.brain._move_step(thorin, game, game.world.get(thorin.location_id))
    assert thorin.goal_kind == "heal"  # survival wins over gold-lust


def test_an_explicit_stay_at_my_side_overrides_follow_lead():
    game = Game(seed=1)
    thorin = game.characters["thorin"]
    game.process_player_input("thorin, follow me")   # forced guard
    game.process_player_input("follow thorin")        # ...and we follow him
    thorin.brain._move_step(thorin, game, game.world.get(thorin.location_id))
    assert thorin.goal_kind != "lead"  # the explicit order wins


def test_follow_stop():
    game = Game(seed=1)
    game.process_player_input("follow thorin")
    assert game.player_follow == "thorin"
    msgs = game.process_player_input("follow")
    assert game.player_follow is None
    assert any("stop following" in m.lower() for m in msgs)


def test_waiting_keeps_pace_but_resting_breaks_the_march():
    """Settling down to rest or stopping to eat means you are no longer
    keeping pace -- but merely waiting is how you travel with them."""
    game = Game(seed=1)
    game.process_player_input("follow thorin")
    msgs = " ".join(str(getattr(m, "text", m)) for m in game.process_player_input("wait"))
    assert game.player_follow == "thorin"
    assert "keep pace" in msgs

    for verb in ("rest", "eat bread"):
        game = Game(seed=1)
        game.process_player_input("follow thorin")
        msgs = " ".join(str(getattr(m, "text", m))
                        for m in game.process_player_input(verb))
        assert game.player_follow is None, verb
        assert "break off" in msgs, verb


def test_walking_off_on_your_own_breaks_the_march():
    """Choosing your own direction means you've stopped following -- and you
    end up where YOU went, never dragged back to the leader."""
    game = Game(seed=1)
    game.process_player_input("follow thorin")
    for _ in range(3):
        game.process_player_input("wait")  # let him lead a while
    here = game.player.location_id
    chosen = game.world.get(here).exits["west"]
    msgs = " ".join(str(getattr(m, "text", m))
                    for m in game.process_player_input("west"))
    assert game.player_follow is None
    assert "break off" in msgs
    assert game.player.location_id == chosen  # not yanked after Thorin


def test_checking_your_status_does_not_break_the_march():
    game = Game(seed=1)
    game.process_player_input("follow thorin")
    for cmd in ("party", "status", "look", "inventory", "help", "examine map"):
        game.process_player_input(cmd)
    assert game.player_follow == "thorin"


def test_fighting_does_not_break_the_march():
    """Combat is thrust upon you, not a decision to stop marching."""
    game = Game(seed=1)
    game.process_player_input("follow thorin")
    game.process_player_input("attack thorin")
    assert game.player_follow == "thorin"


def test_wait_is_no_longer_merely_a_synonym_for_rest():
    game = Game(seed=1)
    game.player.fatigue = 50
    game.process_player_input("wait")
    assert game.player.fatigue >= 50  # waiting does not recover you
    before = game.player.fatigue
    game.process_player_input("rest")
    assert game.player.fatigue < before


def test_unfollow_has_its_own_word():
    """'follow' alone meaning "stop following" was a pun, not a command."""
    for phrase in ("unfollow", "stop following", "stop follow", "stop"):
        game = Game(seed=1)
        game.process_player_input("follow thorin")
        assert game.player_follow == "thorin"
        msgs = game.process_player_input(phrase)
        assert game.player_follow is None, phrase
        assert any("stop following" in m.lower() for m in msgs), phrase


def test_bare_follow_still_stops_for_old_habits():
    game = Game(seed=1)
    game.process_player_input("follow thorin")
    game.process_player_input("follow")
    assert game.player_follow is None


def test_unfollow_when_not_following_says_so():
    game = Game(seed=1)
    msgs = game.process_player_input("unfollow")
    assert any("aren't following" in m.lower() for m in msgs)


def test_telling_a_companion_to_stop_releases_them():
    game = Game(seed=1)
    game.process_player_input("thorin, follow me")
    assert game.characters["thorin"].forced_goal == "guard_bilbo"
    game.process_player_input("thorin, stop")
    assert game.characters["thorin"].forced_goal is None


def test_order_companion_to_follow_me():
    game = Game(seed=1)
    msgs = game.process_player_input("thorin, follow me")
    thorin = game.characters["thorin"]
    assert thorin.forced_goal == "guard_bilbo"
    assert any("side" in m.lower() for m in msgs)


def _place_at(game, cid, room):
    char = game.characters[cid]
    old = game.world.get(char.location_id)
    if cid in old.npcs:
        old.npcs.remove(cid)
    char.location_id = room
    if cid not in game.world.get(room).npcs:
        game.world.get(room).npcs.append(cid)


def test_companions_reconsider_at_once_when_things_turn_bad():
    """Goals are normally reconsidered every GOAL_REPLAN_INTERVAL turns, so a
    dwarf who dropped to death's door kept marching for ~11 more turns on a
    goal chosen while hale. That is how Thorin came to grief two rooms from
    Rivendell."""
    for ruin, expected in (("hurt", "heal"), ("starving", "forage")):
        game = Game(seed=1)
        balin = game.characters["balin"]
        _place_at(game, "balin", "rivendell_bridge")
        game.player.location_id = "rivendell_bridge"
        balin.brain._assign_goal(balin, game)
        assert balin.goal_kind == "escort"
        if ruin == "hurt":
            balin.health = 4
        else:
            balin.inventory, balin.hunger = [], 95
        balin.brain._move_step(balin, game, game.world.get(balin.location_id))
        assert balin.goal_kind == expected, ruin  # the very next turn


def test_reacting_promptly_does_not_make_neglect_survivable():
    """Self-preservation is about not being oblivious, not about immunity: a
    starving fighter pinned by a monster still dies."""
    game = Game(seed=1)
    thorin = game.characters["thorin"]
    _place_at(game, "thorin", "misty_foothills")
    thorin.hunger, thorin.fatigue, thorin.health = 100, 6, 14
    thorin.inventory = []
    _place_at(game, "warg", "misty_foothills")
    game.characters["warg"].alive = True
    game.player.location_id = "rivendell_hall"
    for _ in range(25):
        game._advance_world_turn()
        if not thorin.alive:
            break
    assert not thorin.alive
