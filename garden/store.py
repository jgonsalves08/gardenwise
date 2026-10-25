"""Optional accounts and saved gardens (SQLite, stdlib only).

Guests never touch this module. Logged-in users can save plans, tick off tasks and
shopping items, and come back later. The database is a single local file created on
first run (gitignored), so a fresh clone needs no setup.

Security:
- Passwords are hashed with PBKDF2-HMAC-SHA256 (200k iterations, per-user random salt);
  comparisons are constant-time.
- 5 failed logins lock the account for 5 minutes (brute-force protection).
- No addresses, ZIP codes, emails or photos are stored. Only the location dropdown id,
  the plan, and checklist state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from . import config

DB_PATH = config.REPO_ROOT / "garden.db"
PBKDF2_ITERATIONS = 200_000
MAX_FAILED = 5
LOCKOUT = timedelta(minutes=5)
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
);
CREATE TABLE IF NOT EXISTS gardens (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rec_json TEXT NOT NULL,
    chosen_json TEXT NOT NULL,
    addons_json TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT
);
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    organizer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    join_code TEXT UNIQUE NOT NULL,
    settings_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id)
);
CREATE TABLE IF NOT EXISTS group_tasks (
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    claimed_by INTEGER REFERENCES users(id),
    done_at TEXT,
    PRIMARY KEY (group_id, item_key)
);
CREATE TABLE IF NOT EXISTS harvests (
    id INTEGER PRIMARY KEY,
    garden_id INTEGER NOT NULL REFERENCES gardens(id) ON DELETE CASCADE,
    plant_id TEXT NOT NULL,
    picked_on TEXT NOT NULL,
    size TEXT NOT NULL,
    est_lb REAL NOT NULL,
    donated INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS task_dates (
    garden_id INTEGER NOT NULL REFERENCES gardens(id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    new_date TEXT NOT NULL,
    PRIMARY KEY (garden_id, item_key)
);
CREATE TABLE IF NOT EXISTS checks (
    garden_id INTEGER NOT NULL REFERENCES gardens(id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    done_at TEXT NOT NULL,
    done_by INTEGER REFERENCES users(id),
    PRIMARY KEY (garden_id, item_key)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(os.fspath(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first release to older garden.db files."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(gardens)")}
    for col, typ in (("start_date", "TEXT"), ("end_date", "TEXT"), ("group_id", "INTEGER"),
                     ("plot_label", "TEXT"), ("assigned_to", "TEXT"), ("plot_id", "INTEGER")):
        if col not in cols:
            conn.execute(f"ALTER TABLE gardens ADD COLUMN {col} {typ}")
    # A garden is a plot of land; each saved plan is one season of it. Old rows become 1-season plots.
    conn.execute("UPDATE gardens SET plot_id = id WHERE plot_id IS NULL")


# ---------- accounts ----------
class AuthError(ValueError):
    pass


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt),
                               PBKDF2_ITERATIONS).hex()


def create_user(username: str, password: str) -> dict:
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise AuthError("Username must be 3–30 letters, numbers, dots, dashes or underscores.")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    salt = secrets.token_hex(16)
    try:
        with connect() as db:
            cur = db.execute(
                "INSERT INTO users (username, pw_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                (username, _hash(password, salt), salt, _now()))
            return {"id": cur.lastrowid, "username": username}
    except sqlite3.IntegrityError:
        raise AuthError("That username is taken.") from None


def authenticate(username: str, password: str) -> dict:
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        if row is None:
            _hash(password, secrets.token_hex(16))  # same work either way: no username probing by timing
            raise AuthError("Wrong username or password.")
        if row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > datetime.now(timezone.utc):
            raise AuthError("Too many failed attempts. Try again in a few minutes.")
        if not hmac.compare_digest(_hash(password, row["salt"]), row["pw_hash"]):
            fails = row["failed_attempts"] + 1
            locked = (datetime.now(timezone.utc) + LOCKOUT).isoformat() if fails >= MAX_FAILED else None
            db.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                       (0 if locked else fails, locked, row["id"]))
            db.commit()   # save the failed attempt before raising (otherwise the lockout never triggers)
            raise AuthError("Wrong username or password.")
        db.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (row["id"],))
        return {"id": row["id"], "username": row["username"]}


# ---------- gardens ----------
def save_garden(owner_id: int, name: str, rec_json: dict, chosen: list[str], addons: list[str],
                group_id: int | None = None, plot_label: str = "", assigned_to: str = "",
                plot_id: int | None = None) -> int:
    """Save one season. plot_id links seasons of the same plot of land (None = a new plot)."""
    start = rec_json["constraints"]["start_date"]  # the plan's start date; editable later
    with connect() as db:
        cur = db.execute(
            "INSERT INTO gardens (owner_id, name, created_at, updated_at, rec_json, chosen_json, "
            "addons_json, start_date, group_id, plot_label, assigned_to) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (owner_id, name.strip()[:60] or "My garden", _now(), _now(),
             json.dumps(rec_json), json.dumps(chosen), json.dumps(addons), start,
             group_id, plot_label[:30], assigned_to[:30]))
        gid = cur.lastrowid
        if plot_id is not None:
            owns = db.execute("SELECT 1 FROM gardens WHERE id = ? AND owner_id = ?", (plot_id, owner_id)).fetchone()
            plot_id = plot_id if owns else None
        db.execute("UPDATE gardens SET plot_id = ? WHERE id = ?", (plot_id or gid, gid))
        return gid


def set_dates(garden_id: int, owner_id: int, start: date, end: date | None) -> None:
    """Changing the start date re-anchors the plan, so every task date moves with it."""
    if end is not None and end < start:
        raise ValueError("The end date can't be before the start date.")
    with connect() as db:
        row = db.execute("SELECT rec_json FROM gardens WHERE id = ? AND owner_id = ?",
                         (garden_id, owner_id)).fetchone()
        if not row:
            return
        rec = json.loads(row["rec_json"])
        rec["constraints"]["start_date"] = start.isoformat()
        db.execute("UPDATE gardens SET start_date = ?, end_date = ?, rec_json = ?, updated_at = ? "
                   "WHERE id = ? AND owner_id = ?",
                   (start.isoformat(), end.isoformat() if end else None, json.dumps(rec), _now(),
                    garden_id, owner_id))


def garden_status(g: dict, today: date | None = None) -> str:
    """'past' once an end date is set and reached, 'future' before the start date, else 'current'."""
    today = today or date.today()
    if g["end_date"] and g["end_date"] <= today:
        return "past"
    if g["start_date"] > today:
        return "future"
    return "current"


def list_gardens(owner_id: int) -> list[dict]:
    """Personal gardens plus community plots this user has claimed. Unclaimed plots an organizer
    created from a CSV live on the Community page, not in My gardens."""
    with connect() as db:
        rows = db.execute(
            "SELECT g.* FROM gardens g JOIN users u ON u.id = g.owner_id WHERE g.owner_id = ? "
            "AND (g.group_id IS NULL OR g.assigned_to = u.username) ORDER BY g.updated_at DESC",
            (owner_id,)).fetchall()
        return [_garden_row(r) for r in rows]


def get_garden(garden_id: int, owner_id: int) -> dict | None:
    """Owner check is part of the query: you can only load your own gardens."""
    with connect() as db:
        r = db.execute("SELECT * FROM gardens WHERE id = ? AND owner_id = ?",
                       (garden_id, owner_id)).fetchone()
        return _garden_row(r) if r else None


def _garden_row(r: sqlite3.Row) -> dict:
    rec = json.loads(r["rec_json"])
    start = r["start_date"] or rec["constraints"]["start_date"]
    return {"id": r["id"], "name": r["name"], "created_at": r["created_at"],
            "updated_at": r["updated_at"], "rec": rec,
            "chosen": json.loads(r["chosen_json"]), "addons": json.loads(r["addons_json"]),
            "start_date": date.fromisoformat(start),
            "end_date": date.fromisoformat(r["end_date"]) if r["end_date"] else None,
            "owner_id": r["owner_id"], "group_id": r["group_id"],
            "plot_label": r["plot_label"] or "", "assigned_to": r["assigned_to"] or "",
            "plot_id": r["plot_id"] or r["id"]}


def update_garden(garden_id: int, owner_id: int, *, name: str | None = None,
                  chosen: list[str] | None = None, addons: list[str] | None = None) -> None:
    sets, args = ["updated_at = ?"], [_now()]
    if name is not None:
        sets.append("name = ?")
        args.append(name.strip()[:60] or "My garden")
    if chosen is not None:
        sets.append("chosen_json = ?")
        args.append(json.dumps(chosen))
    if addons is not None:
        sets.append("addons_json = ?")
        args.append(json.dumps(addons))
    with connect() as db:
        db.execute(f"UPDATE gardens SET {', '.join(sets)} WHERE id = ? AND owner_id = ?",
                   (*args, garden_id, owner_id))


def delete_garden(garden_id: int, owner_id: int) -> None:
    with connect() as db:
        db.execute("DELETE FROM gardens WHERE id = ? AND owner_id = ?", (garden_id, owner_id))


# ---------- checklists ----------
def get_checks(garden_id: int) -> dict[str, str]:
    with connect() as db:
        rows = db.execute("SELECT item_key, done_at FROM checks WHERE garden_id = ?",
                          (garden_id,)).fetchall()
        return {r["item_key"]: r["done_at"] for r in rows}


def set_check(garden_id: int, owner_id: int, item_key: str, done: bool) -> None:
    with connect() as db:
        owns = db.execute("SELECT 1 FROM gardens WHERE id = ? AND owner_id = ?",
                          (garden_id, owner_id)).fetchone()
        if not owns:
            return
        if done:
            db.execute("INSERT OR REPLACE INTO checks (garden_id, item_key, done_at, done_by) "
                       "VALUES (?, ?, ?, ?)", (garden_id, item_key[:200], _now(), owner_id))
        else:
            db.execute("DELETE FROM checks WHERE garden_id = ? AND item_key = ?",
                       (garden_id, item_key[:200]))


def update_rec(garden_id: int, owner_id: int, rec_json: dict, chosen: list[str] | None = None,
               addons: list[str] | None = None) -> None:
    """Replace the saved plan (after a site change or an AI re-plan). Checklist ticks are kept."""
    sets, args = ["rec_json = ?", "updated_at = ?"], [json.dumps(rec_json), _now()]
    if chosen is not None:
        sets.append("chosen_json = ?")
        args.append(json.dumps(chosen))
    if addons is not None:
        sets.append("addons_json = ?")
        args.append(json.dumps(addons))
    with connect() as db:
        db.execute(f"UPDATE gardens SET {', '.join(sets)} WHERE id = ? AND owner_id = ?",
                   (*args, garden_id, owner_id))


def place_of(g: dict) -> str:
    return (g["rec"]["constraints"].get("place") or "").strip()


def builds_at_place(owner_id: int, place: str, exclude_id: int | None = None) -> set[str]:
    """Add-on builds already planned in the owner's other current/future gardens at this place."""
    if not place:
        return set()
    out: set[str] = set()
    for g in list_gardens(owner_id):
        if g["id"] == exclude_id or garden_status(g) == "past":
            continue
        if place_of(g).lower() == place.lower():
            out |= set(g["addons"])
    return out



