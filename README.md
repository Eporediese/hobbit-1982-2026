# The Hobbit

A modern, playable recreation of Beam Software's 1982 text adventure *The Hobbit*,
built in Python 3.11+. Faithful-in-spirit recreation of the map (Bag End to the
Lonely Mountain), Gandalf and the thirteen dwarves as autonomous companions,
and the original's hunger/fatigue mechanic -- not a byte-exact port of the
original BASIC source.

## Why this game

Beam Software's *The Hobbit* was extraordinary, and it is worth saying plainly
why before this README starts listing things it repaired.

In 1982 the state of the art was a room, a list of nouns, and a parser that
understood two words. Philip Mitchell and Veronika Megler shipped a game in
which **the other characters carried on without you**. Gandalf wandered off.
Thorin sang about gold. The dwarves got themselves captured, picked things up,
lost them, and occasionally solved a puzzle you were still standing in front
of. Come back to a room and it had changed while you were gone. Nothing else
did that for years, and nothing else on a 48K machine had any business doing it
at all. Its parser, Inglish, took full sentences, chained clauses with *and*
and *then*, and let you address characters directly -- telling a dwarf to pick
something up and carry it for you is 1982, not a modern convenience. Both are
still in this recreation because they were never mine to add.

And whoever wrote it had plainly read the book and loved it. The dwarves are
distinct, the Elvenking's halls feel like a trap that has to be *escaped*
rather than fought, and the game trusts you to know why a small silver key
matters. It is a reading of Tolkien, not a licence being spent.

What it lacked was room. Persistent characters need memory to remember
anything; ambition on that scale needs cycles the hardware simply did not have.
So the seams show -- locks that could not be opened, prose promising exits that
were never built, a hunger loop that told you to eat and then refused the
command. Those are not design failures. They are a game reaching past its
machine, and mostly getting there.

This recreation keeps the reach and gives it the room. Every mechanic here that
sounds modern -- companions with goals, characters who know when a friend has
fallen, a world that moves while you are elsewhere -- is Beam's idea, running
on hardware they would have killed for.

> **This README is deliberately spoiler-light.** It tells you how to run the
> game and what its systems are, not how to solve it. If you'd rather read the
> puzzles, the secrets and the full mechanics up front, everything is written
> out in **[SPOILERS.md](SPOILERS.md)** -- but the game is better found out
> for yourself.

## Running it

```
python main.py
```

No third-party dependencies are required (standard library only). If your
default `python` doesn't resolve to a real interpreter, use a full path, e.g.
`C:\Users\<you>\AppData\Local\Programs\Python\Python313\python.exe main.py`.

## Playing

Core verbs: `go` (or a bare direction: `north`/`n`, `south`/`s`, `east`/`e`,
`west`/`w`, `up`/`u`, `down`/`d`), `take`, `drop`, `attack`, `give X to Y`,
`open`, `close`, `talk to`, `look`, `examine`, `inventory`, `eat`, `wear`,
`remove`, `wield`, `sheathe`, `light`, `rest`, `wait`, `follow`, `unfollow`,
`status`, `party`, `stock up`, `mode`, `save`, `load`, `quit`, `help`.

- Chain commands: `take sword and go north then attack troll`.
- Command a companion directly by addressing them first: `thorin, attack the goblin`.
- `status` shows Bilbo's condition; `party` shows the whole company -- where
  everyone is, how they're faring, and who is carrying what.
- Checking `status`, `party`, `inventory`, `look` or `help` costs no game time.
  Only real actions advance the world.
- After you move, the new room is shown automatically. In purist mode it's off
  -- you `look` for yourself, as in 1982.

`help` lists everything in-game, and the game tells you what you need to know
as you meet it. The systems below are worth knowing you *have*; how they play
out is yours to discover.

### What the game keeps track of

- **Hunger and fatigue.** Everyone gets hungry and tired -- you and every
  companion. Ignore it and you weaken; keep ignoring it and it wears your
  health away until you collapse. Food is carried as real items and a pack
  holds a **weight**, not a count, so what you choose to carry is a decision.
  Provisioning before a long stretch of wild is your responsibility.
