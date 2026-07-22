from hobbit.parser import Parser


def make_parser():
    return Parser(npc_names={"thorin": "thorin", "gandalf": "gandalf"})


def test_bare_direction():
    cmds = make_parser().parse_line("north")
    assert len(cmds) == 1
    assert cmds[0].verb == "go"
    assert cmds[0].obj == "north"


def test_synonym_and_direction_abbreviation():
    cmds = make_parser().parse_line("n")
    assert cmds[0].verb == "go"
    assert cmds[0].obj == "north"


def test_multi_word_verb_take():
    cmds = make_parser().parse_line("pick up the sword")
    assert cmds[0].verb == "take"
    assert cmds[0].obj == "sword"


def test_multi_word_verb_talk_to():
    cmds = make_parser().parse_line("talk to gandalf")
    assert cmds[0].verb == "talk"
    assert cmds[0].obj == "gandalf"


def test_give_with_indirect_object():
    cmds = make_parser().parse_line("give sword to thorin")
    assert cmds[0].verb == "give"
    assert cmds[0].obj == "sword"
    assert cmds[0].indirect == "thorin"


def test_multi_step_and_then():
    cmds = make_parser().parse_line("take sword and go north then attack troll")
    assert [c.verb for c in cmds] == ["take", "go", "attack"]
    assert cmds[0].obj == "sword"
    assert cmds[1].obj == "north"
    assert cmds[2].obj == "troll"


def test_addressed_npc_command():
    cmds = make_parser().parse_line("thorin, attack the goblin")
    assert cmds[0].actor_override == "thorin"
    assert cmds[0].verb == "attack"
    assert cmds[0].obj == "goblin"


def test_unknown_verb_reports_error():
    cmds = make_parser().parse_line("frobnicate the widget")
    assert cmds[0].unknown
    assert cmds[0].error


def test_kill_synonym_maps_to_attack():
    cmds = make_parser().parse_line("kill the troll")
    assert cmds[0].verb == "attack"
    assert cmds[0].obj == "troll"