# ---------- community gardens ----------
CODE_WORDS = ["ELM", "OAK", "FERN", "SAGE", "MINT", "PEA", "BEAN", "KALE", "LEEK", "CORN",
              "ROSE", "IVY", "PINE", "BIRCH", "MAPLE", "CLOVER", "BASIL", "THYME", "DILL", "CHIVE"]
MAX_JOIN_ATTEMPTS = 5


def _new_code(db) -> str:
    while True:
        code = f"{secrets.choice(CODE_WORDS)}-{secrets.randbelow(9000) + 1000}"
        if not db.execute("SELECT 1 FROM groups WHERE join_code = ?", (code,)).fetchone():
            return code


def create_group(organizer_id: int, name: str, settings: dict) -> dict:
    with connect() as db:
        code = _new_code(db)
        cur = db.execute("INSERT INTO groups (name, organizer_id, join_code, settings_json, created_at) "
                         "VALUES (?, ?, ?, ?, ?)",
                         (name.strip()[:60] or "Community garden", organizer_id, code,
                          json.dumps(settings), _now()))
        gid = cur.lastrowid
        db.execute("INSERT INTO members (group_id, user_id, role, joined_at) VALUES (?, ?, 'organizer', ?)",
                   (gid, organizer_id, _now()))
        return {"id": gid, "join_code": code}


