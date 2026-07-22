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

def choose_command(game: Game, rng: random.Random) -> str:
    """A player who is trying, roughly, to get somewhere and stay alive."""
    player = game.player
    loc = game.world.get(player.location_id)

    if player.is_fainted() or player.hunger > 50:
        if game.carried_food(player):
            return "eat"
        if loc.food_source:
            return "stock up"
    if player.fatigue > 55:
        return "rest"

    # A guard turns back anyone he can see. A real player works out that the
    # ring gets them past -- so the bot does too, or every path stops here.
    if "ring" in player.inventory and "ring" not in player.worn:
        for direction, dest in loc.exits.items():
            if game.guard_at(dest) is not None:
                return "wear ring"

    monsters = [c for c in game.characters.values()
                if c.alive and c.location_id == loc.id
                and getattr(c, "def_", None) and c.def_.is_monster
                and not getattr(c, "captured", False)]
    if monsters and rng.random() < 0.8:
        return f"attack {monsters[0].name}"

    if loc.food_source and len(game.carried_food(player)) < 4:
        return "stock up"

    takeable = [i for i in loc.items if game.items.get(i).takeable]
    if takeable and rng.random() < 0.5:
        return f"take {game.items.get(takeable[0]).name}"

    if loc.locked is False and rng.random() < 0.08:
        return rng.choice(["look", "party", "status", "inventory"])

    # Head for the Mountain most of the time, wander sometimes -- a player
    # explores, but does not wander forever.
    if rng.random() < 0.75:
        step = game.world.path_step(loc.id, "front_gate")
        if step:
            return step
    exits = list(loc.exits)
    if loc.barrel_route:
        exits.append("barrel")
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
        # Food stacks by design -- a dozen loaves are a dozen loaves.
        if n > 1 and not game.items.get(item_id).is_food:
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
