"""Page: About & credits — coverage, data sources, how the AI is checked, photo credits."""

from __future__ import annotations

import html

import streamlit as st

from .. import config, ui
from ..data import plants


def page() -> None:
    ui.hero(f"ℹ️ About {config.APP_NAME}", config.APP_TAGLINE)
    st.markdown(f'<div class="region-note">📍 {config.REGION_NOTE}</div>', unsafe_allow_html=True)
    st.markdown(f"""
### Where the numbers come from
- **Frost dates and zones:** USDA Plant Hardiness Zone Map (2023), NOAA 1991–2020 climate normals and
  Old Farmer's Almanac averages for reference cities in every contiguous state. Frost dates are 50/50 averages, and low spots
  can run colder.
- **Plant timing, spacing and yields:** state extension services (Cornell, UMass, UConn, Penn State, UNH,
  UVM, UMaine, Rutgers, UMN).
- **Pet toxicity:** ASPCA Toxic and Non-Toxic Plants list.
- **Prices:** {config.SHOP_PRICE_NOTE} Grocery values: {config.GROCERY_PRICE_NOTE}
- **AI:** `{config.MODEL_NAME}` (via Portkey) picks plants and builds; **code** checks every pick against the
  plant data and your frost dates, computes all dates, quantities and prices, and caps AI spending per session.
""")
    st.markdown("### Plant photo credits")
    st.caption("Photos from Wikimedia Commons under the licenses listed. Hover a photo in the app to see its credit.")
    rows = []
    for pid, cr in sorted(ui.photo_credits().items(), key=lambda kv: plants()[kv[0]].name):
        src = html.escape(cr.get("source", ""))
        lic = html.escape(cr.get("license", ""))
        lic_url = html.escape(cr.get("license_url", ""))
        rows.append(f"<tr><td>{html.escape(plants()[pid].name)}</td><td>{html.escape(cr.get('author', ''))}</td>"
                    f"<td>{f'<a href={chr(34)}{lic_url}{chr(34)} target=_blank>{lic}</a>' if lic_url else lic}</td>"
                    f"<td><a href=\"{src}\" target=_blank>source</a></td></tr>")
    st.markdown('<table class="shop"><tr><th>Plant</th><th>Photographer / author</th><th>License</th>'
                f'<th>Link</th></tr>{"".join(rows)}</table>', unsafe_allow_html=True)