def _group_row(r) -> dict:
    return {"id": r["id"], "name": r["name"], "organizer_id": r["organizer_id"],
            "join_code": r["join_code"], "settings": json.loads(r["settings_json"]),
            "created_at": r["created_at"]}


def my_groups(user_id: int) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT g.*, m.role FROM groups g JOIN members m ON m.group_id = g.id "
                          "WHERE m.user_id = ? ORDER BY g.created_at DESC", (user_id,)).fetchall()
        return [_group_row(r) | {"role": r["role"]} for r in rows]


def get_group(group_id: int, user_id: int) -> dict | None:
    """Members only."""
    with connect() as db:
        r = db.execute("SELECT g.*, m.role FROM groups g JOIN members m ON m.group_id = g.id "
                       "WHERE g.id = ? AND m.user_id = ?", (group_id, user_id)).fetchone()
        return _group_row(r) | {"role": r["role"]} if r else None


ROLE_RANK = {"member": 1, "admin": 2, "organizer": 3}


def _role(db, group_id: int, user_id: int) -> str | None:
    r = db.execute("SELECT role FROM members WHERE group_id = ? AND user_id = ?",
                   (group_id, user_id)).fetchone()
    return r["role"] if r else None


def role_in(group_id: int, user_id: int) -> str | None:
    with connect() as db:
        return _role(db, group_id, user_id)


