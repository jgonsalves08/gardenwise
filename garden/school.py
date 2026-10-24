"""School-garden rules (CODE): harvests should land while students are in the building.

School gardens commonly fail over summer break: crops ripen in July with nobody there.
Without summer care, each plant must have at least part of its harvest window inside the
school year. With summer care, we add a weekly summer-care rota to the calendar instead.
"""

from __future__ import annotations

from datetime import date, timedelta

from .schemas import Constraints, PlantSchedule, Task

MIN_SCHOOL_HARVEST_DAYS = 7


def _sessions(c: Constraints, around: date) -> list[tuple[date, date]]:
    """School-year sessions near a date (previous, current, next year)."""
    if not (c.school_start and c.school_end):
        return []
    out = []
    for dy in (-1, 0, 1, 2):
        try:
            s = c.school_start.replace(year=c.school_start.year + dy)
            e = c.school_end.replace(year=c.school_end.year + dy)
        except ValueError:  # Feb 29
            continue
        out.append((s, e))
    return out


def school_days_between(c: Constraints, start: date, end: date) -> int:
    days = 0
    for s, e in _sessions(c, start):
        lo, hi = max(s, start), min(e, end)
        if hi >= lo:
            days += (hi - lo).days + 1
    return days


def harvest_in_school(s: PlantSchedule, c: Constraints) -> bool:
    return school_days_between(c, s.harvest_start, s.harvest_end) >= MIN_SCHOOL_HARVEST_DAYS


def summer_breaks(c: Constraints, start: date, end: date) -> list[tuple[date, date]]:
    out = []
    sess = _sessions(c, start)
    for (s1, e1), (s2, _e2) in zip(sess, sess[1:]):
        b_start, b_end = e1 + timedelta(days=1), s2 - timedelta(days=1)
        if b_end >= start and b_start <= end:
            out.append((max(b_start, start), min(b_end, end)))
    return out


def summer_care_tasks(schedules: list[PlantSchedule], c: Constraints) -> list[Task]:
    """One task per summer week while something is growing: who waters and harvests."""
    if c.audience != "school" or not c.summer_care or not schedules:
        return []
    first = min(s.plant_out for s in schedules)
    last = max(s.harvest_end for s in schedules)
    tasks = []
    for b_start, b_end in summer_breaks(c, first, last):
        week = b_start - timedelta(days=b_start.weekday())  # Monday
        while week <= b_end:
            growing = [s.plant_id for s in schedules if s.plant_out <= week + timedelta(days=6)
                       and s.harvest_end >= week]
            if growing:
                tasks.append(Task(when=max(week, b_start), kind="care",
                                  title=f"Summer care: week of {week:%b %d}",
                                  detail="Water deeply twice, pull weeds, pick anything ripe. "
                                         "Sign up a family or staff member for this week."))
            week += timedelta(weeks=1)
    return tasks