- **Wounds.** Battle costs health, a hurt fighter strikes weaker, and wounds
  mend when you are safe and fed -- slowly on the road, faster where you are
  cared for. Healing takes time, so there is a real reason to linger.
- **Weapons.** `wield` draws a blade and `sheathe` puts it away; better blades
  hit harder. Marching with drawn steel is wearying, so there is a cost to
  going about armed. Companions arm and disarm themselves as danger comes and
  goes.
- **Treasure.** The quest is to reclaim a hoard, so what the company carries
  out of the Mountain is scored at the end -- the whole company's haul, not
  just Bilbo's. Weight decides who can bear what.
- **The company.** They travel with you, fight, forage, rest and look after
  themselves. A death or a capture becomes known to all of them, is remembered
  in their conversation, and is marked on the map you walk back over.
- **The dark.** Some places are black, and you will want a light. Some things
  in the dark want you.

### AI companions (`--ai`)

```
python main.py --ai                       # uses hermes3:8b on local Ollama
python main.py --ai --model llama3.1:8b   # pick a different model
python main.py --ai --ollama-url http://host:11434
```

Gandalf and the dwarves have **agency and personality**:

- **Goals.** Each companion pursues an aim and pathfinds toward it, so the
  company travels the road as a group instead of milling about. This works
  with no model at all (a scripted floor). With `--ai`, the model *chooses*
  each companion's goal from the situation -- press on, hang back, rest,
  wander -- consulted only occasionally while free pathfinding does the
  walking.
- **Voice.** With `--ai`, `talk to` a companion for a live in-character reply.
  Companions also speak up on their own now and then -- banter, a grumble, an
  observation on where they are or what just happened -- and one narrates a
  flourish when it fights beside you.
- **Gandalf scouts.** The wizard ranges ahead of the company, peeks at dangers
  without blundering into them, and comes back with news of what lies on the
  road you haven't walked yet. He also reads the traces of what happened while
  you weren't looking. His discoveries inform his conversation, so asking him
  for counsel is genuinely useful. `gandalf, follow me` recalls him to your
  side; `gandalf, follow stop` sends him ranging again.
- **Following.** `follow <name>` bids a companion take the lead and draws you
  along behind them -- the book's own pull between guarding the burglar and
  pressing on for the gold. `unfollow` hands the lead back to you.
  `<name>, follow me` does the opposite and pins a companion to your side.

Every model call has a silent fallback to the scripted behaviour, so a slow,
missing, or crashing model never breaks the game. In purist mode the whole AI
layer is off and the characters revert to the original's own wandering --
which was itself remarkable for 1982, just undirected.

### What it costs

Measured against a live model, which is the only way this came out right.

A real game asks the model something on **about one turn in one** -- roughly
one call per turn, counted over a 130-turn run with fights, remarks and
narration in it. At the rates a reseller charges for Sonnet that puts a full
playthrough somewhere around **fifty pence to a pound**, so a family of five
playing through twice is a few pounds rather than a few pence.

An earlier version of this section claimed three pence, from a stub run that
mostly waited in empty rooms where almost nothing fires. It was wrong by more
than an order of magnitude. If you want your own number rather than this one,
`tools/soak.py --ai` and a counter on the client will give it to you in ten
minutes.

One good model for everything is therefore the default and the recommendation.

`HOBBIT_LLM_FAST_MODEL` remains available for anyone who wants it: goal picks
sit on the turn path, where somebody is waiting for the room to appear, so
pointing those at a quicker model shaves latency while dialogue -- the only
text a player reads -- stays with the better one. It is a speed option, not a
saving; unset, one model does everything.

### Configuring a model

```
HOBBIT_LLM_URL=https://api.ppq.ai        # or any OpenAI-compatible endpoint
HOBBIT_LLM_MODEL=claude-sonnet-5
HOBBIT_LLM_KEY_FILE=/path/to/key         # or HOBBIT_LLM_KEY
```

`python tools/check_llm.py` makes two real calls and reports what came back,
which is the only way to catch a provider passing a field through to a model
that rejects it. Run it before pointing anyone else at the game.

Needs a reachable [Ollama](https://ollama.com) server (or any compatible
endpoint via `--ollama-url`). An 8B model keeps replies at ~2-3s once warm;
14B models are noticeably slower. The model is warmed up at startup and kept
resident between turns. This is Phase 1 (local, single-player); a hosted,
multiplayer web version is planned next.

