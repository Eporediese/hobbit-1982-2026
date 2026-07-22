"""LLM client for AI-driven NPCs.

Self-contained (standard library only) so the game stays portable and easy
to deploy. Two wire formats are supported behind one `chat(system, user)`
interface, chosen by `LLMConfig.api_style`:

  ollama     -- a local Ollama server (the default; what --ai has always used)
  openai     -- any OpenAI-compatible /chat/completions endpoint, which is
                what most hosted providers speak (Z.ai GLM, ppq.ai,
                OpenRouter, vLLM, llama.cpp's server, and others)
  anthropic  -- Anthropic's own Messages API, which is a different shape:
                the system prompt is a top-level field rather than a message,
                auth is x-api-key rather than a bearer token, and the reply
                arrives as a list of content blocks.

The brains never see the difference, so which model voices the company is a
deployment decision -- an environment variable -- rather than a code change.

Design rule: `chat` NEVER raises and NEVER blocks the game for long. On any
error, timeout, or unreachable server it returns None, and callers fall back
to the non-AI behaviour. That keeps the game fully playable when the model is
slow, down, or absent -- which matters far more on a shared server than it
did on one player's laptop.
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field

OLLAMA = "ollama"
OPENAI = "openai"
ANTHROPIC = "anthropic"

# The Messages API is versioned by header, not by URL path.
ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:11434"
    # An 8B model keeps in-character replies fast (~3s warm); the 14B models
    # are noticeably slower for little dialogue-quality gain.
    model: str = "hermes3:8b"
    # Which wire format the endpoint speaks (see the module docstring).
    api_style: str = OLLAMA
    # Bearer token for hosted endpoints. Never logged, never echoed into the
    # game -- a companion's dialogue prompt must not be able to reach it.
    api_key: str | None = None
    # A little more variety between lines. None omits it entirely, which is
    # required for Claude models: they reject a non-default temperature with
    # a 400, whether reached directly or through an OpenAI-compatible proxy.
    temperature: float | None = 0.9
    timeout: float = 60.0  # generous enough to survive a cold model load
    max_tokens: int = 90  # room to finish a sentence; _clean trims to two anyway
    keep_alive: str = "15m"  # keep a local model resident between turns
    options: dict = field(default_factory=dict)

    @property
    def is_remote(self) -> bool:
        return self.api_style in (OPENAI, ANTHROPIC)


def config_from_env(env: dict[str, str] | None = None) -> LLMConfig | None:
    """Build a config from the environment, or None if AI isn't configured.

    Deployment sets these; nothing about the provider is baked into the code:

      HOBBIT_LLM_URL    the endpoint's base URL (including any version path,
                        e.g. https://api.z.ai/api/paas/v4)
      HOBBIT_LLM_MODEL  the model name
      HOBBIT_LLM_KEY    bearer token, if the endpoint wants one
      HOBBIT_LLM_STYLE  'anthropic', 'openai' or 'ollama' (inferred if unset)
    """
    env = os.environ if env is None else env
    url = env.get("HOBBIT_LLM_URL")
    model = env.get("HOBBIT_LLM_MODEL")
    if not url or not model:
        return None
    key = env.get("HOBBIT_LLM_KEY") or None
    style = env.get("HOBBIT_LLM_STYLE")
    if not style:
        # Guessing here saves one more thing to get wrong in a deployment
        # config: Anthropic's own host speaks its own shape, a bearer token
        # means some hosted OpenAI-compatible provider, and everything else
        # is the local Ollama we started with.
        if "api.anthropic.com" in url:
            style = ANTHROPIC
        else:
            style = OLLAMA if (not key and ":11434" in url) else OPENAI
    cfg = LLMConfig(base_url=url.rstrip("/"), model=model,
                    api_style=style, api_key=key)
    if cfg.is_remote:
        # A hosted call has no cold-load to wait out, and a player is watching
        # a web page rather than a terminal -- fail fast and fall back.
        cfg.timeout = float(env.get("HOBBIT_LLM_TIMEOUT", "20"))
    # Claude rejects a non-default temperature outright -- including when it is
    # reached through an OpenAI-compatible proxy such as ppq.ai, which passes
    # the field straight through. Drop it by default for those models rather
    # than let every companion line 400 in production.
    if "claude" in model.lower():
        cfg.temperature = None
    if "HOBBIT_LLM_TEMPERATURE" in env:
        raw = env["HOBBIT_LLM_TEMPERATURE"].strip().lower()
        cfg.temperature = None if raw in ("", "none", "off") else float(raw)
    if "HOBBIT_LLM_MAX_TOKENS" in env:
        cfg.max_tokens = int(env["HOBBIT_LLM_MAX_TOKENS"])
    return cfg


class LLMClient:
    """Chat wrapper with hard failure isolation, over either wire format."""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()

    # -- transport ------------------------------------------------------

    def _post(self, path: str, payload: dict, timeout: float) -> dict | None:
        headers = {"Content-Type": "application/json"}
        if self.config.api_style == ANTHROPIC:
            if self.config.api_key:
                headers["x-api-key"] = self.config.api_key
            headers["anthropic-version"] = ANTHROPIC_VERSION
        elif self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        try:
            req = urllib.request.Request(
                f"{self.config.base_url}{path}",
                data=json.dumps(payload).encode(),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception:
            return None

    # -- public API -----------------------------------------------------

    def health(self) -> bool:
        """True if the endpoint answers (5s budget for the local case)."""
        if self.config.is_remote:
            # Hosted endpoints vary in what they expose besides the chat route,
            # so the only reliable probe is a real (tiny) completion.
            return self.chat("You are ready.",
                             "Reply with the single word: ok.") is not None
        try:
            req = urllib.request.Request(f"{self.config.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False

    def warmup(self) -> bool:
        """Trigger the model to load now (turning an unpredictable mid-game
        cold-start hang into an explicit startup step). Returns True if the
        model responded. Hosted models have nothing to warm, so this is just
        a reachability check there."""
        return self.chat("You are ready.", "Reply with the single word: ok.") is not None

    def _chat_anthropic(self, system: str, user: str) -> str | None:
        """Anthropic's Messages API.

        Two things here are load-bearing and easy to get wrong:

        Thinking is off. On the current Sonnet, leaving the `thinking` field
        out means *adaptive thinking runs anyway*, and thinking tokens are
        spent against the same max_tokens as the reply. With a budget of 90 --
        which is all a dwarf's one-liner needs -- the model would think its
        way through the whole allowance and Bofur would say nothing at all.

        No temperature. The current Sonnet rejects a non-default temperature
        with a 400, so the variety knob that works on Ollama has to stay off
        here. The prompts already push for specificity; that carries it.
        """
        data = self._post("/v1/messages", {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": system,           # a top-level field, not a message
            "messages": [{"role": "user", "content": user}],
            "thinking": {"type": "disabled"},
            **self.config.options,
        }, self.config.timeout)
        if not data:
            return None
        # A refusal is a successful HTTP 200 with no usable content. Check it
        # before reading blocks, or a declined line reads as a silent NPC.
        if data.get("stop_reason") == "refusal":
            return None
        for block in data.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = (block.get("text") or "").strip()
                if text:
                    return text
        return None

    def chat(self, system: str, user: str) -> str | None:
        """Return the assistant reply text, or None on any failure."""
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        if self.config.api_style == ANTHROPIC:
            return self._chat_anthropic(system, user)
        if self.config.is_remote:
            data = self._post("/chat/completions", {
                "model": self.config.model,
                "messages": messages,
                "stream": False,
                "max_tokens": self.config.max_tokens,
                **({} if self.config.temperature is None
                   else {"temperature": self.config.temperature}),
                **self.config.options,
            }, self.config.timeout)
            if not data:
                return None
            try:
                text = (data["choices"][0]["message"]["content"] or "").strip()
            except (KeyError, IndexError, TypeError):
                return None  # an error body, or a shape we don't know
            return text or None

        data = self._post("/api/chat", {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.config.keep_alive,
            "options": {
                **({} if self.config.temperature is None
                   else {"temperature": self.config.temperature}),
                "num_predict": self.config.max_tokens,
                **self.config.options,
            },
        }, self.config.timeout)
        if not data:
            return None
        text = (data.get("message", {}).get("content") or "").strip()
        return text or None
