"""Build the self-contained report.html and slides.html from docs/*_src.html.

Run from the repo folder:   python scripts/build_docs.py  [--github https://github.com/you/repo]
- Embeds every screenshot (as compressed JPEG data URIs) so the files open anywhere, offline.
- Fills tables and headline numbers from results/*.md and results/*.csv, so re-running the
  benchmarks and then this script keeps the report honest.
"""

from __future__ import annotations

import base64
import csv
import io
import re
import statistics as stats
import sys
from datetime import date
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SHOTS, RES, DOCS = ROOT / "screenshots", ROOT / "results", ROOT / "docs"


def img_uri(name: str, max_w: int = 1440, quality: int = 80) -> str:
    crop = None
    if "|" in name:            # name|left,top,right,bottom  (pixels) to crop, e.g. drop the sidebar
        name, box = name.split("|", 1)
        crop = tuple(int(v) for v in box.split(","))
    im = Image.open(SHOTS / f"{name}.png").convert("RGB")
    if crop:
        im = im.crop(crop)
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def md_tables(path: Path) -> list[str]:
    """Convert markdown tables in a results file to HTML tables (in order)."""
    out, rows = [], []
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
            continue
        if rows:
            head, body = rows[0], [r for r in rows[2:]]
            fmt = lambda c: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", c.replace("<", "&lt;").replace(">", "&gt;"))
            html = "<table><tr>" + "".join(f"<th>{fmt(h)}</th>" for h in head) + "</tr>"
            html += "".join("<tr>" + "".join(f"<td>{fmt(c)}</td>" for c in r) + "</tr>" for r in body) + "</table>"
            out.append(html)
            rows = []
    return out


def numbers() -> dict:
    runs = list(csv.DictReader((RES / "cost_runs.csv").open()))
    warm = [r for r in runs if r["mode"] == "warm"]
    cost = stats.mean(float(r["cost_usd"]) for r in warm)
    cached = sum(float(r["cached_tokens"]) for r in warm) / max(1, sum(float(r["input_tokens"]) for r in warm))
    secs = stats.mean(float(r["seconds"]) for r in warm)
    summary = (RES / "cost_summary.md").read_text()
    helper = re.search(r"\$([0-9.]+) per message", summary).group(1)
    scale = re.search(r"\| 10,000 \| (\$[0-9,.]+) \|", summary).group(1)
    return {"COST_WARM": f"${cost:.5f}", "CACHE_PCT": f"{cached:.0%}", "HELPER_COST": f"${helper}",
            "SCALE_10K": scale, "COMMUNITY_40": f"${40 * cost:.3f}", "SECONDS_PLAN": f"{secs:.0f}",
            "BUILD_DATE": date.today().strftime("%B %d, %Y")}


