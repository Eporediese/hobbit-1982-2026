"""Attack resolution shared by the player and NPCs."""
from __future__ import annotations

import random

from . import ui
from .entities import Character


def resolve_attack(attacker: Character, defender: Character, rng: random.Random) -> list[str]:
    """Run one round of combat. Mutates health on both sides. Returns
    narrative messages."""
    messages: list[str] = []

    if not attacker.alive or not defender.alive:
        return messages

    if defender.invisible and rng.random() < 0.6:
        messages.append(ui.sentence(f"{attacker.name} swings at where {defender.name} was, but misses "
                         f"-- {defender.name} is nowhere to be seen!"))
        return messages

    attacker.add_combat_fatigue()
    power = attacker.effective_attack()
    if power <= 0:
        messages.append(ui.sentence(f"{attacker.name} is too exhausted to fight."))
        return messages

    hit_chance = 0.75
    if rng.random() > hit_chance:
        messages.append(ui.sentence(f"{attacker.name} attacks {defender.name} and misses."))
        return messages

    damage = max(1, rng.randint(power // 2, power))
    defender.take_damage(damage)
    messages.append(ui.sentence(f"{attacker.name} hits {defender.name} for {damage} damage."))

    if not defender.alive:
        messages.append(ui.sentence(f"{defender.name} has been defeated!"))

    return messages
