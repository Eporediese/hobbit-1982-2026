"""JSON save/load of full game state (world + all characters)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .game import Game


def _game_to_dict(game: "Game") -> dict[str, Any]:
    return {
        "turn": game.turn,
        "faint_turns": game.faint_turns,
        "won": game.won,
        "lost": game.lost,
        "annotation_level": game.annotation_level,
        "world": game.world.to_dict(),
        "characters": {cid: c.to_dict() for cid, c in game.characters.items()},
        "captured": {cid: c.captured for cid, c in game.characters.items()
                     if hasattr(c, "captured")},
        "scout": {cid: {"phase": c.scout_phase, "memory": c.scout_memory,
                         "unreported": c.scout_unreported,
                         "seen": sorted(c.scout_seen)}
                   for cid, c in game.characters.items()
                   if getattr(c, "scout_memory", None)},
        "world_events": game.world_events,
        "event_seq": game._event_seq,
        "company_lore": game.company_lore,
        "moon_letters_read": game.moon_letters_read,
    }


def save_game(game: "Game", path: Path) -> None:
    path.write_text(json.dumps(_game_to_dict(game), indent=2), encoding="utf-8")


def load_game(game: "Game", path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    game.turn = data["turn"]
    game.faint_turns = data["faint_turns"]
    game.won = data["won"]
    game.lost = data["lost"]
    # annotation_level drives everything, including whether we're in the
    # authentic/purist experience -- so it fully restores the mode too.
    game.annotation_level = data.get("annotation_level", game.annotation_level)
    game.world.load_state(data["world"])
    for cid, cdata in data["characters"].items():
        char = game.characters.get(cid)
        if char:
            char.load_dict(cdata)
    for cid, captured in data.get("captured", {}).items():
        char = game.characters.get(cid)
        if char and hasattr(char, "captured"):
            char.captured = captured
    for cid, scout in data.get("scout", {}).items():
        char = game.characters.get(cid)
        if char is not None and hasattr(char, "scout_phase"):
            char.scout_phase = scout.get("phase", "ranging")
            char.scout_memory = list(scout.get("memory", []))
            # Older saves stored bare strings; the current shape is
            # {"text", "concern"}. Normalise either way.
            char.scout_unreported = [
                e if isinstance(e, dict) else {"text": e, "concern": None}
                for e in scout.get("unreported", [])]
            char.scout_seen = set(scout.get("seen", []))
    game.world_events = list(data.get("world_events", []))
    game._event_seq = data.get("event_seq", len(game.world_events))
    game.company_lore = list(data.get("company_lore", []))
    game.moon_letters_read = data.get("moon_letters_read", False)
