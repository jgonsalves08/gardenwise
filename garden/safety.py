"""Input guards that run in CODE before any LLM call.

- Length caps on free text.
- Refuse foraging / wild mushroom questions outright (identification mistakes can kill;
  this app must never be the reason someone eats a wild plant or mushroom).
- Flag obvious prompt-injection phrasing (we still pass the text, wrapped as data,
  but the flag is logged and shown so the defense is visible).
- Wrap user text in delimiters so the model treats it as data, not instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import config

FORAGING_PATTERNS = [
    r"\bforag\w*", r"\bmushroom\w*", r"\bfung(i|us)\b", r"\bmorels?\b", r"\bchanterelles?\b",
    r"\bwild (edible|plant|berr|green|food)\w*", r"\bis (this|it) (safe|ok|okay) to eat\b",
    r"\bidentify (this|a|the) (plant|berry|mushroom|weed)\b", r"\bpoisonous\b.*\beat\b",
]
INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"\b(system|developer) prompt\b", r"\breveal\b.*\b(prompt|instructions|rules)\b",
    r"\byou are now\b", r"\bact as\b", r"\bpretend (to be|you are)\b", r"\bjailbreak\b",
    r"</?\s*(gardener_profile|user_message|system)\s*>", r"\bnew instructions?\b",
    r"\bdisregard\b.*\b(instructions|rules)\b",
]

FORAGING_REFUSAL = (
    "🍄 I can't help with foraging or identifying wild plants or mushrooms. Look-alikes can be "
    "deadly, and an app (or AI) is not a safe way to decide what's edible. For wild mushrooms, "
    "contact your state's mycological society; for a possible poisoning, call Poison Control at "
    "1-800-222-1222. I'm happy to help you plan a garden of plants you grow yourself!"
)


@dataclass
class Screen:
    text: str                 # cleaned, length-capped text
    refused: bool = False
    refusal: str = ""
    injection_flag: bool = False
    truncated: bool = False


def screen_text(raw: str, max_chars: int = config.MAX_FREE_TEXT_CHARS) -> Screen:
    text = (raw or "").replace("\x00", "").strip()
    truncated = len(text) > max_chars
    text = text[:max_chars]
    low = text.lower()
    if any(re.search(p, low) for p in FORAGING_PATTERNS):
        return Screen(text=text, refused=True, refusal=FORAGING_REFUSAL, truncated=truncated)
    flag = any(re.search(p, text, flags=re.IGNORECASE) for p in INJECTION_PATTERNS)
    return Screen(text=text, injection_flag=flag, truncated=truncated)


def wrap_user_text(text: str, tag: str = "user_message") -> str:
    """Delimit user text as data. Angle brackets are neutralized so the user can't close the tag."""
    safe = text.replace("<", "‹").replace(">", "›")
    return f"<{tag}>\n{safe}\n</{tag}>"


URL_RE = re.compile(r"https?://|www\.|\[.*\]\(.*\)|<[a-z/]", re.IGNORECASE)


def clean_model_text(text: str, max_chars: int = 240) -> str:
    """Model-written text shown to users: plain text only, no links or markup."""
    text = URL_RE.sub("", text or "")
    return text.strip()[:max_chars]


STREET_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z0-9.'-]+\s+){0,4}"
    r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|ln|lane|dr|drive|ct|court|way|pl|place|"
    r"ter|terrace|hwy|highway|pkwy|parkway|cir|circle)\b\.?", re.IGNORECASE)
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")


def clean_place(raw: str) -> tuple[str, str | None]:
    """Place nicknames group gardens ("Home", "Lincoln School"). We never store addresses,
    so anything that looks like a street address or ZIP code is rejected."""
    text = re.sub(r"\s+", " ", (raw or "")).strip()[:40]
    if STREET_RE.search(text) or ZIP_RE.search(text):
        return "", ("That looks like a street address or ZIP code. Please use a nickname instead "
                    "(like “Home” or “School”) — we don't store addresses.")
    return text.replace("<", "").replace(">", ""), None