def require_role(group_id: int, user_id: int, minimum: str) -> None:
    """Server-side permission check: the UI hides buttons, but this is what actually enforces it."""
    with connect() as db:
        role = _role(db, group_id, user_id)
    if ROLE_RANK.get(role or "", 0) < ROLE_RANK[minimum]:
        raise PermissionError(f"Only a garden {minimum} can do that.")


def update_group_settings(group_id: int, actor_id: int, settings: dict, name: str | None = None) -> None:
    require_role(group_id, actor_id, "admin")
    with connect() as db:
        db.execute("UPDATE groups SET settings_json = ? WHERE id = ?", (json.dumps(settings), group_id))
        if name is not None:
            db.execute("UPDATE groups SET name = ? WHERE id = ?", (name.strip()[:60] or "Community garden", group_id))


def set_role(group_id: int, actor_id: int, target_id: int, role: str) -> None:
    """Only the organizer promotes members to admin (or back). The organizer role can't be changed here."""
    if role not in ("admin", "member"):
        raise ValueError("Role must be admin or member.")
    require_role(group_id, actor_id, "organizer")
    with connect() as db:
        if _role(db, group_id, target_id) in ("admin", "member"):
            db.execute("UPDATE members SET role = ? WHERE group_id = ? AND user_id = ?",
                       (role, group_id, target_id))


def delete_plot(group_id: int, actor_id: int, garden_id: int) -> None:
    require_role(group_id, actor_id, "admin")
    with connect() as db:
        db.execute("DELETE FROM gardens WHERE id = ? AND group_id = ?", (garden_id, group_id))


def join_group(user_id: int, code: str) -> dict:
    code = (code or "").strip().upper()
    with connect() as db:
        r = db.execute("SELECT * FROM groups WHERE join_code = ?", (code,)).fetchone()
        if not r:
            raise AuthError("That join code doesn't match any community garden.")
        db.execute("INSERT OR IGNORE INTO members (group_id, user_id, role, joined_at) "
                   "VALUES (?, ?, 'member', ?)", (r["id"], user_id, _now()))
        return _group_row(r)


def group_members(group_id: int) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT u.id, u.username, m.role FROM members m JOIN users u ON u.id = m.user_id "
                          "WHERE m.group_id = ? ORDER BY m.role DESC, u.username", (group_id,)).fetchall()
        return [dict(r) for r in rows]


def remove_member(group_id: int, actor_id: int, user_id: int) -> None:
    """Admins can remove members; only the organizer can remove admins; nobody removes the organizer."""
    with connect() as db:
        actor, target = _role(db, group_id, actor_id), _role(db, group_id, user_id)
        if actor in ("admin", "organizer") and target and ROLE_RANK[actor] > ROLE_RANK[target]:
            db.execute("DELETE FROM members WHERE group_id = ? AND user_id = ?", (group_id, user_id))


