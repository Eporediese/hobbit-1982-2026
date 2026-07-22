"""Run the web server: python -m hobbit.serve

Everything comes from the environment, so the same command works on a laptop
and on a deployment platform -- the difference is only what is set.

    HOBBIT_PORT       port to listen on (default 8080; platforms set $PORT)
    HOBBIT_SAVES      directory for players' journeys (default ./saves)
    HOBBIT_PASSWORD   the shared word; unset leaves the door open
    HOBBIT_SECRET     signs login tokens; unset means a restart logs everyone
                      out (the safe failure) -- set it in production
    HOBBIT_PURIST     '1' to run the 1982-flavoured game

  ...plus the HOBBIT_LLM_* settings that voice the companions (see llm.py);
  unset, they fall back to the simple routines and the game still plays.
"""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from .llm import LLMClient, config_from_env, fast_config_from_env
from .web import serve


def _make_llm():
    """(client, fast_client) from the environment, or (None, None).

    A model failure at startup must not stop the server coming up -- the game
    is fully playable without one. So an unreachable model logs a line and
    yields the scripted companions rather than raising.
    """
    cfg = config_from_env()
    if cfg is None:
        print("No model configured; companions use the simple routines.")
        return None, None
    client = LLMClient(cfg)
    print(f"Reaching the model ({cfg.model})...", end=" ", flush=True)
    if not client.health():
        print("no answer; companions use the simple routines.")
        return None, None
    print("ready.")
    fast_cfg = fast_config_from_env()
    fast = LLMClient(fast_cfg) if fast_cfg else None
    if fast:
        print(f"Goal decisions go to {fast_cfg.model}; dialogue to {cfg.model}.")
    return client, fast


def main() -> int:
    port = int(os.environ.get("HOBBIT_PORT") or os.environ.get("PORT") or 8080)
    saves = Path(os.environ.get("HOBBIT_SAVES", "saves"))
    purist = os.environ.get("HOBBIT_PURIST", "") in ("1", "true", "yes")
    password = os.environ.get("HOBBIT_PASSWORD") or None

    llm, llm_fast = _make_llm()
    httpd = serve(host="0.0.0.0", port=port, saves=saves, llm=llm,
                  llm_fast=llm_fast, authentic=purist, password=password)

    where = "closed with a shared word" if password else "OPEN to anyone"
    print(f"The Hobbit is served on port {port} -- {where}.")
    if not password:
        print("  (set HOBBIT_PASSWORD to keep strangers off your model credit.)")
    print(f"  saves: {saves.resolve()}")

    # Persist every live journey on the way down, so a deploy or a Ctrl-C
    # costs nobody their game. Handles both an interactive stop and the
    # SIGTERM a platform sends when it recycles the process.
    def shutdown(*_):
        print("\nSaving journeys...", end=" ", flush=True)
        httpd.store.save_all()
        httpd.shutdown()
        print("done.")

    signal.signal(signal.SIGTERM, shutdown)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
