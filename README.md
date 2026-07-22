# The Hobbit

A modern, playable recreation of Beam Software's 1982 text adventure *The Hobbit*,
built in Python 3.11+. Faithful-in-spirit recreation of the map (Bag End to the
Lonely Mountain), Gandalf and the thirteen dwarves as autonomous companions,
and the original's hunger/fatigue mechanic -- not a byte-exact port of the
original BASIC source.

## Running it

```
python main.py
```

No third-party dependencies are required (standard library only). If your
default `python` doesn't resolve to a real interpreter, use a full path, e.g.
`C:\Users\<you>\AppData\Local\Programs\Python\Python313\python.exe main.py`.

### AI companions (`--ai`)

```
python main.py --ai                       # uses hermes3:8b on local Ollama
python main.py --ai --model llama3.1:8b   # pick a different model
python main.py --ai --ollama-url http://host:11434
```

Gandalf and the dwarves have **agency and personality**:

- **Goals.** Each companion pursues an aim and pathfinds toward it. By default
  you lead: the dwarves march *with* Bilbo and Gandalf ranges ahead as scout,
  so the company travels the road as a group instead of milling about -- and if
  you'd rather a companion set the pace, `follow` them and they take the lead
  for the Mountain (see Playing). This works even with no model (a scripted
  floor). With `--ai`, the model *chooses* each companion's goal from the
  situation (press on, hang back, rest, wander), consulted only occasionally
  while free pathfinding does the walking.
- **Voice.** With `--ai`, `talk to` a companion for a live in-character reply.
  Companions also speak up on their own now and then -- banter, a grumble, an
  observation on where they are or what just happened -- and one narrates a
  flourish when it fights beside you.
- **Gandalf scouts.** The wizard ranges a few rooms ahead of the company,
  peeks at dangers without blundering into them, and returns to Bilbo with
  news of what he found: monsters lurking, locked ways, dark stretches,
  shelter, and unclaimed treasures -- only about places you haven't yet been.
  If a companion is taken captive, Gandalf can *find* them: a friend spotted
  in chains is urgent news, reported first, wherever he sees them.
  He also reads the *traces of what happened* while you weren't looking --
  signs of a skirmish, who fell in battle, drag-marks where a companion was
  seized. Traces go cold after a while, he only reports what Bilbo didn't
  witness himself, and an abduction always jumps to the top of the report.
- **The company knows its own.** A companion's death or capture becomes
  known to everyone: it's announced ("Word passes through the company..."),
  remembered in every companion's conversation, mourned aloud in AI mode,
  and `party` records where the fallen fell. And a capture can be *undone*:
  fight your way to the cell where a companion is held and you free them on
  the spot -- they rejoin the company and the rescue becomes part of its
  story.
- **Dark places take the ones who drift.** In the goblin tunnels a companion
  can be dragged off; one at Bilbo's side is far harder to snatch, but -- as in
  the tale, where the tunnels take the whole company -- not untouchable.
  Keeping together is protection, not immunity. Once the **Great Goblin is
  slain** the tunnels have no master and the abductions stop, so a rescue stays
  rescued.
- **Mirkwood has its own captors.** In the black of the forest **you cannot
  fight what you cannot see** -- and it is being unable to strike back that
  gets you webbed and hauled up to the Spiders' Nest. A torch is no ward
  against spiders; it simply lets the company swing. There is only **one torch
  in all the world**, and whoever carries it lights the room for everyone in
  it -- so keep it with you, and pity the straggler a room behind. Spiders have
  no use for gold and leave a prisoner his purse (goblins are not so nice). Cut
  the webbed free as you would any captive; the webbing stops once the great
  spider falls.
