"""LLM client for AI-driven NPCs.

Self-contained (standard library only) so the game stays portable and
easy to deploy. It talks to a local Ollama server today; the same
`chat(system, user)` interface can later wrap a remote OpenAI-compatible
endpoint (e.g. Z.ai GLM) without any change to the brains that use it.

Design rule: `chat` NEVER raises and NEVER blocks the game for long. On
any error, timeout, or unreachable server it returns None, and callers
fall back to the non-AI behavior. That keeps the game fully playable when
the model is slow, down, or absent.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:11434"
    # An 8B model keeps in-character replies fast (~3s warm); the 14B models
    # are noticeably slower for little dialogue-quality gain.
    model: str = "hermes3:8b"
    temperature: float = 0.9  # a little more variety between lines
    timeout: float = 60.0  # generous enough to survive a cold model load
    max_tokens: int = 90  # room to finish a sentence; _clean trims to two anyway
    keep_alive: str = "15m"  # keep the model resident between turns
    options: dict = field(default_factory=dict)


class LLMClient:
    """Thin Ollama chat wrapper with hard failure isolation."""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()

    def health(self) -> bool:
        """True if the server is reachable (5s budget)."""
        try:
            req = urllib.request.Request(f"{self.config.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False

    def warmup(self) -> bool:
        """Trigger the model to load now (turning an unpredictable mid-game
        cold-start hang into an explicit startup step). Returns True if the
        model responded."""
        return self.chat("You are ready.", "Reply with the single word: ok.") is not None

    def chat(self, system: str, user: str) -> str | None:
        """Return the assistant reply text, or None on any failure."""
        payload = json.dumps({
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "keep_alive": self.config.keep_alive,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
                **self.config.options,
            },
        }).encode()
        try:
            req = urllib.request.Request(
                f"{self.config.base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                data = json.loads(resp.read())
            text = (data.get("message", {}).get("content") or "").strip()
            return text or None
        except Exception:
            return None