DIAGRAM = """
<svg viewBox="0 0 880 370" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Gardenwise agent flow"
     style="width:100%;height:auto;font-family:-apple-system,'Segoe UI',Inter,sans-serif;margin:8px 0 14px">
  <defs>
    <marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#5C6B5F"/></marker>
    <style>
      .ai{fill:#2F6B3F} .code{fill:#FFFFFF;stroke:#2F6B3F;stroke-width:2} .user{fill:#EEF6EC;stroke:#9BC27E;stroke-width:1.5}
      .t{font-size:14px;font-weight:700} .w{fill:#fff} .g{fill:#2F6B3F} .s{font-size:11px} .ln{stroke:#5C6B5F;stroke-width:1.6;fill:none}
    </style>
  </defs>
  <rect x="10" y="20" width="150" height="70" rx="12" class="user"/>
  <text x="85" y="48" text-anchor="middle" class="t g">Gardener</text>
  <text x="85" y="66" text-anchor="middle" class="s g">form · chat · photos</text>
  <rect x="200" y="20" width="140" height="70" rx="12" class="code"/>
  <text x="270" y="48" text-anchor="middle" class="t g">Screen (code)</text>
  <text x="270" y="66" text-anchor="middle" class="s g">limits · injection · foraging</text>
  <rect x="380" y="8" width="150" height="48" rx="12" class="ai"/>
  <text x="455" y="30" text-anchor="middle" class="t w">Intake (AI)</text>
  <text x="455" y="46" text-anchor="middle" class="s w">chat → strict fields</text>
  <rect x="380" y="64" width="150" height="48" rx="12" class="ai"/>
  <text x="455" y="86" text-anchor="middle" class="t w">Site Scout (AI)</text>
  <text x="455" y="102" text-anchor="middle" class="s w">photos → findings ✓/✗</text>
  <rect x="580" y="20" width="140" height="70" rx="12" class="ai"/>
  <text x="650" y="48" text-anchor="middle" class="t w">Selector (AI)</text>
  <text x="650" y="66" text-anchor="middle" class="s w">plant IDs + reasons</text>
  <rect x="740" y="20" width="130" height="70" rx="12" class="code"/>
  <text x="805" y="48" text-anchor="middle" class="t g">Verifier (code)</text>
  <text x="805" y="66" text-anchor="middle" class="s g">~35 checks · 1 retry</text>
  <rect x="740" y="130" width="130" height="62" rx="12" class="code"/>
  <text x="805" y="156" text-anchor="middle" class="t g">Calendar (code)</text>
  <text x="805" y="174" text-anchor="middle" class="s g">frost-based dates</text>
  <rect x="560" y="130" width="150" height="62" rx="12" class="code"/>
  <text x="635" y="156" text-anchor="middle" class="t g">Space &amp; costs (code)</text>
  <text x="635" y="174" text-anchor="middle" class="s g">counts · layout · prices</text>
  <rect x="380" y="130" width="150" height="62" rx="12" class="ai"/>
  <text x="455" y="156" text-anchor="middle" class="t w">Build advisor (AI)</text>
  <text x="455" y="174" text-anchor="middle" class="s w">which builds; code prices</text>
  <rect x="160" y="130" width="180" height="62" rx="12" class="user"/>
  <text x="250" y="156" text-anchor="middle" class="t g">Your plan</text>
  <text x="250" y="174" text-anchor="middle" class="s g">tick plants · save · export</text>
  <rect x="160" y="230" width="270" height="62" rx="12" class="ai"/>
  <text x="295" y="256" text-anchor="middle" class="t w">Garden helper (AI + 8 tools)</text>
  <text x="295" y="274" text-anchor="middle" class="s w">answers · fills form · proposes changes → Confirm</text>
  <rect x="470" y="230" width="400" height="62" rx="12" class="code"/>
  <text x="670" y="256" text-anchor="middle" class="t g">Saved gardens &amp; community data (SQLite)</text>
  <text x="670" y="274" text-anchor="middle" class="s g">seasons · tasks · harvests · roles · work days</text>
  <rect x="10" y="312" width="860" height="44" rx="10" fill="#FFF7E0" stroke="#F1DDB0"/>
  <text x="440" y="339" text-anchor="middle" class="s" fill="#6B4E00">Every AI call: budget check (session token &amp; call caps) → gpt-6-luna via Portkey → Pydantic-validated JSON → usage logged (in / cached / out / latency / $)</text>
  <path d="M160,55 L198,55" class="ln" marker-end="url(#a)"/>
  <path d="M340,45 L378,32" class="ln" marker-end="url(#a)"/>
  <path d="M340,65 L378,88" class="ln" marker-end="url(#a)"/>
  <path d="M530,32 L578,48" class="ln" marker-end="url(#a)"/>
  <path d="M530,88 L578,64" class="ln" marker-end="url(#a)"/>
  <path d="M720,48 L738,48" class="ln" marker-end="url(#a)"/>
  <path d="M738,64 L722,64" class="ln" marker-end="url(#a)"/>
  <text x="729" y="105" text-anchor="middle" class="s" fill="#5C6B5F">retry</text>
  <path d="M805,90 L805,128" class="ln" marker-end="url(#a)"/>
  <path d="M740,161 L712,161" class="ln" marker-end="url(#a)"/>
  <path d="M560,161 L532,161" class="ln" marker-end="url(#a)"/>
  <path d="M380,161 L342,161" class="ln" marker-end="url(#a)"/>
  <path d="M250,192 L250,228" class="ln" marker-end="url(#a)"/>
  <path d="M430,261 L468,261" class="ln" marker-end="url(#a)"/>
  <path d="M468,268 L432,268" class="ln" marker-end="url(#a)"/>
</svg>"""


def build(src: str, out: Path, github: str) -> None:
    html = (DOCS / src).read_text(encoding="utf-8")
    cost_tables = md_tables(RES / "cost_summary.md")
    repl = numbers() | {
        "GITHUB_URL": f'<a href="{github}">{github}</a>' if github else "<i>[add the GitHub URL after publishing]</i>",
        "DIAGRAM": DIAGRAM,
        "table:cost": cost_tables[0], "table:scale": cost_tables[1],
        "table:baseline": md_tables(RES / "baseline_summary.md")[0],
        "table:injection": md_tables(RES / "injection_results.md")[0],
    }
    for k, v in repl.items():
        html = html.replace("{{" + k + "}}", v)
    html = re.sub(r"\{\{img:([\w\-]+)\}\}", lambda m: f'<img src="{img_uri(m.group(1))}" alt="{m.group(1)}">', html)
    html = re.sub(r"\{\{imgsrc:([\w\-|,]+)\}\}", lambda m: img_uri(m.group(1)), html)
    left = re.findall(r"\{\{[^}]+\}\}", html)
    if left:
        print("  unfilled placeholders:", sorted(set(left)))
    out.write_text(html, encoding="utf-8")
    print(f"  wrote {out.name} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    gh = sys.argv[sys.argv.index("--github") + 1] if "--github" in sys.argv else ""
    build("report_src.html", ROOT / "report.html", gh)
    if (DOCS / "slides_src.html").exists():
        build("slides_src.html", ROOT / "slides.html", gh)
