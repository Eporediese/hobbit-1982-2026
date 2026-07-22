"""Item definitions and the item catalog loaded from data/items.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Words in an item's name that shouldn't, on their own, be used to refer to it.
_NAME_STOPWORDS = {"the", "of", "and", "some", "a", "an", "plain", "small", "old"}


class ItemDef:
    """Static definition of an item type (there is at most one live instance
    of each item id in the world at a time, matching the original game)."""

    def __init__(self, item_id: str, data: dict[str, Any]):
        self.id = item_id
        self.name: str = data["name"]
        self.aliases: list[str] = data.get("aliases", [])
        self.description: str = data.get("description", "")
        self.takeable: bool = data.get("takeable", True)
        # What this costs to carry: packs hold a weight, not a count, so a
        # dragon's heap crowds out the bread a small pile of coins would not.
        self.weight: int = data.get("weight", 1)
        # Worth in the final reckoning of what the company carried out.
        self.value: int = data.get("value", 0)
        self.type: str = data.get("type", "misc")
        self.damage: int = data.get("damage", 0)
        self.light_turns: int = data.get("light_turns", 0)
        self.food_value: int = data.get("food_value", 0)
        self.opens: str | None = data.get("opens")
        self.wearable: bool = data.get("wearable", False)
        # A walking staff: eases the march when in hand, though a poor weapon.
        self.walking_aid: bool = data.get("walking_aid", False)
        # Set only for items that are themselves an added feature (e.g. a prop
        # that used to be pure unexaminable flavor text and is now a real,
        # examinable item) -- shown in color at the 'standard'/'verbose'
        # annotation levels. bugfix_note additionally explains what was wrong,
        # shown only at 'verbose'.
        self.added: bool = data.get("added", False)
        self.bugfix_note: str | None = data.get("bugfix_note")

    @property
    def is_weapon(self) -> bool:
        return self.type == "weapon"

    @property
    def travel_mod(self) -> int:
        """How wielding this changes march fatigue: a walking aid eases it,
        a drawn weapon wearies you."""
        if self.walking_aid:
            return -1
        if self.is_weapon:
            return 1
        return 0

    @property
    def is_light_source(self) -> bool:
        return self.type == "light"

    @property
    def is_food(self) -> bool:
        return self.type == "food"

    @property
    def is_key(self) -> bool:
        return self.type == "key"

    @property
    def is_treasure(self) -> bool:
        return self.type == "treasure"

    def matches(self, word: str) -> bool:
        word = word.lower()
        if word == self.name.lower() or word == self.id:
            return True
        flat = word.replace("-", " ")
        if any(flat == a.lower().replace("-", " ") for a in self.aliases):
            return True
        name_tokens = self.name.lower().replace("-", " ").split()
        query = word.replace("-", " ").split()
        if len(query) == 1:
            # A meaningful single word from the name, so "iron key" answers to
            # "key" and "small pile of gold coins" to "coins" or "gold".
            return query[0] in [t for t in name_tokens
                                if len(t) >= 3 and t not in _NAME_STOPWORDS]
        # Several words: accept any run of the name's own words, so the coins
        # answer to "gold coins" as readily as to "gold".
        return any(name_tokens[i:i + len(query)] == query
                   for i in range(len(name_tokens) - len(query) + 1))


class ItemCatalog:
    def __init__(self, items: dict[str, ItemDef]):
        self.items = items

    @classmethod
    def load(cls, path: Path) -> "ItemCatalog":
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = {item_id: ItemDef(item_id, data) for item_id, data in raw.items()}
        return cls(items)

    def get(self, item_id: str) -> ItemDef:
        return self.items[item_id]

    def find_by_word(self, word: str) -> ItemDef | None:
        for item in self.items.values():
            if item.matches(word):
                return item
        return None
