"""Tests for the hybrid LLM-driven NPC brain, using a fake client so no
network or model is needed."""
from hobbit.game import Game
from hobbit.npc import LLMBrain, SimpleBrain


class FakeLLM:
    """Records prompts and returns a canned reply (or raises, to test
    fallback)."""
    def __init__(self, reply="A canned in-character line.", raise_on_call=False):
        self.reply = reply
        self.raise_on_call = raise_on_call
        self.calls = []

    def chat(self, system, user):
        self.calls.append((system, user))
        if self.raise_on_call:
            raise RuntimeError("model exploded")
        return self.reply


def test_ai_flag_set_when_llm_supplied():
    assert Game(seed=1, llm=FakeLLM()).ai is True
    assert Game(seed=1).ai is False


def test_party_npcs_get_llmbrain_only_when_ai_on():
    ai_game = Game(seed=1, llm=FakeLLM())
    assert isinstance(ai_game.characters["thorin"].brain, LLMBrain)
    # monsters stay rule-based even in AI mode
    assert not isinstance(ai_game.characters["smaug"].brain, LLMBrain)

    plain = Game(seed=1)
    assert isinstance(plain.characters["thorin"].brain, SimpleBrain)


def test_clean_preserves_mr_baggins_across_the_honorific_period():
    from hobbit.npc import _clean
    line = "We have much to do, Mr. Baggins, ere the year turns."
    assert _clean(line) == line


def test_clean_extracts_speech_from_mixed_narration_and_quotes():
    from hobbit.npc import _clean
    raw = 'Thorin looked at the hobbit with a furrowed brow. "We have much to do, Mr. Baggins."'
    assert _clean(raw) == "We have much to do, Mr. Baggins."


def test_clean_handles_token_cut_with_lost_closing_quote():
    from hobbit.npc import _clean
    raw = 'Thorin frowned. "We march at dawn, Mr. Baggins, and'
    out = _clean(raw)
    assert out == "We march at dawn, Mr. Baggins, and..."


def test_clean_caps_by_length_not_by_sentence_count():
    """This used to assert a flat two-sentence cap. That rule was tuned
    against a small local model which rambled in long sentences, and it
    amputated a stronger model's short, punchy dialogue -- so the cap is now
    a character budget, and three brief sentences survive together."""
    from hobbit.npc import _clean
    raw = "One is here. Two is here. Three should stay."
    assert _clean(raw) == "One is here. Two is here. Three should stay."


def test_anachronistic_sauron_is_scrubbed_to_the_necromancer():
    fake = FakeLLM(reply="We must not become lost in Sauron's realm, Bilbo.")
    game = Game(seed=1, llm=fake)
    messages = game.process_player_input("talk to thorin")
    joined = " ".join(messages)
    assert "Sauron" not in joined
    assert "Necromancer" in joined


def test_talk_uses_llm_line_in_ai_mode():
    fake = FakeLLM(reply="I am Thorin, and I do not suffer burglars gladly.")
    game = Game(seed=1, llm=fake)
    messages = game.process_player_input("talk to thorin")
    assert any("do not suffer burglars" in m for m in messages)
    assert fake.calls, "the LLM should have been consulted"


def test_talk_falls_back_to_static_dialogue_when_model_fails():
    game = Game(seed=1, llm=FakeLLM(raise_on_call=True))
    messages = game.process_player_input("talk to thorin")
    # the static line from npcs.json comes through instead of crashing
    assert any("reclaim what is ours" in m for m in messages)


def test_talk_static_when_ai_off():
    game = Game(seed=1)
    messages = game.process_player_input("talk to gandalf")
    assert any("more in you of good" in m for m in messages)


def test_llmbrain_actions_delegate_to_base_brain():
    """The hybrid keeps mechanical actions rule-based, so decisions match
    the plain SimpleBrain given the same seed and state."""
    ai_game = Game(seed=99, llm=FakeLLM())
    plain = Game(seed=99)
    thorin_ai = ai_game.characters["thorin"]
    thorin_plain = plain.characters["thorin"]
    # move both to the same non-trivial spot
    for g, t in ((ai_game, thorin_ai), (plain, thorin_plain)):
        t.location_id = "mirkwood_path_1"
    a = thorin_ai.decide(ai_game)
    b = thorin_plain.decide(plain)
    assert (a.verb, a.obj) == (b.verb, b.obj) if a and b else a == b


def test_ambient_remark_fires_with_a_present_companion():
    fake = FakeLLM(reply="These roads are longer than the songs let on.")
    game = Game(seed=1, llm=fake)
    game.rng.random = lambda: 0.0  # force the ambient chance to trigger
    msgs = game._maybe_ambient_remark()
    assert any("longer than the songs" in m for m in msgs)


def test_ambient_remark_skipped_when_no_companion_present():
    fake = FakeLLM()
    game = Game(seed=1, llm=fake)
    game.rng.random = lambda: 0.0
    # strand the player far from everyone
    game.player.location_id = "smaugs_lair" if "smaugs_lair" in game.world.locations else "treasure_chamber"
    assert game._maybe_ambient_remark() == []


def test_ambient_remark_absent_without_ai():
    game = Game(seed=1)  # no llm
    game.rng.random = lambda: 0.0
    assert game._maybe_ambient_remark() == []


