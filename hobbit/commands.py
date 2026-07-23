"""Verb handlers. Every handler is actor-agnostic: it takes whichever
Character is performing the action (the player or an NPC acting on a
player's direct command), so the same code path drives both, and a future
networked mode can call these for any connected player's actor."""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from . import ui
from .combat import resolve_attack
from .entities import Character
from .parser import FREE_VERBS, Command
from .ui import Note
from .world import OPPOSITE

if TYPE_CHECKING:
    from .game import Game


def _find_item(game: "Game", word: str, pool: list[str]) -> str | None:
    for item_id in pool:
        item = game.items.get(item_id)
        if item.matches(word):
            return item_id
    return None


_display_name = ui.item_display_name


_the = ui.with_article


def _find_character(game: "Game", word: str, candidate_ids: list[str]) -> str | None:
    word = word.lower()
    # The parser strips articles, so "attack William the troll" arrives here as
    # "william troll" -- which is NOT a substring of the name "william the
    # troll". So match on whole words too: every word the player gave must
    # appear in the name. "william troll" and "troll" both find the troll;
    # "william" alone finds only William.
    tokens = word.split()
    for char_id in candidate_ids:
        char = game.characters.get(char_id)
        if not char:
            continue
        name = char.name.lower()
        if (word == char.id
                or word in name
                or (tokens and all(t in name.split() for t in tokens))
                or word in (a.lower() for a in char.aliases)):
            return char_id
    return None