def delete_group(group_id: int, organizer_id: int) -> None:
    require_role(group_id, organizer_id, "organizer")
    with connect() as db:
        if db.execute("SELECT 1 FROM groups WHERE id = ? AND organizer_id = ?",
                      (group_id, organizer_id)).fetchone():
            db.execute("DELETE FROM gardens WHERE group_id = ?", (group_id,))
            db.execute("DELETE FROM groups WHERE id = ?", (group_id,))


def group_plots(group_id: int) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM gardens WHERE group_id = ? ORDER BY plot_label, id",
                          (group_id,)).fetchall()
        return [_garden_row(r) for r in rows]


def claim_plot(garden_id: int, group_id: int, user_id: int, username: str) -> bool:
    """A member takes over an unclaimed plot (one the organizer created from the CSV)."""
    with connect() as db:
        g = db.execute("SELECT g.owner_id, gr.organizer_id FROM gardens g JOIN groups gr ON gr.id = g.group_id "
                       "WHERE g.id = ? AND g.group_id = ?", (garden_id, group_id)).fetchone()
        member = db.execute("SELECT 1 FROM members WHERE group_id = ? AND user_id = ?",
                            (group_id, user_id)).fetchone()
        if not g or not member or g["owner_id"] != g["organizer_id"]:
            return False
        db.execute("UPDATE gardens SET owner_id = ?, assigned_to = ?, updated_at = ? WHERE id = ?",
                   (user_id, username[:30], _now(), garden_id))
        return True


def group_task_state(group_id: int) -> dict[str, dict]:
    with connect() as db:
        rows = db.execute("SELECT t.item_key, t.claimed_by, t.done_at, u.username FROM group_tasks t "
                          "LEFT JOIN users u ON u.id = t.claimed_by WHERE t.group_id = ?",
                          (group_id,)).fetchall()
        return {r["item_key"]: {"claimed_by": r["claimed_by"], "username": r["username"],
                                "done_at": r["done_at"]} for r in rows}


def set_group_task(group_id: int, user_id: int, item_key: str, *, claim: bool | None = None,
                   done: bool | None = None) -> None:
    with connect() as db:
        if not db.execute("SELECT 1 FROM members WHERE group_id = ? AND user_id = ?",
                          (group_id, user_id)).fetchone():
            return
        db.execute("INSERT OR IGNORE INTO group_tasks (group_id, item_key) VALUES (?, ?)",
                   (group_id, item_key[:200]))
        if claim is not None:
            db.execute("UPDATE group_tasks SET claimed_by = ? WHERE group_id = ? AND item_key = ?",
                       (user_id if claim else None, group_id, item_key[:200]))
        if done is not None:
            db.execute("UPDATE group_tasks SET done_at = ? WHERE group_id = ? AND item_key = ?",
                       (_now() if done else None, group_id, item_key[:200]))



# ---------- harvest log (optional, one tap) ----------
# No scale needed: people tap a size and we convert to approximate pounds.
HARVEST_SIZES = {"handful": 0.25, "bowl": 1.0, "basket": 5.0}
HERB_FACTOR = 0.2   # a "bowl" of basil weighs far less than a bowl of tomatoes


def size_to_lb(size: str, category: str, edible: bool) -> float:
    if not edible:
        return 0.0
    lb = HARVEST_SIZES.get(size, 0.0)
    return round(lb * (HERB_FACTOR if category == "herb" else 1.0), 3)


def log_harvest(garden_id: int, user_id: int, plant_id: str, size: str, est_lb: float,
                donated: bool = False, picked_on: date | None = None) -> None:
    with connect() as db:
        if not db.execute("SELECT 1 FROM gardens WHERE id = ? AND owner_id = ?", (garden_id, user_id)).fetchone():
            return
        db.execute("INSERT INTO harvests (garden_id, plant_id, picked_on, size, est_lb, donated, user_id) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (garden_id, plant_id, (picked_on or date.today()).isoformat(), size, est_lb,
                    int(donated), user_id))


