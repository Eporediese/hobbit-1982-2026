"""The map: locations and the world container that holds mutable state
(items lying around, who is standing where)."""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

DIRECTIONS = ["north", "south", "east", "west", "up", "down",
              "northeast", "northwest", "southeast", "southwest"]

# How many fighters can engage at once in an ordinary room (see
# Location.melee_width).
DEFAULT_MELEE_WIDTH = 4

OPPOSITE = {
    "north": "south", "south": "north",
    "east": "west", "west": "east",
    "up": "down", "down": "up",
    "northeast": "southwest", "southwest": "northeast",
    "northwest": "southeast", "southeast": "northwest",
}


class Scenery:
    """A described-but-not-carryable detail of a room (a door, a map on the
    wall, a throne). Exists purely so `examine <noun>` can find something
    for the nouns used in room prose, instead of failing with 'you see no
    X here' whenever a description mentions something that isn't a real
    item, NPC, or exit."""

    def __init__(self, data: dict[str, Any]):
        self.name: str = data["name"]
        self.aliases: list[str] = data.get("aliases", [])
        self.description: str = data["description"]
        # Set only for scenery that poses a puzzle the room itself resolves --
        # a keyhole reads as a riddle while it's locked and as a memory once
        # the key has turned. Falls back to the one description when unset.
        self.opened_description: str = data.get("opened_description", self.description)
        # Set only for scenery whose text used to describe a bug (e.g. implying
        # an exit that didn't exist) -- explains what was wrong and how it was
        # fixed, shown only at the 'verbose' annotation level.
        self.bugfix_note: str | None = data.get("bugfix_note")

    def matches(self, word: str) -> bool:
        word = word.lower()
        return word == self.name.lower() or word in (a.lower() for a in self.aliases)


class Location:
    def __init__(self, loc_id: str, data: dict[str, Any]):
        self.id = loc_id
        self.name: str = data["name"]
        self.description: str = data["description"]
        # The pre-fix description used in authenticity mode, for rooms whose
        # prose was rewritten to remove a false affordance. Falls back to the
        # normal description when no separate original was recorded.
        self.original_description: str = data.get("original_description", self.description)
        # A clause describing an added feature (e.g. that you can restock
        # provisions here) -- appended and coloured in enhanced mode, dropped
        # in purist.
        self.added_description: str = data.get("added_description", "")
        self.exits: dict[str, str] = dict(data.get("exits", {}))
        self.items: list[str] = list(data.get("items", []))
        self.npcs: list[str] = list(data.get("npcs", []))
        self.dark: bool = data.get("dark", False)
        self.region: str = data.get("region", "")
        self.locked: bool = data.get("locked", False)
        self.key_item: str | None = data.get("key_item")
        self.hidden_items: list[str] = list(data.get("hidden_items", []))
        self.scenery: list[Scenery] = [Scenery(d) for d in data.get("scenery", [])]
        # Set only for rooms that used to be permanently unreachable due to a
        # fixed bug (e.g. a locked room 'open'/'close' could never actually
        # unlock) -- surfaced by Game.describe_location, shown only at the
        # 'verbose' annotation level.
        self.bugfix_note: str | None = data.get("bugfix_note")
        # A settlement where travellers can refill their provisions, and the
        # fare it supplies -- Rivendell presses waybread on you, the Green
        # Dragon plain loaves.
        self.food_source: bool = data.get("food_source", False)
        self.staple_food: str | None = data.get("staple_food")
        # A room lit well enough by moonlight to read moon-letters (the
        # reading table in Elrond's Library) -- where the map's secret pays off.
        self.moonlit: bool = data.get("moonlit", False)
        # How many of the company can come to blows here at once. A goblin-cut
        # tunnel takes two abreast; a hall takes many. Without this the whole
        # company piles onto one foe and nothing in the world survives a round.
        self.melee_width: int = data.get("melee_width", DEFAULT_MELEE_WIDTH)
        # Ways out that are shut to everyone, whatever they carry (the
        # Elvenking's gate is barred, and no key opens it -- you leave by the
        # river). Direction -> why. Unlike `locked`, this bars one exit rather
        # than sealing the room, so the place stays reachable from elsewhere.
        self.barred_exits: dict[str, str] = dict(data.get("barred_exits", {}))
        # Where the barrels in this room float to, if any.
        self.barrel_route: str | None = data.get("barrel_route")
        self.visited: bool = False
        # The pristine placement from the data files, kept so a save written
        # before an item or a lock existed can have it restored on load
        # (see Game.reconcile_after_load).
        self.initial_items: list[str] = list(self.items)
        self.initial_locked: bool = self.locked
        # Names of monsters slain here, and companions given graves here --
        # the marks a battle leaves behind.
        self.slain: list[str] = []
        self.graves: list[str] = []

    def find_scenery(self, word: str) -> Scenery | None:
        for scenery in self.scenery:
            if scenery.matches(word):
                return scenery
        return None

    def open_up(self) -> list[str]:
        """Unlock the location, revealing any hidden items. Returns revealed item ids."""
        self.locked = False
        revealed = self.hidden_items
        self.items.extend(revealed)
        self.hidden_items = []
        return revealed


