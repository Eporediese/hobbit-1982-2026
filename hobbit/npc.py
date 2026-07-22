"""NPCs and their autonomous behavior.

The behavior system is intentionally isolated behind the NPCBrain
interface so it can be swapped later (e.g. for an LLM-driven brain)
without touching world.py, parser.py, or game.py. SimpleBrain reproduces
the original 1982 game's simple routine: NPCs wander their home region on
their own schedule, fight monsters they run into, occasionally land in
scripted trouble, and yield to direct player commands (handled upstream
in Game, which routes an addressed command straight through commands.py
instead of calling decide() that turn).
"""
from __future__ import annotations

import random
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from .entities import Character
from .parser import Command

if TYPE_CHECKING:
    from .game import Game


class NPCDef:
    def __init__(self, npc_id: str, data: dict[str, Any]):
        self.id = npc_id
        self.name: str = data["name"]
        self.aliases: list[str] = data.get("aliases", [])
        self.start_location: str = data["start_location"]
        self.health: int = data.get("health", 15)
        self.attack: int = data.get("attack", 3)
        self.dialogue: str = data.get("dialogue", "...")
        self.region: str = data.get("region", "")
        self.is_party: bool = data.get("is_party", False)
        self.is_monster: bool = data.get("is_monster", False)
        self.aggressive: bool = data.get("aggressive", False)
        self.stationary: bool = data.get("stationary", False)
        # A breath weapon sweeps the whole front rank rather than biting
        # one fighter -- see Game.breath_attack.
        self.breath: dict | None = data.get("breath")
        self.wander_chance: float = data.get("wander_chance", 0.35)
        self.trouble_chance: float = data.get("trouble_chance", 0.05)
        self.captured_location: str | None = data.get("captured_location")
        self.inventory: list[str] = data.get("inventory", [])
        self.loot: list[str] = data.get("loot", [])
        self.max_carry: int = data.get("max_carry", 16)
        # A scout ranges ahead of the company, learns the road, and reports
        # back (Gandalf).
        self.is_scout: bool = data.get("is_scout", False)
        # A leader (Thorin, Gandalf) rallies the company: when hard-pressed in
        # a fight they call for aid, drawing nearby companions in and focusing
        # the company's blows on their foe.
        self.is_leader: bool = data.get("is_leader", False)
        # A guard turns visitors back at the door. Nobody walks past one who
        # can be seen -- but a burglar wearing the ring is not seen.
        self.is_guard: bool = data.get("is_guard", False)
        # Short character brief used to prompt the LLM in AI mode. Optional;
        # falls back to a generic description.
        self.persona: str = data.get("persona", "")


class NPCBrain(ABC):
    @abstractmethod
    def decide(self, npc: "NPC", game: "Game") -> Command | None:
        """Return the Command the NPC performs this tick, or None to idle."""
        raise NotImplementedError

    def speak(self, npc: "NPC", game: "Game", player_line: str | None = None) -> str | None:
        """An in-character spoken line, or None to use the static dialogue.
        Non-AI brains return None."""
        return None

    def narrate(self, npc: "NPC", game: "Game", action: Command,
                outcome: str | None = None) -> str | None:
        """Flavorful narration of an action, or None to use the plain line.
        `outcome` names the mechanical result ('kill'/'hit'/'miss') so the
        flourish can't contradict it. Non-AI brains return None."""
        return None

    def remark(self, npc: "NPC", game: "Game") -> str | None:
        """A spontaneous, unprompted in-character line to the company, or
        None. Non-AI brains return None."""
        return None


