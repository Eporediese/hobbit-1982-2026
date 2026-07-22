# The Hobbit

A modern, playable recreation of Beam Software's 1982 text adventure *The Hobbit*,
built in Python 3.11+. Faithful-in-spirit recreation of the map (Bag End to the
Lonely Mountain), Gandalf and the thirteen dwarves as autonomous companions,
and the original's hunger/fatigue mechanic -- not a byte-exact port of the
original BASIC source.

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
layer is off and the characters revert to the aimless 1982 random walk.

Needs a reachable [Ollama](https://ollama.com) server (or any compatible
endpoint via `--ollama-url`). An 8B model keeps replies at ~2-3s once warm;
14B models are noticeably slower. The model is warmed up at startup and kept
resident between turns. This is Phase 1 (local, single-player); a hosted,
multiplayer web version is planned next.

## Modes

**Which game you are playing is chosen when you start it, and holds for the
whole journey.** Purist and enhanced are different worlds, not two views of the
same one -- the map is a real object in one and wall flavour in the other, locks
work in one and misbehave in the other. Switching mid-journey would rearrange
the world around a company already standing in it, so it isn't offered.

```
python main.py            # the enhanced game
python main.py --purist   # the raw 1982-flavoured experience
```

In purist mode you get reverted room descriptions, no scenery/examine system,
the original's quirky locks -- which leave some rooms unreachable and may leave
the game unwinnable -- and the original's hunger death spiral. No colour, no
meta-commentary. It reproduces the *classes* of period jank; it is not a
byte-exact reproduction of Beam Software's actual game, which was never
available to copy from.

In the enhanced game, anything added for this recreation is **shown in cyan**,
so you can always tell a modern addition from 1982 without being lectured
about it. That is the whole of the annotation: there is no commentary layer
and nothing to configure.

Command chaining (`and`/`then`) and addressing companions directly are kept in
every mode -- they are *not* additions; the real 1982 game's Inglish parser
genuinely supported both.

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
