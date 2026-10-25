# 🌱 Gardenwise

A Streamlit app that turns a one-minute form (location, skill level, goals, start timing, space,
optional sun) into a garden plan for the contiguous US: the right plants, a dated planting
calendar based on local frost dates, a bed layout, and a costed shopping list.

> Status: baseline end-to-end (selector agent + code calendar/layout/costs). Intake chat,
> build advisor, verifier and defenses are being added next.

## Run it locally

1. **Python 3.11+** is required. From this folder:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **API key.** The app looks for a `.env` file in this repo folder first, then in the folder
   above it. It needs `PORTKEY_API_KEY` (course key, model `gpt-6-luna`), or `OPENAI_API_KEY`
   as a fallback. See `.env.example`.
3. **Start the app:**
   ```bash
   streamlit run app.py
   ```
   Then open http://localhost:8501.

## Data (static, no live APIs)
- `data/locations.json` — 111 reference cities covering every contiguous state + DC and every ZIP prefix: USDA zone, average frost dates, rainfall, soil note, region and a support level. Hot-climate cities (most of zones 9–11) are marked *limited support* and planning is turned off there for now.
- `data/plants.json` — 48 plants across beginner/intermediate/experienced, with timing, spacing, goals and pet toxicity (ASPCA).
- `data/builds.json` — 8 builds (raised bed, containers, trellis, cold frame, rain barrel, compost bin, drip irrigation, low tunnel) with estimated prices and store-search links.

Every AI call is logged to `logs/usage.jsonl` (input, cached, output tokens, latency, cost).
