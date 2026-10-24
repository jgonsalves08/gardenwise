"""App-wide settings and .env loading.

The .env file is looked up in exactly two places, in order:
  1. this repo's folder (garden-planner/.env)
  2. the folder above it (where the teaching staff keep their shared .env)
The first value found wins (override=False), so a repo-local key beats the shared one.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
LOG_DIR = REPO_ROOT / "logs"
USAGE_LOG = LOG_DIR / "usage.jsonl"
RESULTS_DIR = REPO_ROOT / "results"

ENV_SEARCH_PATHS = [REPO_ROOT / ".env", REPO_ROOT.parent / ".env"]
for _env in ENV_SEARCH_PATHS:
    if _env.exists():
        load_dotenv(_env, override=False)

# Branding: change the name here and it updates everywhere in the app.
APP_NAME = "Gardenwise"
APP_TAGLINE = "Garden plans that fit your space, skill, budget and frost dates"

REGION_NOTE = ("Gardenwise currently covers the Northeast US only: CT, MA, RI, NH, VT, ME, NY, NJ and PA. "
               "Frost dates, zones and plant timing for other regions aren't included yet.")

# Course key allows gpt-6-luna only.
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-6-luna")
PORTKEY_BASE_URL = os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1").rstrip("/")

# USD per 1M tokens (course pricing sheet, standard tier).
PRICES = {
    "gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "output": 0.50},
}

# Prices are static estimates; they are labeled with this date everywhere they appear.
PRICES_AS_OF = "fall 2025"
SHOP_PRICE_NOTE = (f"Estimated, as of {PRICES_AS_OF}: typical Home Depot, Lowe's and garden-center prices, "
                   "rounded. Prices change by store and season, so use the store links for today's price.")
GROCERY_PRICE_NOTE = (f"Estimated, as of {PRICES_AS_OF}: pounds × average US retail prices "
                      "(USDA ERS Fruit and Vegetable Prices; herb prices are rougher estimates).")

# Guardrails
MAX_FREE_TEXT_CHARS = 500          # per chat message
MAX_CHAT_FOLLOWUPS = 2             # intake may ask at most 2 clarifying questions
SESSION_TOKEN_BUDGET = 60_000      # total tokens (input + output) per browser session
MAX_CALLS_PER_SESSION = 25         # hard stop on LLM calls per session
MAX_VERIFIER_RETRIES = 1           # selector gets one retry after a failed verification
MAX_OUTPUT_TOKENS = 1_500          # per call


def env_status() -> dict:
    """Which key is available and where .env files were found (never returns key values)."""
    return {
        "portkey_key": bool(os.getenv("PORTKEY_API_KEY", "").strip()),
        "openai_key": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "env_files_found": [str(p) for p in ENV_SEARCH_PATHS if p.exists()],
    }
