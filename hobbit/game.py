"""Main game object: owns world/item/NPC state and runs the turn loop."""
from __future__ import annotations

import random
import re
from collections import deque
from pathlib import Path
from typing import Optional

from . import commands, ui
from .entities import Character, Player
from .items import ItemCatalog
from .npc import NPC, NPCDef, build_npc
from .parser import ADDED_VERBS, FREE_VERBS, Command, Parser
from .save import load_game, save_game
from .world import World

DATA_DIR = Path(__file__).parent / "data"
MAX_FAINT_TURNS = 8
AMBIENT_CHANCE = 0.3  # per-turn chance a companion speaks up unprompted (AI mode)
SUCCOR_RANGE = 1  # rooms away a companion will hear a leader's call and rush to aid
LADEN_PAUSE_CHANCE = 0.35  # chance a heavily laden companion pauses instead of marching
SEIZED_BESIDE_BILBO = 0.35  # how much harder captors find it to snatch someone at his side
MONSTER_RECOVERY = 5  # fatigue a monster shakes off each turn it isn't fighting

# Phrases that mark a scout finding as news about someone being held, so it can
# be expired once they're freed.
_CAPTIVITY_PHRASES = ("held captive", "was taken by", "was seized by", "in chains")

# Places whose inhabitants carry off stragglers, and what that looks like. A
# region stops taking anyone once its master is slain. `light_saves` marks the
# lairs where a lamp is protection: the spiders of Mirkwood take those who
# blunder about in the dark, while goblins know their own tunnels blind.
CAPTOR_REGIONS: dict[str, dict] = {
    "goblin": {
        "master": "goblin_captain",
        "prison": "goblin_dungeon",
        "light_saves": False,
        "loots": True,          # goblins strip their prisoners of anything of worth
        "trace": "{name} was seized by goblins near {place} -- drag-marks lead into the deeps",
        "news": "{name} was taken by goblins near {place}",
        "cry": "A cry echoes down the tunnels -- {name} has been taken by goblins!",
    },
    "mirkwood": {
        "master": "giant_spider",
        "prison": "spiders_nest",
        "light_saves": True,
        "loots": False,         # spiders have no use for gold
        "trace": "{name} was taken by spiders near {place} -- a silk-wrapped shape was hauled up into the branches",
        "news": "{name} was webbed by the spiders near {place}",
        "cry": "A shriek among the black branches -- {name} has been caught in the spiders' webs!",
    },
}

# Turning aside to do something of your own breaks off a march: if you settle
# down to rest or stop to eat, you are no longer keeping pace with whoever you
# were following. Waiting keeps pace (that IS following), fighting is thrust
# upon you rather than chosen, and the FREE_VERBS above cost no time at all.
FOLLOW_KEEPING_VERBS = {"wait", "attack", "follow"}


_join_names = ui.join_names


# With 13 dwarves doing the same thing at once, per-character lines become a
# wall of spam. These recognise the common company-wide actions so they can
# be collapsed into a single line when three or more do the same thing.
_COLLAPSE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(.+?) goes (\w+)\.$"), "The company heads {1}."),
    (re.compile(r"^(.+?) catches up\.$"), "The company catches up."),
    (re.compile(r"^(.+?) pauses to eat some .+\.$"), "The company pauses to eat."),
    (re.compile(r"^(.+?) stops for breath\.$"), "The company stops for breath."),
    (re.compile(r"^(.+?) feels weak with hunger and fatigue\.$"), "The company feels weak with hunger and fatigue."),
    (re.compile(r"^(.+?) refills a pack with (.+)\.$"), "The company refill their packs with {1}."),
    (re.compile(r"^(.+?) tucks into a hearty meal\.$"), "The company tucks into a hearty meal."),
    (re.compile(r"^(.+?) settles in by the fire to rest\.$"), "The company settles in by the fire to rest."),
    (re.compile(r"^(.+?) makes ready with .+\.$"), "The company draws their weapons."),
    (re.compile(r"^(.+?) puts away the .+\.$"), "The company put away their weapons."),
    (re.compile(r"^(.+?) faints from exhaustion and hunger!$"), "The company is fainting from exhaustion and hunger!"),
    (re.compile(r"^(.+?) rushes off to aid (.+)!$"), "The company rushes off to aid {1}!"),
]


def _collapse_company_messages(messages: list[str]) -> list[str]:
    """Collapse runs of near-identical per-character lines ('X goes east.'
    x13) into one company-wide line. Notes pass through."""
    keyed: list[tuple[str | None, str | None, str]] = []
    counts: dict[str, int] = {}
    for msg in messages:
        if type(msg) is not str:  # keep Note subclasses untouched
            keyed.append((None, None, msg))
            continue
        for pattern, template in _COLLAPSE_PATTERNS:
            m = pattern.match(msg)
            if m:
                collapsed = template.format(*m.groups())
                key = collapsed
                keyed.append((key, collapsed, msg))
                counts[key] = counts.get(key, 0) + 1
                break
        else:
            keyed.append((None, None, msg))
    out: list[str] = []
    emitted: set[str] = set()
    for key, collapsed, original in keyed:
        if key is None or counts[key] < 3:
            out.append(original)
        elif key not in emitted:
            emitted.add(key)
            out.append(collapsed)
    return out