## Modes

**Which game you are playing is chosen when you start it, and holds for the
whole journey.** Purist and enhanced are different worlds, not two views of the
same one -- the map is a real object in one and wall flavour in the other, locks
work in one and behave as they originally did in the other. Switching
mid-journey would rearrange
the world around a company already standing in it, so it isn't offered.

```
python main.py            # the enhanced game
python main.py --purist   # the raw 1982-flavoured experience
```

Purist is the 1982 experience as it actually played: reverted room
descriptions, no scenery/examine system, the original's locks -- which leave
some rooms unreachable and can leave the game unwinnable -- and its hunger
loop, which tells you to eat and then declines the command. No colour, no
meta-commentary.

Those limits are period-accurate rather than period-mocking. A 48K machine had
no room for the checks that would have caught them, and playing this mode is
the clearest way to feel how much the original was attempting with how little.
It reproduces the *classes* of constraint the original worked under; it is not
a byte-exact reproduction of Beam Software's game, which was never available
to copy from.

Early builds tinted anything added for this recreation in cyan, so you could
tell a modern touch from 1982 at a glance. That marking has been removed: the
enhanced game is reworked thoroughly enough that nearly every line is "modern",
and colouring almost all of it said nothing. If you want the unimproved
article, play the purist game -- it *is* the 1982 design, not an annotation of
it. There is no commentary layer and nothing to configure.

Command chaining (`and`/`then`) and addressing companions directly are kept in
every mode -- they are *not* additions. Inglish did both in 1982, and taking
them out to make this recreation look more generous would be a lie about what
the original could do.

## Architecture

```
hobbit/
  game.py       Turn loop, win/lose conditions
  parser.py     Tokenizing, synonyms, multi-word/multi-step commands
  world.py      Location/exit/map state
  items.py      Item catalog
  entities.py   Character base (hunger/fatigue/health) + Player
  npc.py        NPCBrain interface, SimpleBrain, MonsterBrain, NPC
  combat.py     Attack resolution
  commands.py   Verb handlers (actor-agnostic: work for player or NPC)
  save.py       JSON save/load
  data/*.json   Locations, items, NPCs, monsters
```

### Swapping the NPC brain

Companion behavior lives entirely behind the `NPCBrain` interface in
`hobbit/npc.py` (`decide(npc, game) -> Command | None`). The shipped
`SimpleBrain` reproduces the original's basic routine: wander on a schedule,
fight monsters encountered along the way, occasionally land in scripted
trouble, and yield to direct player commands.

To swap in an LLM-driven companion, implement a new class satisfying the same
interface and change the one factory call in `build_npc()` -- `world.py`,
`parser.py`, `commands.py`, and `game.py` don't need to change.

### Multiplayer groundwork

Not implemented yet, but kept easy to add:
- `Game` holds all state separately from terminal I/O.
- `Parser.parse_line()` and `commands.execute()` take an explicit actor
  rather than assuming a single global player.
- The turn loop separates "resolve one actor's command" from "advance the
  world," so a networked loop can collect actions from multiple human
  players before resolving a turn.

## Tests

```
python -m pytest tests/
```

## Status and licensing

A non-commercial fan work, shared for people who want to play it and for
anyone curious how the pieces fit together.

Two different things live in this repository, and only one of them is mine
to give away:

- **The code** (`hobbit/`, `main.py`, `tests/`) is my own, written from
  scratch, and is released under the MIT License (see `LICENSE`). No part of
  the original BASIC source was used, consulted, or copied -- the map and
  puzzles were reconstructed from publicly documented knowledge of the 1982
  game, so this is faithful in spirit rather than a port.

- **The setting is not mine.** *The Hobbit* and its characters, places, and
  names are the work of J.R.R. Tolkien, and the 1982 adventure game is the
  work of Beam Software. Nothing here is licensed, endorsed by, or affiliated
  with the Tolkien Estate, Middle-earth Enterprises, or the rights holders of
  the original game. The MIT License above covers my code only and grants no
  rights whatsoever in the underlying works.

No money is asked for this and none should be. If a rights holder would
rather it not exist, that is their call to make and I will take it down.
