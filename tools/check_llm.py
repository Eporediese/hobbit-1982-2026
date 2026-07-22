#!/usr/bin/env python3
"""Check that a configured model can actually voice a companion.

Run this once after setting the environment, before pointing family at the
server. It makes two real calls and reports what came back -- which is the only
way to find out whether a provider passes a field straight through to a model
that rejects it.

    set HOBBIT_LLM_URL=https://api.ppq.ai
    set HOBBIT_LLM_MODEL=claude-sonnet-5
    set HOBBIT_LLM_KEY=<your key>
    python tools/check_llm.py

Nothing here prints the key.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hobbit.llm import LLMClient, config_from_env  # noqa: E402

PERSONA = ("You are Bofur, a dwarf of Thorin's company: talkative, fond of a "
           "song and a joke, and the kindest to Bilbo of any of them. Reply "
           "in one or two sentences, in character, and never break character.")


def main() -> int:
    cfg = config_from_env()
    if cfg is None:
        print("Not configured -- nothing to check yet.\n")
        print("These are read from the environment of the shell you run this")
        print("in, so set them first, in the same window:\n")
        if sys.platform == "win32":
            print("  cmd.exe:")
            print("    set HOBBIT_LLM_URL=https://api.ppq.ai")
            print("    set HOBBIT_LLM_MODEL=claude-sonnet-5")
            print("    set HOBBIT_LLM_KEY=<your key>")
            print("    python tools\\check_llm.py\n")
            print("  PowerShell:")
            print('    $env:HOBBIT_LLM_URL="https://api.ppq.ai"')
            print('    $env:HOBBIT_LLM_MODEL="claude-sonnet-5"')
            print('    $env:HOBBIT_LLM_KEY="<your key>"')
            print("    python tools\\check_llm.py")
        else:
            print("    export HOBBIT_LLM_URL=https://api.ppq.ai")
            print("    export HOBBIT_LLM_MODEL=claude-sonnet-5")
            print("    export HOBBIT_LLM_KEY=<your key>")
            print("    python tools/check_llm.py")
        print("\nThey last only for that shell session, which is what you want")
        print("for a key -- close the window and it's gone.")
        return 2

    print(f"  endpoint : {cfg.base_url}")
    print(f"  model    : {cfg.model}")
    print(f"  wire     : {cfg.api_style}")
    print(f"  key      : {'set' if cfg.api_key else 'none'}")
    print(f"  temp     : {'omitted' if cfg.temperature is None else cfg.temperature}")
    print(f"  max_tok  : {cfg.max_tokens}   timeout: {cfg.timeout}s")
    print()

    client = LLMClient(cfg)

    print("1/2  reachability ...", end=" ", flush=True)
    if not client.warmup():
        print("FAILED")
        print("\n  No usable reply. Most likely one of:")
        print("   - wrong URL (this posts to <URL>/chat/completions for the")
        print("     openai wire, <URL>/v1/messages for anthropic)")
        print("   - key rejected, or no credit on the account")
        print("   - the provider passed a field the model refuses. If the model")
        print("     is a Claude one, try HOBBIT_LLM_TEMPERATURE=none")
        return 1
    print("ok")

    print("2/2  in character ...", end=" ", flush=True)
    line = client.chat(PERSONA, "Bilbo asks whether the road ahead is safe. "
                                "Answer him.")
    if not line:
        print("EMPTY")
        print("\n  Reachable, but produced nothing usable. If this is a Claude")
        print("  model behind an OpenAI-compatible proxy, its thinking tokens")
        print("  may be consuming the whole budget before any words are")
        print("  written. Try a larger allowance:  HOBBIT_LLM_MAX_TOKENS=400")
        return 1
    print("ok\n")
    print(f'  Bofur: "{line}"')
    print("\n  Good. The companions can speak.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
