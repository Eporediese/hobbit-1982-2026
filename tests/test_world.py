from pathlib import Path

from hobbit.items import ItemCatalog
from hobbit.world import World

DATA_DIR = Path(__file__).parent.parent / "hobbit" / "data"


def test_locations_load():
    world = World.load(DATA_DIR / "locations.json")
    assert "bag_end" in world.locations
    assert len(world.locations) >= 60


def test_all_exits_point_to_real_locations():
    world = World.load(DATA_DIR / "locations.json")
    ids = set(world.locations.keys())
    for loc in world.locations.values():
        for direction, target in loc.exits.items():
            assert target in ids, f"{loc.id} exit {direction} -> missing {target}"


def test_items_load_and_lookup():
    catalog = ItemCatalog.load(DATA_DIR / "items.json")
    sting = catalog.get("sting")
    assert sting.is_weapon
    assert catalog.find_by_word("sword") is sting


def test_locked_location_has_key_defined():
    world = World.load(DATA_DIR / "locations.json")
    catalog = ItemCatalog.load(DATA_DIR / "items.json")
    for loc in world.locations.values():
        if loc.locked:
            assert loc.key_item is not None
            assert loc.key_item in catalog.items


def test_scenery_lookup_by_alias():
    world = World.load(DATA_DIR / "locations.json")
    garden = world.get("bag_end_garden")
    scenery = garden.find_scenery("low gate")
    assert scenery is not None
    assert "north" in scenery.description.lower()


def test_bag_end_map_is_a_real_item():
    catalog = ItemCatalog.load(DATA_DIR / "items.json")
    world = World.load(DATA_DIR / "locations.json")
    bag_end = world.get("bag_end")
    assert "thorin_map" in bag_end.items
    assert catalog.find_by_word("map") is catalog.get("thorin_map")


def test_every_location_reachable_from_bag_end():
    """Every room should be reachable by walking exits from the start,
    ignoring locks (locks are meant to gate progress, not orphan rooms)."""
    world = World.load(DATA_DIR / "locations.json")
    seen = {"bag_end"}
    frontier = ["bag_end"]
    while frontier:
        current = frontier.pop()
        for target in world.get(current).exits.values():
            if target not in seen:
                seen.add(target)
                frontier.append(target)
    unreachable = set(world.locations.keys()) - seen
    assert not unreachable, f"unreachable locations: {unreachable}"


def test_room_has_its_own_bugfix_note_whenever_its_scenery_does():
    """Regression: a room's own description can be the thing that was
    fixed (e.g. a false 'this leads somewhere' promise), and a plain
    'look' should surface that -- not just 'examine <the specific noun>'.
    Every location with at least one scenery bugfix_note must also carry
    a location-level one."""
    world = World.load(DATA_DIR / "locations.json")
    offenders = []
    for loc in world.locations.values():
        has_scenery_bugfix = any(s.bugfix_note for s in loc.scenery)
        if has_scenery_bugfix and not loc.bugfix_note:
            offenders.append(loc.id)
    assert not offenders, f"locations missing a room-level bugfix_note: {offenders}"
