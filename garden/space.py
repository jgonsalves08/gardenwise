"""Space math (CODE): which plants suit the space, how many fit, and a simple bed layout.

Beds and in-ground plots use square-foot-gardening squares (1 ft x 1 ft).
Plants with per_sqft >= 1 fit several to a square; bigger plants take several squares.
In-ground plots lose ~30% of their area to paths.
"""

from __future__ import annotations

import math

from .data import Plant
from .schemas import Allocation, Constraints

IN_GROUND_USABLE = 0.7
MIN_CAP_SQUARES_SMALL = 4          # small plants: up to at least 4 sq ft each
MAX_CAP_SQUARES_SMALL = 16         # ...and never more than 16 sq ft of one crop
MAX_PLANTS_SMALL = 48              # a household doesn't need 200 cloves of garlic
MIN_CAP_BIG_PLANTS = 4             # big plants (tomato, squash): at least 4 each
MAX_CAP_BIG_PLANTS = 8
MAX_SHARE = 0.4                    # no single plant takes more than ~40% of the space


def suits_space(plant: Plant, c: Constraints) -> bool:
    if c.space_type == "windowsill":
        return plant.indoor_ok
    if c.space_type == "containers":
        return plant.container_ok and not plant.sprawling
    if plant.season == "indoor":
        return False
    return True


def usable_squares(c: Constraints) -> int:
    if c.space_type == "raised_bed":
        return int(c.width_ft * c.length_ft)
    if c.space_type == "in_ground":
        return int(c.width_ft * c.length_ft * IN_GROUND_USABLE)
    return 0


def squares_per_unit(plant: Plant) -> int:
    """Squares one planting unit takes (a unit = one square of small plants, or one big plant)."""
    if plant.per_sqft >= 1:
        return 1
    return math.ceil(1 / plant.per_sqft)


def plants_per_unit(plant: Plant) -> int:
    return int(plant.per_sqft) if plant.per_sqft >= 1 else 1


def container_size_class(plant: Plant) -> str:
    gal = plant.min_container_gal or 2
    if gal <= 2:
        return "pot_small"
    if gal <= 5:
        return "pot_medium"
    return "pot_large"


def min_footprint(plants: list[Plant], c: Constraints) -> int:
    """Squares (or containers) needed for one unit of every plant."""
    if c.space_type in ("containers", "windowsill"):
        return len(plants)
    return sum(squares_per_unit(p) for p in plants)


def capacity(c: Constraints) -> int:
    if c.space_type in ("containers", "windowsill"):
        return c.num_containers
    return usable_squares(c)


def sizes_to_people(c: Constraints) -> bool:
    return c.audience in ("me", "household")


def plants_in_unit(p: Plant, c: Constraints) -> int:
    if c.space_type in ("containers", "windowsill"):
        return max(1, min(plants_per_unit(p), 4)) if p.per_sqft >= 1 else 1
    return plants_per_unit(p)


def target_count(p: Plant, c: Constraints) -> int | None:
    """Plants needed to feed this many people for a season (None = no guideline / not sizing)."""
    if not sizes_to_people(c) or not p.plants_per_person:
        return None
    return max(1, math.ceil(p.plants_per_person * c.people))


def target_units(p: Plant, c: Constraints) -> int | None:
    t = target_count(p, c)
    return None if t is None else max(1, math.ceil(t / plants_in_unit(p, c)))


def coverage(allocs: list[Allocation], plants: dict[str, Plant], c: Constraints) -> list[tuple[str, int, int]]:
    """(plant_id, planned, needed) for crops with a per-person guideline."""
    out = []
    for a in allocs:
        need = target_count(plants[a.plant_id], c)
        if need is not None:
            out.append((a.plant_id, a.count, need))
    return out


def allocate(plants: list[Plant], c: Constraints) -> list[Allocation]:
    """Round-robin: give every plant one unit, then keep adding units until space runs out."""
    cap = capacity(c)
    units = {p.id: 0 for p in plants}
    used = 0

    def unit_cost(p: Plant) -> int:
        return 1 if c.space_type in ("containers", "windowsill") else squares_per_unit(p)

    def at_limit(p: Plant) -> bool:
        n = units[p.id]
        target = target_units(p, c)
        if target is not None:
            return n >= target  # sized to how much the household will eat
        if c.space_type in ("containers", "windowsill"):
            return n >= max(1, math.ceil(cap / max(1, len(plants))) + 1)
        share = MAX_SHARE * cap
        if p.per_sqft < 1:
            limit = min(MAX_CAP_BIG_PLANTS, max(MIN_CAP_BIG_PLANTS, int(share // squares_per_unit(p))))
            return n >= limit
        by_count = max(1, math.ceil(MAX_PLANTS_SMALL / plants_per_unit(p)))
        limit = min(MAX_CAP_SQUARES_SMALL, by_count, max(MIN_CAP_SQUARES_SMALL, int(share)))
        return n >= limit

    progress = True
    while progress:
        progress = False
        for p in plants:
            cost = unit_cost(p)
            if used + cost <= cap and not at_limit(p):
                units[p.id] += 1
                used += cost
                progress = True

    out = []
    for p in plants:
        n = units[p.id]
        if c.space_type in ("containers", "windowsill"):
            out.append(Allocation(plant_id=p.id, count=n * plants_in_unit(p, c), containers=n))
        else:
            out.append(Allocation(plant_id=p.id, count=n * plants_per_unit(p), squares=n * squares_per_unit(p)))
    return out


def layout_grid(allocs: list[Allocation], plants: dict[str, Plant], c: Constraints,
                max_cols: int = 16, max_rows: int = 16) -> list[list[str | None]]:
    """A top-down grid (north at top). Tall plants go on the north rows so they don't shade others."""
    if c.space_type in ("containers", "windowsill"):
        return []
    cols = max(1, min(int(c.width_ft), max_cols))
    total = sum(a.squares for a in allocs)
    rows = max(1, min(math.ceil(total / cols), max_rows))
    order = sorted(allocs, key=lambda a: (not plants[a.plant_id].tall, plants[a.plant_id].sprawling))
    cells: list[str | None] = []
    for a in order:
        cells.extend([a.plant_id] * a.squares)
    cells = cells[: rows * cols]
    cells += [None] * (rows * cols - len(cells))
    grid = [cells[r * cols:(r + 1) * cols] for r in range(rows)]
    # Snake every other row so a plant's squares stay next to each other.
    for r in range(1, rows, 2):
        grid[r].reverse()
    return grid
