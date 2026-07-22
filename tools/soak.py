#!/usr/bin/env python3
"""Play many paths through the game and report anything that looks wrong.

One human can play one path. This plays hundreds, with a plausible-but-varied
player, and checks after every turn for the things a human would notice only
if they happened to be looking: prose that reads badly, state that has gone
impossible, journeys that have quietly stopped being winnable.

Deliberately runs with no model. The AI layer adds dialogue on top of the same
mechanics, so a scripted run exercises the machinery a hundred times faster,
for nothing, and repeatably. Prose from the model is checked separately.

    python tools/soak.py                 # 40 seeds, 400 turns each
    python tools/soak.py --seeds 200     # a longer soak
    python tools/soak.py --seed 17 -v    # replay one path, verbosely
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hobbit.game import Game  # noqa: E402
from hobbit import ui  # noqa: E402

DIRECTIONS = ["north", "south", "east", "west", "up", "down"]


# -- what a plausible player does ------------------------------------------

# Things a competent player picks up when they see them, and what they are
# for. The bot detours for these the way a player does once Gandalf has
# mentioned them -- without them the back half of the game is unreachable.
ERRANDS = [
    ("moon_key", "rivendell_library"),        # opens the Secret Door, a world away
    ("ring", "gollum_lake_shore"),            # gets you past the wood-elf guard
    ("elven_cellar_key", "elvenking_halls"),  # in the hall the guard keeps
]
FINALE = "treasure_chamber"
KEEP = ("key", "light", "weapon")        # item types always worth carrying


def choose_command(game: Game, rng: random.Random) -> str:
    """A player who is trying to finish the game and stay alive."""
    player = game.player
    loc = game.world.get(player.location_id)

    # Stay alive first.
    if player.is_fainted() or player.hunger > 50:
        if game.carried_food(player):
            return "eat"
        if loc.food_source and game.free_capacity(player) > 0:
            return "stock up"
    if player.fatigue > 55:
        return "rest"
    # Light up before stepping into the dark, not after -- you cannot enter a
    # dark room to discover you needed a light.
    going_dark = any(game.world.get(d).dark for d in loc.exits.values())
    if ((loc.dark or going_dark) and player.light_remaining <= 0
            and any(game.items.get(i).is_light_source for i in player.inventory)):
        return "light torch"

    # Draw the best blade you have before swinging at anything.
    best = None
    for item_id in player.inventory:
        item = game.items.get(item_id)
        if item.is_weapon and (best is None or item.damage > best[1]):
            best = (item_id, item.damage)
    if best and player.wielded != best[0]:
        return f"wield {game.items.get(best[0]).name}"

    monsters = [c for c in game.characters.values()
                if c.alive and c.location_id == loc.id
                and getattr(c, "def_", None) and c.def_.is_monster
                and not getattr(c, "captured", False)]
    if monsters and game.can_fight_here(loc.id):
        return f"attack {monsters[0].name}"

    # Only if there is room -- otherwise a pack full of gear means "stock up"
    # can never reach its target and the bot stands at the inn for ever.
    if (loc.food_source and len(game.carried_food(player)) < 6
            and game.free_capacity(player) > 0):
        return "stock up"

    # Pick up what is worth having: keys, lights, treasure, the ring -- and a
    # blade only if it beats the one in hand. Hoarding every sword filled the
    # pack, left no room for food, and starved Bilbo on the last leg.
    held = game.items.get(player.wielded).damage if player.wielded else 0
    for item_id in list(loc.items):
        item = game.items.get(item_id)
        if not item.takeable:
            continue
        if item.is_weapon and item.damage <= held:
            continue
        if item.type in KEEP or item.value > 0:
            return f"take {item.name}"

    # A guard turns back anyone he can see; the ring is the answer.
    if "ring" in player.inventory and "ring" not in player.worn:
        if any(game.guard_at(dest) is not None for dest in loc.exits.values()):
            return "wear ring"

    # A locked door you hold the key to is a door you open.
    for direction, dest in loc.exits.items():
        room = game.world.get(dest)
        if room.locked and room.key_item and room.key_item in player.inventory:
            return "open door"

    # The barrels leave when the company is aboard, and not before.
    if loc.barrel_route:
        here = sum(1 for c in game.characters.values()
                   if getattr(c, "def_", None) and c.def_.is_party
                   and c.alive and not c.captured and c.location_id == loc.id)
        alive = sum(1 for c in game.characters.values()
                    if getattr(c, "def_", None) and c.def_.is_party and c.alive
                    and not c.captured)
        if here >= alive or rng.random() < 0.15:   # or give up waiting
            return "barrel"
        return "wait"

    # Errands first, then the Mountain.
    target = FINALE
    for item_id, where in ERRANDS:
        if item_id not in player.inventory and where in game.world.locations:
            target = where
            break
    # Don't outrun the company: a player notices when the dwarves fall behind.
    behind = [c for c in game.characters.values()
              if getattr(c, "def_", None) and c.def_.is_party and c.alive
              and not c.captured
              and game.world.distance(c.location_id, loc.id) > 2]
    if len(behind) > 6 and rng.random() < 0.7:
        return "wait"

    if rng.random() < 0.9:
        step = game.world.path_step(loc.id, target)
        if step and step != "barrel":
            return step
    exits = list(loc.exits)
    return rng.choice(exits) if exits else "look"


# -- what counts as wrong ---------------------------------------------------

_BAD_PROSE = [
    (re.compile(r"\ba (?=[aeiou])", re.I), "'a' before a vowel"),
    (re.compile(r"\bthe the\b|\ba a\b|\bof of\b", re.I), "doubled word"),
    (re.compile(r"\bNone\b"), "literal None in output"),
    (re.compile(r"\{|\}"), "unformatted placeholder"),
    (re.compile(r"  +"), "double space"),
    (re.compile(r"^[a-z]"), "sentence starts lower-case"),
    (re.compile(r"\.\s*\."), "doubled full stop"),
    (re.compile(r"\bs's\b"), "malformed possessive"),
]


# `status` and `party` lay their output out in aligned columns, so runs of
# spaces there are deliberate formatting rather than broken prose.
_TABULAR = re.compile(r"^\s{2,}|Health \d|^The company:")
_ANSI = re.compile(r"\[[0-9;]*m")


def check_messages(lines, found: Counter, examples: dict) -> None:
    for raw in lines:
        text = _ANSI.sub("", str(getattr(raw, "text", raw)))
        if not text.strip():
            found["empty message"] += 1
            continue
        if _TABULAR.search(text):
            continue
        for pattern, label in _BAD_PROSE:
            if pattern.search(text):
                found[label] += 1
                examples.setdefault(label, text[:110])


def check_state(game: Game, found: Counter, examples: dict) -> None:
    for cid, char in game.characters.items():
        if char.location_id not in game.world.locations:
            found["character in a room that doesn't exist"] += 1
            examples.setdefault("character in a room that doesn't exist",
                                f"{char.name} at {char.location_id}")
        if char.health > char.max_health:
            found["health above maximum"] += 1
            examples.setdefault("health above maximum",
                                f"{char.name} {char.health}/{char.max_health}")
        if char.alive and char.health <= 0:
            found["alive at zero health"] += 1
            examples.setdefault("alive at zero health", char.name)
        if not char.alive and char.health > 0:
            found["dead with health left"] += 1
        # A living companion should be listed in the room they stand in.
        if (char is not game.player and char.alive
                and cid not in game.world.get(char.location_id).npcs):
            found["character missing from their room's roster"] += 1
            examples.setdefault("character missing from their room's roster",
                                f"{char.name} at {char.location_id}")
    # An item should exist in exactly one place.
    seen: Counter = Counter()
    for loc in game.world.locations.values():
        seen.update(loc.items)
    for char in game.characters.values():
        seen.update(char.inventory)
    for item_id, n in seen.items():
        # Food and torches are resupplied at havens, so several of each in the
        # world at once is the design rather than a bug.
        item = game.items.get(item_id)
        if n > 1 and not (item.is_food or item.is_light_source):
            found["item exists in two places at once"] += 1
            examples.setdefault("item exists in two places at once",
                                f"{item_id} x{n}")


# -- one path ---------------------------------------------------------------

def play(seed: int, turns: int, verbose: bool = False) -> dict:
    rng = random.Random(seed * 7919)
    game = Game(seed=seed)
    game.player.light_remaining = 40  # a torch's worth; not infinite
    found: Counter = Counter()
    examples: dict[str, str] = {}
    rooms_seen = set()
    stuck = 0
    last_room = None

    for turn in range(turns):
        if game.won or game.lost or not game.player.alive:
            break
        command = choose_command(game, rng)
        try:
            lines = game.process_player_input(command)
        except Exception:
            found["EXCEPTION"] += 1
            examples.setdefault("EXCEPTION",
                                f"'{command}' at turn {turn}: "
                                + traceback.format_exc().strip().splitlines()[-1])
            break
        if verbose:
            print(f"> {command}")
            for line in lines:
                print("   ", str(getattr(line, "text", line))[:120])
        # Check what a player sees. present() is where capitalisation and
        # colouring happen, so checking the raw objects tests the wrong layer.
        check_messages(ui.present(lines, "standard"), found, examples)
        check_state(game, found, examples)

        rooms_seen.add(game.player.location_id)
        stuck = stuck + 1 if game.player.location_id == last_room else 0
        last_room = game.player.location_id

    living = sum(1 for c in game.characters.values()
                 if getattr(c, "def_", None) and c.def_.is_party and c.alive)
    return {
        "seed": seed, "turns": turn + 1, "won": game.won,
        "player_alive": game.player.alive, "company_alive": living,
        "rooms_seen": len(rooms_seen), "farthest": game.player.location_id,
        "found": found, "examples": examples,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Soak-test the game")
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--turns", type=int, default=400)
    ap.add_argument("--seed", type=int, help="replay a single path")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    seeds = [args.seed] if args.seed is not None else range(1, args.seeds + 1)
    totals: Counter = Counter()
    examples: dict[str, str] = {}
    results = []
    for seed in seeds:
        r = play(seed, args.turns, args.verbose)
        results.append(r)
        totals.update(r["found"])
        for k, v in r["examples"].items():
            examples.setdefault(k, f"[seed {seed}] {v}")

    n = len(results)
    print(f"\n=== {n} paths, up to {args.turns} turns each ===")
    print(f"  reached the end (won) : {sum(1 for r in results if r['won'])}/{n}")
    print(f"  Bilbo died            : {sum(1 for r in results if not r['player_alive'])}/{n}")
    print(f"  rooms seen (avg)      : {sum(r['rooms_seen'] for r in results)/n:.0f}")
    print(f"  company alive (avg)   : {sum(r['company_alive'] for r in results)/n:.1f} of 13")
    ends = Counter(r["farthest"] for r in results)
    print(f"  most common end point : {ends.most_common(3)}")

    if not totals:
        print("\n  No anomalies found.")
        return 0
    print(f"\n=== anomalies ({sum(totals.values())} across {n} paths) ===")
    for label, count in totals.most_common():
        print(f"  {count:6}  {label}")
        if label in examples:
            print(f"          e.g. {examples[label]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
