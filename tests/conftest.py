"""Shared test setup: every test gets a fresh, throwaway SQLite database."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from garden import store
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    return store


@pytest.fixture()
def people(db):
    from garden import seeds_people
    seeds_people.ensure_people()
    return {u: db.authenticate(u, seeds_people.TEST_PASSWORD) for u in seeds_people.USERS}


def has_api_key() -> bool:
    from garden import config
    s = config.env_status()
    return s["portkey_key"] or s["openai_key"]