class SimpleBrain(NPCBrain):
    """Faithful-to-the-original: mostly random wandering within the NPC's
    home region, fights any monster sharing the room, and has a small
    chance of scripted trouble (getting captured) when unaccompanied."""

    def decide(self, npc: "NPC", game: "Game") -> Command | None:
        rng = game.rng

        if npc.captured:
            return None  # waits to be rescued

        loc = game.world.get(npc.location_id)

        # In the enhanced game the company coordinates: they spread across the
        # foes in the room, but focus fire when a leader calls for aid. The raw
        # 1982 routine just swings at the first thing it sees.
        if game.authentic:
            hostile = self._hostile_in_room(npc, game, loc.npcs)
        else:
            hostile = game.choose_combat_target(npc, loc)
        # You cannot fight what you cannot see: in the black of Mirkwood, with
        # no torch among the company, there is nothing to do but grope about
        # and hope -- which is how the spiders get you.
        if hostile and game.can_fight_here(npc.location_id):
            return Command(verb="attack", obj=game.characters[hostile].name)

        if not npc.def_.stationary and npc.def_.is_monster is False:
            if rng.random() < game.seizure_chance(npc):
                trace, news, cry, loots = game.capture_texts(npc, loc.name)
                dest = game.prison_for(npc)
                npc.captured = True
                if npc.id in loc.npcs:
                    loc.npcs.remove(npc.id)
                npc.location_id = dest
                game.world.get(dest).npcs.append(npc.id)
                game.record_event(loc.id, "captured", trace, urgent=True, subject=npc.id)
                game.company_news(news, announce=cry)
                # Goblins rob their prisoners: what he bore is heaped in the
                # cell, so it counts for nothing until someone frees him.
                # (Spiders have no use for gold and leave it on him.)
                if loots:
                    game.loot_captive(npc, dest)
                return None

        if npc.def_.stationary:
            return None

        return self._move_step(npc, game, loc)

    def _move_step(self, npc: "NPC", game: "Game", loc) -> Command | None:
        """The wander step -- overridden by goal-seeking brains. The base
        version is the faithful 1982 random walk."""
        if game.rng.random() < npc.def_.wander_chance:
            exits = list(loc.exits.items())
            if exits:
                direction, _ = game.rng.choice(exits)
                return Command(verb="go", obj=direction)
        return None

    @staticmethod
    def _hostile_in_room(npc: "NPC", game: "Game", occupant_ids: list[str]) -> str | None:
        for other_id in occupant_ids:
            if other_id == npc.id:
                continue
            other = game.characters.get(other_id)
            if (other and other.alive and game.is_hostile_pair(npc, other)
                    and not game.unseen(other)
                    and not getattr(other, "captured", False)):
                return other_id
        return None


class MonsterBrain(NPCBrain):
    """Mostly stationary guardians/hazards: attack anyone sharing the room
    if aggressive, otherwise sit still (e.g. a sleeping Smaug)."""

    def decide(self, npc: "NPC", game: "Game") -> Command | None:
        if not npc.def_.aggressive:
            return None
        loc = game.world.get(npc.location_id)
        occupants = [c for c in loc.npcs if c != npc.id]
        if game.player.location_id == loc.id:
            occupants.append("bilbo")
        for other_id in occupants:
            other = game.characters.get(other_id)
            if (other and other.alive and game.is_hostile_pair(npc, other)
                    and not game.unseen(other)
                    and not getattr(other, "captured", False)):
                return Command(verb="attack", obj=other.name)
        return None


# -- Goal-directed agency ---------------------------------------------------

LONELY_MOUNTAIN = "front_gate"  # the party's ultimate destination
BARREL_STEP = "barrel"          # a way through, but never a step taken alone
GOAL_REPLAN_INTERVAL = 12       # turns a goal holds before it's reconsidered
PARTY_LEASH = 2                # rooms a companion may stray from Bilbo before heading back
HUNGER_FORAGE = 42             # hunger at which an NPC with no food goes foraging
HEAL_SEEK_RANGE = 9            # rooms a badly-hurt NPC will travel to reach a haven
                               # (the Misty Mountains sit 6-9 rooms from any
                               # haven, and were a healing desert at 5)
SCOUT_RANGE = 4                # rooms a scout may range ahead of Bilbo before turning back


