"""Crop rotation (CODE): don't plant the same plant family in the same plot year after year.

Extension guidance (e.g. Cornell, UMass, UMN) is to rotate crop families on a 3–4 year cycle,
because soil-borne diseases and pests build up when the same family returns to the same spot
(tomato early blight, clubroot in cabbage-family crops, onion maggot, squash bugs).
The rule matters most for the heavy-hitter families below; herbs, flowers and perennials are exempt.
"""

from __future__ import annotations

from .data import plants

FAMILY = {
    # nightshades
    "tomato_cherry": "nightshade", "tomato_slicing": "nightshade", "tomato_paste": "nightshade",
    "tomatillo": "nightshade", "pepper_bell": "nightshade", "pepper_jalapeno": "nightshade", "potato": "nightshade",
    # cabbage family
    "kale": "brassica", "arugula": "brassica", "radish": "brassica",
    # squash family
    "cucumber_pickling": "cucurbit", "zucchini": "cucurbit", "squash_butternut": "cucurbit", "pumpkin": "cucurbit",
    # onion family
    "garlic": "allium", "onion_sets": "allium", "scallion": "allium", "chives": "allium",
    # beans and peas (they add nitrogen: good to follow heavy feeders)
    "bean_bush": "legume", "bean_pole": "legume", "pea_snap": "legume",
    # beet/spinach family
    "beet": "goosefoot", "spinach": "goosefoot", "swiss_chard": "goosefoot",
    # carrot family
    "carrot": "umbel", "dill": "umbel", "parsley": "umbel", "cilantro": "umbel",
    # grasses
    "corn_sweet": "grass", "winter_rye": "grass",
}
FAMILY_LABEL = {"nightshade": "tomato family (tomatoes, peppers, potatoes)", "brassica": "cabbage family",
                "cucurbit": "squash family", "allium": "onion family", "legume": "bean & pea family",
                "goosefoot": "beet & spinach family", "umbel": "carrot family", "grass": "corn & grains"}
# Families where repeating in the same soil really causes trouble.
ROTATE = {"nightshade", "brassica", "cucurbit", "allium", "goosefoot", "umbel"}
YEARS = 3


def family_of(pid: str) -> str | None:
    p = plants().get(pid)
    if p is None or p.season == "perennial":
        return None
    return FAMILY.get(pid)


def history_from_seasons(seasons: list[dict]) -> list[dict]:
    """[{"year": 2025, "plants": [...], "families": [...]}] from a plot's earlier seasons."""
    out = []
    for g in seasons:
        fams = sorted({f for pid in g["chosen"] if (f := family_of(pid))})
        out.append({"year": g["start_date"].year, "plants": list(g["chosen"]), "families": fams})
    return out


def recent_families(history: list[dict], this_year: int) -> dict[str, int]:
    """Rotation-sensitive family → most recent year it grew in this plot (within the rotation window)."""
    recent: dict[str, int] = {}
    for h in history:
        if this_year - h["year"] < YEARS:
            for f in h["families"]:
                if f in ROTATE:
                    recent[f] = max(recent.get(f, 0), h["year"])
    return recent


def conflicts(pids: list[str], history: list[dict], this_year: int) -> list[tuple[str, str, int]]:
    """(plant_id, family, last_year) for picks that repeat a rotation-sensitive family too soon."""
    recent = recent_families(history, this_year)
    out = []
    for pid in pids:
        f = family_of(pid)
        if f in recent:
            out.append((pid, f, recent[f]))
    return out


def tips(history: list[dict], this_year: int, space_type: str) -> list[str]:
    if not history:
        return []
    recent = recent_families(history, this_year)
    lines = []
    if recent:
        names = "; ".join(f"{FAMILY_LABEL[f]} in {y}" for f, y in sorted(recent.items(), key=lambda kv: -kv[1]))
        lines.append(f"🔁 **Crop rotation:** this plot grew the {names}. Extension guides suggest waiting "
                     f"{YEARS} years before planting a family in the same spot again, to keep soil diseases and "
                     "pests from building up.")
    if "nightshade" in recent or "cucurbit" in recent or "brassica" in recent:
        lines.append("🫘 Beans and peas are a great follow-up: they're a different family and add nitrogen "
                     "back to the soil.")
    if space_type in ("containers", "windowsill"):
        lines.append("🪴 In containers, replacing the potting mix each year does most of the work of rotation.")
    return lines