- **A kill says what it leaves behind** ("The Great Goblin falls, leaving the
  goblin cell key on the ground"), and a locked door names the key you're
  missing -- so a story-critical key can't lie unnoticed on the floor.
  His discoveries also inform his conversation, so asking him for counsel is
  genuinely useful. Works without a model (plain reports); with `--ai` he
  phrases them in his own voice. `gandalf, follow me` recalls him to your
  side; `gandalf, follow stop` sends him ranging again.
- **Follow them.** `follow thorin` bids a companion take the lead: instead of
  escorting you, they strike out for the Lonely Mountain and draw you (and the
  rest of the company) along behind -- the book's own pull between guarding the
  burglar and pressing on for the gold. **`wait`** keeps pace with them; turning
  aside to your own business (resting, eating, picking things up) breaks off the
  march, while checking `status` or `party` costs nothing and never does.
  **`unfollow`** (or `stop following`) hands the lead back to you and returns
  them to the ranks. (A grievously hurt or starving leader still breaks off to
  a haven first.) `thorin, follow me` does the opposite -- pins a companion to
  your side, until `thorin, stop` releases them.

Every model call has a silent fallback to the scripted behavior, so a slow,
missing, or crashing model never breaks the game. In purist mode the whole AI
layer is off and the characters revert to the aimless 1982 random walk.

Needs a reachable [Ollama](https://ollama.com) server (or any compatible
endpoint via `--ollama-url`). An 8B model keeps replies at ~2-3s once warm;
14B models are noticeably slower. The model is warmed up at startup and kept
resident between turns. This is Phase 1 (local, single-player); a hosted,
multiplayer web version is planned next.

## Playing

Core verbs: `go` (or a bare direction: `north`/`n`, `south`/`s`, `east`/`e`,
`west`/`w`, `up`/`u`, `down`/`d`), `take`, `drop`, `attack`, `give X to Y`,
`open`, `close`, `talk to`, `look`, `examine`, `inventory`, `eat`, `wear`,
`remove`, `wield`, `light`, `rest`, `wait`, `follow`, `unfollow`, `status`,
`party`, `stock up`,
`save`, `load`, `quit`, `help`.

- Chain commands: `take sword and go north then attack troll`.
- Command a companion directly by addressing them first: `thorin, attack the goblin`.
- After you move, the new room is shown automatically (in the annotation
  colour, since auto-look is a modern convenience). In purist mode it's off --
  you `look` for yourself, as in 1982.

### Weapons

- `wield sting` draws a weapon; `sheathe` puts it away. `status` shows what's
  in hand and your attack. Better blades hit harder (walking stick 4, Sting 7,
  Orcrist and Glamdring 8; bare hands are Bilbo's 3).
- Marching with a **drawn sword is wearying** (extra fatigue per move), so put
  it away on a quiet road -- but the **walking stick is a walking aid** that
  *lowers* your march fatigue (and still beats bare fists in a pinch). Stroll
  with the stick; draw steel when Gandalf warns of trouble.
- Companions do this for themselves: they **make ready when danger is near**
  (a scout's warning lets them arm before it arrives) and sheathe when the road
  is quiet. Hand a fallen friend's blade to another dwarf (`give orcrist to
  dwalin`) and he'll wield it in the next fight.

### The ring

`wear ring` makes Bilbo genuinely unseen, and that cuts both ways:

- **Nothing will attack you.** Not a hard target -- no target at all. Walk
  through a warg pack or past the trolls untouched, and scout the road ahead
  yourself instead of sending Gandalf.
- **The company cannot follow what they cannot see.** They make for the spot
  where you vanished and wait there. Slip away wearing it and you are on your
  own until you take it off, whereupon they gather to you again. Nor will they
  talk to you, greet you, or bring you news while you're unseen -- Gandalf
  saves his scouting report for a hobbit he can find.
- **Speaking aloud gives you away**, as surely as striking does: they answer
  the voice, and there you are. (`status` shows what you're wearing and
  reminds you that you're unseen.)
- **You may still follow them** -- `follow thorin` works while unseen; it's
  being *followed* that the ring denies.
- **Strike a blow and you give yourself away** -- and the ring genuinely slips
  loose, falling at your feet. You must stoop for it (`take ring`) in the middle
  of the fight, or leave it lying where you stood. It hides you; it does not let
  you kill a dragon in safety.
- **It counts as treasure.** The ring is worth a great deal in the final
  reckoning, and `party` shows who holds it -- so dropping it in a troll
  clearing and marching on costs you more than the invisibility.
- **You keep your sight in the deep places** while you wear it, as Gollum did:
  Bilbo alone can walk the pitch dark without a torch. It lights nothing for
  anybody else, so the company still cannot fight in the black -- but it lets a
  burglar go where no one else can. Slip it on, walk into the Spiders' Nest
  unseen, and cut your friends down without ever drawing a blade.

### The Elvenking's halls

The one leg of the road you cannot simply march. The great gate east is **shut
and barred**, as in the book -- you leave by the river or not at all.

- A **wood-elf guard** keeps the feasting hall and turns back anyone he can
  see. Slip the **ring** on and walk past him unseen; his key hangs at his belt.
- That key opens the **wine cellars**, which are both the Elvenking's larder
  (help yourselves to **elven cake**) and the way out. The company can't cross
  to Lake-town on Bilbo's pack alone -- twelve loaves between fourteen -- so
  this is where you provision for the last leg.
- **`barrel` is a direction**, listed in the cellars' exits beside `up` -- no
  special explanation needed. It tips the company into the empty barrels and out
  under the gate on the black water, shooting the rapids with elvish horns
  crying behind you. Barred ways show as `east (barred)` so a shut gate reads
  like a locked door.
- The barrels take **only those standing there**, and the gate shuts behind
  them -- so the game will not cast off while anyone is adrift; it names who
  is missing and where. While you wait at the barrels the whole company musters
  to you, scout included, and eats from the larder as they arrive.

### The fighting front

Only so many can come to blows at once. A goblin-cut tunnel takes **two
abreast**, an ordinary place four, a great hall six -- the rest of the company
press behind, waiting their turn. Without it fourteen companions fell on every
foe at once and nothing in the world survived a round (Smaug included). So a
narrow tunnel is a real fight, the front rank takes the punishment, and Bilbo
is often one of the few who can actually reach. Bosses are built to match: the
Great Goblin and Smaug will not go down in a turn.

### Wounds and healing

- Battle costs health. A **badly wounded** fighter strikes weaker (as does a
  weak, hungry, or exhausted one) -- see it on `status` and in `party`.
- Wounds **mend when you're safe and fed**: slowly on the open road, and
  **quickly in a haven's care** (Rivendell, the Green Dragon, Beorn's Hall,
  Lake-town). `rest` knits them a little too. You won't heal while weak from
  hunger or fatigue -- so **being fed comes first**, and at a haven the hosts
  see to that: a hearty meal there costs you none of your own rations and
  fills you right up, so the mending can begin the same turn.
- **Healing takes time, so linger.** `wait` a few turns at a haven and you'll
  see it happen ("Under the care of The Last Homely House, Gandalf mends...
  Bombur is whole again"). Checking `status` or `party` costs no time, so it
  won't advance a convalescence -- only real turns do.
- **Each haven keeps its own fare.** Rivendell presses **waybread** on you
  (far more sustaining than a plain loaf, and just as light to carry),
  Lake-town has cram, the Shire its loaves. `stock up` fills your pack with
  whatever the house supplies.
- **Elrond** keeps the Last Homely House and never leaves it. `talk to elrond`
  for counsel on rest and healing.
- A **badly hurt companion will break off** toward a nearby haven to be
  mended, then rejoin.

### Fallen in battle

Death leaves a mark. Slain monsters' **bodies lie where they fell**, and once
a fight is won the company **raise a cairn** over any of their own who fell --
a lasting grave you'll pass on the road, remembered in the room's description.

### Treasure and the reckoning

The quest is to reclaim a hoard, so what you carry out of the Mountain counts.

- Treasure is scored for the **whole company**, not just Bilbo. Hand a heap to
  Bombur, a goblet to Balin, and it all counts the same at the end -- so a
  hobbit who can't lift a dragon's hoard alone can still bring one home.
- **Companions make room for a gift.** Hand something to a dwarf whose pack is
  full and he'll set down lighter oddments to take it -- never the weapon in
  his hand, and never his last couple of meals.
- **`party` shows who bears what** -- treasure, keys, torches, and weapons
  (carried or drawn), with Bilbo listed alongside the rest with his own
  condition and share -- so you always know where the Arkenstone is, who has
  the key, and who's carrying the only torch before you head underground.
- **Weight decides who bears what.** The heap of treasure is simply too heavy
  for a hobbit; it takes a dwarf, and only Bombur carries it comfortably.
- **The Arkenstone matters.** Put the Heart of the Mountain into Thorin's hands
  (`give arkenstone to thorin`) and the dwarf-lord's grimness leaves him for
  once -- the company remembers it. But lift it while he's standing there and
  he'll claim it himself; he will not watch another carry it out.
- **Goblins rob their prisoners.** A companion dragged into the deeps is
  stripped of everything of worth, and it's heaped in the cell beyond his
  reach -- so a captive's gold counts for nothing while he's down there. You
  hear only the cry as he's taken; the robbery happens far out of sight, and
  you find the hoard when you fight your way in -- winning back the friend
  *and* the plunder.
- When Smaug falls, the ending tallies **who carried what, and what it was
  worth in all**. Treasure that fell with the dead, or that is still lying in a
  goblin cell, is not counted -- only what the company actually carried out.

### Hunger, fatigue, and food

Everyone gets hungry and tired. Ignore it and you grow weak; keep ignoring it
and hunger and exhaustion **wear your health away** until you collapse.

Collapsed, you can no longer fight or march -- but you can still **eat, rest,
and wait**, so there is always a way back if you have food. (In purist mode the
original's death spiral stands: it tells you to eat, then refuses the command,
and collapse is the end.)

- Food is carried as **real items in your inventory**, stacked -- e.g.
  `loaf of bread (x4)`. A pack holds a **weight**, not a count, shared by
  everything you carry (12 for Bilbo; the dwarves bear more, Bombur most).
  **Bread is light** -- Bilbo can shoulder a dozen loaves, Bombur two dozen --
  so provisioning generously is easy; it's gold and steel that fill a pack.
- **A heavy pack tells on you.** Past about seven-tenths full you tire faster
  on every march, and a near-brimful one worse still. A heavily laden companion
  keeps stopping to shift the load, so they fall behind -- a dwarf hauling a
  dragon's hoard is not a fast dwarf.
- Everyone sets out with a single loaf, so provisioning is your first job:
  at a **food source** (the Green Dragon Inn, Rivendell, Beorn's Hall,
  Lake-town) the loaves never run out -- `take loaf` grabs one, `stock up`
  fills your pack. Food found in the wild (mutton, waybread, cram) is picked
  up like any other item.
- `eat` eats one carried food item and restores hunger.
- `status` shows Bilbo's health, hunger, fatigue, and food (and warns you when
  he's weak); `party` shows the whole company. Plan restocks around
  settlements before long stretches of wild (Mirkwood is a hungry road).
- Companions look after themselves: they eat from their packs when hungry,
  rest when spent, restock at settlements, and -- when their pack runs empty --
  will break off to forage at the nearest food source, then rejoin.
- The company travels **with** Bilbo: you lead, and they stay within a couple
  of rooms, coming back if they drift too far (so they never wander off and
  strand you). They still fight, forage, and chatter on their own. (`thorin,
  follow me` pins a companion to your side.) When many of them do the same
  thing at once it reads as one line ("The company heads east."), and wounds
  knit back up while a character is fed and rested.
- Checking `status`, `party`, `inventory`, `look`, or `help` costs no game
  time -- only real actions (moving, taking, eating, fighting...) advance the
  world.

### Modes

**Which game you are playing is chosen when you start it, and holds for the
whole journey.** Purist and enhanced are different worlds, not two views of the
same one -- the map is a real object in one and wall flavour in the other, locks
work in one and misbehave in the other, the Elvenking's gate is barred in one
and open in the other. Switching mid-journey would rearrange the world around a
company already standing in it, so it isn't offered.

```
python main.py            # the enhanced game
python main.py --purist   # the raw 1982-flavoured experience
```

Within the enhanced game, `annotate standard` / `annotate verbose` control only
what is *printed* (whether amber bug-fix notes are shown), so those are free to
change at any time. `mode` reports which game you're in.

### Annotation levels

There is a single spectrum from the most-original experience to the most-
annotated one, switchable live in-game (or set at launch):

- `purist` -- the raw 1982-flavored experience. Reverted room descriptions,
  the map is just flavor on the wall (not a takeable object), no
  scenery/examine system, and the original quirky locks -- so some rooms
  (the Trolls' Cave, Goblin Dungeon, Secret Door) are unreachable and the
  game may not be winnable. No color, no meta-commentary. Launch straight
  into it with `python main.py --authentic`.
- `annotate standard` (default) -- the enhanced, fixed game; added features
  (the map as a real item, the scenery/examine system) are shown in cyan.
- `annotate verbose` -- enhanced, and also shows in amber exactly where a
  bug in this recreation was found and fixed, and why.
- `annotate` alone reports the current level; `mode` describes it in full.

Purist reproduces the *classes* of period jank; it is not a byte-exact
reproduction of Beam Software's actual game, which was never available to
copy from. Command chaining (`and`/`then`) and addressing companions
directly are kept in every mode -- they are *not* additions; the real 1982
game's Inglish parser genuinely supported both.

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
trouble (captured by goblins), and yield to direct player commands.

To swap in an LLM-driven companion later, implement a new class satisfying
the same interface and change the one factory call in `build_npc()` --
`world.py`, `parser.py`, `commands.py`, and `game.py` don't need to change.

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