class GoalBrain(SimpleBrain):
    """Gives party NPCs actual agency: instead of the random walk, each
    holds a goal (a destination) and pathfinds toward it, so their
    movement matches what they say they want. Combat, capture, and idling
    are inherited unchanged from SimpleBrain. In purist/authentic mode this
    falls back to the original random walk, keeping the 1982 characters as
    aimless as they always were."""

    def _move_step(self, npc: "NPC", game: "Game", loc) -> Command | None:
        if game.authentic:
            return super()._move_step(npc, game, loc)

        # A leader's call for aid trumps everything else: rush toward the
        # nearby fight (dropping the leash on Bilbo -- that's the point).
        aid_room = game.fight_needing_aid(npc)
        if aid_room:
            step = game.world.path_step(npc.location_id, aid_room)
            if step:
                npc.rushing_to_aid = True
                return Command(verb="go", obj=step)
        npc.rushing_to_aid = False

        # Bilbo standing at the barrels calls everyone in -- including the
        # scout, who would otherwise keep ranging and be left behind a barred
        # gate when the company casts off.
        muster = game.mustering_room()
        if muster:
            if npc.location_id == muster:
                # Arrived -- and staying. Falling through from here sent the
                # scout straight back out to range ahead, so Gandalf bounced
                # between the cellars and the dungeon every single turn and the
                # barrels could never cast off: the company was never all
                # present on the turn the player tried. An ordinary companion
                # happens to stay put, because escorting Bilbo means standing
                # where he already is. The scout had somewhere else to be.
                npc.goal_target, npc.goal_desc, npc.goal_kind = (
                    muster, "waiting at the barrels", "escort")
                return None
            step = game.world.path_step(npc.location_id, muster)
            if step:
                npc.goal_target, npc.goal_desc, npc.goal_kind = (
                    muster, "gathering for the barrels", "escort")
                return Command(verb="go", obj=step)

        # Bilbo following THIS companion promotes them to leader of the march:
        # they make for the Mountain (drawing the hobbit and the rest of the
        # company along behind) rather than escorting him or scouting. It's the
        # book's own tension -- guard the burglar, or press on for the gold. An
        # explicit "<name>, follow me" (forced_goal) still overrides, and an
        # ordinary companion in real trouble still breaks off to survive.
        if game.player_follow == npc.id and npc.forced_goal is None:
            if not npc.def_.is_scout:
                dest, desc, kind = self._scripted_goal(npc, game)
                if kind in ("heal", "forage"):
                    npc.goal_target, npc.goal_desc, npc.goal_kind = dest, desc, kind
                    step = game.world.path_step(npc.location_id, dest)
                    return Command(verb="go", obj=step) if step and dest != npc.location_id else None
            npc.goal_target, npc.goal_desc, npc.goal_kind = (
                LONELY_MOUNTAIN, "leading the way toward the Mountain", "lead")
            npc.goal_age = 0
            if npc.location_id == LONELY_MOUNTAIN:
                return None
            step = game.world.path_step(npc.location_id, LONELY_MOUNTAIN)
            return Command(verb="go", obj=step) if step else None

        # A scout has their own rhythm: range ahead, learn the road, come
        # back with news. 'gandalf, follow me' (forced_goal) suspends it.
        # But a scout must eat like anybody else: his loop never consulted the
        # survival goals, so Gandalf ranged on with an empty pack until he
        # starved to death three rooms from Lake-town. Needs come first; the
        # scouting resumes once he is fed and whole.
        if npc.def_.is_scout and npc.forced_goal is None:
            dest, desc, kind = self._scripted_goal(npc, game)
            if kind in ("heal", "forage"):
                npc.goal_target, npc.goal_desc, npc.goal_kind = dest, desc, kind
                npc.goal_age = 0
                if dest != npc.location_id:
                    step = game.world.path_step(npc.location_id, dest)
                    if step:
                        return Command(verb="go", obj=step)
                return None
            return self._scout_step(npc, game)

        # Falling badly hurt or running out of food is urgent news: reconsider
        # at once rather than marching on for up to GOAL_REPLAN_INTERVAL turns
        # on a goal chosen while hale. (It does not make them safer -- a
        # starving dwarf with no food in reach still dies -- it only stops them
        # trudging obliviously past a haven at death's door, which is how
        # Thorin came to grief two rooms from Rivendell.)
        if npc.goal_kind not in ("forage", "heal") and (
                npc.is_badly_hurt()
                or (game.food_count(npc) == 0 and npc.hunger >= HUNGER_FORAGE)):
            self._assign_goal(npc, game)
            npc.goal_age = 0

        # No longer being followed? A former leader falls back into the ranks.
        if npc.goal_kind == "lead":
            self._assign_goal(npc, game)
            npc.goal_age = 0

        # (Re)choose a goal periodically, or when a fixed-destination goal is
        # reached. Escort goals track a moving target (Bilbo), so they don't
        # trigger an "arrived" replan.
        if (npc.goal_kind is None or npc.goal_age >= GOAL_REPLAN_INTERVAL
                or (npc.goal_kind != "escort" and npc.location_id == npc.goal_target)):
            self._assign_goal(npc, game)
            npc.goal_age = 0
        else:
            npc.goal_age += 1

        # Escort goals always head for Bilbo's *current* room.
        target = game.player_beacon() if npc.goal_kind == "escort" else npc.goal_target

        # Leash: the company travels WITH the burglar, so no one strays more
        # than PARTY_LEASH rooms from Bilbo -- beyond that they turn back to
        # him. Foraging and seeking healing are exempt so they can actually
        # reach a settlement.
        if (npc.goal_kind not in ("forage", "heal")
                and game.world.distance(npc.location_id, game.player_beacon()) > PARTY_LEASH):
            target = game.player_beacon()

        if not target or target == npc.location_id:
            return None
        direction = game.world.path_step(npc.location_id, target)
        if direction == BARREL_STEP:
            # The road east runs through the barrels, so routing points here --
            # but the barrels carry whoever is standing in them and the gate
            # shuts behind. A companion who took that step alone would cast off
            # without Bilbo. Arriving is the whole job: wait to be gathered.
            return None
        return Command(verb="go", obj=direction) if direction else None

    def _scout_step(self, npc: "NPC", game: "Game") -> Command | None:
        """The scout's loop: range ahead along the road to the Mountain (up
        to SCOUT_RANGE rooms from Bilbo), peek at danger without walking into
        it, then return to Bilbo to report. Exempt from the party leash."""
        player_room = game.player_beacon()
        npc.scout_ranged = max(npc.scout_ranged,
                               game.world.distance(npc.location_id, player_room))

        if npc.scout_phase == "ranging":
            npc.goal_desc, npc.goal_kind = "scouting the road ahead", "scout"
            if game.world.distance(npc.location_id, player_room) >= SCOUT_RANGE:
                npc.scout_phase = "returning"
            else:
                direction = game.world.path_step(npc.location_id, LONELY_MOUNTAIN)
                if direction is None:
                    npc.scout_phase = "returning"  # road's end: bring word back
                else:
                    ahead = (None if direction == BARREL_STEP
                             else game.world.destination(npc.location_id, direction))
                    if ahead is None:
                        # No further road a scout may walk (the barrels are
                        # not a thing to scout through) -- take word back.
                        npc.scout_phase = "returning"
                        return None
                    if game.room_has_live_monsters(ahead):
                        # Peek from cover rather than blundering in; that
                        # sighting alone is worth carrying back.
                        game.scout_observe(npc, ahead)
                        npc.scout_phase = "returning"
                    else:
                        return Command(verb="go", obj=direction)

        # returning (possibly just switched)
        npc.goal_desc, npc.goal_kind = "returning to Bilbo with news", "scout"
        if npc.location_id == player_room:
            npc.scout_phase = "ranging"  # report is delivered by the game loop
            return None
        direction = game.world.path_step(npc.location_id, player_room)
        return Command(verb="go", obj=direction) if direction else None

    def _assign_goal(self, npc: "NPC", game: "Game") -> None:
        npc.goal_target, npc.goal_desc, npc.goal_kind = self._scripted_goal(npc, game)

    def _scripted_goal(self, npc: "NPC", game: "Game") -> tuple[str, str, str]:
        """The rule-based floor: everyone travels with Bilbo, breaking off
        only to forage (empty pack) or to seek healing at a nearby haven
        when badly hurt."""
        if npc.forced_goal == "guard_bilbo":
            return game.player_beacon(), "keeping close to Bilbo", "escort"
        # Bilbo standing at the barrels calls everyone in: a way out that takes
        # only those present outranks every errand, and the larder is right
        # there, so a hungry dwarf can eat when he arrives rather than wander
        # off for food and be left behind a barred gate.
        muster = game.mustering_room()
        if muster and npc.location_id != muster:
            return muster, "gathering for the barrels", "escort"
        # Badly wounded and a haven is close by -- make for it to be mended,
        # unless the company is already resting at one.
        if npc.is_badly_hurt() and not game.world.get(npc.location_id).food_source:
            haven = game.world.nearest_food_source(npc.location_id)
            if haven and game.world.distance(npc.location_id, haven) <= HEAL_SEEK_RANGE:
                return haven, "seeking healing at a safe haven", "heal"
        if game.food_count(npc) == 0 and npc.hunger >= HUNGER_FORAGE:
            source = game.world.nearest_food_source(npc.location_id)
            if source:
                return source, "going in search of food", "forage"
        return game.player_beacon(), "travelling with Bilbo", "escort"