def test_narration_is_told_the_real_combat_outcome():
    """The flourish is handed the mechanical result so it can't invent a
    kill on a miss -- the bug where Thorin 'missed' yet the prose said he
    struck the troll down in a lifeless heap."""
    from hobbit.parser import Command
    fake = FakeLLM(reply="A flourish.")
    game = Game(seed=1, llm=fake)
    thorin = game.characters["thorin"]
    cmd = Command(verb="attack", obj="Tom the troll")
    thorin.narrate(game, cmd, "kill")
    assert "killing blow" in fake.calls[-1][1]
    thorin.narrate(game, cmd, "hit")
    assert "still stands" in fake.calls[-1][1]
    thorin.narrate(game, cmd, "miss")
    assert "trading blows" in fake.calls[-1][1] and "killing" not in fake.calls[-1][1]


def test_a_missed_swing_earns_no_flourish():
    fake = FakeLLM(reply="Thorin's blade strikes the troll down in a lifeless heap.")
    game = Game(seed=5, llm=fake)
    game.rng.random = lambda: 1.0  # every swing misses
    game.player.location_id = "goblin_tunnel_1"
    thorin = game.characters["thorin"]
    game.world.get("bag_end").npcs.remove("thorin")
    thorin.location_id = "goblin_tunnel_1"
    game.world.get("goblin_tunnel_1").npcs.append("thorin")
    tom = game.characters["troll_tom"]
    game.world.get(tom.location_id).npcs.remove("troll_tom")
    tom.location_id = "goblin_tunnel_1"
    tom.alive = True
    tom.health = 60
    game.world.get("goblin_tunnel_1").npcs.append("troll_tom")
    game.player.light_remaining = 20
    msgs = [getattr(m, "text", m) for m in game._advance_world_turn()]
    assert any("misses" in m for m in msgs)  # the fight happened
    assert not any("lifeless heap" in m for m in msgs)  # but no false kill


def test_combat_narration_is_capped_and_optional(monkeypatch):
    fake = FakeLLM(reply="Thorin's blade bites deep into the goblin.")
    game = Game(seed=5, llm=fake)
    # put Thorin and a hostile goblin in the player's room
    game.player.location_id = "goblin_tunnel_1"
    thorin = game.characters["thorin"]
    game.world.get("bag_end").npcs.remove("thorin")
    thorin.location_id = "goblin_tunnel_1"
    game.world.get("goblin_tunnel_1").npcs.append("thorin")
    game.player.light_remaining = 20
    msgs = game._advance_world_turn()
    # narration is best-effort; if Thorin fought, at most one flourish appears
    flourishes = [m for m in msgs if "bites deep" in m]
    assert len(flourishes) <= 1


def test_every_companion_has_a_persona():
    """A dwarf with no brief leaves the model to improvise -- which is how
    Ori became 'little Ori', a trait from the films, not the book."""
    game = Game(seed=1)
    from hobbit.npc import NPC
    for char in game.characters.values():
        if isinstance(char, NPC) and char.def_.is_party:
            assert char.def_.persona, f"{char.id} has no persona"


def test_personas_place_the_youngest_correctly():
    game = Game(seed=1)
    for youngest in ("fili", "kili"):
        assert "youngest" in game.characters[youngest].def_.persona
    # and nobody else claims it
    for cid in ("ori", "nori", "dori", "bifur", "bofur"):
        assert "youngest" not in game.characters[cid].def_.persona, cid


def test_the_lore_guard_forbids_invented_traits():
    from hobbit.npc import _LORE_GUARD
    assert "invent no ages" in _LORE_GUARD
    assert "film" in _LORE_GUARD


def test_short_punchy_dialogue_is_not_amputated():
    """Regression from the first live Sonnet run: a flat two-sentence cap was
    tuned against a small model that rambled in long sentences. A stronger one
    writes the way people speak, and the cap cut this to 'Safe? Ha!'"""
    from hobbit.npc import _clean
    raw = ("Safe? Ha! There's no such thing on this road, Master Baggins. "
           "But don't you fret -- you've fourteen dwarves to watch your back.")
    out = _clean(raw)
    assert out.startswith("Safe? Ha!")
    assert "fourteen dwarves" in out


def test_a_rambler_is_still_trimmed():
    """The budget has to bite on the case it was written for."""
    from hobbit.npc import _clean, REPLY_BUDGET
    raw = " ".join(
        f"This is a long and winding sentence number {i} that goes on well "
        f"past the point of usefulness and really ought to be cut." 
        for i in range(6))
    out = _clean(raw)
    assert len(out) <= REPLY_BUDGET + 120   # one sentence may overshoot
    assert len(out) < len(raw) / 2


def test_a_single_long_sentence_is_never_dropped_entirely():
    from hobbit.npc import _clean
    raw = ("I have been thinking about the road ahead and the weather and the "
           "provisions and whether the ponies will hold out as far as the ford "
           "and what we shall do about the wargs if they come again in numbers.")
    assert _clean(raw)          # not None, not empty


def test_emphasis_asterisks_keep_their_word():
    """Live regression: a stronger model stresses a word with *asterisks*, and
    deleting the span left "Nothing's ever , laddie" -- a broken sentence
    shown to the player."""
    from hobbit.npc import _clean
    out = _clean("Nothing's ever *safe*, laddie, but keep your feet quick.")
    assert out == "Nothing's ever safe, laddie, but keep your feet quick."


def test_stage_directions_are_still_removed():
    from hobbit.npc import _clean
    out = _clean("*chuckles and claps Bilbo on the back* Safe enough, laddie.")
    assert out == "Safe enough, laddie."
    assert "chuckles" not in out
