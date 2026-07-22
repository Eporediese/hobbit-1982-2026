"""Shared character state: player and NPCs both derive from Character so
hunger/fatigue, inventory, and combat stats work identically for both."""
from __future__ import annotations

from typing import Any

HUNGER_WEAK = 60
HUNGER_FAINT = 100
FATIGUE_WEAK = 60
FATIGUE_FAINT = 100

# With food now plentiful at settlements, hunger should be a real pressure:
# it climbs every turn and marching works up an appetite besides.
HUNGER_PER_TURN = 2
HUNGER_PER_TRAVEL = 1
FATIGUE_PER_TURN = 1
FATIGUE_PER_TRAVEL = 2
FATIGUE_PER_COMBAT_ROUND = 4

DEFAULT_MAX_CARRY = 12  # total WEIGHT (food + gear) an ordinary traveller can carry


class Character:
    def __init__(self, char_id: str, name: str, location_id: str,
                 health: int = 20, attack: int = 3, aliases: list[str] | None = None):
        self.id = char_id
        self.name = name
        self.location_id = location_id
        self.inventory: list[str] = []
        self.worn: list[str] = []
        self.wielded: str | None = None
        self.light_remaining: int = 0
        self.health = health
        self.max_health = health
        self.base_attack = attack   # unarmed strength
        self.attack_power = attack  # base_attack, or the wielded weapon's bite
        self.travel_mod = 0         # per-weapon change to march fatigue
        self.hunger = 0
        self.fatigue = 0
        # Whether hunger and fatigue apply to this character at all. Travellers
        # (the player and companions) must eat and rest; monsters don't -- a
        # dragon in its lair should never starve to death waiting for you.
        self.feels_needs = True
        self.alive = True
        self.invisible = False
        self.aliases = aliases or []
        # How many food items this character can carry in their pack.
        self.max_carry = DEFAULT_MAX_CARRY
        # Where this character fell, if they died (shown in 'party').
        self.death_place: str | None = None

    # -- needs -----------------------------------------------------------
    def is_weak(self) -> bool:
        return self.hunger >= HUNGER_WEAK or self.fatigue >= FATIGUE_WEAK

    def is_fainted(self) -> bool:
        return self.hunger >= HUNGER_FAINT or self.fatigue >= FATIGUE_FAINT

    def hunger_word(self) -> str:
        if self.hunger >= HUNGER_FAINT:
            return "starving"
        if self.hunger >= HUNGER_WEAK:
            return "famished"
        if self.hunger >= HUNGER_WEAK * 0.5:
            return "hungry"
        if self.hunger >= HUNGER_WEAK * 0.25:
            return "peckish"
        return "well-fed"

    def fatigue_word(self) -> str:
        if self.fatigue >= FATIGUE_FAINT:
            return "ready to drop"
        if self.fatigue >= FATIGUE_WEAK:
            return "exhausted"
        if self.fatigue >= FATIGUE_WEAK * 0.5:
            return "weary"
        if self.fatigue >= FATIGUE_WEAK * 0.25:
            return "tiring"
        return "rested"

    def needs_health_drain(self) -> int:
        """Health lost this turn to hunger/fatigue: none until you're weak,
        then a steady wearing-down, worse once you've collapsed."""
        if not self.feels_needs:
            return 0
        if self.is_fainted():
            return 3
        if self.is_weak():
            return 1
        return 0

    def is_badly_hurt(self) -> bool:
        return self.health <= self.max_health // 3

    def effective_attack(self) -> int:
        power = self.attack_power
        if self.is_fainted():
            return 0
        if self.is_weak():
            power = max(1, power // 2)
        if self.is_badly_hurt():  # a wounded fighter strikes weakly
            power = max(1, (power * 3) // 5)
        return power

    def tick_needs(self) -> list[str]:
        """Advance hunger/fatigue by one turn. Returns messages about state
        transitions (e.g. becoming weak or fainting)."""
        messages: list[str] = []
        if not self.feels_needs:
            return messages
        was_weak, was_fainted = self.is_weak(), self.is_fainted()
        self.hunger = min(HUNGER_FAINT, self.hunger + HUNGER_PER_TURN)
        self.fatigue = min(FATIGUE_FAINT, self.fatigue + FATIGUE_PER_TURN)
        if self.is_fainted() and not was_fainted:
            messages.append(f"{self.name} faints from exhaustion and hunger!")
        elif self.is_weak() and not was_weak:
            messages.append(f"{self.name} feels weak with hunger and fatigue.")
        return messages

    def add_travel_fatigue(self, load_mod: int = 0) -> None:
        if not self.feels_needs:
            return  # a monster does not tire of guarding its lair
        # What's in hand changes the march: a drawn sword is wearying
        # (travel_mod +1), a walking staff eases the road (travel_mod -1).
        # A heavy pack (load_mod, supplied by the caller, which knows what
        # everything weighs) tells on you too.
        step = max(0, FATIGUE_PER_TRAVEL + self.travel_mod + load_mod)
        self.fatigue = min(FATIGUE_FAINT, self.fatigue + step)
        self.hunger = min(HUNGER_FAINT, self.hunger + HUNGER_PER_TRAVEL)

    def sheathe(self) -> None:
        self.wielded = None
        self.attack_power = self.base_attack
        self.travel_mod = 0

    def add_combat_fatigue(self) -> None:
        # Everything tires from a real fight, monsters included -- a long
        # battle wears a beast down, so persistence pays. (Monsters recover
        # between fights; see Game._advance_world_turn. And penning prisoners
        # is not fighting, so it costs them nothing -- see combat_hostiles.)
        #
        # This does mean a boss weakens as a long fight drags on -- Smaug's
        # blows drop from 17 to 10 once he tires. That looks backwards, and
        # exempting bosses was tried; but measured over 40 fights it changed
        # nothing for a full company (which wins long before he tires) and
        # halved a battered one's already-slim odds. It is the underdog's
        # lifeline, so it stays.
        self.fatigue = min(FATIGUE_FAINT, self.fatigue + FATIGUE_PER_COMBAT_ROUND)

    def eat(self, food_value: int) -> str:
        self.hunger = max(0, self.hunger - food_value)
        return f"{self.name} feels better after eating."

    def condition_word(self) -> str:
        """A plain-language summary of how this character is holding up."""
        if not self.alive:
            return "dead"
        if self.is_fainted():
            return "collapsed from hunger and exhaustion"
        parts = []
        if self.hunger >= HUNGER_WEAK:
            parts.append("famished")
        elif self.hunger >= HUNGER_WEAK * 0.6:
            parts.append("hungry")
        if self.fatigue >= FATIGUE_WEAK:
            parts.append("exhausted")
        elif self.fatigue >= FATIGUE_WEAK * 0.6:
            parts.append("weary")
        if self.health <= self.max_health // 3:
            parts.append("badly hurt")
        elif self.health < self.max_health:
            parts.append("wounded")
        return ", ".join(parts) if parts else "hale and well-fed"

    def rest(self, amount: int = 40, mend: int = 2) -> str:
        self.fatigue = max(0, self.fatigue - amount)
        # Rest knits wounds a little, too.
        self.health = min(self.max_health, self.health + mend)
        return f"{self.name} rests and recovers some energy."

    def wield_weapon(self, item_id: str, damage: int, travel_mod: int = 0) -> None:
        self.wielded = item_id
        self.attack_power = max(self.base_attack, damage)
        self.travel_mod = travel_mod

    def disarm_if_lost(self, item_id: str) -> None:
        """Called when an item leaves this character's hands: if it was the
        wielded weapon (and no copy remains), fight bare-handed again."""
        if self.wielded == item_id and item_id not in self.inventory:
            self.sheathe()

    def take_damage(self, amount: int) -> None:
        self.health = max(0, self.health - amount)
        if self.health == 0:
            self.alive = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "location_id": self.location_id,
            "inventory": self.inventory, "worn": self.worn, "wielded": self.wielded,
            "light_remaining": self.light_remaining,
            "health": self.health, "max_health": self.max_health,
            "attack_power": self.attack_power,
            "base_attack": self.base_attack,
            "travel_mod": self.travel_mod,
            "death_place": self.death_place,
            "hunger": self.hunger, "fatigue": self.fatigue,
            "alive": self.alive, "invisible": self.invisible,
            "max_carry": self.max_carry,
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        self.location_id = data["location_id"]
        self.inventory = data["inventory"]
        self.worn = data.get("worn", [])
        self.wielded = data.get("wielded")
        self.light_remaining = data.get("light_remaining", 0)
        self.health = data["health"]
        self.max_health = data["max_health"]
        self.attack_power = data["attack_power"]
        self.base_attack = data.get("base_attack", self.base_attack)
        self.travel_mod = data.get("travel_mod", 0)
        self.death_place = data.get("death_place")
        self.hunger = data["hunger"]
        self.fatigue = data["fatigue"]
        self.alive = data["alive"]
        self.invisible = data.get("invisible", False)
        self.max_carry = data.get("max_carry", self.max_carry)


class Player(Character):
    def __init__(self, location_id: str):
        super().__init__("bilbo", "Bilbo Baggins", location_id, health=25, attack=3)
        self.has_ring = False