# Intent keywords the LLM may choose from, resolved to a concrete target.
_GOAL_INTENTS = ("ADVANCE", "FOLLOW_THORIN", "GUARD_BILBO", "REST", "EXPLORE")


class LLMGoalBrain(GoalBrain):
    """When a model is available (and not in purist mode), the LLM chooses
    each character's goal from the situation -- so a companion might press
    on, hang back to guard Bilbo, rest when spent, or wander off on a whim.
    Rule-based pathfinding then pursues whatever it picked, so the model is
    only consulted occasionally (goal changes), not every step. Always
    falls back to the scripted goal."""

    def _assign_goal(self, npc: "NPC", game: "Game") -> None:
        if (not game.authentic and getattr(game, "llm", None) is not None
                and npc.forced_goal is None and game.take_goal_budget()):
            goal = self._llm_goal(npc, game)
            if goal:
                npc.goal_target, npc.goal_desc, npc.goal_kind = goal
                return
        super()._assign_goal(npc, game)

    def _llm_goal(self, npc: "NPC", game: "Game"):
        # Every option stays within the leash (see _move_step), so the LLM
        # adds flavour to how a companion moves without ever wandering off.
        targets = {
            "ADVANCE": (LONELY_MOUNTAIN, "eager to press on toward the Mountain", "roam"),
            "FOLLOW_THORIN": (game.player_beacon(), "keeping with the company", "escort"),
            "GUARD_BILBO": (game.player_beacon(), "keeping close to Bilbo", "escort"),
            "REST": (npc.location_id, "resting a while", "rest"),
        }
        loc = game.world.get(npc.location_id)
        exits = list(loc.exits.values())
        if exits:
            targets["EXPLORE"] = (game.rng.choice(exits), "scouting nearby", "roam")

        system = ("You decide the immediate goal of a character in a Tolkien-inspired "
                  "text adventure. Reply with EXACTLY ONE of these keywords and nothing "
                  "else: " + ", ".join(_GOAL_INTENTS) + ".")
        user = (f"You are {_persona(npc)}. {_scene(npc, game)} "
                "What is your immediate goal right now? One keyword only.")
        # A goal is one keyword -- "ADVANCE" -- so the model's eloquence is
        # irrelevant here, and three quarters of all model calls in a run are
        # this. Use the cheap fast client when one is configured and keep the
        # good model for the lines a player actually reads.
        client = getattr(game, "llm_fast", None) or getattr(game, "llm", None)
        reply = _safe_chat(client, system, user)
        if not reply:
            return None
        upper = reply.upper()
        for key in _GOAL_INTENTS:
            if key in upper and key in targets:
                return targets[key]
        return None