class World:
    def __init__(self, locations: dict[str, Location]):
        self.locations = locations

    @classmethod
    def load(cls, path: Path) -> "World":
        raw = json.loads(path.read_text(encoding="utf-8"))
        locations = {loc_id: Location(loc_id, data) for loc_id, data in raw.items()}
        return cls(locations)

    def get(self, loc_id: str) -> Location:
        return self.locations[loc_id]

    def path_step(self, start_id: str, target_id: str) -> str | None:
        """Return the direction of the first step on a shortest path from
        `start_id` toward `target_id`, or None if already there or no route
        exists. Optimistic: it ignores locks/darkness (the actual `go`
        command still enforces those), so a goal-seeker may stall at a
        barrier it can't cross -- which reads as the character being held up
        there."""
        if start_id == target_id or target_id not in self.locations:
            return None
        # BFS, remembering how each room was first reached.
        came_from: dict[str, tuple[str | None, str | None]] = {start_id: (None, None)}
        queue = deque([start_id])
        while queue:
            current = queue.popleft()
            if current == target_id:
                break
            for direction, neighbor in self.get(current).exits.items():
                if neighbor not in came_from:
                    came_from[neighbor] = (current, direction)
                    queue.append(neighbor)
        if target_id not in came_from:
            return None
        # Walk the chain back to recover the very first direction taken.
        node, first_direction = target_id, None
        while came_from[node][0] is not None:
            first_direction = came_from[node][1]
            node = came_from[node][0]
        return first_direction

    def distance(self, a: str, b: str) -> int:
        """Hop count of the shortest route from a to b, or a large number if
        unreachable."""
        if a == b:
            return 0
        seen = {a}
        queue = deque([(a, 0)])
        while queue:
            current, dist = queue.popleft()
            for neighbor in self.get(current).exits.values():
                if neighbor == b:
                    return dist + 1
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, dist + 1))
        return 9999

    def nearest_food_source(self, start_id: str) -> str | None:
        """The id of the closest location where provisions can be restocked
        (by BFS hop count), or None if none is reachable.

        Barred ways are respected: a hungry dwarf inside the Elvenking's halls
        must not set off for Lake-town through a gate that no one can open,
        stall against it, and be lost to the company for good. (Locked rooms
        are still counted -- a door with a key is a door you may yet open.)
        """
        seen = {start_id}
        queue = deque([start_id])
        while queue:
            current = queue.popleft()
            if self.get(current).food_source:
                return current
            here = self.get(current)
            for direction, neighbor in here.exits.items():
                if direction in here.barred_exits or neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        return None

    def neighbors_of_region(self, region: str) -> list[str]:
        return [loc.id for loc in self.locations.values() if loc.region == region]

    def to_dict(self) -> dict[str, Any]:
        return {
            loc_id: {
                "items": loc.items,
                "npcs": loc.npcs,
                "locked": loc.locked,
                "hidden_items": loc.hidden_items,
                "visited": loc.visited,
                "slain": loc.slain,
                "graves": loc.graves,
            }
            for loc_id, loc in self.locations.items()
        }

    def load_state(self, state: dict[str, Any]) -> None:
        for loc_id, loc_state in state.items():
            loc = self.locations.get(loc_id)
            if not loc:
                continue
            loc.items = list(loc_state.get("items", loc.items))
            loc.npcs = list(loc_state.get("npcs", loc.npcs))
            loc.locked = loc_state.get("locked", loc.locked)
            loc.hidden_items = list(loc_state.get("hidden_items", loc.hidden_items))
            loc.visited = loc_state.get("visited", loc.visited)
            loc.slain = list(loc_state.get("slain", loc.slain))
            loc.graves = list(loc_state.get("graves", loc.graves))
