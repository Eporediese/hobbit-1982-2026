"""Command-line parser: turns raw player input into a list of Command
objects. Supports multi-word verbs ("talk to", "pick up"), multi-step
input ("take sword and go north then attack troll"), and addressing an
NPC directly ("thorin, attack the goblin")."""
from __future__ import annotations

from dataclasses import dataclass, field

STOPWORDS = {"the", "a", "an", "at", "my", "please"}

# Commands that just report or manage things -- they cost no game time, so
# checking your status doesn't make the whole company hungrier.
FREE_VERBS = {"look", "examine", "inventory", "status", "party", "help",
              "mode", "purist", "save", "load", "quit"}

# Verbs this recreation added that have no 1982 equivalent: the party/roster and
# status read-outs, the rations system, the follow/march helper, and the
# draw-and-sheathe combat prep. In the purist game these words are not in the
# vocabulary at all -- typing one gets the same "I don't know how" a 1982 player
# would have got, rather than a modern feature the purist game claims not to
# have. (The recreation-meta verbs 'mode'/'purist' and the program utilities
# save/load/quit/help stay: they operate the program, not the 1937 world.)
ADDED_VERBS = {"party", "status", "stock", "follow", "unfollow", "sheathe"}

DIRECTION_WORDS = {
    "north": "north", "n": "north",
    "south": "south", "s": "south",
    "east": "east", "e": "east",
    "west": "west", "w": "west",
    "up": "up", "u": "up",
    "down": "down", "d": "down",
    "northeast": "northeast", "ne": "northeast",
    "northwest": "northwest", "nw": "northwest",
    "southeast": "southeast", "se": "southeast",
    "southwest": "southwest", "sw": "southwest",
}

# canonical verb -> synonyms (each synonym may be multiple words)
VERB_SYNONYMS: dict[str, list[str]] = {
    "go": ["go", "walk", "move", "travel", "head"],
    "take": ["take", "get", "grab", "pick up", "pickup"],
    "drop": ["drop", "put down", "discard", "leave"],
    "attack": ["attack", "kill", "hit", "fight", "strike"],
    "give": ["give", "hand", "offer"],
    "open": ["open", "unlock"],
    "close": ["close", "shut", "lock"],
    "talk": ["talk to", "speak to", "speak with", "chat with", "talk"],
    "look": ["look", "l"],
    "examine": ["examine", "look at", "inspect", "x"],
    "inventory": ["inventory", "inv", "i"],
    "eat": ["eat", "consume"],
    "wear": ["wear", "put on", "don"],
    "wield": ["wield", "hold", "equip", "draw", "take up"],
    "sheathe": ["sheathe", "sheath", "put away", "unwield", "put up"],
    "remove": ["remove", "unwear", "take off"],
    "light": ["light"],
    "rest": ["rest", "sleep"],
    # Waiting is not resting: it lets the world move on while you keep pace
    # with whoever you're following. Settling down to rest breaks the march.
    "wait": ["wait", "z"],
    "barrel": ["barrel", "barrels", "ride the barrels", "ride barrel",
               "get in a barrel", "get in barrel", "enter barrel", "board barrel"],
    "save": ["save"],
    "load": ["load", "restore"],
    "quit": ["quit", "exit"],
    "help": ["help", "?"],
    "follow": ["follow"],
    "unfollow": ["unfollow", "stop following", "stop follow", "stop"],
    "purist": ["purist"],
    "mode": ["mode"],
    "status": ["status", "health", "condition"],
    "party": ["party", "company", "companions"],
    "stock": ["stock up", "stock", "provision", "provisions", "restock", "gather food"],
}

# Sorted longest-phrase-first so multi-word synonyms match before single words.
_SYNONYM_LOOKUP: list[tuple[str, str]] = sorted(
    ((phrase, canon) for canon, phrases in VERB_SYNONYMS.items() for phrase in phrases),
    key=lambda pair: -len(pair[0].split()),
)

STEP_SEPARATORS = [" then ", " and then ", ". ", "; ", " and "]


@dataclass
class Command:
    verb: str
    obj: str | None = None
    indirect: str | None = None
    actor_override: str | None = None  # NPC name/id being addressed, or None for the player
    raw: str = ""
    unknown: bool = False
    error: str | None = None


def _split_steps(text: str) -> list[str]:
    text = text.strip().rstrip(".")
    parts = [text]
    for sep in STEP_SEPARATORS:
        new_parts: list[str] = []
        for part in parts:
            new_parts.extend(part.split(sep))
        parts = new_parts
    return [p.strip() for p in parts if p.strip()]


def _strip_stopwords(words: list[str]) -> list[str]:
    return [w for w in words if w not in STOPWORDS]


def _match_verb(words: list[str]) -> tuple[str | None, list[str]]:
    """Return (canonical_verb, remaining_words) matching the longest known
    synonym phrase at the start of words."""
    text = " ".join(words)
    for phrase, canon in _SYNONYM_LOOKUP:
        if text == phrase or text.startswith(phrase + " "):
            remainder = text[len(phrase):].strip()
            return canon, (remainder.split() if remainder else [])
    return None, words


class Parser:
    def __init__(self, npc_names: dict[str, str] | None = None):
        # maps lowercase name/alias -> npc id, used to detect "thorin, ..." addressing
        self.npc_names = npc_names or {}

    def parse_line(self, text: str) -> list[Command]:
        text = text.strip().lower()
        if not text:
            return []

        actor_override = None
        if "," in text:
            head, _, rest = text.partition(",")
            head = head.strip()
            if head in self.npc_names:
                actor_override = self.npc_names[head]
                text = rest.strip()

        commands: list[Command] = []
        for step in _split_steps(text):
            cmd = self._parse_step(step)
            cmd.actor_override = actor_override
            commands.append(cmd)
        return commands

    def _parse_step(self, step: str) -> Command:
        raw = step
        words = _strip_stopwords(step.split())
        if not words:
            return Command(verb="", raw=raw, unknown=True, error="I didn't understand that.")

        # bare direction, e.g. "north" or "n"
        if len(words) == 1 and words[0] in DIRECTION_WORDS:
            return Command(verb="go", obj=DIRECTION_WORDS[words[0]], raw=raw)

        canon, remainder = _match_verb(words)
        if canon is None:
            return Command(verb="", raw=raw, unknown=True,
                            error=f"I don't know how to '{raw}'.")

        if canon == "go":
            if remainder and remainder[0] in DIRECTION_WORDS:
                return Command(verb="go", obj=DIRECTION_WORDS[remainder[0]], raw=raw)
            return Command(verb="go", obj=" ".join(remainder) or None, raw=raw)

        if canon == "give":
            # "give sword to thorin" -> obj=sword, indirect=thorin
            rem_text = " ".join(remainder)
            if " to " in rem_text:
                obj, _, indirect = rem_text.partition(" to ")
                return Command(verb="give", obj=obj.strip() or None,
                                indirect=indirect.strip() or None, raw=raw)
            return Command(verb="give", obj=rem_text or None, raw=raw)

        if canon in ("inventory", "look", "quit", "help", "save", "load", "rest", "wait"):
            return Command(verb=canon, obj=" ".join(remainder) or None, raw=raw)

        return Command(verb=canon, obj=" ".join(remainder) or None, raw=raw)
