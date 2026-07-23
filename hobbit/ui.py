"""Terminal presentation helpers.

Some things in this recreation are not in the 1982 original -- the scenery
examine system, a few parser conveniences (command chaining, direct NPC
addressing), the companions' voices. Early builds tinted every such addition
cyan so you could tell new from old at a glance.

That marking is gone. The enhanced game is so thoroughly reworked that nearly
every line is "modern", and colouring almost all of it told you nothing. A
player who wants the unimproved article plays the purist game, which *is* the
1982 design rather than a running annotation of it.

`Note`, `mark()` and `item_display_name()` survive as plain semantic seams --
in the code they still say "this is added content", they just no longer change
how it looks.

There are two games, settled when one starts (see commands.py / game.py):

  purist    -- reverted prose and the original's quirky, sometimes unwinnable
               mechanics.
  standard  -- the enhanced game (the default).
"""
from __future__ import annotations

import os

LEVELS = ("purist", "standard")
DEFAULT_LEVEL = "standard"


def enable_ansi_on_windows() -> None:
    if os.name == "nt":
        os.system("")  # harmless no-op that flips the console into ANSI mode


def note_line(text: str) -> str:
    """A one-off system/meta line (e.g. the AI-enabled notice). Once cyan, now
    plain -- kept as a named seam so its call sites read clearly."""
    return text


class Note(str):
    """A message that is a modern addition rather than 1982 original. Once
    rendered in cyan; now indistinguishable in output, kept as a code-level
    marker of provenance."""
    __slots__ = ()


def mark(text: str) -> str:
    """Once wrapped a span (an item's name, an exit tag) so just that part of a
    line could be tinted. The tinting is gone, so this is now identity -- kept
    so its call sites, which record *what* was added, don't all have to
    change."""
    return text


def item_display_name(item) -> str:
    """An item's name for use inside an ordinary sentence. Plain now -- added
    items are no longer tinted -- but kept as the one place item names are
    formatted for prose."""
    return item.name


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
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
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
    """A describe_location() result shown as the auto-look after a move. The
    room title was once tinted to mark the auto-look as a modern convenience;
    now it reads just as an ordinary look would."""
    return list(described)


def present(messages: list[str], level: str = DEFAULT_LEVEL) -> list[str]:
    """Render a batch of game messages for display.

    Its one remaining job is to capitalise the opening letter of each line --
    several characters are named in lower case on purpose ('goblin scout',
    'wood-elf guard'), which reads right mid-line but not at the start of one,
    and doing it here saves remembering it at every message. `level` is still
    accepted so callers need not change, but no longer alters the output: the
    cyan marking of additions was removed."""
    return [sentence(m) if isinstance(m, str) else m for m in messages]