class Game:
    def __init__(self, seed: int | None = None, authentic: bool = False,
                 llm=None, llm_fast=None):
        # There are two games, settled at the start and held for the journey:
        #   'purist'   -- the raw 1982-flavoured experience (a.k.a. authentic):
        #                 reverted descriptions, added items are back to being
        #                 unexaminable wall flavour, the scenery system is off,
        #                 and open/close use the original quirky current-room
        #                 logic (so some rooms are unreachable).
        #   'standard' -- the enhanced game (the default).
        # The 'authentic' argument is just sugar for starting in 'purist'.
        # (This field also drives the `authentic` property below; additions are
        # no longer visually marked, so it no longer affects presentation.)
        self.annotation_level = "purist" if authentic else ui.DEFAULT_LEVEL
        # When an LLM client is supplied, party NPCs get the hybrid LLMBrain
        # (AI dialogue + narration over the same rule-based actions). Absent
        # or unreachable, everything falls back to the simple routines.
        self.llm = llm
        # An optional cheaper, faster client for the calls whose answer is one
        # keyword. Roughly three quarters of a run's model calls are goal
        # picks ("ADVANCE"), where eloquence buys nothing -- so the good model
        # is kept for the lines a player actually reads. Falls back to `llm`
        # when unset, which is the single-model setup unchanged.
        self.llm_fast = llm_fast
        self.ai = llm is not None
        # Short rolling log of notable events, fed into NPC prompts so their
        # dialogue/narration reflects what just happened.
        self.recent_events: deque[str] = deque(maxlen=6)
        # Located, time-stamped record of things that HAPPENED around the
        # world (fights, deaths, abductions) -- the traces a scout can read
        # when passing through. Pruned by age in record_event.
        self.world_events: list[dict] = []
        self._event_seq = 0
        # Durable news the whole company knows -- deaths, captures, rescues.
        # Word travels fast in a close-knit company; these feed every
        # companion's dialogue and are announced to the player once.
        self.company_lore: list[str] = []
        self._pending_news: list[str] = []
        self._pending_grief: str | None = None
        # Fallen companions (loc_id, name) awaiting burial once the fight ends,
        # and who has already been mourned so no one falls twice.
        self._pending_burials: list[tuple[str, str]] = []
        self._mourned: set[str] = set()
        # Names already laid under a cairn, remembered independently of any
        # one room's grave list (which a load can rebuild beneath us).
        self._buried: set[str] = set()
        # Active rallies: room_id -> the foe the company is focusing there,
        # set when a leader in that room calls for aid, cleared when the foe
        # falls or the fight moves on.
        self.rally_targets: dict[str, str] = {}
        self.world = World.load(DATA_DIR / "locations.json")
        self.items = ItemCatalog.load(DATA_DIR / "items.json")
        self.rng = random.Random(seed)

        self.player = Player(location_id="bag_end")
        self.characters: dict[str, Character] = {"bilbo": self.player}
        self.npc_defs: dict[str, NPCDef] = {}

        self._load_npc_file(DATA_DIR / "npcs.json")
        self._load_npc_file(DATA_DIR / "monsters.json")

        self.parser = Parser(npc_names=self._build_npc_name_lookup())

        self.turn = 0
        self.faint_turns = 0
        # NPC id the player is trailing (set by the 'follow' command), or None.
        self.player_follow: str | None = None
        # Per-turn budget of LLM goal-planning calls, to keep turns snappy.
        self._goal_budget = 0
        self.request_save = False
        self.request_load = False
        self.request_quit = False
        self.won = False
        self.lost = False
        self.lose_reason = ""
        # Set once the player deciphers the map's moon-letters at a moonlit
        # reading table -- the secret door's key is spelled out thereafter.
        self.moon_letters_read = False
        # Where the company last saw Bilbo. With the ring on he cannot be
        # followed -- they steer to where he vanished and wait there.
        self.last_seen_player = self.player.location_id

        # Bilbo and the company set out with a single loaf each -- provisioning
        # at the Green Dragon's bakery is the first order of business. Monsters
        # carry no such thing. Companions also start with slightly varied
        # hunger/fatigue so they don't all eat, tire, and rest in lockstep.
        for character in self.characters.values():
            if character is self.player or (isinstance(character, NPC) and character.def_.is_party):
                self.add_food(character, self.STAPLE_FOOD, 1)
            if character is not self.player and isinstance(character, NPC) and character.def_.is_party:
                character.hunger = self.rng.randint(0, 24)
                character.fatigue = self.rng.randint(0, 18)

        start = self.world.get(self.player.location_id)
        start.visited = True

    # -- food (carried as real, stackable items) ----------------------
    STAPLE_FOOD = "bread"  # the fare a settlement supplies when it names none

    def staple_at(self, loc_id: str) -> str:
        """What this settlement presses on travellers."""
        return self.world.get(loc_id).staple_food or self.STAPLE_FOOD

    def haven_meal(self, character) -> str | None:
        """A proper sit-down meal at a haven: the hosts feed you, so it costs
        none of your own rations and it fills you right up. Returns the name of
        what was served, or None if this isn't a haven."""
        loc = self.world.get(character.location_id)
        if not loc.food_source:
            return None
        character.hunger = 0
        return self.items.get(self.staple_at(loc.id)).name

    # -- load (packs hold a weight, not a count) -------------------------
    def carried_weight(self, character) -> int:
        return sum(self.items.get(i).weight for i in character.inventory)

    def free_capacity(self, character) -> int:
        return character.max_carry - self.carried_weight(character)

    def can_carry(self, character, item) -> bool:
        return item.weight <= self.free_capacity(character)

    def load_burden(self, character) -> int:
        """Extra march fatigue from a heavy pack: a laden traveller tires
        faster, and a badly overloaded one worse still."""
        if character.max_carry <= 0:
            return 0
        ratio = self.carried_weight(character) / character.max_carry
        if ratio >= 0.9:
            return 2
        if ratio >= 0.7:
            return 1
        return 0

    def is_heavily_laden(self, character) -> bool:
        return self.load_burden(character) >= 2

    # -- treasure ---------------------------------------------------------
    def company_treasure(self) -> list[tuple[str, str, int]]:
        """Everything of worth the whole company is carrying out, as
        (bearer, item name, value). It's the company's haul, not Bilbo's --
        the Arkenstone counts just as much in Thorin's hands as in his."""
        haul: list[tuple[str, str, int]] = []
        for char in self.characters.values():
            if not char.alive or getattr(char, "captured", False):
                continue  # the dead and the still-imprisoned carried nothing out
            if char is not self.player and not (
                    isinstance(char, NPC) and char.def_.is_party):
                continue
            for item_id in char.inventory:
                item = self.items.get(item_id)
                if item.value > 0:
                    haul.append((char.name, item.name, item.value))
        return haul

    def notable_carried(self, character) -> list[str]:
        """What this character bears that's worth keeping track of: treasure,
        keys, torches (a light is life in the deep places), and weapons --
        carried or drawn. Ordinary rations are left out; they'd drown the
        signal. Stacks are counted."""
        out: list[str] = []
        for item_id in dict.fromkeys(character.inventory):
            item = self.items.get(item_id)
            if not (item.value > 0 or item.type in ("key", "light") or item.is_weapon):
                continue
            n = character.inventory.count(item_id)
            label = ui.item_display_name(item)
            if n > 1:
                label += f" (x{n})"
            if character.wielded == item_id:
                label += " in hand"
            out.append(label)
        if character.wielded and character.wielded not in character.inventory:
            out.append(f"{ui.item_display_name(self.items.get(character.wielded))} in hand")
        return out

    def treasure_total(self) -> int:
        return sum(value for _, _, value in self.company_treasure())

    def gather_the_hoard(self) -> list[str]:
        """With the dragon dead, the company loads what it can bear.

        The hoard was never counted in the reckoning, because the only way to
        pick it up was to break off mid-battle and loot the floor while Smaug
        was still breathing. Now the dragon falls first and the loading happens
        after, as it does in the book -- but the packs still have a bottom, so
        what comes out is bounded by who survived to carry it.
        """
        lair = self.world.get(self.player.location_id)
        loot = [i for i in lair.items + lair.hidden_items
                if self.items.get(i).value > 0]
        if not loot:
            return []
        bearers = [c for c in self.characters.values()
                   if c.alive and not getattr(c, "captured", False)
                   and c.location_id == lair.id
                   and (c is self.player or (isinstance(c, NPC) and c.def_.is_party))]
        if not bearers:
            return []
        # The road is walked. Nobody needs a week's bread walking out of a hall
        # they have just won, and without this the heap of treasure -- the
        # single biggest prize in the Mountain at 14 of a dwarf's 16 -- was
        # left behind in every run by a company that had eaten well.
        set_down = 0
        for holder in bearers:
            rations = [i for i in holder.inventory if self.items.get(i).is_food]
            for item_id in rations:
                holder.inventory.remove(item_id)
                lair.items.append(item_id)
                set_down += 1
        # Heaviest-worth first, so a full pack is a rich one.
        loot.sort(key=lambda i: self.items.get(i).value, reverse=True)
        # The Arkenstone is not shared out like plunder: Thorin's if he lives to
        # claim it, else Bilbo pockets it, exactly as he does in the book.
        claimants = {c.id: c for c in bearers}
        taken: list[str] = []
        for item_id in loot:
            first = []
            if item_id == "arkenstone":
                first = [c for c in (claimants.get("thorin"), self.player) if c]
            # Otherwise it goes to whoever has the most room left, so the haul
            # is spread across the company's backs instead of piled onto the
            # first pair of hands that can take it.
            roomiest = sorted(bearers, key=self.free_capacity, reverse=True)
            for holder in first + roomiest:
                if self.can_carry(holder, self.items.get(item_id)):
                    holder.inventory.append(item_id)
                    taken.append(item_id)
                    break
        for item_id in taken:
            if item_id in lair.items:
                lair.items.remove(item_id)
            if item_id in lair.hidden_items:
                lair.hidden_items.remove(item_id)
        if not taken:
            return [ui.Note("\nThe hoard lies open, and not one of the company has "
                            "a hand free to lift a single coin of it.")]
        left = [self.items.get(i).name for i in loot if i not in taken]
        bread = (", setting down the last of their bread to make room for it"
                 if set_down else "")
        lines = [ui.Note("\nThe dragon lies still. The company fall upon the hoard "
                         f"of Thror and load what they can bear{bread}.")]
        if left:
            lines.append(ui.Note("  Left behind, past all carrying: "
                                 f"{_join_names(left)}."))
        lines.extend(self._arkenstone_thanks(taken))
        return lines

    def _arkenstone_thanks(self, taken: list[str]) -> list[str]:
        """Thorin, if he lived to see the Mountain retaken, does not take the
        Heart of it in silence. He is not a warm man, and the thanks come out
        stiffly -- but they are the last thing he says in the game, and they
        are meant."""
        thorin = self.characters.get("thorin")
        if ("arkenstone" not in taken or not thorin or not thorin.alive
                or "arkenstone" not in thorin.inventory):
            return []
        if self.ai:
            line = thorin.speak(
                self, "Smaug is dead, the Mountain is yours again, and the "
                      "Arkenstone is in your hands. Thank Bilbo and the company "
                      "in your own words -- proud, stiff, and meant.")
            if line:
                return [f'\nThorin: "{line}"']
        return ['\nThorin holds the Arkenstone up, and the light of it is on his '
                'face. "The Heart of the Mountain, and the Mountain under it.'
                '" He turns to you. "I have said hard things on this road, '
                'burglar, and I will not take them back for they were said. '
                'But we would not be standing here without you. Nor without '
                'any of you." He does not say more. He does not have to.']

    def treasure_reckoning(self) -> list[str]:
        """The tally at journey's end: what the company carried out between
        them, and who bore it. Nothing is counted twice and nothing that fell
        with the dead is counted at all."""
        haul = self.company_treasure()
        if not haul:
            return [ui.Note("\nThe company comes away with the Mountain won but "
                            "not a coin of it carried out.")]
        by_bearer: dict[str, list[str]] = {}
        for bearer, item_name, _ in haul:
            by_bearer.setdefault(bearer, []).append(item_name)
        lines = [ui.Note("\nThe reckoning of what the company carried out:")]
        for bearer, items in by_bearer.items():
            counts = {name: items.count(name) for name in dict.fromkeys(items)}
            parts = [f"{name} (x{n})" if n > 1 else name for name, n in counts.items()]
            lines.append(ui.Note(f"  {bearer}: {', '.join(parts)}"))
        lines.append(ui.Note(f"  Worth in all: {self.treasure_total()}"))
        return lines

    def ending_lines(self) -> list[str]:
        """Everything after the killing blow, in the order it should be read:
        the company loads the hoard, the roster shows who ended up bearing
        what, the reckoning totals it, and only then is the game called won.

        The purist game ends the way 1982 did -- on the deed itself, with no
        company audit of who carried out what."""
        if self.authentic:
            return ["\nYou have won!"]
        from . import commands
        lines = list(self.gather_the_hoard())
        lines.append(ui.Note("\nAnd so the company stood, at the end of it:"))
        lines.extend(commands.do_party(self, self.player, None)[1:])
        lines.extend(self.treasure_reckoning())
        lines.append("\nYou have won!")
        return lines

    def carried_food(self, character) -> list[str]:
        return [i for i in character.inventory if self.items.get(i).is_food]

    def food_count(self, character) -> int:
        return len(self.carried_food(character))

    def add_food(self, character, item_id: str, n: int = 1,
                 upto_weight: int | None = None) -> int:
        """Add up to n food items, respecting the carry weight (food and gear
        share it). `upto_weight` stops short of the brim. Returns how many
        were actually added."""
        added = 0
        weight = self.items.get(item_id).weight
        cap = character.max_carry if upto_weight is None else min(character.max_carry,
                                                                  upto_weight)
        while added < n and self.carried_weight(character) + weight <= cap:
            character.inventory.append(item_id)
            added += 1
        return added

    def fill_food(self, character, item_id: str | None = None,
                  upto_weight: int | None = None) -> int:
        """Fill free carrying space with loaves. Returns how many added."""
        return self.add_food(character, item_id or self.staple_at(character.location_id),
                             character.max_carry, upto_weight)

    # Companions provision sensibly rather than stuffing their packs: a pack
    # crammed to the brim would leave them permanently laden and forever
    # stopping to shift it.
    NPC_PACK_TARGET = 0.5

    def restock_npc(self, npc) -> int:
        return self.fill_food(npc, upto_weight=max(2, int(npc.max_carry * self.NPC_PACK_TARGET)))

    def eat_one_food(self, character):
        """Eat one carried food item (restoring hunger). Returns the ItemDef
        eaten, or None if there's nothing to eat."""
        for item_id in list(character.inventory):
            item = self.items.get(item_id)
            if item.is_food:
                character.inventory.remove(item_id)
                character.eat(item.food_value)
                return item
        return None

    @property
    def authentic(self) -> bool:
        """True in the raw original experience ('purist' level)."""
        return self.annotation_level == "purist"

    def visible_items(self, loc) -> list[str]:
        """Item ids in a location the player can see and interact with. In
        authentic mode, items this recreation added (e.g. the map, which the
        original left as unexaminable wall flavor) are hidden -- they revert
        to being mentioned only in the room's prose."""
        if not self.authentic:
            return list(loc.items)
        return [i for i in loc.items if not self.items.get(i).added]

    # -- setup -------------------------------------------------------
    def _load_npc_file(self, path: Path) -> None:
        import json
        raw = json.loads(path.read_text(encoding="utf-8"))
        for npc_id, data in raw.items():
            npc = build_npc(npc_id, data, ai=self.ai)
            self.characters[npc_id] = npc
            self.npc_defs[npc_id] = npc.def_
            self.world.get(npc.location_id).npcs.append(npc_id)

    def _build_npc_name_lookup(self) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for npc_id, npc_def in self.npc_defs.items():
            if npc_def.is_monster:
                continue
            lookup[npc_def.name.lower()] = npc_id
            for alias in npc_def.aliases:
                lookup[alias.lower()] = npc_id
        return lookup

    # -- company news (what every companion knows) ---------------------
    def company_news(self, text: str, announce: str | None = None) -> None:
        """A death, capture, or rescue becomes known to the whole company:
        remembered durably (feeding all dialogue) and announced to the
        player once at the end of the turn."""
        self.company_lore.append(text)
        del self.company_lore[:-10]
        self.recent_events.append(text)
        if announce:
            self._pending_news.append(announce)

    # -- world events (the traces a scout can read) --------------------
    EVENT_FRESH = 30  # turns before a trace goes cold and stops being news

    def record_event(self, loc_id: str, kind: str, text: str,
                     urgent: bool = False, subject: str | None = None) -> None:
        """Note that something happened at a place. Rate-limited per
        kind+room so a three-round brawl leaves one trace, not three, and
        pruned so old traces go cold."""
        for e in self.world_events[-8:]:
            if (e["kind"] == kind and e["loc"] == loc_id
                    and self.turn - e["turn"] <= 2):
                return
        self._event_seq += 1
        self.world_events.append({"id": self._event_seq, "turn": self.turn,
                                   "loc": loc_id, "kind": kind, "text": text,
                                   "urgent": urgent, "subject": subject,
                                   # what Bilbo witnessed himself is not news
                                   "seen": self.player.location_id == loc_id})
        self.world_events = [e for e in self.world_events
                             if self.turn - e["turn"] <= self.EVENT_FRESH][-40:]

    def fresh_events_at(self, loc_id: str) -> list[dict]:
        return [e for e in self.world_events
                if e["loc"] == loc_id and self.turn - e["turn"] <= self.EVENT_FRESH]

    def danger_near(self, loc_id: str) -> bool:
        """Live monsters here or one room away -- close enough to make ready."""
        if self.room_has_live_monsters(loc_id):
            return True
        return any(self.room_has_live_monsters(dest)
                   for dest in self.world.get(loc_id).exits.values())

    # -- scouting ------------------------------------------------------
    def room_has_live_monsters(self, loc_id: str) -> bool:
        return any(isinstance(self.characters.get(n), NPC)
                   and self.characters[n].def_.is_monster
                   and self.characters[n].alive
                   for n in self.world.get(loc_id).npcs)

    def scout_observe(self, npc, loc_id: str) -> None:
        """Record what a scout can tell about a room -- monsters, locked
        ways, darkness, food, notable items, and companions in captivity.
        Deduped per fact so the same discovery isn't carried home twice, and
        rooms Bilbo has already visited aren't news (except captives, which
        are urgent news wherever they're found)."""
        loc = self.world.get(loc_id)

        def note(key: str, text: str, urgent: bool = False,
                 concern: str | None = None,
                 subjects: list[str] | None = None) -> None:
            # Keys name the FACT (kind + room it concerns), not where it was
            # observed from, so a troll camp peeked at from the road and the
            # same camp glanced at from a side-way dedupe to one report.
            # `concern` is the room the fact is about: once Bilbo has seen it
            # himself, the fact is stale news and won't be reported.
            if key in npc.scout_seen:
                return
            npc.scout_seen.add(key)
            npc.scout_memory.append(text)
            # `subjects` names the companions a finding is about, so news of
            # a captive expires the moment he is freed -- otherwise Gandalf
            # solemnly reports four dwarves as held while they stand beside you.
            entry = {"text": text, "concern": concern, "subjects": subjects}
            if urgent:
                npc.scout_unreported.insert(0, entry)  # tell Bilbo this FIRST
            else:
                npc.scout_unreported.append(entry)
            del npc.scout_memory[:-12]  # keep the freshest dozen

        def note_monsters(room) -> None:
            names = [self.characters[n].name for n in room.npcs
                     if isinstance(self.characters.get(n), NPC)
                     and self.characters[n].def_.is_monster and self.characters[n].alive]
            if names:
                note(f"monsters:{room.id}",
                     f"{_join_names(names)} lurk at {room.name}"
                     if len(names) > 1 else f"{names[0]} lurks at {room.name}",
                     concern=room.id)

        def note_captives(room) -> None:
            held = [n for n in room.npcs
                    if isinstance(self.characters.get(n), NPC)
                    and self.characters[n].def_.is_party
                    and self.characters[n].captured and self.characters[n].alive]
            if held:
                names = _join_names([self.characters[n].name for n in held])
                verb = "are" if len(held) > 1 else "is"
                # No `concern` -- a captive is news even in a room Bilbo knows.
                note(f"captives:{room.id}:{','.join(sorted(held))}",
                     f"{names} {verb} held captive at {room.name}",
                     urgent=True, subjects=list(held))

        def note_events(room_id: str) -> None:
            # Traces of things that HAPPENED -- fresh events are news even in
            # rooms Bilbo has visited (they may have happened since), but not
            # ones he witnessed himself, and never the room he's standing in
            # (he can see that fight for himself).
            if room_id == self.player.location_id:
                return
            for e in self.fresh_events_at(room_id):
                if not e.get("seen"):
                    subject = e.get("subject")
                    note(f"event:{e['id']}", e["text"],
                         urgent=e.get("urgent", False),
                         subjects=[subject] if subject else None)

        # Captives and fresh happenings are checked in every room the scout
        # can see, visited or not -- a friend in chains or drag-marks on the
        # ground are always news.
        note_captives(loc)
        note_events(loc_id)
        if not loc.visited:  # a room Bilbo has seen himself isn't news
            note_monsters(loc)
            for direction, dest_id in loc.exits.items():
                if self.world.get(dest_id).locked:
                    note(f"locked:{dest_id}",
                         f"a locked way bars passage {direction} of {loc.name}",
                         concern=loc_id)
            if loc.dark:
                note(f"dark:{loc_id}", f"the road turns pitch dark at {loc.name} -- torches will be wanted",
                     concern=loc_id)
            if loc.food_source:
                note(f"food:{loc_id}", f"food and shelter can be had at {loc.name}",
                     concern=loc_id)
            notable = [self.items.get(i).name for i in loc.items
                       if self.items.get(i).type in ("weapon", "key", "treasure")]
            if notable:
                note(f"items:{loc_id}", f"{_join_names(notable)} lies unclaimed at {loc.name}",
                     concern=loc_id)
        # A scout also glances down the side-ways for what's conspicuous from
        # here: shelter (an inn's lights), danger (a campfire's glow), or a
        # companion in chains.
        for dest_id in loc.exits.values():
            dest = self.world.get(dest_id)
            note_captives(dest)
            note_events(dest_id)
            if dest.visited:
                continue
            if dest.food_source:
                note(f"food:{dest_id}", f"food and shelter can be had at {dest.name}",
                     concern=dest_id)
            note_monsters(dest)

    def _scout_report(self) -> list[str]:
        """When a scout stands with Bilbo carrying untold news, they share
        it. Plainly phrased by default; in AI mode the model may put it in
        the scout's own voice (with the plain report as fallback)."""
        if self.authentic or self.player.invisible:
            return []  # a scout cannot report to someone he cannot see
        messages: list[str] = []
        for npc in self.characters.values():
            if not (isinstance(npc, NPC) and npc.def_.is_scout and npc.alive):
                continue
            if npc.location_id != self.player.location_id:
                continue
            # Drop findings that are now stale -- facts about rooms Bilbo has
            # since seen for himself (e.g. an inn reported just as he walks in),
            # and anything about the very room he's standing in (he can see it).
            here_name = self.world.get(self.player.location_id).name
            fresh = [f for f in npc.scout_unreported
                     if not (f.get("concern") and self.world.get(f["concern"]).visited)
                     and not f["text"].rstrip(".").endswith(f"at {here_name}")
                     and self._finding_still_stands(f)]
            if not fresh:
                npc.scout_unreported = []
                continue
            npc.scout_unreported = fresh[3:]  # carry any overflow to next report
            findings = [f["text"] for f in fresh[:3]]
            report = "; ".join(findings)
            # Frame honestly: did he range off, or just spy it from the road
            # while marching with the company?
            if npc.scout_ranged >= 2:
                lead = f"{npc.name} returns from scouting ahead."
            else:
                lead = f"{npc.name}, keeping pace with the company, marks the road ahead."
            npc.scout_ranged = 0
            line = None
            if self.ai:
                line = npc.speak(self, "What news of the road ahead? Name every "
                                        f"place and danger exactly as you found it: {report}")
                # If the model waffled past the facts, fall back to plain.
                if line and not any(f.split(" at ")[-1] in line for f in findings):
                    line = None
            messages.append(ui.Note(f'{lead} '
                                     f'"{line or f"Mark what I have seen: {report}."}"'))
        return messages

    def _finding_still_stands(self, finding: dict) -> bool:
        """Has this news gone out of date? A finding about captives expires the
        moment they're freed -- otherwise Gandalf reports four dwarves as held
        at the Spiders' Nest while all four stand beside you, rescued.

        Findings normally name their `subjects`, but ones queued before that
        field existed (or restored from an older save) don't, so fall back to
        reading the names out of the text itself.
        """
        subjects = finding.get("subjects") or self._captives_named_in(finding["text"])
        if not subjects:
            return True
        return any(getattr(self.characters.get(cid), "captured", False)
                   for cid in subjects)

    def _captives_named_in(self, text: str) -> list[str]:
        """Which companions a piece of captivity-news is about, read from the
        prose. Word-bounded so 'Ori' doesn't match inside 'Dori' or 'Nori'."""
        if not any(m in text.lower() for m in _CAPTIVITY_PHRASES):
            return []
        # Whole words only, so "Ori" never matches inside "Dori" or "Nori".
        words = {w.strip(",.;:!?'\"-").lower() for w in text.split()}
        return [c.id for c in self.characters.values()
                if isinstance(c, NPC) and c.def_.is_party
                and c.name.split()[0].lower() in words]

    def take_goal_budget(self) -> bool:
        """Consume one of this turn's LLM goal-planning calls. Returns True
        if a call is allowed; brains fall back to scripted goals otherwise.
        Bounds per-turn model latency when many NPCs replan at once."""
        if self._goal_budget > 0:
            self._goal_budget -= 1
            return True
        return False

    # -- helpers used by commands/npc modules -------------------------
    def is_hostile_pair(self, a: Character, b: Character) -> bool:
        a_monster = isinstance(a, NPC) and a.def_.is_monster
        b_monster = isinstance(b, NPC) and b.def_.is_monster
        return a_monster != b_monster

    # -- combat coordination ---------------------------------------------
    @staticmethod
    def is_leader(char: Character) -> bool:
        return isinstance(char, NPC) and char.def_.is_leader

    def combat_hostiles(self, fighter: Character, loc) -> list[str]:
        """Ids of living foes of `fighter` present in `loc`. A bound prisoner
        is not a foe: he is larder. Without this a spider stood over its own
        webbed captives beating them to death round after round -- they cannot
        strike back or flee -- and wore itself out doing it."""
        return [cid for cid in loc.npcs
                if (c := self.characters.get(cid)) and c is not fighter
                and c.alive and not getattr(c, "captured", False)
                and self.is_hostile_pair(fighter, c)]

    def choose_combat_target(self, npc: "NPC", loc) -> str | None:
        """Pick which foe a companion swings at. The company spreads across
        the foes present -- each fighter keeps to their own so long as it
        lives -- but when a leader has called for aid here, everyone piles
        onto the rally target until it falls."""
        hostiles = self.combat_hostiles(npc, loc)
        if not hostiles:
            npc.combat_target = None
            return None
        rally = self.rally_targets.get(loc.id)
        if rally in hostiles:
            npc.combat_target = rally
            return rally
        if npc.combat_target in hostiles:
            return npc.combat_target
        # Spread out: take the foe the fewest companions here are already on.
        load = {h: 0 for h in hostiles}
        for cid in loc.npcs:
            other = self.characters.get(cid)
            if (other is not None and other is not npc and other.alive
                    and isinstance(other, NPC) and other.def_.is_party
                    and other.combat_target in load):
                load[other.combat_target] += 1
        target = min(hostiles, key=lambda h: (load[h], hostiles.index(h)))
        npc.combat_target = target
        return target

    def fight_needing_aid(self, npc: "NPC") -> str | None:
        """The nearest room (within SUCCOR_RANGE, not the one they're in)
        where a leader has raised a rally the company can still help with, or
        None. Only party members answer a call."""
        if not (isinstance(npc, NPC) and npc.def_.is_party) or npc.captured:
            return None
        best, best_dist = None, SUCCOR_RANGE + 1
        for room_id, foe_id in self.rally_targets.items():
            if room_id == npc.location_id:
                continue
            foe = self.characters.get(foe_id)
            if not foe or not foe.alive:
                continue
            dist = self.world.distance(npc.location_id, room_id)
            if dist <= SUCCOR_RANGE and dist < best_dist:
                best, best_dist = room_id, dist
        return best

    def _direction_between(self, from_id: str, to_id: str) -> str | None:
        """The exit direction leading from one room to an adjacent one, if
        they're neighbours."""
        for direction, neighbor in self.world.get(from_id).exits.items():
            if neighbor == to_id:
                return direction
        return None

    def _rally_leader_name(self, room_id: str) -> str:
        for cid in self.world.get(room_id).npcs:
            c = self.characters.get(cid)
            if c and c.alive and self.is_leader(c):
                return c.name
        return "the leader"

    def _maybe_call_for_help(self, leader: "NPC") -> list[str]:
        """A leader engaged and hard-pressed (badly hurt or weary) calls for
        aid: sets a rally on their room and, if the player is near enough,
        the cry is heard. No-op if a rally is already up here."""
        loc = self.world.get(leader.location_id)
        if loc.id in self.rally_targets:
            return []
        hostiles = self.combat_hostiles(leader, loc)
        if not hostiles:
            return []
        from .entities import FATIGUE_WEAK
        if not (leader.is_badly_hurt() or leader.fatigue >= FATIGUE_WEAK):
            return []
        foe_id = leader.combat_target if leader.combat_target in hostiles else hostiles[0]
        self.rally_targets[loc.id] = foe_id
        here = self.player.location_id
        if here == loc.id:
            return [f'{leader.name}: "To me! Bring this brute down!"']
        direction = self._direction_between(here, loc.id)
        if direction:
            return [f"A shout for aid rings out from the {direction} -- "
                    f"{leader.name}'s voice!"]
        return []

    def _clear_stale_rallies(self) -> None:
        for room_id in list(self.rally_targets):
            foe = self.characters.get(self.rally_targets[room_id])
            if not foe or not foe.alive or foe.location_id != room_id:
                del self.rally_targets[room_id]

    def player_can_see_in_dark(self, actor: Character) -> bool:
        """The ring's other gift. Gollum kept his sight in the deep places
        while he bore it, and so does Bilbo: wearing it he can feel his way
        through the pitch dark, unseen and unheard.

        It is no substitute for a torch, mind -- a light is what lets the
        *company* fight, and the ring lights nothing for anyone but him.
        """
        return bool(getattr(actor, "invisible", False))

    # -- the ring -----------------------------------------------------------
    def player_beacon(self) -> str:
        """The room the company steers toward. Ordinarily Bilbo's own -- but
        with the ring on he isn't there to be followed, so they make for the
        spot where he vanished and mill about waiting."""
        if self.player.invisible:
            return self.last_seen_player
        return self.player.location_id

    def unseen(self, character) -> bool:
        """Invisible, and so no target at all -- not merely a hard one."""
        return bool(getattr(character, "invisible", False))

    # -- the Elvenking's halls ---------------------------------------------
    def guard_at(self, loc_id: str):
        """A living warden posted in this room, if any -- nobody walks past one
        who can be seen."""
        for cid in self.world.get(loc_id).npcs:
            c = self.characters.get(cid)
            if c is not None and c.alive and isinstance(c, NPC) and c.def_.is_guard:
                return c
        return None

    def mustering_room(self) -> str | None:
        """Where the company should gather, if Bilbo is standing at a way out
        that only takes those present -- the barrels. Everything else a
        companion might wander off to do (foraging, seeking a haven) is
        outranked by it, and since the larder is right there they can eat when
        they arrive. Without this a dwarf who wandered off for food would never
        come back, and the barrels could never cast off."""
        here = self.world.get(self.player.location_id)
        if here.barrel_route and not here.locked:
            return here.id
        return None

    def company_adrift(self) -> list:
        """Companions who could walk to Bilbo but haven't -- checked before the
        barrels cast off, so nobody able to follow is left on the wrong side of
        a barred gate.

        Captives are deliberately excluded. A webbed dwarf is not lagging
        behind; he is held, and no amount of waiting will bring him. Counting
        him here made the barrels refuse to leave for ever: since Mirkwood's
        spiders take prisoners in the room before the Elvenking's halls, one
        capture soft-locked the game with advice -- "call them with 'follow
        me'" -- that cannot be obeyed. See company_captive."""
        here = self.player.location_id
        return [c for c in self.characters.values()
                if isinstance(c, NPC) and c.def_.is_party and c.alive
                and not c.captured and c.location_id != here]

    def company_captive(self) -> list:
        """Living companions held somewhere -- who cannot come to the barrels
        under their own power, and must be freed or left."""
        return [c for c in self.characters.values()
                if isinstance(c, NPC) and c.def_.is_party and c.alive
                and c.captured]

    # -- goblin abductions ------------------------------------------------
    def goblins_routed(self) -> bool:
        """With the Great Goblin slain the tunnels have no master, and the
        leaderless remnant drags no one else into the deeps."""
        return self.captors_routed("goblin")

    def captors_routed(self, region: str) -> bool:
        """A lair stops taking prisoners once its master is dead -- the Great
        Goblin for the tunnels, the great spider for Mirkwood."""
        cfg = CAPTOR_REGIONS.get(region)
        if not cfg:
            return True
        master = self.characters.get(cfg["master"])
        return master is None or not master.alive

    def carries_light(self, character) -> bool:
        """A brand actually burning in this character's hand.

        An unlit torch in the pack used to count, which made fuel decorative:
        the light never ran out because merely owning a torch was light. It has
        to be lit, and lighting it costs a turn -- so walking into the dark is
        a thing you do on purpose."""
        return getattr(character, "light_remaining", 0) > 0

    def burn_torches(self) -> list[str]:
        """Burn every lit brand down by a turn, and gutter out the ones that
        reach the end of their span.

        A torch that never goes out is not a light source, it is a permit. But
        it is not a fuel economy either: the brand survives and can be lit
        again as often as you like. What it costs you is the turn spent doing
        it, and the moment of dark before you notice."""
        messages: list[str] = []
        # `characters` already contains the player; listing them separately
        # burned every torch twice as fast as it should.
        seen: set[int] = set()
        for char in list(self.characters.values()) + [self.player]:
            if id(char) in seen or getattr(char, "light_remaining", 0) <= 0:
                continue
            seen.add(id(char))
            char.light_remaining -= 1
            if char is not self.player and self.player.location_id != char.location_id:
                continue  # a torch guttering two rooms away is not your problem
            left = char.light_remaining
            whose = "Your torch" if char is self.player else f"{char.name}'s torch"
            if left == 0:
                # Out, but not spent: the brand can be lit again whenever it
                # is wanted. The tension is in having to stop and do it -- and
                # in the turn you spend doing it while something is coming --
                # not in a fuel gauge running down towards a dead end.
                messages.append(ui.sentence(
                    f"{whose} gutters, flares once, and goes out. The dark "
                    "closes in."))
            elif left == 3:
                messages.append(ui.Note(ui.sentence(
                    f"{whose} burns low and flickers.")))
        return messages

    def room_is_lit(self, loc_id: str) -> bool:
        """Does anyone standing here carry a light? There is only one torch in
        all the world, so it has to serve the whole party: whoever holds it
        lights the room for everyone in it -- and for nobody who has straggled
        into the next one."""
        if self.player.alive and self.player.location_id == loc_id \
                and self.carries_light(self.player):
            return True
        return any(self.carries_light(c) for cid in self.world.get(loc_id).npcs
                   if (c := self.characters.get(cid)) and c.alive)

    def can_fight_here(self, loc_id: str) -> bool:
        """Whether a blow can be struck at all. In the black of Mirkwood you
        cannot fight what you cannot see -- and it is being unable to fight
        back, not the dark itself, that gets you webbed. A torch doesn't save
        anyone; it lets them swing."""
        cfg = self.captor_config(loc_id)
        if not cfg or not cfg["light_saves"]:
            return True
        return self.room_is_lit(loc_id)

    def captor_config(self, loc_id: str) -> dict | None:
        loc = self.world.get(loc_id)
        cfg = CAPTOR_REGIONS.get(loc.region)
        return cfg if cfg and loc.dark else None

    def prison_for(self, npc) -> str:
        """Where this companion would be dragged, if taken."""
        cfg = self.captor_config(npc.location_id)
        if cfg:
            return cfg["prison"]
        return npc.def_.captured_location or npc.location_id

    def seizure_chance(self, npc) -> float:
        """How likely this companion is to be carried off this turn. In the
        tale both the tunnels and the forest take the whole company, so Bilbo's
        presence is protection, not immunity -- but a straggler who has drifted
        from him is far likelier to simply vanish. Never into the cell they
        already stand in (that was the rescue/recapture loop), never once the
        lair's master has fallen, and -- where a lamp helps -- never from
        someone who carries a light."""
        cfg = self.captor_config(npc.location_id)
        if not cfg:
            return 0.0
        if self.captors_routed(self.world.get(npc.location_id).region):
            return 0.0
        if cfg["prison"] == npc.location_id:
            return 0.0
        # Where the dark blinds you, it is being unable to fight back that gets
        # you taken -- anyone who can swing is not carried off helpless.
        if cfg["light_saves"] and self.can_fight_here(npc.location_id):
            return 0.0
        chance = npc.def_.trouble_chance
        if self.player.alive and self.player.location_id == npc.location_id:
            chance *= SEIZED_BESIDE_BILBO
        return chance

    def can_be_seized(self, npc) -> bool:
        return self.seizure_chance(npc) > 0.0

    def capture_texts(self, npc, place: str) -> tuple[str, str, str, bool]:
        """(trace, news, cry, loots) for a capture in this region."""
        cfg = self.captor_config(npc.location_id) or CAPTOR_REGIONS["goblin"]
        fill = {"name": npc.name, "place": place}
        return (cfg["trace"].format(**fill), cfg["news"].format(**fill),
                cfg["cry"].format(**fill), cfg["loots"])

    def loot_captive(self, npc, cell_id: str) -> None:
        """Goblins strip a prisoner of what he carries and heap it in the cell
        with him. So a captive contributes nothing to the final reckoning --
        he carried nothing out -- and freeing him wins back the plunder too.

        Silent by design: this happens in the deeps, far from Bilbo, and he has
        no way of knowing it. He finds the hoard when he reaches the cell.
        """
        spoils = [i for i in npc.inventory if self.items.get(i).value > 0]
        for item_id in spoils:
            npc.inventory.remove(item_id)
            npc.disarm_if_lost(item_id)
        self.world.get(cell_id).items.extend(spoils)

    def breath_attack(self, actor: Character, target: Character) -> list[str] | None:
        """A dragon does not fence. Every few rounds Smaug breathes instead of
        biting, and the fire takes everyone who has come within reach.

        This is what makes the front rank a real decision rather than free
        damage. Melee width lets six fight him at once and he could only
        answer one of them, so numbers alone settled the climax: a full
        company won every single time. Fire answers the whole rank at once,
        so bringing more swords now costs more lives -- while a small company
        still faces fewer, smaller hits, which is why it doesn't simply make
        a battered party's odds worse.

        Returns None when this isn't a breath round, so the caller falls
        through to an ordinary attack.
        """
        breath = getattr(getattr(actor, "def_", None), "breath", None)
        if not breath or not actor.alive:
            return None
        actor.breath_count = getattr(actor, "breath_count", 0) + 1
        if actor.breath_count % int(breath.get("every", 3)) != 0:
            return None
        loc = self.world.get(actor.location_id)
        caught = [self.characters[cid] for cid in self.combat_hostiles(actor, loc)]
        # Bilbo stands in the room's occupants, not its npc list.
        if (self.player.alive and self.player.location_id == loc.id
                and not self.unseen(self.player)
                and self.is_hostile_pair(actor, self.player)):
            caught.append(self.player)
        # Only those actually at the front are in the fire's path -- the same
        # limit that lets them reach him.
        caught = caught[:loc.melee_width] or [target]
        actor.add_combat_fatigue()
        power = actor.effective_attack()
        if power <= 0:
            return None
        messages = [ui.Note(breath.get("text", f"{actor.name} breathes fire."))]
        fallen: list[Character] = []
        for victim in caught:
            # Split across the rank rather than dealt whole to each -- the
            # fire is wide, not six times as deadly.
            damage = max(1, self.rng.randint(power // 3, (power * 2) // 3))
            victim.take_damage(damage)
            messages.append(ui.sentence(
                f"{victim.name} is caught in the fire for {damage} damage."))
            if not victim.alive:
                fallen.append(victim)
        for victim in fallen:
            messages.append(ui.sentence(f"{victim.name} has been defeated!"))
            messages.extend(self.handle_death(victim))
        return messages

    def handle_death(self, character: Character) -> list[str]:
        messages = []
        loc = self.world.get(character.location_id)
        # Falling is a thing that happens once. Processing it twice dropped the
        # loot twice, announced the death twice, and raised a second cairn --
        # "Cairns stand here, raised over Gandalf and Gandalf."
        if character.id in self._mourned:
            return messages
        self._mourned.add(character.id)
        dropped: list[str] = []
        loot = character.inventory
        if loot:
            loc.items.extend(loot)
            dropped.extend(loot)
            character.inventory = []
        if isinstance(character, NPC) and character.def_.loot:
            loc.items.extend(character.def_.loot)
            dropped.extend(character.def_.loot)
        # Say what falls with them. Loot used to drop in total silence, so a
        # key the story turns on could sit unnoticed on the floor forever.
        if dropped:
            names = _join_names([ui.with_article(ui.item_display_name(self.items.get(i)))
                                 for i in dropped])
            messages.append(ui.sentence(f"{character.name} falls, leaving {names} on the ground."))
        if character.id != "bilbo" and character.id in loc.npcs:
            loc.npcs.remove(character.id)
        if character.id != "bilbo":
            self.record_event(loc.id, "slain",
                              f"{character.name} was slain in battle at {loc.name}")
        # A slain monster leaves a body where it fell.
        if isinstance(character, NPC) and character.def_.is_monster:
            loc.slain.append(character.name)
        # A fallen companion is known and mourned by the whole company, and
        # awaits a proper burial once the fighting is done (see the turn loop).
        # All of that -- the word passing through the company, the cairn, the
        # grief -- is this recreation's doing; in 1982 a character simply fell.
        # So the purist game skips it: the body's loot drops and they are gone.
        if (isinstance(character, NPC) and character.def_.is_party
                and not self.authentic):
            character.death_place = loc.name
            self._pending_burials.append((loc.id, character.name))
            self.company_news(
                f"{character.name} fell in battle at {loc.name}",
                announce=f"Word passes through the company: {character.name} has fallen.")
            self._pending_grief = character.name
        if character.id == "smaug":
            self.won = True
            # Just the fact here. "You have won" is the last word of the game,
            # printed after the burials, the loading of the hoard and the
            # reckoning -- it reads as a verdict on all of that, not as an
            # interruption of it.
            messages.append("With Smaug slain, the way to the Lonely Mountain's "
                            "treasure lies open.")
        if character.id == "bilbo":
            self.lost = True
            self.lose_reason = "You have died."
        return messages

    def describe_location(self, actor: Character) -> list[str]:
        """Returns a list of display lines, not a single string: the main
        room block is one joined line, so callers can colour it via ui.present."""
        loc = self.world.get(actor.location_id)
        # In authenticity mode we use the pre-fix prose and drop the
        # added-feature clause -- the point of that mode is the raw experience.
        if self.authentic:
            description = loc.original_description
        else:
            description = loc.description
            if loc.added_description:
                # Colour just the added clause (marks the new provisioning feature).
                description = f"{description} {ui.mark(loc.added_description)}"

        lines = [f"== {loc.name} =="]
        if loc.dark and actor.light_remaining <= 0:
            lines.append("It is pitch dark. You can make out very little.")
            return ["\n".join(lines)]
        lines.append(description)
        # Split live occupants into companions and hostile monsters, so a
        # room only announces monsters while they're actually alive there
        # (no more "trolls loom here" once they've been slain).
        companions, monsters = [], []
        for n in loc.npcs:
            if n == actor.id:
                continue
            c = self.characters[n]
            if not c.alive:
                continue
            if isinstance(c, NPC) and c.def_.is_monster:
                monsters.append(c.name)
            else:
                companions.append(c.name)
        if actor.id != "bilbo" and self.player.location_id == loc.id and self.player.alive:
            companions.append(self.player.name)
        if companions:
            lines.append("Also here: " + _join_names(companions) + ".")
        if monsters:
            loom = "looms" if len(monsters) == 1 else "loom"
            lines.append(f"{_join_names(monsters)} {loom} here.")
        visible = self.visible_items(loc)
        if visible:
            item_names = ", ".join(ui.item_display_name(self.items.get(i)) for i in visible)
            lines.append(f"You see: {item_names}.")
        # Mark locked ways so the player knows there's a door to deal with
        # (a modern courtesy, so it's coloured and absent in purist mode).
        exit_parts = []
        for direction in sorted(loc.exits.keys()):
            if not self.authentic and direction in loc.barred_exits:
                exit_parts.append(f"{direction} {ui.mark('(barred)')}")
            elif not self.authentic and self.world.get(loc.exits[direction]).locked:
                exit_parts.append(f"{direction} {ui.mark('(locked)')}")
            else:
                exit_parts.append(direction)
        # The barrels are a way out like any other, so they belong in the list
        # rather than in a paragraph explaining themselves.
        if loc.barrel_route and not self.authentic:
            exit_parts.append(ui.mark("barrel"))
        if exit_parts:
            lines.append(f"Exits: {', '.join(exit_parts)}.")
        # The marks a battle leaves: bodies of the slain, graves of the fallen.
        if loc.slain:
            one = len(loc.slain) == 1
            lines.append(f"The {'body' if one else 'bodies'} of "
                         f"{ui.tally_names(loc.slain)} "
                         f"{'lies' if one else 'lie'} where "
                         f"{'it' if one else 'they'} fell.")
        if loc.graves:
            word = "A cairn stands" if len(loc.graves) == 1 else "Cairns stand"
            lines.append(f"{word} here, raised over {_join_names(loc.graves)}.")
        return ["\n".join(lines)]

    # -- turn processing -----------------------------------------------
    def process_player_input(self, text: str) -> list[str]:
        messages: list[str] = []
        start_loc = self.player.location_id
        cmds = self.parser.parse_line(text)
        if not cmds:
            return ["I didn't understand that."]
        acted = False  # did anything happen that should cost game time?
        for cmd in cmds:
            actor = self.characters.get(cmd.actor_override) if cmd.actor_override else self.player
            if actor is None:
                messages.append(f"There is no one here called {cmd.actor_override}.")
                continue
            # In the purist game the recreation's own verbs simply don't exist:
            # treat them as words the 1982 parser never knew, so 'party' and the
            # like are turned away instead of exposing a modern system.
            if self.authentic and cmd.verb in ADDED_VERBS:
                cmd.unknown = True
                cmd.error = f"I don't know how to '{cmd.raw}'."
            messages.extend(commands.execute(self, actor, cmd))
            if not cmd.unknown and cmd.verb not in FREE_VERBS:
                acted = True
                # Turning aside to your own business breaks off the march.
                if (actor is self.player and self.player_follow
                        and cmd.verb not in FOLLOW_KEEPING_VERBS):
                    leader = self.characters.get(self.player_follow)
                    self.player_follow = None
                    if leader:
                        messages.append(ui.Note(
                            f"You break off to your own business; {leader.name} goes "
                            "on without you. ('follow' again to fall back in.)"))
            if actor is self.player and cmd.verb == "attack" and cmd.obj:
                self.recent_events.append(f"Bilbo attacked {cmd.obj}.")
            if self.request_quit or self.won or self.lost:
                break
        if acted and not (self.request_quit or self.won or self.lost):
            messages.extend(_collapse_company_messages(self._advance_world_turn()))
        # Modern convenience: after any move (by the player or by following a
        # companion), automatically show the new room. Off in purist, where --
        # as in 1982 -- you look for yourself.
        if (not self.authentic and self.player.alive
                and not (self.request_quit or self.won or self.lost)
                and self.player.location_id != start_loc):
            messages.extend(ui.autolook_lines(self.describe_location(self.player)))
        return messages

    def _advance_world_turn(self) -> list[str]:
        messages: list[str] = []
        self.turn += 1
        if not self.player.invisible:
            self.last_seen_player = self.player.location_id
        narrated = False  # cap LLM narration at one per turn for responsiveness
        cue_used = False  # at most one off-screen "sounds of battle" cue per turn
        # Fighting room per location this turn (see Location.melee_width), and
        # the rooms already told the player their company can't all get in.
        self._melee_used: dict[str, int] = {}
        pressed: set[str] = set()
        self._goal_budget = 1  # at most one LLM goal-plan per turn

        # Before the company acts, a hard-pressed leader calls for aid -- so
        # the rally is up in time for the others to answer it this same turn.
        if not self.authentic:
            for leader in list(self.characters.values()):
                if (self.is_leader(leader) and leader.alive
                        and not getattr(leader, "captured", False)):
                    messages.extend(self._maybe_call_for_help(leader))

        # When Bilbo is trailing a companion, that companion moves FIRST and
        # Bilbo goes with them straight away -- otherwise the rest of the
        # company escorts him to the room he's about to leave, and trails a
        # room behind for the whole journey.
        order = list(self.characters.items())
        if self.player_follow:
            order.sort(key=lambda kv: kv[0] != self.player_follow)
        followed_resolved = False

        for npc_id, npc in order:
            if npc_id == "bilbo" or not npc.alive:
                continue
            # The leader has had their turn; Bilbo travels with them now, so
            # everyone else escorts him to where he actually ends up.
            if (not followed_resolved and self.player_follow
                    and npc_id != self.player_follow):
                messages.extend(self._resolve_player_follow())
                followed_resolved = True
            upkeep_msgs, skip = self._npc_upkeep(npc)
            messages.extend(upkeep_msgs)
            if skip:
                continue
            cmd = npc.decide(self)
            if cmd is None:
                continue
            # Only so many can come to blows at once. In a goblin-cut tunnel
            # two abreast is all that fits, so the rest press behind and wait
            # their turn -- without this the whole company falls on one foe
            # and nothing in the world survives a single round.
            if (cmd.verb == "attack" and not self.authentic
                    and isinstance(npc, NPC) and npc.def_.is_party):
                room = npc.location_id
                width = self.world.get(room).melee_width
                if self._melee_used.get(room, 0) >= width:
                    if room == self.player.location_id and room not in pressed:
                        pressed.add(room)
                        messages.append("The rest of the company press behind, "
                                        "unable to reach past the crush.")
                    continue
                self._melee_used[room] = self._melee_used.get(room, 0) + 1
            was_with_player = npc.location_id == self.player.location_id
            room_before = npc.location_id
            result = commands.execute(self, npc, cmd)
            killed = any(isinstance(m, str) and "has been defeated!" in m for m in result)
            # A ranging scout takes stock of each new room they enter.
            if (npc.def_.is_party and npc.def_.is_scout
                    and npc.location_id != room_before and not self.authentic):
                self.scout_observe(npc, npc.location_id)
            now_with_player = npc.location_id == self.player.location_id
            off_screen = not (was_with_player or now_with_player)
            if was_with_player or now_with_player:
                moved = npc.location_id != room_before
                # A companion peeling off to answer a leader's call reads as
                # exactly that, not a generic "heads east".
                if cmd.verb == "go" and moved and getattr(npc, "rushing_to_aid", False):
                    result = [f"{npc.name} rushes off to aid "
                              f"{self._rally_leader_name(npc.location_id)}!"]
                # Arriving into Bilbo's room is catching up, not "heading east"
                # -- the direction of travel misreads as leaving otherwise. But
                # they can't catch up to a hobbit they can't see: wearing the
                # ring, you just watch them walk in.
                elif (cmd.verb == "go" and moved and now_with_player
                        and not was_with_player and not self.player.invisible):
                    result = [f"{npc.name} catches up."]
                # A companion bumping into a locked or blocked way isn't
                # news -- their failure text reads like the player's own.
                elif cmd.verb == "go" and not moved:
                    result = []
                messages.extend(result)
                # A companion's combat in the player's room earns one
                # LLM-narrated flourish per turn (silent fallback if the
                # model is off/slow), keeping the turn responsive. The
                # flourish is told the real result so it can't crow about a
                # kill on a whiffed swing -- and a plain miss gets no flourish.
                if (self.ai and not narrated and cmd.verb == "attack"
                        and isinstance(npc, NPC) and not npc.def_.is_monster):
                    landed = any(isinstance(m, str) and " hits " in m for m in result)
                    outcome = "kill" if killed else ("hit" if landed else "miss")
                    flavor = npc.narrate(self, cmd, outcome) if outcome != "miss" else None
                    if flavor:
                        messages.append(flavor)
                        narrated = True
            elif (cmd.verb == "attack" and not cue_used
                    and isinstance(npc, NPC) and npc.def_.is_party
                    and self._direction_between(self.player.location_id, npc.location_id)):
                # A fight one room away is heard, not seen.
                direction = self._direction_between(self.player.location_id, npc.location_id)
                messages.append(f"From the {direction} comes the clash of steel.")
                cue_used = True
            # A victory the player didn't witness becomes a boast for when the
            # fighter is back at Bilbo's side.
            if killed and off_screen and isinstance(npc, NPC) and npc.def_.is_party:
                npc.pending_warcry = cmd.obj
            if cmd.verb == "attack":
                self.recent_events.append(f"{npc.name} traded blows with {cmd.obj}.")

        self._clear_stale_rallies()

        messages.extend(self.burn_torches())
        messages.extend(self._resolve_rescues())
        messages.extend(self._resolve_burials())
        messages.extend(self._deliver_company_news())
        messages.extend(self._deliver_warcries())
        messages.extend(self._scout_report())

        # If the flavor slot wasn't spent on narration, a companion in the
        # room may pipe up unprompted -- banter, a grumble, an observation.
        if self.ai and not narrated:
            messages.extend(self._maybe_ambient_remark())

        if not followed_resolved:
            messages.extend(self._resolve_player_follow())

        # Who is visibly mending under a haven's care this turn, so the healing
        # is something you can watch happen rather than infer from `party`.
        mending: list[str] = []
        whole: list[str] = []
        for char in self.characters.values():
            if not char.alive:
                continue
            # A beast tires in a long fight, but gets its wind back in the lull
            # -- otherwise fatigue only ever climbs and it eventually faints in
            # its own lair, having never eaten or slept in its life.
            if (isinstance(char, NPC) and char.def_.is_monster and char.fatigue > 0
                    and not self.combat_hostiles(char, self.world.get(char.location_id))):
                char.fatigue = max(0, char.fatigue - MONSTER_RECOVERY)
            needs_msgs = char.tick_needs()
            # Being weak or collapsed steadily wears down health -- but not
            # while captured (imprisoned, awaiting rescue, not adventuring).
            if not getattr(char, "captured", False):
                drain = char.needs_health_drain()
                if drain:
                    was_alive = char.alive
                    char.take_damage(drain)
                    if char is self.player:
                        if char.is_fainted():  # dire: warn every turn now
                            needs_msgs.append("Hunger and exhaustion are overwhelming "
                                              "you -- eat or rest, quickly!")
                        if was_alive and not char.alive:
                            self.lose_reason = ("Worn down by hunger and exhaustion, "
                                                "Bilbo can go no further.")
                    elif was_alive and not char.alive and isinstance(char, NPC):
                        needs_msgs.extend(self.handle_death(char))
                elif (not self.authentic and not char.is_weak()
                        and char.health < char.max_health):
                    # Wounds mend when safe and fed -- fast in a haven's care
                    # (Rivendell, an inn), slowly on the open road. This gentle
                    # healing is a modern mercy: the purist game keeps its
                    # wounds, so there a hurt only ever deepens.
                    at_haven = self.world.get(char.location_id).food_source
                    char.health = min(char.max_health, char.health + (5 if at_haven else 1))
                    if at_haven and char.location_id == self.player.location_id:
                        mending.append(char.name)
                        if char.health >= char.max_health:
                            whole.append(char.name)
            if char.id == "bilbo" or char.location_id == self.player.location_id:
                messages.extend(needs_msgs)

        # One line for the whole room, however many are being tended.
        if mending:
            house = self.world.get(self.player.location_id).name
            messages.append(ui.Note(
                f"Under the care of {house}, {_join_names(mending)} "
                f"{'mend' if len(mending) > 1 else 'mends'}."))
        if whole:
            messages.append(ui.Note(
                f"{_join_names(whole)} {'are' if len(whole) > 1 else 'is'} "
                "whole again."))

        if self.player.is_fainted():
            self.faint_turns += 1
            if self.faint_turns >= MAX_FAINT_TURNS:
                self.lost = True
                self.lose_reason = "You succumb to hunger and exhaustion, and your journey ends here."
        else:
            self.faint_turns = 0

        if not self.player.alive:
            self.lost = True
            self.lose_reason = self.lose_reason or "You have died."

        return messages

    def _npc_upkeep(self, npc) -> tuple[list[str], bool]:
        """Companions look after themselves: restock at food sources, eat
        from their pack when hungry, and stop to rest when spent. Returns
        (messages, skip) -- skip means they rest instead of acting this turn.
        Only party members do this; monsters don't. Messages are shown only
        when the NPC is with the player."""
        from .entities import FATIGUE_WEAK, HUNGER_WEAK
        if not (isinstance(npc, NPC) and npc.def_.is_party) or npc.captured:
            return [], False
        msgs: list[str] = []
        visible = npc.location_id == self.player.location_id
        loc = self.world.get(npc.location_id)

        # Weapons are drawn when danger is near and put away on a quiet road
        # (marching armed is wearying) -- so a scout's warning lets the
        # company make ready before trouble arrives.
        if self.danger_near(npc.location_id):
            weapons = [i for i in npc.inventory if self.items.get(i).is_weapon]
            if weapons:
                best = max(weapons, key=lambda i: self.items.get(i).damage)
                best_item = self.items.get(best)
                current = (self.items.get(npc.wielded).damage
                           if npc.wielded in npc.inventory else 0)
                if best_item.damage > current and best_item.damage > npc.base_attack:
                    npc.wield_weapon(best, best_item.damage, best_item.travel_mod)
                    if visible:
                        msgs.append(f"{npc.name} makes ready with {best_item.name}.")
        elif npc.wielded:
            stowed = self.items.get(npc.wielded).name
            npc.sheathe()
            if visible:
                msgs.append(f"{npc.name} puts away {ui.with_article(stowed)}.")

        if loc.food_source:
            # A haven: free food and a real hearth. Companions top up fully,
            # so nobody lingers 'hungry' or 'weary' at an inn.
            # Only speak up when something actually went into the pack --
            # otherwise a well-provisioned dwarf "refills" every single turn.
            if self.restock_npc(npc) and visible:
                fare = self.items.get(self.staple_at(loc.id)).name
                msgs.append(f"{npc.name} refills a pack with {fare}.")
            if npc.hunger >= 20:
                # The hosts do the feeding here -- a real meal, and it costs
                # the traveller none of their own rations.
                self.haven_meal(npc)
                if visible:
                    msgs.append(f"{npc.name} tucks into a hearty meal.")
            if npc.fatigue >= 20:
                npc.rest(60)
                if visible:
                    msgs.append(f"{npc.name} settles in by the fire to rest.")
                return msgs, True
            return msgs, False

        # On the road: eat as soon as they'd start feeling hungry (the same
        # point the 'hungry' description appears), and rest before weakness.
        if npc.hunger >= HUNGER_WEAK * 0.6 and self.food_count(npc) > 0:
            item = self.eat_one_food(npc)
            if visible and item:
                msgs.append(f"{npc.name} pauses to eat some {item.name}.")

        if npc.fatigue >= FATIGUE_WEAK * 0.7:
            npc.rest(40)
            if visible:
                msgs.append(f"{npc.name} stops for breath.")
            return msgs, True

        # A heavily laden traveller keeps stopping to shift the load, so they
        # move less often -- a dwarf hauling a dragon's hoard falls behind.
        if self.is_heavily_laden(npc) and self.rng.random() < LADEN_PAUSE_CHANCE:
            if visible:
                msgs.append(f"{npc.name} shifts a heavy load and trudges on.")
            return msgs, True

        return msgs, False

    def _resolve_rescues(self) -> list[str]:
        """Reaching a captive companion frees them: they rejoin the company on
        the spot (their goal machinery takes over again next turn).

        Any free companion will do it, not only Bilbo. A dwarf who walks into
        the cell where his cousin is chained and steps over him to look at the
        gold is not a character anyone wants in their company -- and it left a
        rescue impossible while the player was elsewhere, even with half the
        company standing in the room."""
        messages: list[str] = []
        for npc in self.characters.values():
            if not (isinstance(npc, NPC) and npc.def_.is_party and npc.alive
                    and npc.captured):
                continue
            by_player = npc.location_id == self.player.location_id
            rescuer = None
            if not by_player:
                rescuer = next(
                    (c for c in self.characters.values()
                     if isinstance(c, NPC) and c.def_.is_party and c.alive
                     and not c.captured and c.location_id == npc.location_id),
                    None)
            if not by_player and rescuer is None:
                continue
            npc.captured = False
            npc.goal_kind = None  # replan: fall back in with the company
            if by_player:
                messages.append(f"You strike off {npc.name}'s bonds -- "
                                f"{npc.name} is free!")
            else:
                messages.append(ui.sentence(
                    f"{rescuer.name} cuts {npc.name} loose."))
            self.company_news(f"{npc.name} was rescued")
        return messages

    def _resolve_burials(self) -> list[str]:
        """Once a room is clear of foes, living companions there raise a
        cairn over any of their own who fell -- a lasting mark in the room."""
        messages: list[str] = []
        still_pending: list[tuple[str, str]] = []
        for loc_id, name in self._pending_burials:
            loc = self.world.get(loc_id)
            if self.room_has_live_monsters(loc_id):
                still_pending.append((loc_id, name))  # the fight isn't over
                continue
            buriers = [c for c in self.characters.values()
                       if isinstance(c, NPC) and c.def_.is_party and c.alive
                       and not c.captured and c.location_id == loc_id]
            if not buriers and self.player.location_id != loc_id:
                still_pending.append((loc_id, name))  # no one here to dig
                continue
            # No one is buried twice. The room's own graves catch the ordinary
            # case, but they're rebuilt from the save on load and restored by
            # reconcile_after_load, so a companion who fell before a save could
            # be laid to rest a second time. `_buried` is the memory that
            # survives all of that.
            if name in loc.graves or name in self._buried:
                continue
            loc.graves.append(name)
            self._buried.add(name)
            if self.player.location_id == loc_id:
                messages.append(f"The company raise a cairn of stones over {name}, "
                                 "and stand a while in silence.")
        self._pending_burials = still_pending
        return messages

    def _deliver_company_news(self) -> list[str]:
        """Announce queued news once, and let a companion give voice to
        grief when one of their own has fallen (AI mode)."""
        messages: list[str] = list(self._pending_news)
        self._pending_news = []
        if self._pending_grief:
            fallen = self._pending_grief
            self._pending_grief = None
            if self.ai:
                here = self.player.location_id
                mourners = [c for c in self.characters.values()
                            if isinstance(c, NPC) and c.def_.is_party and c.alive
                            and not c.captured and c.location_id == here]
                if mourners:
                    speaker = self.rng.choice(mourners)
                    line = speaker.speak(
                        self, f"{fallen} has just fallen in battle. Speak a few "
                              f"words of grief or resolve for {fallen}.")
                    if line:
                        messages.append(f'{speaker.name}: "{line}"')
        return messages

    def _maybe_ambient_remark(self) -> list[str]:
        """Occasionally, a companion sharing the player's room says something
        in character, unprompted. Costs at most one model call (the shared
        flavor slot) and only fires some turns, so it stays affordable and
        unobtrusive."""
        if self.rng.random() >= AMBIENT_CHANCE:
            return []
        if self.player.invisible:
            return []  # they speak to the company, not to a hobbit they can't see
        here = self.player.location_id
        speakers = [c for c in self.characters.values()
                    if isinstance(c, NPC) and c.def_.is_party and c.alive
                    and not c.captured and c.location_id == here]
        if not speakers:
            return []
        npc = self.rng.choice(speakers)
        line = npc.remark(self)
        if not line:
            return []
        self.recent_events.append(f'{npc.name} said: "{line}"')
        return [f'{npc.name}: "{line}"']

    def _deliver_warcries(self) -> list[str]:
        """A companion back at Bilbo's side mentions a fight they won while
        out of his sight. At most one per turn, so a big off-screen scrap
        doesn't turn into a wall of boasts."""
        here = self.player.location_id
        for c in self.characters.values():
            if (isinstance(c, NPC) and c.def_.is_party and c.alive
                    and not c.captured and c.location_id == here
                    and c.pending_warcry):
                foe = c.pending_warcry
                c.pending_warcry = None
                return [f'{c.name}, still breathing hard: '
                        f'"{foe} won\'t trouble the road again -- back down the way."']
        return []

    def _resolve_player_follow(self) -> list[str]:
        """If the player is trailing a companion, move with them when they
        change rooms (stopping if they vanish into the dark)."""
        if not self.player_follow:
            return []
        leader = self.characters.get(self.player_follow)
        if not leader or not leader.alive:
            self.player_follow = None
            return []
        if leader.location_id == self.player.location_id:
            return []
        dest = self.world.get(leader.location_id)
        if (dest.dark and self.player.light_remaining <= 0
                and not self.player_can_see_in_dark(self.player)):
            self.player_follow = None
            return [f"{leader.name} disappears into the dark ahead; you cannot follow "
                    "without a light."]
        self.player.location_id = leader.location_id
        self.player.add_travel_fatigue()
        dest.visited = True
        # The room itself is shown by the auto-look in process_player_input.
        return [f"You follow {leader.name}."]

    # -- persistence -----------------------------------------------------
    def save(self, path: Path) -> None:
        save_game(self, path)

    def load(self, path: Path) -> None:
        load_game(self, path)
        self.reconcile_after_load()

    def reconcile_after_load(self) -> list[str]:
        """Fold in anything the save has never heard of.

        A save records the world as it stood when written, so loading one made
        after the game has grown would quietly erase the new parts: rooms come
        back with `npcs: []` and `items: []`, which deleted the wood-elf guard,
        his key, and the lock on the cellars from a game in progress. Rather
        than make old saves unplayable, restore what the save cannot have known
        about. Returns a note of what was put back, for the curious.
        """
        restored: list[str] = []
        # Anyone already dead has been mourned; don't bury them again.
        self._mourned.update(c.id for c in self.characters.values() if not c.alive)
        # And tidy any double burials a save already carries.
        for loc in self.world.locations.values():
            if len(set(loc.graves)) != len(loc.graves):
                loc.graves = list(dict.fromkeys(loc.graves))
            self._buried.update(loc.graves)

        # Characters know where they stand; make sure the rooms agree. This
        # also repairs any desync, not just newly added folk.
        for char in self.characters.values():
            if char is self.player or not char.alive:
                continue
            room = self.world.get(char.location_id)
            if char.id not in room.npcs:
                room.npcs.append(char.id)
                restored.append(char.name)

        # An item the save mentions nowhere at all is one that didn't exist
        # when it was written -- put it back where the world data puts it.
        known = {i for loc in self.world.locations.values()
                 for i in loc.items + loc.hidden_items}
        for char in self.characters.values():
            known.update(char.inventory)
            known.update(char.worn)
        for loc in self.world.locations.values():
            for item_id in loc.initial_items:
                if item_id not in known:
                    loc.items.append(item_id)
                    known.add(item_id)
                    restored.append(self.items.get(item_id).name)

        # A door that has grown a lock since the save was written should be
        # locked again -- but only where the player has never been, since a
        # room he has stood in he may legitimately have opened.
        for loc in self.world.locations.values():
            if loc.initial_locked and not loc.locked and not loc.visited:
                loc.locked = True
                restored.append(f"the lock on {loc.name}")
        return restored
