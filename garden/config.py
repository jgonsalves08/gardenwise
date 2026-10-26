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

# HTML (shown inside a styled box on Home, step 2 of the planner and About).
REGION_NOTE = ("Gardenwise works across the continental US (every state except Alaska and Hawaii). It doesn't "
               "fully support places where it rarely freezes, because there summer heat, not frost, decides when "
               "to plant:<ul class='region-list'>"
               "<li>All of Florida</li>"
               "<li>The Gulf and southern Atlantic coast: Mobile (AL), New Orleans (LA), Savannah (GA), "
               "Charleston (SC)</li>"
               "<li>South and central Texas: Houston, Austin, San Antonio, the Rio Grande Valley</li>"
               "<li>The low deserts: Phoenix and Tucson (AZ), Las Vegas (NV), Palm Springs (CA)</li>"
               "<li>Most of California outside the mountains: Los Angeles, San Diego, the Bay Area, Sacramento, "
               "the Central Valley and the North Coast</li></ul>")
LIMITED_NOTE = ("🌴 **{city} isn't fully supported yet.** Gardenwise times every planting from when frost "
                "usually ends in spring and starts in fall, but here the weather works differently. {reason} "
                "Our dates would be wrong, so planning is turned off here for now. Your county's extension "
                "office (free local gardening help from your state university) publishes planting calendars "
                "for your area.")

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

# Sample accounts for testing (local copies only). Turn off for any public deployment:
#   GARDENWISE_TEST_ACCOUNTS=0
SEED_TEST_ACCOUNTS = os.getenv("GARDENWISE_TEST_ACCOUNTS", "1") == "1"

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
