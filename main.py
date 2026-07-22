#!/usr/bin/env python3
"""Entry point: run The Hobbit in a terminal."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hobbit import ui
from hobbit.game import Game
from hobbit.llm import (LLMClient, LLMConfig, config_from_env,
                        fast_config_from_env)

# Anchored beside the game itself, so saving and loading work no matter
# which directory the game was launched from.
SAVE_PATH = Path(__file__).resolve().parent / "savegame.json"

BANNER = """\
THE HOBBIT
A modern recreation of Beam Software's 1982 text adventure.

Type 'help' for a list of commands. Good luck, Master Baggins.
"""


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="The Hobbit -- a text adventure")
    p.add_argument("--authentic", "--purist", action="store_true", dest="authentic",
                   help="start in the raw 1982-flavored mode")
    p.add_argument("--ai", action="store_true",
                   help="AI-driven companions (needs a reachable Ollama or compatible server)")
    p.add_argument("--model", default="hermes3:8b",
                   help="LLM model name for --ai (default: hermes3:8b -- fast 8B; "
                        "14B models are slower)")
    p.add_argument("--ollama-url", default="http://localhost:11434",
                   help="LLM server base URL for --ai")
    return p.parse_args()


def _make_llm(args: argparse.Namespace):
    """Return (client, fast_client) if --ai is set and a model answers, else
    (None, None) -- companions fall back to the simple routines.

    A configured environment wins over the Ollama flags, so the same settings
    the server will use can be played against here first.
    """
    if not args.ai:
        return None, None
    env_cfg = config_from_env()
    if env_cfg is not None:
        client = LLMClient(env_cfg)
        print(f"Waking the companions ({env_cfg.model})...", end=" ", flush=True)
        if not client.warmup():
            print("no reply; using the simple routines.\n")
            return None, None
        print("ready.")
        fast_cfg = fast_config_from_env()
        fast = None
        if fast_cfg is not None:
            fast = LLMClient(fast_cfg)
            print(ui.note_line(
                f"(goal decisions go to {fast_cfg.model}; dialogue to "
                f"{env_cfg.model}.)"))
        print()
        return client, fast
    client = LLMClient(LLMConfig(base_url=args.ollama_url, model=args.model))
    if not client.health():
        print(ui.note_line(f"(--ai: no model at {args.ollama_url}; companions use the simple routines.)"))
        return None, None
    print(f"Waking the companions ({args.model})...", end=" ", flush=True)
    if client.warmup():
        print("ready.\n")
        return client, None
    print("no reply; using the simple routines.\n")
    return None, None


def main() -> None:
    ui.enable_ansi_on_windows()
    args = _parse_args()
    authentic = args.authentic
    print(BANNER)
    llm, llm_fast = _make_llm(args)
    game = Game(authentic=authentic, llm=llm, llm_fast=llm_fast)

    if authentic:
        print("** PURIST MODE -- the raw 1982-flavored experience **")
        print("Reverted descriptions, the map as wall flavor only, no scenery/examine "
              "system, and the original quirky locks -- some rooms cannot be reached, "
              "and the game may not be winnable. For the enhanced game, start again "
              "without --purist.\n")
    else:
        for line in ui.present([ui.Note(
            "Text in this colour marks something added for this recreation that "
            "wasn't in the 1982 original -- everything else is in plain text. "
            "For the raw 1982 game instead, start again with --purist."
        )], game.annotation_level):
            print(line)
        if game.ai:
            print(ui.note_line("The company are awake and in character."))
    for line in ui.present(game.describe_location(game.player), game.annotation_level):
        print(line)

    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nFarewell!")
            return
        if not text:
            continue

        messages = game.process_player_input(text)
        for message in ui.present(messages, game.annotation_level):
            print(message)

        if game.request_save:
            game.save(SAVE_PATH)
            game.request_save = False
        if game.request_load:
            game.request_load = False
            if SAVE_PATH.exists():
                game.load(SAVE_PATH)
                print("Game loaded.")
                for line in ui.present(game.describe_location(game.player), game.annotation_level):
                    print(line)
            else:
                print("No saved game found.")
        if game.request_quit:
            return
        if game.won:
            for line in ui.present(game.ending_lines(), game.annotation_level):
                print(line)
            print("\n*** THE END ***")
            return
        if game.lost:
            print(f"\n{game.lose_reason}")
            print("\n*** GAME OVER ***")
            return


if __name__ == "__main__":
    sys.exit(main() or 0)