def list_harvests(garden_id: int) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM harvests WHERE garden_id = ? ORDER BY picked_on DESC, id DESC",
                          (garden_id,)).fetchall()
        return [dict(r) for r in rows]


def delete_harvest(harvest_id: int, user_id: int) -> None:
    with connect() as db:
        db.execute("DELETE FROM harvests WHERE id = ? AND garden_id IN "
                   "(SELECT id FROM gardens WHERE owner_id = ?)", (harvest_id, user_id))



# ---------- plots and seasons ----------
def season_label(g: dict) -> str:
    """'2026 season', or '2026–27 season' for plans that start in late summer/fall (garlic, cover crops)."""
    y = g["start_date"].year
    return f"{y}–{(y + 1) % 100:02d} season" if g["start_date"].month >= 8 else f"{y} season"


def plots(owner_id: int) -> list[dict]:
    """The owner's gardens grouped by plot of land: [{plot_id, name, seasons (oldest→newest), latest}]."""
    by_plot: dict[int, list[dict]] = {}
    for g in list_gardens(owner_id):
        by_plot.setdefault(g["plot_id"], []).append(g)
    out = []
    for pid, seasons in by_plot.items():
        seasons.sort(key=lambda g: (g["start_date"], g["id"]))
        current = [g for g in seasons if garden_status(g) == "current"]
        # The season shown on the card: the one growing now, else the newest.
        active = current[-1] if current else seasons[-1]
        out.append({"plot_id": pid, "name": seasons[0]["name"], "seasons": seasons, "latest": seasons[-1],
                    "active": active})
    out.sort(key=lambda p: p["latest"]["updated_at"], reverse=True)
    return out


def plot_seasons(owner_id: int, plot_id: int) -> list[dict]:
    return next((p["seasons"] for p in plots(owner_id) if p["plot_id"] == plot_id), [])


def rename_plot(owner_id: int, plot_id: int, name: str) -> None:
    with connect() as db:
        db.execute("UPDATE gardens SET name = ?, updated_at = ? WHERE plot_id = ? AND owner_id = ?",
                   (name.strip()[:60] or "My garden", _now(), plot_id, owner_id))


def delete_plot(owner_id: int, plot_id: int) -> None:
    with connect() as db:
        db.execute("DELETE FROM gardens WHERE plot_id = ? AND owner_id = ? AND group_id IS NULL",
                   (plot_id, owner_id))



# ---------- user-edited task dates (Gardenwise recommends; the gardener can move any task) ----------
def get_task_dates(garden_id: int) -> dict[str, date]:
    with connect() as db:
        rows = db.execute("SELECT item_key, new_date FROM task_dates WHERE garden_id = ?", (garden_id,)).fetchall()
        return {r["item_key"]: date.fromisoformat(r["new_date"]) for r in rows}


def set_task_date(garden_id: int, owner_id: int, item_key: str, new: date | None) -> None:
    """new=None resets the task to its recommended date."""
    with connect() as db:
        if not db.execute("SELECT 1 FROM gardens WHERE id = ? AND owner_id = ?", (garden_id, owner_id)).fetchone():
            return
        if new is None:
            db.execute("DELETE FROM task_dates WHERE garden_id = ? AND item_key = ?", (garden_id, item_key[:200]))
        else:
            db.execute("INSERT OR REPLACE INTO task_dates (garden_id, item_key, new_date) VALUES (?, ?, ?)",
                       (garden_id, item_key[:200], new.isoformat()))


def set_checks_bulk(garden_id: int, owner_id: int, item_keys: list[str], done: bool = True) -> int:
    with connect() as db:
        if not db.execute("SELECT 1 FROM gardens WHERE id = ? AND owner_id = ?", (garden_id, owner_id)).fetchone():
            return 0
        for k in item_keys:
            if done:
                db.execute("INSERT OR IGNORE INTO checks (garden_id, item_key, done_at, done_by) VALUES (?, ?, ?, ?)",
                           (garden_id, k[:200], _now(), owner_id))
            else:
                db.execute("DELETE FROM checks WHERE garden_id = ? AND item_key = ?", (garden_id, k[:200]))
        return len(item_keys)
