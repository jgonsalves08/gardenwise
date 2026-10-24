"""Seed and transplant cost estimates (CODE). Prices live in data/builds.json → plant_prices."""

from __future__ import annotations

import math
from urllib.parse import quote_plus

from .data import Plant, builds
from .schemas import Allocation, MaterialLine, PlantSchedule


def _links(search: str) -> dict[str, str]:
    templates = builds()["store_link_templates"]
    return {store: t.format(query=quote_plus(search)) for store, t in templates.items()}


def _line(item: str, qty: int, price: float, search: str) -> MaterialLine:
    return MaterialLine(item=item, qty=qty, unit_price=price, subtotal=round(qty * price, 2),
                        store_links=_links(search))


def plant_cost_lines(chosen: list[Plant], allocs: list[Allocation],
                     schedules: list[PlantSchedule]) -> list[MaterialLine]:
    pp = builds()["plant_prices"]
    count = {a.plant_id: a.count for a in allocs}
    method = {s.plant_id: s.method for s in schedules}
    lines = []
    for p in chosen:
        n = max(1, count.get(p.id, 1))
        m = method.get(p.id, "direct_sow")
        if p.id == "garlic":
            lb = math.ceil(n / pp["garlic_cloves_per_lb"])
            lines.append(_line("Seed garlic (hardneck), 1 lb", lb, pp["garlic_lb"], "seed garlic"))
        elif p.id == "onion_sets":
            bags = math.ceil(n / pp["onion_sets_per_bag"])
            lines.append(_line("Onion sets (bag)", bags, pp["onion_sets_bag"], "onion sets"))
        elif m == "indoor":
            lines.append(_line(f"{p.name} seed kit", 1, pp["microgreen_kit"], f"{p.name} seeds"))
        elif m == "buy_transplants":
            if p.season == "perennial" or p.category == "flower" and p.per_sqft < 1:
                lines.append(_line(f"{p.name} plant (quart/gallon pot)", n, pp["perennial_pot"],
                                   f"{p.name} plant"))
            elif p.per_sqft < 1 or n < 4:
                lines.append(_line(f"{p.name} transplant", n, pp["single_transplant"],
                                   f"{p.name} plant"))
            else:
                lines.append(_line(f"{p.name} transplants (6-pack)", math.ceil(n / 6), pp["six_pack"],
                                   f"{p.name} plants"))
        else:  # direct_sow or start_indoors: one seed packet covers a home garden
            lines.append(_line(f"{p.name} seed packet", 1, pp["seed_packet"], f"{p.name} seeds"))
    return lines