def do_go(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Go where?"]
    loc = game.world.get(actor.location_id)
    direction = cmd.obj
    # "go barrel", "climb into the barrel", "take the trap-door" -- all the
    # natural ways of saying it, rather than dead-ending on "you can't go
    # barrel from here".
    if loc.barrel_route and direction in _BARREL_WORDS:
        return do_barrel(game, actor, cmd)
    if direction not in loc.exits:
        return [f"You can't go {direction} from here."]
    if direction in loc.barred_exits and not game.authentic:
        return [loc.barred_exits[direction]]
    dest_id = loc.exits[direction]
    dest = game.world.get(dest_id)
    # A guarded room turns back anyone who can be seen walking into it.
    warden = game.guard_at(dest_id)
    if warden is not None and not game.unseen(actor):
        return [f'{warden.name} bars the way. "{warden.def_.dialogue}"']
    if dest.locked:
        # Nudge the player toward 'open' when they're carrying the right key.
        if dest.key_item and dest.key_item in actor.inventory:
            key_name = game.items.get(dest.key_item).name
            return [f"The way {direction} is locked -- but you have the {key_name}. "
                    "Try 'open door' first."]
        return [f"The way {direction} is locked."]
    # Darkness only stops the player -- the seasoned dwarves and Gandalf press
    # on regardless (and may blunder into goblin-held dark, as in the tale).
    # The one torch serves the whole party: Bilbo can go where a companion
    # carries it, whether that companion is here (to come down with him) or has
    # already gone ahead with it into the dark below.
    if (actor.id == "bilbo" and dest.dark
            and not game.room_is_lit(actor.location_id)
            and not game.room_is_lit(dest_id)
            and not game.player_can_see_in_dark(actor)):
        # ...but never into a trap. A torch that gutters out in the middle of
        # the tunnels leaves every way on dark, and a player who cannot move
        # at all simply starves where they stand. The way you came is the one
        # way you can still find by feel.
        if dest_id not in actor.trail:
            # Name the remedy, exactly as a locked door names its key. Now
            # that carrying a torch is no longer the same as burning one,
            # "you dare not go on" left a player holding the answer and not
            # being told -- and the whole journey stopped at the cave mouth.
            spare = next((i for i in actor.inventory
                          if game.items.get(i).is_light_source), None)
            if spare:
                return [f"It's pitch dark {direction} of here -- but you have "
                        f"{_the(game.items.get(spare).name)}. "
                        "Try 'light torch' first."]
            return [f"It's pitch dark {direction} of here and you dare not go "
                    "on without a light."]
        messages_back = [Note("You feel your way back along the wall, the way "
                              "you came.")]
    else:
        messages_back = []

    if actor.id != "bilbo" and actor.id in loc.npcs:
        loc.npcs.remove(actor.id)
    # Breadcrumbs: remember where you have been, so the dark can be retraced.
    actor.trail = ([r for r in actor.trail if r != dest_id] + [loc.id])[-12:]
    actor.location_id = dest_id
    actor.add_travel_fatigue(game.load_burden(actor))
    dest.visited = True
    if actor.id != "bilbo":
        dest.npcs.append(actor.id)
    return messages_back + [f"You go {direction}." if actor.id == "bilbo"
                            else f"{actor.name} goes {direction}."]


def do_take(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Take what?"]
    loc = game.world.get(actor.location_id)
    if (loc.dark and actor.light_remaining <= 0
            and not game.player_can_see_in_dark(actor)):
        return ["It's too dark to see what's here. You need a light."]
    # visible_items hides added-but-reverted props (the map) in authentic mode,
    # so they can't be picked up -- they're just wall flavor there.
    item_id = _find_item(game, cmd.obj, game.visible_items(loc))
    if not item_id:
        # A settlement's fare is inexhaustible -- grabbing some pulls a fresh
        # helping from the counter into your pack. Ask for it by its own name
        # as well as by the generic words: at Rivendell it is waybread and in
        # the Elvenking's cellars elven cake, and 'take cake' should work there
        # (Bilbo starved amid a full larder because it only knew "loaf").
        word = (cmd.obj or "").strip().lower()
        staple = game.staple_at(loc.id)
        if loc.food_source and (word in _FOOD_GRAB_WORDS
                                or game.items.get(staple).matches(word)):
            if not game.add_food(actor, staple):
                return [f"Your pack is full -- you can carry only {actor.max_carry} "
                        "in weight, food and gear together."]
            fare = game.items.get(staple).name
            return [f"You take {ui.an(fare)}. {_carry_line(game, actor)}"]
        if loc.barrel_route and word in _BARREL_WORDS:
            return do_barrel(game, actor, cmd)
        return [f"There is no {cmd.obj} here."]
    item = game.items.get(item_id)
    if not item.takeable:
        return [f"You can't take {_the(_display_name(item))}."]
    # A pack holds a weight, not a count -- a dragon's heap is a burden that a
    # pile of coins is not, and a hobbit simply cannot shift some of it.
    if not game.can_carry(actor, item):
        return [f"The {_display_name(item)} is too heavy for what you're already "
                f"carrying; you leave it. {_carry_line(game, actor)}"]
    loc.items.remove(item_id)
    actor.inventory.append(item_id)
    # The Heart of the Mountain is not a thing Thorin lets pass by.
    claimed = _thorin_claims_arkenstone(game, actor, item_id)
    if claimed:
        return claimed
    if item.is_food:
        return [f"You take {_the(item.name)}. {_carry_line(game, actor)}"]
    return [f"{'You take' if actor.id == 'bilbo' else actor.name + ' takes'} {_the(_display_name(item))}."]


def _carry_line(game: "Game", actor: Character) -> str:
    return f"(carrying {game.carried_weight(actor)}/{actor.max_carry})"


ARKENSTONE = "arkenstone"


def _thorin_claims_arkenstone(game: "Game", actor: Character, item_id: str) -> list[str] | None:
    """If the Heart of the Mountain is lifted while Thorin looks on, it is his
    the moment he sees it -- he will not watch another carry it out."""
    if item_id != ARKENSTONE or actor.id == "thorin":
        return None
    thorin = game.characters.get("thorin")
    if (not thorin or not thorin.alive or getattr(thorin, "captured", False)
            or thorin.location_id != actor.location_id):
        return None
    if not game.can_carry(thorin, game.items.get(item_id)):
        return None
    actor.inventory.remove(item_id)
    thorin.inventory.append(item_id)
    game.company_news(
        "Thorin holds the Arkenstone, the Heart of the Mountain",
        announce="Thorin takes the Arkenstone into his hands, and does not look away from it.")
    return [Note("Thorin's hand closes over the Arkenstone before yours can lift it "
                 "clear. \"The Heart of the Mountain,\" he breathes. \"It is mine.\"")]


def do_drop(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Drop what?"]
    item_id = _find_item(game, cmd.obj, actor.inventory)
    if not item_id:
        return [f"You aren't carrying a {cmd.obj}."]
    actor.inventory.remove(item_id)
    actor.disarm_if_lost(item_id)
    game.world.get(actor.location_id).items.append(item_id)
    item = game.items.get(item_id)
    return [f"{'You drop' if actor.id == 'bilbo' else actor.name + ' drops'} {_the(_display_name(item))}."]


def do_attack(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Attack what?"]
    loc = game.world.get(actor.location_id)
    candidates = [c for c in loc.npcs if c != actor.id]
    if actor.id != "bilbo" and game.player.location_id == loc.id:
        candidates.append("bilbo")
    target_id = _find_character(game, cmd.obj, candidates)
    if not target_id:
        return [f"There is no {cmd.obj} here to attack."]
    target = game.characters[target_id]
    if not target.alive:
        return [ui.sentence(f"{target.name} is already dead.")]
    messages: list[str] = []
    # Striking from nowhere gives you away: the ring hides you, it does not
    # make you a ghost. Without this you could kill anything, Smaug included,
    # in perfect safety.
    if actor.id == "bilbo" and actor.invisible:
        actor.invisible = False
        if "ring" in actor.worn:
            actor.worn.remove("ring")
        # It really does slip loose: the ring falls where you stand, and you
        # must stoop for it mid-fight or leave it behind.
        if "ring" in actor.inventory:
            actor.inventory.remove("ring")
            loc.items.append("ring")
        messages.append(Note("You strike -- and the ring slips from your finger as "
                             "you lunge, falling among the stones at your feet. "
                             "They can see you now."))
    swept = game.breath_attack(actor, target)
    messages += swept if swept is not None else resolve_attack(actor, target, game.rng)
    game.record_event(loc.id, "fight",
                       f"signs of a recent skirmish at {loc.name}")
    if not target.alive:
        messages.extend(game.handle_death(target))
    return messages


def do_give(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj or not cmd.indirect:
        return ["Give what to whom?"]
    item_id = _find_item(game, cmd.obj, actor.inventory)
    if not item_id:
        return [f"You aren't carrying a {cmd.obj}."]
    loc = game.world.get(actor.location_id)
    candidates = [c for c in loc.npcs if c != actor.id]
    if actor.id != "bilbo" and game.player.location_id == loc.id:
        candidates.append("bilbo")
    target_id = _find_character(game, cmd.indirect, candidates)
    if not target_id:
        # A companion can be commanded from anywhere (that is how you recall a
        # scout who has ranged ahead), but they can only hand something to
        # whoever shares their room. When the player tells such a companion to
        # give them something, "there is no bilbo here" blames the wrong
        # person -- the player IS Bilbo. Name the one who is actually away.
        if actor.id != "bilbo" and _find_character(game, cmd.indirect, ["bilbo"]):
            return [f"{actor.name} isn't here beside you to hand it over."]
        return [f"There is no {cmd.indirect} here."]
    target = game.characters[target_id]
    item = game.items.get(item_id)
    shed: list[str] = []
    if not game.can_carry(target, item):
        # Rather than refuse, they set down lighter oddments to take it.
        shed = _make_room_for(game, target, item, loc)
        if not game.can_carry(target, item):
            return [f"{target.name} has no room for {_the(_display_name(item))} -- they can "
                    f"carry only {target.max_carry} in weight, and nothing lighter to spare."]
    actor.inventory.remove(item_id)
    actor.disarm_if_lost(item_id)
    target.inventory.append(item_id)
    # Putting the Heart of the Mountain into Thorin's hands is a moment the
    # whole company remembers.
    messages: list[str] = []
    if shed:
        messages.append(f"{target.name} sets down {ui.join_names(shed)} to make room.")
    if item_id == ARKENSTONE and target_id == "thorin":
        game.company_news(
            "Bilbo gave the Arkenstone into Thorin's own hands",
            announce="Word runs through the company: the Arkenstone is found, and "
                     "Bilbo has given it to Thorin.")
        return messages + [Note(
            f"{actor.name} places the Arkenstone in Thorin's hands. The "
            "dwarf-lord stares into its depths, and for once there is no "
            "grimness in him at all. \"You have given me a king's gift, "
            "Mr. Baggins.\"")]
    return messages + [f"{actor.name} gives {_the(_display_name(item))} to {target.name}."]


def _make_room_for(game: "Game", target: Character, item, loc) -> list[str]:
    """Shed lighter oddments so a companion can accept something better --
    lightest first. Never drops the weapon in hand, never strips them of their
    last couple of meals, never sheds anything of worth (nobody sets down the
    Arkenstone -- or the ring, which weighs nothing at all -- to hold a loaf),
    and never sheds anything as heavy as the thing being handed over. Returns
    what was set down."""
    need = item.weight - game.free_capacity(target)
    if need <= 0:
        return []
    protected: set[int] = set()
    if target.wielded and target.wielded in target.inventory:
        protected.add(target.inventory.index(target.wielded))
    kept_food = 0
    for idx, held in enumerate(target.inventory):
        if game.items.get(held).is_food and kept_food < 2:
            protected.add(idx)
            kept_food += 1
    candidates = sorted(
        (game.items.get(held).weight, idx, held)
        for idx, held in enumerate(target.inventory)
        if idx not in protected
        and game.items.get(held).value == 0
        and game.items.get(held).weight < item.weight)
    freed, chosen = 0, []
    for weight, idx, held in candidates:
        chosen.append((idx, held))
        freed += weight
        if freed >= need:
            break
    if freed < need:
        return []  # even shedding everything spare wouldn't make room
    dropped: list[str] = []
    for idx, held in sorted(chosen, reverse=True):  # from the back, so indices hold
        target.inventory.pop(idx)
        target.disarm_if_lost(held)
        loc.items.append(held)
        dropped.append(held)
    # Stack repeats, so shedding six loaves doesn't print six times.
    counts = Counter(dropped)
    return [f"{_display_name(game.items.get(i))} (x{n})" if n > 1
            else _display_name(game.items.get(i))
            for i, n in counts.items()]


_DOOR_WORDS = ("door", "gate", "way", "chest", "box")

# Everything a player might reach for when they mean "get in a barrel".
_BARREL_WORDS = {"barrel", "barrels", "trapdoor", "trap-door", "trap door",
                 "hatch", "river", "water", "black water", "cask", "casks"}


def _find_lockable_neighbor(game: "Game", loc, cmd_obj: str):
    """A locked exit blocks its destination room, not the room you're
    standing in -- so 'open'/'close' need to look at neighboring rooms
    reached by an exit, not just the actor's current location. Returns
    the first neighboring Location that has a lock mechanism (a key_item
    defined), or None."""
    if cmd_obj not in loc.name.lower() and cmd_obj not in _DOOR_WORDS:
        return None
    for dest_id in loc.exits.values():
        dest = game.world.get(dest_id)
        if dest.key_item is not None:
            return dest
    return None


def _scenery_text(scenery, room) -> str:
    """A lock reads differently once its key has turned.

    The keyhole on the Secret Door poses a riddle -- small, silver, found by
    moonlight -- but you can only stand in that room after you've solved it,
    so the riddle would always be read by someone holding the answer. Rooms
    that carry a puzzle in their scenery get a second reading for after.
    """
    return scenery.description if room.locked else scenery.opened_description


def _open_locked_room(actor: Character, room, game: "Game") -> list[str]:
    """Shared 'you have the key -> unlock it' handling for a locked room.

    Name the key that turned. You may be carrying four of them by the Lonely
    Mountain, and a key hauled the length of the world deserves its moment.
    """
    key = game.items.get(room.key_item) if room.key_item else None
    revealed = room.open_up()
    names = ", ".join(game.items.get(i).name for i in revealed) if revealed else ""
    msg = (f"You unlock and open it with {_the(key.name)}."
           if key else "You unlock and open it.")
    if names:
        msg += f" Inside you find: {names}."
    return [msg]


def _locked_hint(game: "Game", room) -> str:
    """Say WHICH key is wanted. The bare 'you don't have the key' left players
    with no idea what to look for -- and the key's own name is right here."""
    if room.key_item:
        key = game.items.get(room.key_item)
        if key:
            return f"It's locked. You'd need {ui.with_article(key.name)}."
    return "It's locked, and you don't have the key."


def do_open(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Open what?"]
    loc = game.world.get(actor.location_id)

    if game.authentic:
        # Pre-fix behavior: 'open' only ever acts on the room you're standing
        # in. A locked room reached through an exit can never be unlocked
        # (you can't get inside to open it), reproducing the original-flavor
        # dead ends -- the Trolls' Cave, Goblin Dungeon and Secret Door.
        if cmd.obj in loc.name.lower() or cmd.obj in _DOOR_WORDS:
            if not loc.locked:
                return ["It's already open."]
            if loc.key_item and loc.key_item in actor.inventory:
                return _open_locked_room(actor, loc, game)
            return [_locked_hint(game, loc)]
        return [f"You can't open the {cmd.obj}."]

    neighbor = _find_lockable_neighbor(game, loc, cmd.obj)
    if neighbor:
        if not neighbor.locked:
            return ["It's already open."]
        if neighbor.key_item in actor.inventory:
            return _open_locked_room(actor, neighbor, game)
        return [_locked_hint(game, neighbor)]
    scenery = loc.find_scenery(cmd.obj)
    if scenery:
        messages = ["It's already open.", Note(_scenery_text(scenery, loc))]
        return messages
    if cmd.obj in loc.name.lower() or cmd.obj in _DOOR_WORDS:
        return ["It's already open."]
    return [f"You can't open the {cmd.obj}."]


def do_close(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Close what?"]
    loc = game.world.get(actor.location_id)

    if game.authentic:
        # Mirror the pre-fix 'open': act only on the current room. We still
        # require the room to actually have a lock, so a stray 'close' can't
        # brick an ordinary room (that particular softlock was a regression
        # in this recreation, not original-game behavior).
        if cmd.obj not in loc.name.lower() and cmd.obj not in _DOOR_WORDS:
            return [f"You can't close the {cmd.obj}."]
        if loc.key_item is None:
            return ["There's nothing here with a lock -- it can't be closed shut."]
        loc.locked = True
        return ["You close and lock it."]

    neighbor = _find_lockable_neighbor(game, loc, cmd.obj)
    if not neighbor:
        return ["There's nothing here with a lock -- it can't be closed shut."]
    if neighbor.locked:
        return ["It's already closed."]
    neighbor.locked = True
    return ["You close and lock it."]


def do_talk(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Talk to whom?"]
    loc = game.world.get(actor.location_id)
    target_id = _find_character(game, cmd.obj, loc.npcs)
    if not target_id:
        return [f"There is no {cmd.obj} here to talk to."]
    target = game.characters[target_id]
    prelude: list[str] = []
    # Speaking aloud gives you away as surely as striking does -- they answer
    # the voice, and there you are.
    if actor.id == "bilbo" and actor.invisible:
        actor.invisible = False
        if "ring" in actor.worn:
            actor.worn.remove("ring")
        prelude.append(Note("You speak, and the ring is no use to a voice out of "
                            "thin air -- you slip it off as they turn to you."))
    # In AI mode the NPC's brain generates an in-character line; otherwise
    # (or if the model is unavailable) fall back to the static dialogue.
    line = None
    speak = getattr(target, "speak", None)
    if speak is not None:
        line = speak(game)
    if not line:
        npc_def = game.npc_defs.get(target_id)
        line = npc_def.dialogue if npc_def else "..."
    else:
        # Record it so companions can react to (and avoid repeating) it.
        game.recent_events.append(f'{target.name} said: "{line}"')
    return prelude + [f'{target.name} says: "{line}"']


def do_look(game: "Game", actor: Character, cmd: Command) -> list[str]:
    return game.describe_location(actor)


def _describe_item(game: "Game", item_id: str) -> list[str]:
    item = game.items.get(item_id)
    messages = [Note(item.description) if item.added else item.description]
    return messages


def _describe_map(game: "Game", actor: Character, loc) -> list[str]:
    """Examining the map. At a moonlit reading table its moon-letters can be
    read, revealing what the silver key is for; elsewhere it's just the map
    (with a reminder, once you've read them)."""
    item = game.items.get("thorin_map")
    messages: list[str] = [Note(item.description)]
    if loc.moonlit:
        first = not game.moon_letters_read
        game.moon_letters_read = True
        lead = ("You tilt the map to the moonlit window. Silver moon-letters "
                "glimmer into view across the back:" if first else
                "Held to the moonlight, the moon-letters shine out again:")
        reveal = ("\"Stand by the grey stone when the thrush knocks, and the "
                  "setting sun with the last light of Durin's Day will shine "
                  "upon the key-hole.\" A smaller hand adds: the hidden door "
                  "lies in the Mountain's western side, and the slim silver "
                  "moon-letter key is the very one cut to open it.")
        messages += [Note(lead), Note(reveal)]
    elif game.moon_letters_read:
        messages.append(Note("(You have read its moon-letters: a hidden door "
                             "in the Mountain's western side, opened by the "
                             "silver moon-letter key.)"))
    return messages


def do_examine(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Examine what?"]
    loc = game.world.get(actor.location_id)
    if (loc.dark and actor.light_remaining <= 0
            and not game.player_can_see_in_dark(actor)):
        item_id = _find_item(game, cmd.obj, actor.inventory)
        return _describe_item(game, item_id) if item_id else ["It's too dark to see."]
    item_id = _find_item(game, cmd.obj, game.visible_items(loc) + actor.inventory)
    if item_id == "thorin_map" and not game.authentic:
        return _describe_map(game, actor, loc)
    if item_id:
        return _describe_item(game, item_id)
    char_id = _find_character(game, cmd.obj, loc.npcs)
    if char_id:
        char = game.characters[char_id]
        status = "unharmed"
        if not char.alive:
            status = "dead"
        elif char.is_fainted():
            status = "fainted from exhaustion"
        elif char.is_weak():
            status = "looking weak and hungry"
        return [f"{char.name}: {status}."]
    # The scenery/examine system is one of this recreation's additions, so in
    # authenticity mode it's disabled -- examining prose nouns fails just as
    # it did in the original.
    scenery = None if game.authentic else loc.find_scenery(cmd.obj)
    if scenery:
        messages = [Note(_scenery_text(scenery, loc))]
        return messages
    return [f"You see no {cmd.obj} here."]


def do_inventory(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not actor.inventory:
        return ["You are carrying nothing."]
    # Group identical items so a stack of loaves reads as "loaf of bread (x6)".
    counts = Counter(actor.inventory)
    parts = []
    for item_id, n in counts.items():
        label = _display_name(game.items.get(item_id))
        parts.append(f"{label} (x{n})" if n > 1 else label)
    return [f"You are carrying: {', '.join(parts)}. {_carry_line(game, actor)}"]


def _food_line(game: "Game", actor: Character) -> str:
    carry = f"carrying {game.carried_weight(actor)}/{actor.max_carry} in weight"
    food = game.carried_food(actor)
    if not food:
        return f"  Food: none -- stock up at a settlement. ({carry})"
    # Name what's actually in the pack -- a leg of mutton is not a loaf.
    counts = Counter(food)
    parts = [f"{game.items.get(i).name} (x{n})" if n > 1 else game.items.get(i).name
             for i, n in counts.items()]
    return f"  Food: {', '.join(parts)}. ({carry})"


# Words meaning "eat whatever food I have" rather than a specific item.
_EAT_ANY = {"food", "something", "a meal", "some food", "anything"}
# Generic free food a settlement offers -- taking any of these grabs a loaf.
_FOOD_GRAB_WORDS = {"loaf", "loaves", "bread", "food", "provisions", "provision",
                    "supplies", "supply", "ration", "rations"}


def do_eat(game: "Game", actor: Character, cmd: Command) -> list[str]:
    obj = (cmd.obj or "").strip().lower()
    if obj and obj not in _EAT_ANY:
        item_id = _find_item(game, cmd.obj, actor.inventory)
        if item_id:
            item = game.items.get(item_id)
            if not item.is_food:
                return [f"You can't eat {_the(_display_name(item))}."]
            actor.inventory.remove(item_id)
            actor.eat(item.food_value)
            return [f"You eat {_the(item.name)}. ({game.food_count(actor)} left)"]
        # fall through to eating whatever food is in the pack
    item = game.eat_one_food(actor)
    if item:
        return [f"You eat {_the(item.name)}. ({game.food_count(actor)} left)"]
    return ["You have no food left. Find a settlement and 'stock up' on loaves."]


def do_stock(game: "Game", actor: Character, cmd: Command) -> list[str]:
    loc = game.world.get(actor.location_id)
    if not loc.food_source:
        return ["There's nowhere to lay in provisions here. Look for an inn, "
                "Rivendell, Beorn's hall, or Lake-town."]
    added = game.fill_food(actor)
    if added == 0:
        return [f"You've no room for more -- {_carry_line(game, actor)}."]
    fare = game.items.get(game.staple_at(loc.id)).name
    return [f"You fill your pack with {fare}. {_carry_line(game, actor)}"]


def do_status(game: "Game", actor: Character, cmd: Command) -> list[str]:
    p = game.player
    if p.wielded:
        arms = f"wielding {game.items.get(p.wielded).name} (attack {p.attack_power})"
    else:
        arms = f"bare-handed (attack {p.attack_power})"
    lines = [f"Bilbo is {p.condition_word()}.",
             f"  Health {p.health}/{p.max_health}   "
             f"Hunger: {p.hunger_word()}   Fatigue: {p.fatigue_word()}",
             f"  In hand: {arms}.",
             _food_line(game, p)]
    if p.worn:
        worn = ui.join_names([_display_name(game.items.get(i)) for i in p.worn])
        lines.append(f"  Wearing: {worn}.")
    if p.invisible:
        lines.append(Note("  You are unseen -- nothing can find you, and the "
                          "company have lost sight of you."))
    if p.is_weak():
        lines.append("  He is weak -- eat something or rest soon, or hunger and "
                     "fatigue will wear his health away.")
    return lines


def do_party(game: "Game", actor: Character, cmd: Command) -> list[str]:
    from .npc import NPC
    members = [c for c in game.characters.values()
               if isinstance(c, NPC) and not c.def_.is_monster and c.def_.is_party]
    if not members:
        return ["You have no companions."]
    lines = ["The company:"]
    here = game.player.location_id
    for c in members:
        if not c.alive:
            where = f"fell at {c.death_place}" if c.death_place else "lost to you"
        elif c.captured:
            where = "captured!"
        elif c.location_id == here:
            where = "here"
        else:
            # Several wilderness rooms share a name (three Lone-lands...), so
            # a bare name is ambiguous -- give distance and direction too.
            d = game.world.distance(here, c.location_id)
            step = game.world.path_step(here, c.location_id)
            rooms = "a room" if d == 1 else f"{d} rooms"
            toward = f" to the {step}" if step in ("north", "south", "east", "west") else \
                     f" {step}" if step else ""
            where = f"at {game.world.get(c.location_id).name}, {rooms}{toward}"
        bearing = game.notable_carried(c)
        note = f" -- bearing {ui.join_names(bearing)}" if bearing else ""
        lines.append(f"  {c.name} -- {c.condition_word()} ({where}){note}.")
    # Bilbo stands in the roster too -- the haul is reckoned for the whole
    # company, and his own condition belongs beside everyone else's.
    mine = game.notable_carried(game.player)
    note = f" -- bearing {ui.join_names(mine)}" if mine else ""
    lines.append(f"  {game.player.name} (you) -- "
                 f"{game.player.condition_word()} (here){note}.")
    return lines


def do_wear(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Wear what?"]
    item_id = _find_item(game, cmd.obj, actor.inventory)
    if not item_id:
        return [f"You aren't carrying a {cmd.obj}."]
    item = game.items.get(item_id)
    if not item.wearable:
        return [f"You can't wear {_the(_display_name(item))}."]
    actor.worn.append(item_id)
    if item.id == "ring" and actor.id == "bilbo":
        actor.invisible = True
        return ["You slip the ring onto your finger and vanish from sight!",
                Note("The dwarves cast about, peering through you as though you "
                     "were not there.")]
    return [f"You put on {_the(_display_name(item))}."]


def do_remove(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Remove what?"]
    item_id = _find_item(game, cmd.obj, actor.worn)
    if not item_id:
        return [f"You aren't wearing a {cmd.obj}."]
    actor.worn.remove(item_id)
    item = game.items.get(item_id)
    if item.id == "ring" and actor.id == "bilbo":
        actor.invisible = False
        return ["You take off the ring and reappear."]
    return [f"You take off {_the(_display_name(item))}."]


def do_wield(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Wield what?"]
    item_id = _find_item(game, cmd.obj, actor.inventory)
    if not item_id:
        return [f"You aren't carrying a {cmd.obj}."]
    item = game.items.get(item_id)
    if not item.is_weapon:
        return [f"The {_display_name(item)} isn't a weapon."]
    actor.wield_weapon(item_id, item.damage, item.travel_mod)
    verb = "take up" if item.walking_aid else "wield"
    note = ""
    if item.walking_aid:
        note = " It steadies your steps on the road."
    elif item.travel_mod > 0:
        note = " Drawn steel is tiring to march with -- put it up when the road is quiet."
    return [f"You {verb} {_the(_display_name(item))}.{note}"]


def do_sheathe(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not actor.wielded:
        return ["You have nothing in hand."]
    name = game.items.get(actor.wielded).name
    actor.sheathe()
    return [f"You put away {_the(name)}."]


def do_light(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if not cmd.obj:
        return ["Light what?"]
    item_id = _find_item(game, cmd.obj, actor.inventory)
    if not item_id:
        return [f"You aren't carrying a {cmd.obj}."]
    item = game.items.get(item_id)
    if not item.is_light_source:
        return [f"You can't light {_the(_display_name(item))}."]
    if actor.light_remaining > 0:
        return [f"The {_display_name(item)} is already burning."]
    # No torch burns to a schedule. You know roughly how long a brand lasts;
    # you never know how long *this* one will, which is what makes pressing
    # deeper a decision rather than arithmetic.
    span = item.light_turns
    actor.light_remaining = game.rng.randint(int(span * 0.55), int(span * 1.2))
    return [f"The {_display_name(item)} flares to life, casting a warm glow."]


def do_rest(game: "Game", actor: Character, cmd: Command) -> list[str]:
    return [actor.rest()]


def do_barrel(game: "Game", actor: Character, cmd: Command) -> list[str]:
    """Ride the Elvenking's empty barrels out under the gate. Only those in
    the room go, so the company must be gathered first -- the gate is barred
    behind them and a straggler would have no way to follow."""
    loc = game.world.get(actor.location_id)
    if not loc.barrel_route:
        return ["There are no barrels here to ride."]
    adrift = game.company_adrift()
    if adrift:
        who = ui.join_names([c.name for c in adrift])
        where = ui.join_names(sorted({game.world.get(c.location_id).name for c in adrift}))
        return [f"You could climb into a barrel -- but {who} "
                f"{'is' if len(adrift) == 1 else 'are'} not here to come with you, "
                f"and the gate shuts behind the barrels. ({where}.)",
                Note("Gather the whole company here first -- lead them down, or "
                     "call them with '<name>, follow me'.")]
    # A captive cannot walk to the barrels, so waiting is not the answer --
    # but casting off strands them behind a barred gate for good. Say so once
    # and refuse; a second `barrel` is the player deciding to leave them.
    captives = game.company_captive()
    if captives and not getattr(game, "_barrel_warned", False):
        game._barrel_warned = True
        who = ui.join_names([c.name for c in captives])
        where = ui.join_names(sorted({game.world.get(c.location_id).name
                                      for c in captives}))
        return [f"You could climb into a barrel -- but {who} "
                f"{'is' if len(captives) == 1 else 'are'} still held captive, "
                f"and the gate shuts behind the barrels. ({where}.)",
                Note("Go back and cut them free, or say 'barrel' again to cast "
                     "off and leave them behind.")]
    dest_id = loc.barrel_route
    dest = game.world.get(dest_id)
    riders = [game.characters[cid] for cid in list(loc.npcs)
              if isinstance(game.characters.get(cid), object)
              and getattr(game.characters[cid], "def_", None)
              and game.characters[cid].def_.is_party and game.characters[cid].alive]
    for rider in riders:
        loc.npcs.remove(rider.id)
        rider.location_id = dest_id
        dest.npcs.append(rider.id)
    game.player.location_id = dest_id
    dest.visited = True
    game.player_follow = None          # the river does the leading now
    game.company_news(
        "the company escaped the Elvenking's halls by the river",
        announce="Word runs among you: the barrels carried the whole company clear.")
    return [
        Note("You tip yourself into an empty barrel and the trap-door bangs shut "
             "overhead. Black water takes it, and the world becomes a roaring, "
             "spinning dark."),
        Note("The barrels shoot the rapids under the gate. Somewhere behind, elvish "
             "horns cry out and there is shouting along the bank -- but the river is "
             "faster than they are, and the current bears you east, battered and "
             "soaked and free."),
    ]


def do_wait(game: "Game", actor: Character, cmd: Command) -> list[str]:
    """Let a turn pass without settling down. This is how you keep pace with
    someone you're following -- resting would break the march."""
    if actor.id == "bilbo" and game.player_follow:
        leader = game.characters.get(game.player_follow)
        if leader and leader.alive:
            return [f"You keep pace with {leader.name}."]
    return ["You wait a while."]


_FOLLOW_ME = {"me", "you", "bilbo", "us"}
_STOP_WORDS = {"stop", "none", "off", "nobody", "no one"}


def do_follow(game: "Game", actor: Character, cmd: Command) -> list[str]:
    obj = (cmd.obj or "").strip().lower()

    # An NPC ordered to follow the player: "thorin, follow me".
    if actor.id != "bilbo":
        if obj in _FOLLOW_ME or not obj:
            actor.forced_goal = "guard_bilbo"
            actor.goal_target = game.player.location_id
            actor.goal_age = 0
            return [f"{actor.name} moves to your side and will stay close."]
        if obj in _STOP_WORDS:
            actor.forced_goal = None
            return [f"{actor.name} falls back into the ranks."]
        return [f"{actor.name} isn't sure who you mean."]

    # The player choosing to trail a companion.
    if not obj or obj in _STOP_WORDS:
        if game.player_follow:
            name = game.characters[game.player_follow].name
            game.player_follow = None
            return [f"You stop following {name}."]
        return ["Follow whom?"]
    loc = game.world.get(actor.location_id)
    target_id = _find_character(game, obj, loc.npcs)
    if not target_id:
        return [f"There is no {cmd.obj} here to follow."]
    game.player_follow = target_id
    return [f"You resolve to follow {game.characters[target_id].name}. "
            "Wait or move and you'll go where they go; 'unfollow' to stop."]


def do_unfollow(game: "Game", actor: Character, cmd: Command) -> list[str]:
    """Stopping deserves its own word -- 'follow' alone meaning "stop
    following" was a pun, not a command."""
    if actor.id != "bilbo":
        # "thorin, stop" -- releases a companion pinned to your side.
        if actor.forced_goal:
            actor.forced_goal = None
            return [f"{actor.name} falls back into the ranks."]
        return [f"{actor.name} is under no such order."]
    if game.player_follow:
        name = game.characters[game.player_follow].name
        game.player_follow = None
        return [f"You stop following {name}."]
    return ["You aren't following anyone."]


def do_save(game: "Game", actor: Character, cmd: Command) -> list[str]:
    game.request_save = True
    return ["Game saved."]


def do_load(game: "Game", actor: Character, cmd: Command) -> list[str]:
    # The actual load (and its success/failure message) is handled by the
    # host loop, which knows whether a save file exists.
    game.request_load = True
    return []


def do_quit(game: "Game", actor: Character, cmd: Command) -> list[str]:
    game.request_quit = True
    return ["Farewell!"]


def do_help(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if game.authentic:
        # The purist vocabulary is the 1982 one: none of the recreation's
        # party/status/follow/stock verbs, so help must not advertise them.
        return [
            "Verbs: go/north/south/east/west/up/down, take, drop, attack, "
            "give X to Y, open, close, talk to, look, examine, inventory, eat, "
            "wear, remove, wield, light, rest, wait, save, load, quit.",
            "You can address a companion directly ('thorin, attack the goblin') "
            "and chain commands with 'and'/'then' ('take sword and go north') -- "
            "just as the original's Inglish parser allowed.",
            "You are playing the PURIST game -- the raw 1982-flavoured "
            "experience: reverted descriptions, the map is just wall flavour "
            "(not an object), no scenery/examine system, and the original quirky "
            "locks, so some rooms cannot be reached. This was chosen when the "
            "game began and holds for the whole journey.",
        ]
    return [
        "Verbs: go/north/south/east/west/up/down, take, drop, attack, give X to Y, "
        "open, close, talk to, look, examine, inventory, eat, wear, remove, wield, "
        "light, rest, wait, follow, unfollow, status, party, stock up, save, load, quit.",
        "You can address a companion directly ('thorin, attack the goblin' or "
        "'thorin, follow me') and chain commands with 'and'/'then' ('take sword and "
        "go north') -- just as the original's Inglish parser allowed.",
        Note("'status' shows how Bilbo is holding up; 'party' shows the company. Eat "
             "your provisions with 'eat' and refill your pack with 'stock up' at an "
             "inn, Rivendell, Beorn's hall, or Lake-town."),
        Note("'follow thorin' bids a companion take the lead for the Mountain and "
             "draws you along behind -- 'wait' keeps pace; 'unfollow' "
             "-- or 'stop following' -- hands the lead back to you. The company "
             "travel with you, fighting and fending for themselves along the way."),
        Note("You are playing the ENHANCED game. The purist game is a separate "
             "choice made when a new game begins, not a switch you can throw "
             "mid-journey. 'mode' reports which you're in."),
    ]


# Which game you are playing is settled when it begins and cannot change
# mid-journey: purist reverts content AND mechanics (the map is wall flavour
# again, locks misbehave, the Elvenking's gate is not barred and there are no
# barrels), so flipping halfway would rearrange the world around a company
# already standing in it.
_MODE_IS_FIXED = ("The mode is settled when a game begins and cannot be changed "
                  "mid-journey -- purist and enhanced are different worlds, not two "
                  "views of one. To play the other, begin a new game and choose it "
                  "at the start.")


def do_mode(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if game.authentic:
        return ["Mode: PURIST (1982-flavoured). Reverted content and the original "
                "broken locks -- some rooms are unreachable, and the game may not "
                "be winnable.", Note(_MODE_IS_FIXED)]
    return ["Mode: ENHANCED. Corrected descriptions, the map as a real item, "
            "working locks and scenery.",
            Note(_MODE_IS_FIXED)]


def do_purist(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if game.authentic:
        return ["You are already playing the purist game."]
    return [Note(_MODE_IS_FIXED)]


DISPATCH = {
    "go": do_go, "take": do_take, "drop": do_drop, "attack": do_attack,
    "give": do_give, "open": do_open, "close": do_close, "talk": do_talk,
    "look": do_look, "examine": do_examine, "inventory": do_inventory,
    "eat": do_eat, "wear": do_wear, "remove": do_remove, "wield": do_wield,
    "sheathe": do_sheathe,
    "light": do_light, "rest": do_rest, "wait": do_wait, "barrel": do_barrel,
    "follow": do_follow,
    "unfollow": do_unfollow,
    "stock": do_stock, "status": do_status, "party": do_party,
    "save": do_save, "load": do_load, "quit": do_quit, "help": do_help,
    "purist": do_purist, "mode": do_mode,
}


# What you can still do flat on your back: the very things that save you, if
# you had the foresight to carry them. You cannot fight or march while
# collapsed -- so letting yourself get that hungry, that far from supplies, is
# a real and sometimes fatal mistake. Reverted in purist, where even eating is
# refused and collapse is simply the end.
_LAST_STRENGTH_VERBS = {"eat", "rest", "wait", "drop"}


def _may_act_while_fainted(game: "Game", verb: str) -> bool:
    # Reporting commands always work -- being unable to `save` or `look` at
    # death's door would be hostile, not authentic.
    if verb in FREE_VERBS:
        return True
    return not game.authentic and verb in _LAST_STRENGTH_VERBS


def execute(game: "Game", actor: Character, cmd: Command) -> list[str]:
    if cmd.unknown:
        return [cmd.error or "I didn't understand that."]
    if not actor.alive:
        return [ui.sentence(f"{actor.name} cannot act -- they are dead.")]
    if actor.is_fainted() and not _may_act_while_fainted(game, cmd.verb):
        messages = [ui.sentence(f"{actor.name} is too weak from hunger and fatigue to act.")]
        if actor.id == "bilbo" and not game.authentic:
            # Not changelog -- the one thing a collapsed player needs to know
            # is that there IS a way back, and which commands still reach it.
            messages.append(Note(
                "You can still eat, rest and wait -- but not fight or march. "
                "Eat, if you have anything left to eat."))
        return messages
    handler = DISPATCH.get(cmd.verb)
    if not handler:
        return [f"I don't know how to '{cmd.raw}'."]
    return handler(game, actor, cmd)