# -- LLM-driven personality (hybrid) ----------------------------------------

def _persona(npc: "NPC") -> str:
    return npc.def_.persona or (
        f"{npc.name}, one of Thorin Oakenshield's company of dwarves on the quest "
        "to reclaim the Lonely Mountain")


def _scene(npc: "NPC", game: "Game") -> str:
    loc = game.world.get(npc.location_id)
    present = [game.characters[n].name for n in loc.npcs
               if n != npc.id and game.characters[n].alive]
    if game.player.location_id == loc.id and game.player.alive:
        present.append("Bilbo the hobbit")
    parts = [f"You are at: {loc.name}."]
    if present:
        parts.append("Also here: " + ", ".join(present) + ".")
    condition = []
    if npc.is_fainted():
        condition.append("fainting from hunger and exhaustion")
    elif npc.is_weak():
        condition.append("weak and hungry")
    if npc.is_badly_hurt():
        condition.append("badly hurt")
    elif npc.health < max(1, npc.max_health // 2):
        condition.append("wounded")
    if condition:
        parts.append("You are " + " and ".join(condition) + ".")
    recent = list(getattr(game, "recent_events", []) or [])[-3:]
    if recent:
        parts.append("Just now: " + " ".join(recent))
    learned = getattr(npc, "scout_memory", None)
    if learned:
        parts.append("From scouting ahead you know: " + "; ".join(learned[-4:]) + ".")
    lore = getattr(game, "company_lore", None)
    if lore:
        parts.append("The whole company knows: " + "; ".join(lore[-4:]) + ".")
    return " ".join(parts)


def _action_phrase(game: "Game", action: Command, outcome: str | None = None) -> str:
    if action.verb == "attack":
        if outcome == "kill":
            return f"striking down {action.obj} with a killing blow"
        if outcome == "hit":
            return f"landing a solid blow on {action.obj} -- who still stands and fights on"
        return f"trading blows with {action.obj}"
    if action.verb == "go":
        return f"heading {action.obj}"
    return action.verb


# Appended to every dialogue/narration prompt to keep the model inside the
# knowledge of The Hobbit (1937) and out of later-revealed Lord of the Rings
# lore.
_LORE_GUARD = (
    " Stay strictly within the world and knowledge of Tolkien's The Hobbit. In "
    "this age the dark power is known ONLY as 'the Necromancer' -- never say the "
    "name 'Sauron'. Treat Bilbo's ring as merely a magic ring of invisibility, "
    "never as the One Ring, and do not reference people, places, or events from "
    "The Lord of the Rings or later ages. Take the characters only as their "
    "briefs describe them: invent no ages, sizes or infirmities for anyone, and "
    "draw nothing from film portrayals. Fili and Kili are the youngest of the "
    "company; none of the dwarves is a child.")

# Deterministic safety net for the anachronism players are most likely to
# notice, in case the prompt guard slips.
_SAURON_RE = re.compile(r"\bSauron(['’]s)?\b", re.IGNORECASE)


def _scrub_lore(text: str) -> str:
    return _SAURON_RE.sub(
        lambda m: "the Necromancer's" if m.group(1) else "the Necromancer", text)


def _safe_chat(client, system: str, user: str) -> str | None:
    """Call the client, swallowing any failure. LLMClient.chat already
    isolates errors, but this guards against a misbehaving client too, so a
    bad model integration can never crash or hang the game loop."""
    try:
        return client.chat(system, user)
    except Exception:
        return None


# Honorifics whose trailing period must not be mistaken for a sentence end
# ("We have much to do, Mr. Baggins" is one sentence, not two).
_ABBREV_RE = re.compile(r"\b(Mr|Mrs|Ms|Dr|St)\.")
_ABBREV_MARK = "\x00"
# How much a companion may say in one breath, in characters. Roughly two
# full lines of prose: long enough that punchy dialogue survives whole,
# short enough that nobody delivers a monologue mid-fight.
REPLY_BUDGET = 220


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    text = " ".join(text.split()).strip()
    # A token-limit cut can lose a closing quote; balance it so the speech
    # inside can still be recovered.
    if text.count('"') % 2 == 1:
        text += '"'
    # If the model mixed narration with quoted speech ('Thorin frowned.
    # "We march at dawn."'), keep only the spoken words.
    quoted = re.findall(r'"([^"]+)"', text)
    if quoted and re.sub(r'"[^"]*"', "", text).strip():
        text = " ".join(q.strip() for q in quoted)
    text = text.strip('"').strip("'").strip()
    # Drop a leading "Name:" the model sometimes adds.
    if ":" in text[:24]:
        head, _, rest = text.partition(":")
        if len(head.split()) <= 3 and rest.strip():
            text = rest.strip()
    text = _scrub_lore(text)
    # Asterisks mean two different things, and deleting both broke sentences.
    # A multi-word span is stage direction ("*chuckles and claps Bilbo on the
    # back*") and goes. A single word is emphasis on a stressed word
    # ("nothing's ever *safe*, laddie") -- deleting that left "nothing's ever
    # , laddie", so unwrap it and keep the word.
    text = re.sub(r"\*([^*\s]+)\*", r"\1", text)
    text = re.sub(r"\*[^*]*\*", "", text).strip()
    # Keep it short -- but by length, not by counting sentences. A flat cap of
    # two sentences was tuned against a small local model that rambled in long
    # ones. A stronger model writes dialogue the way people speak it, in short
    # bursts, and the cap then amputated the reply: "Safe? Ha! But don't you
    # fret, you've fourteen dwarves to watch your back" came out as "Safe? Ha!"
    # Take whole sentences up to a budget instead, so two long ones are still
    # trimmed and five short ones survive intact.
    protected = _ABBREV_RE.sub(lambda m: m.group(1) + _ABBREV_MARK, text)
    sentences = re.findall(r"[^.!?]*[.!?]", protected)
    if sentences:
        kept: list[str] = []
        for sentence in sentences:
            # Always keep the first, or the reply could vanish entirely.
            if kept and sum(len(s) for s in kept) + len(sentence) > REPLY_BUDGET:
                break
            kept.append(sentence)
        protected = "".join(kept).strip()
    elif protected and protected[-1] not in ".!?":
        # No complete sentence at all (cut mid-thought): trail off cleanly.
        if len(protected) > 200:
            protected = protected[:200].rsplit(" ", 1)[0]
        protected += "..."
    text = protected.replace(_ABBREV_MARK, ".")
    return " ".join(text.split()) or None


class LLMBrain(NPCBrain):
    """Hybrid brain: mechanical actions still come from a rule-based base
    brain (fast, deterministic, always works), while the language model
    adds personality -- in-character dialogue when spoken to and occasional
    narration of what the NPC does. Every LLM call falls back to the base
    behavior if the model is slow, down, or absent, so the game never
    breaks. Swapping this in is the whole point of the NPCBrain interface."""

    def __init__(self, base: NPCBrain):
        self.base = base

    def decide(self, npc: "NPC", game: "Game") -> Command | None:
        return self.base.decide(npc, game)

    def speak(self, npc: "NPC", game: "Game", player_line: str | None = None) -> str | None:
        client = getattr(game, "llm", None)
        if client is None or game.authentic:  # purist -> original static dialogue
            return None
        system = (
            f"You are {_persona(npc)}. You are a character in a Tolkien-inspired "
            "text adventure. Bilbo Baggins the hobbit is speaking WITH YOU right now, "
            "so address your reply TO Bilbo (not to Thorin or the others, though you "
            "may mention them). Reply with ONE or TWO short spoken sentences. Be "
            "SPECIFIC and grounded: react to exactly where you are and what has just "
            "happened, and if you can, say something useful -- a concrete observation, "
            "a suggestion of what to do next, a warning, or a plan. Do NOT give vague, "
            "generic encouragement (no 'the road is perilous but have courage', no "
            "speeches about honour and glory). Vary what you say; never repeat a line "
            "you have already given. No narration, no asterisks, no quotation marks, "
            "no mention of being an AI or a game." + _LORE_GUARD)
        if player_line:
            user = f'{_scene(npc, game)} Bilbo says to you: "{player_line}". Reply to Bilbo in character.'
        else:
            user = (f"{_scene(npc, game)} Bilbo has come up to speak with you. Say "
                    "something fresh and specific to Bilbo, fitting this exact moment.")
        return _clean(_safe_chat(client, system, user))

    def narrate(self, npc: "NPC", game: "Game", action: Command,
                outcome: str | None = None) -> str | None:
        client = getattr(game, "llm", None)
        if client is None or game.authentic:  # no added flourish in purist mode
            return None
        system = (
            "You narrate a Tolkien-inspired text adventure. Given a character and "
            "what they do, write ONE vivid short sentence, third person, present "
            "tense, in the terse style of a classic text adventure. Describe ONLY "
            "the exact outcome given -- never invent a death, victory, or wound "
            "that was not stated (if the blow does not kill, the foe is still up). "
            "No quotation marks." + _LORE_GUARD)
        user = f"{_scene(npc, game)} Narrate {npc.name} {_action_phrase(game, action, outcome)}."
        return _clean(_safe_chat(client, system, user))

    def remark(self, npc: "NPC", game: "Game") -> str | None:
        client = getattr(game, "llm", None)
        if client is None or game.authentic:
            return None
        system = (
            f"You are {_persona(npc)}. You are travelling with the company in a "
            "Tolkien-inspired text adventure. Speak up now with ONE short in-character "
            "line to those around you -- a remark, a grumble, a bit of banter, or an "
            "observation that fits the moment (where you are, how you feel, what just "
            "happened). No narration, no asterisks, no quotation marks, and never "
            "mention being an AI or a game." + _LORE_GUARD)
        user = f"{_scene(npc, game)} What do you say aloud, unprompted, right now?"
        return _clean(_safe_chat(client, system, user))


class NPC(Character):
    def __init__(self, npc_def: NPCDef, brain: NPCBrain):
        super().__init__(npc_def.id, npc_def.name, npc_def.start_location,
                          health=npc_def.health, attack=npc_def.attack,
                          aliases=npc_def.aliases)
        self.def_ = npc_def
        self.brain = brain
        self.inventory = list(npc_def.inventory)
        self.max_carry = npc_def.max_carry
        # Only the travelling company must eat and rest. Monsters don't hunger
        # (a dragon shouldn't starve waiting for you), and neither do the folk
        # who live where they stand: Elrond and the Elvenking's guard have their
        # own larders, but nothing in the game feeds them, so they starved to
        # death at home -- Elrond amid his own feast.
        self.feels_needs = npc_def.is_party
        self.captured = False
        # Goal-directed movement state (used by GoalBrain/LLMGoalBrain).
        self.goal_target: str | None = None
        self.goal_desc: str = ""
        self.goal_kind: str | None = None  # escort / forage / roam / rest
        # Stagger replans across NPCs so they don't all consult the LLM the
        # same turn (a stable per-character offset).
        self.goal_age: int = sum(ord(c) for c in npc_def.id) % GOAL_REPLAN_INTERVAL
        # Set by "<name>, follow me" -- overrides goal-picking to stay with Bilbo.
        self.forced_goal: str | None = None
        # Combat coordination: which foe this fighter is currently set on (so
        # the company spreads across several monsters and sticks to a target
        # rather than reshuffling each round), whether they're presently
        # rushing to a leader's call for aid, and an unspoken boast about a
        # fight just won, surfaced when they're back beside Bilbo.
        self.combat_target: str | None = None
        self.rushing_to_aid: bool = False
        self.pending_warcry: str | None = None
        # Scout state (used when def_.is_scout): ranging/returning cycle,
        # what has been learned, what hasn't been told to Bilbo yet, and a
        # dedupe set so the same discovery isn't reported twice.
        self.scout_phase: str = "ranging"
        self.scout_memory: list[str] = []
        self.scout_unreported: list[str] = []
        self.scout_seen: set[str] = set()
        # Furthest the scout has got from Bilbo since his last report -- lets
        # the report honestly say whether he ranged off or just glanced from
        # the roadside while marching with the company.
        self.scout_ranged: int = 0

    def decide(self, game: "Game") -> Command | None:
        return self.brain.decide(self, game)

    def remark(self, game: "Game") -> str | None:
        return self.brain.remark(self, game)

    def speak(self, game: "Game", player_line: str | None = None) -> str | None:
        return self.brain.speak(self, game, player_line)

    def narrate(self, game: "Game", action: Command,
                outcome: str | None = None) -> str | None:
        return self.brain.narrate(self, game, action, outcome)


def build_npc(npc_id: str, data: dict[str, Any], ai: bool = False) -> NPC:
    npc_def = NPCDef(npc_id, data)
    if npc_def.is_monster:
        brain: NPCBrain = MonsterBrain()
    elif ai:
        # LLM chooses goals (movement) AND supplies dialogue/narration.
        brain = LLMBrain(LLMGoalBrain())
    else:
        # Scripted goals still give purposeful movement without any model.
        brain = GoalBrain()
    return NPC(npc_def, brain)
