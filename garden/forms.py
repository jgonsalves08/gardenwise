"""Turns the intake form's friendly answers into Constraints fields (CODE, no LLM)."""

from __future__ import annotations

from datetime import date

SUN_GUESSES = {
    "Mostly sunny": "full",
    "Some sun, some shade": "part",
    "Mostly shady": "shade",
}
FACINGS = ["South", "East", "West", "North"]

SIZE_PRESETS: dict[str, dict[str, tuple[float, float]]] = {
    "raised_bed": {
        "Small — one 4 × 4 ft bed": (4, 4),
        "Medium — one 4 × 8 ft bed": (4, 8),
        "Large — two 4 × 8 ft beds (8 × 8 ft)": (8, 8),
    },
    "in_ground": {
        "Small — about 5 × 10 ft": (5, 10),
        "Medium — about 10 × 10 ft": (10, 10),
        "Large — about 15 × 20 ft": (15, 20),
    },
}
SPACE_LABELS = {
    "containers": "🪴 Containers (balcony, patio, steps)",
    "raised_bed": "🟫 Raised bed(s)",
    "in_ground": "🌱 In-ground plot",
    "windowsill": "🪟 Windowsill only",
}
SKILL_LABELS = {
    "beginner": "🌱 Beginner — first season",
    "intermediate": "🌿 Intermediate — a few seasons in",
    "experienced": "🌳 Experienced",
}
START_LABELS = {
    "now": "Right away",
    "month": "In a specific month",
    "best_time": "When the time is right for my plants",
    "next_season": "Plan ahead for next season",
}


def estimate_sun(guess: str | None, facing: str | None, blocked: bool) -> tuple[str, str]:
    """Returns (sun level, plain-English basis). Never asks the user to measure anything."""
    if guess in SUN_GUESSES:
        return SUN_GUESSES[guess], f"your estimate: “{guess.lower()}”"
    if facing in FACINGS:
        basis = f"estimated from {facing.lower()}-facing" + (" with some blocking" if blocked else "")
        if facing == "South":
            return ("part" if blocked else "full"), basis
        if facing in ("East", "West"):
            return ("shade" if blocked else "part"), basis
        return "shade", basis
    return "unknown", "not given — favoring plants that handle full or part sun"


def start_date_for(mode: str, today: date, month_choice: date | None) -> date:
    if mode == "month" and month_choice:
        return max(today, month_choice)
    if mode == "next_season":
        return date(today.year + 1, 2, 1) if today.month >= 7 else today
    return today


def month_options(today: date, n: int = 12) -> list[date]:
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(date(y, m, 1))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out

AUDIENCE_LABELS = {
    "me": "🧑 Just me",
    "household": "👨‍👩‍👧 My household",
    "school": "🏫 A school or classroom",
    "community": "🏘️ A community garden",
}
