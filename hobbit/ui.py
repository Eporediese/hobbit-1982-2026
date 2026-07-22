"""Terminal presentation helpers.

Some things in this recreation are not in the 1982 original -- the scenery
examine system, and a few parser conveniences (command chaining, direct
NPC addressing). Those messages are wrapped in Note().

There are two ways to see the game, settled when it starts (see commands.py):

  purist    -- no colour, no meta-commentary. Note text still appears (it's
               real game content, just newly written) but unflagged.
  standard  -- the default. Note text is coloured cyan, so you can always
               tell a modern addition from 1982.

There used to be a third, 'verbose', which annotated in amber exactly which
defect each fix addressed. It was dropped: keeping that commentary accurate
meant re-documenting the whole game every time it changed, and a player who
wants the unimproved article can simply play purist, which *is* the original
design rather than a description of it.
"""
from __future__ import annotations

import os

RESET = "\033[0m"
ADDITION_COLOR = "\033[96m"  # bright cyan

LEVELS = ("purist", "standard")
DEFAULT_LEVEL = "standard"


def enable_ansi_on_windows() -> None:
    if os.name == "nt":
        os.system("")  # harmless no-op that flips the console into ANSI mode


def note_line(text: str) -> str:
    """Cyan-wrap a one-off system/meta line (e.g. the AI-enabled notice)."""
    return f"{ADDITION_COLOR}{text}{RESET}"


class Note(str):
    """A message flagged as a modern addition, not part of the 1982 original."""
    __slots__ = ()


# Sentinel control characters marking an added-feature *span* inside an
# otherwise ordinary line, e.g. just an item's name inside "You are
# carrying: old map, torch." -- unlikely to ever appear in real game text.
_MARK_START = "\x01"
_MARK_END = "\x02"


def mark(text: str) -> str:
    """Wrap a substring of a larger message (an item's name, typically) so
    'present' can color just that span, without tagging the whole line as
    a Note. Use this when a message mixes ordinary and added content --
    e.g. an inventory listing where only one item is new."""
    return f"{_MARK_START}{text}{_MARK_END}"


def item_display_name(item) -> str:
    """An item's name for use inside an ordinary sentence ('You take the
    X.', 'You see: X, Y.') -- marked so it colors as an added feature
    wherever it appears, if the item itself is one."""
    return mark(item.name) if item.added else item.name


def join_names(names: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
                 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def tally_names(names: list[str]) -> str:
    """Render a list of things as prose, counting repeats and giving each its
    article: 'the goblin scout', 'two wargs', 'Tom the troll and the warg'."""
    counts: dict[str, int] = {}
    for name in names:  # dicts keep insertion order, so the prose does too
        counts[name] = counts.get(name, 0) + 1
    parts = []
    for name, n in counts.items():
        if n == 1:
            parts.append(with_article(name))
        else:
            plural = name if name.endswith("s") else f"{name}s"
            parts.append(f"{_NUMBER_WORDS.get(n, str(n))} {plural}")
    return join_names(parts)


def sentence(text: str) -> str:
    """Capitalise the opening letter. Names like 'the Great Goblin' and
    'goblin scout' are lowercase by design mid-sentence, but must not start
    one ('the Great Goblin has been defeated!')."""
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\033":  # step over an ANSI colour escape, not into it
            end = text.find("m", i)
            i = len(text) if end == -1 else end + 1
            continue
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
        i += 1
    return text


def an(name: str) -> str:
    """'a loaf of bread', but 'an elven cake' -- and no article at all for a
    proper name."""
    if name[:1].isupper() or name.lower().startswith("the "):
        return name
    return f"{'an' if name[:1].lower() in 'aeiou' else 'a'} {name}"


def with_article(name: str) -> str:
    """Prefix an article, unless the name doesn't want one: it already carries
    its own ("the Arkenstone" must not become "the the Arkenstone"), or it's a
    proper name and takes none at all -- you wield Sting, not "the Sting"."""
    if name.lower().startswith("the ") or name[:1].isupper():
        return name
    return f"the {name}"


def autolook_lines(described: list[str]) -> list[str]:
    """Turn a describe_location() result into an auto-look shown after a
    move: only the room title (== Name ==) is coloured, marking it as the
    modern auto-look; the description, occupants, items, and exits stay in
    normal formatting."""
    out: list[str] = []
    for line in described:
        rows = line.split("\n")
        if rows and rows[0].startswith("=="):
            rows[0] = f"{ADDITION_COLOR}{rows[0]}{RESET}"
        # Returned as a plain string so present() still colours inline item
        # marks in the body; the title's colour is embedded literally.
        out.append("\n".join(rows))
    return out


def _apply_inline_marks(message: str, level: str) -> str:
    if _MARK_START not in message:
        return message
    if level == "purist":
        return message.replace(_MARK_START, "").replace(_MARK_END, "")
    return message.replace(_MARK_START, ADDITION_COLOR).replace(_MARK_END, RESET)


def present(messages: list[str], level: str = DEFAULT_LEVEL) -> list[str]:
    """Colour a batch of messages for the game being played. Note lines (and
    inline mark() spans) are always kept -- they're real content -- coloured
    at 'standard' and left plain at 'purist'."""
    out: list[str] = []
    for message in messages:
        # Several characters are named in lower case on purpose ("wood-elf
        # guard", "giant spider", "goblin scout"), which reads correctly in the
        # middle of a line but not at the start of one. Capitalising here, at
        # the one place everything is rendered, saves remembering it at every
        # message that happens to begin with a name.
        message = sentence(message) if type(message) is str else message
        if isinstance(message, Note):
            text = sentence(str(message))
            out.append(f"{ADDITION_COLOR}{text}{RESET}"
                       if level != "purist" else text)
            continue
        out.append(_apply_inline_marks(message, level))
    return out
