"""Capture report/slide screenshots for each test persona with headless Chrome (no extra installs).

Start the app first (streamlit run app.py), then:   python scripts/take_screenshots.py
Saves PNGs to screenshots/. Uses the local test accounts (README) and a couple of AI calls.
Drives the UI the way a person would: log in from the top-right menu, click sidebar items, etc.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "screenshots"
APP = os.getenv("APP_URL", "http://localhost:8501")
CHROME = os.getenv("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PASSWORD = "gardenwise-test-2026"
W, H = 1440, 960

JS_HELPERS = r"""
window.gw = {
  sleep: (ms) => new Promise(r => setTimeout(r, ms)),
  btn: (text) => [...document.querySelectorAll('button')].find(b => b.innerText.trim().includes(text)),
  async click(text, wait=2500) { const b = gw.btn(text); if (!b) throw new Error('no button: ' + text); b.click(); await gw.sleep(wait); },
  async nav(key, wait=3500) { document.querySelector('[class*="st-key-navbtn_' + key + '"] button').click(); await gw.sleep(wait); },
  async tab(text, wait=1500) { [...document.querySelectorAll('[role=tab]')].find(t => t.innerText.includes(text)).click(); await gw.sleep(wait); },
  setInput(sel, val) { const el = document.querySelector(sel); const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, val); el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true})); el.blur(); },
  async waitFor(fn, ms=8000) { const t0 = Date.now(); while (Date.now() - t0 < ms) { const v = fn(); if (v) return v; await gw.sleep(200); }
    throw new Error('timed out waiting'); },
  setVal(sel, val) { const el = document.querySelector(sel);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, val);
    el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); },
  async login(user, pw) { await gw.click('Log in / Sign up', 800);
    await gw.waitFor(() => document.querySelector('input[aria-label=Username]'));
    gw.setVal('input[aria-label=Username]', user); gw.setVal('input[aria-label=Password]', pw); await gw.sleep(600);
    const sub = await gw.waitFor(() => [...document.querySelectorAll('[data-testid=stFormSubmitButton] button, button')]
      .find(b => b.innerText.trim() === 'Log in'));
    sub.click();
    await gw.waitFor(() => !document.body.innerText.includes('Log in / Sign up'), 10000); await gw.sleep(1500);
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await gw.sleep(400); },
  scrollTo(sel, block='start') { const el = typeof sel === 'string' ? document.querySelector(sel) : sel; if (el) el.scrollIntoView({block}); window.scrollBy(0, -16); },
  find(text) { return [...document.querySelectorAll('h1,h2,h3,h4,p,summary,button,div')].find(e => e.children.length < 4 && e.innerText && e.innerText.trim().startsWith(text)); },
};
"""


class Browser:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def cmd(self, method, **params):
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def js(self, expr, timeout=90):
        r = await asyncio.wait_for(self.cmd("Runtime.evaluate", expression=f"(async()=>{{{expr}}})()",
                                            awaitPromise=True, returnByValue=True), timeout)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "JS error"))
        return r.get("result", {}).get("value")

    async def goto(self, url, wait=5):
        await self.cmd("Page.navigate", url=url)
        await asyncio.sleep(wait)
        await self.cmd("Runtime.evaluate", expression=JS_HELPERS)

    async def shot(self, name):
        await asyncio.sleep(0.8)
        data = (await self.cmd("Page.captureScreenshot", format="png"))["data"]
        (OUT / f"{name}.png").write_bytes(base64.b64decode(data))
        print("  saved", name)


async def scenario(b: Browser, name: str, steps):
    print(name)
    await b.goto(APP)
    try:
        await steps(b)
    except Exception as e:   # keep going: one broken shot shouldn't stop the rest
        print(f"  ! {name}: {e}")


async def guest(b):
    await b.shot("01_guest_home")
    await b.js("await gw.nav('plan'); gw.scrollTo('.st-key-step_1');")
    await b.shot("02_guest_planner_steps")
    await b.js("gw.setInput('input[aria-label=\"…or ZIP code (not saved)\"]', '33101'); await gw.sleep(3000);"
               "gw.scrollTo('.st-key-step_2');")
    await b.shot("03_limited_support_miami")
    await b.js("gw.setInput('input[aria-label=\"…or ZIP code (not saved)\"]', '60601'); await gw.sleep(3000);"
               "await gw.click('Recommend plants', 26000); gw.scrollTo(gw.find('🌿 Your garden plan'));")
    await b.shot("04_guest_plan_chicago")
    await b.js("gw.scrollTo('img.plant-photo', 'center');")
    await b.shot("05_plant_cards_with_photos")
    await b.js("const s=[...document.querySelectorAll('summary')].find(x=>x.innerText.includes('How we checked'));"
               "s.click(); await gw.sleep(1200); gw.scrollTo(s);")
    await b.shot("06_how_we_checked")
    await b.js("await gw.tab('Layout'); gw.scrollTo('table.grid', 'center');")
    await b.shot("07_layout_grid")
    await b.js("await gw.tab('Calendar'); gw.scrollTo('table.cal', 'center');")
    await b.shot("08_calendar_month_view")
    await b.js("await gw.tab('Shopping'); gw.scrollTo(gw.find('Estimated total'), 'center');")
    await b.shot("09_shopping_and_budget")


async def helper(b):
    await b.js("await gw.click('Garden helper', 2500);"
               "const ta=document.querySelector('.st-key-helper_panel textarea');"
               "Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(ta,"
               "\"I live in Denver and want a salsa garden in a 4 by 8 raised bed. I'm a beginner.\");"
               "ta.dispatchEvent(new Event('input',{bubbles:true})); await gw.sleep(400);"
               "ta.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,bubbles:true}));"
               "await gw.sleep(14000);")
    await b.shot("10_garden_helper_chat")


async def scout(b, path):
    await b.js("await gw.nav('plan'); const s=[...document.querySelectorAll('summary')].find(x=>x.innerText.includes('Add photos'));"
               "s.click(); await gw.sleep(1000); gw.scrollTo(s);")
    doc = await b.cmd("DOM.getDocument", depth=-1)
    node = await b.cmd("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector="input[type=file]")
    await b.cmd("DOM.setFileInputFiles", nodeId=node["nodeId"], files=[str(path)])
    await b.js("await gw.sleep(2500); await gw.click('Scout my photos', 14000);"
               "gw.scrollTo(gw.find('What the Site Scout sees') || gw.find('🛡️'), 'center');")
    await b.shot("11_site_scout_ignores_text_in_photo")


def persona(user, shots):
    async def run(b):
        await b.js(f"await gw.login('{user}', '{PASSWORD}');")
        await shots(b)
    return run


async def individual(b):
    await b.js("await gw.nav('gardens');")
    await b.shot("12_individual_my_gardens")
    await b.js("[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Open').click(); await gw.sleep(4500);"
               "gw.scrollTo(gw.find('🔁 **Crop rotation') || [...document.querySelectorAll('[data-testid=stAlert]')]"
               ".find(a=>a.innerText.includes('Crop rotation')) , 'center');")
    await b.shot("13_individual_seasons_and_rotation")
    await b.js("await gw.nav('week');")
    await b.shot("14_individual_this_week")
    await b.js("document.querySelector('[class*=\"st-key-\"] a[href*=\"dashboard\"], a[href*=\"dashboard\"]').click(); await gw.sleep(5000);")
    await b.shot("15_individual_dashboard")


async def household(b):
    await b.js("await gw.nav('gardens'); [...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Open').click();"
               "await gw.sleep(4500); gw.scrollTo([...document.querySelectorAll('[data-testid=stMetric]')]"
               ".find(m=>m.innerText.includes('Covers')), 'center');")
    await b.shot("16_household_atlanta")


async def school(b):
    await b.js("await gw.nav('gardens'); [...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Open').click();"
               "await gw.sleep(4500); const s=[...document.querySelectorAll('summary')].find(x=>x.innerText.includes('Plants in this garden'));"
               "s.click(); await gw.sleep(1500); gw.scrollTo(s);")
    await b.shot("17_school_minneapolis_lessons")


async def organizer(b):
    await b.js("await gw.nav('community'); await gw.click('Open', 4500); window.scrollTo(0,0);")
    await b.shot("18_organizer_community_garden")
    await b.js("await gw.tab('Work days'); gw.scrollTo('[role=tablist]');")
    await b.shot("19_organizer_work_days")
    await b.js("await gw.tab('Shopping'); gw.scrollTo('[role=tablist]');")
    await b.shot("20_organizer_cost_split")


async def admin(b):
    await b.js("await gw.nav('community'); [...document.querySelectorAll('button')].filter(x=>x.innerText.trim()==='Open')[0].click();"
               "await gw.sleep(4500); await gw.tab('Members'); gw.scrollTo('[role=tablist]');")
    await b.shot("21_admin_members_roles")


async def member(b):
    await b.js("await gw.nav('community'); await gw.click('Open', 4500); window.scrollTo(0,0);")
    await b.shot("22_member_community_view")
    await b.js("document.querySelector('a[href*=\"dashboard\"]').click(); await gw.sleep(5000);"
               "gw.scrollTo(gw.find('🏘️ Elm Street') || gw.find('Garden-wide'), 'start');")
    await b.shot("23_member_dashboard_totals_only")


async def main():
    OUT.mkdir(exist_ok=True)
    try:
        urllib.request.urlopen(APP, timeout=5)
    except Exception:
        sys.exit(f"Start the app first: streamlit run app.py  (expected at {APP})")
    profile = tempfile.mkdtemp()
    chrome = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={profile}",
                               f"--window-size={W},{H}", "--hide-scrollbars", "--force-color-profile=srgb",
                               "--blink-settings=preferredColorScheme=1", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json").read())
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.25)
        async with websockets.connect(ws_url, max_size=None) as ws:
            b = Browser(ws)
            await b.cmd("Page.enable")
            await b.cmd("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
            await b.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
            only = set(sys.argv[1:])   # e.g. `python scripts/take_screenshots.py personas` to redo just those
            if not only or "guest" in only:
                await scenario(b, "Guest", guest)
                await scenario(b, "Garden helper", helper)
                await scenario(b, "Site Scout", lambda br: scout(br, ROOT / "tests" / "fixtures" / "yard_injection.jpg"))
            if only and "personas" not in only:
                return
            await scenario(b, "test_individual", persona("test_individual", individual))
            await scenario(b, "test_household", persona("test_household", household))
            await scenario(b, "test_school", persona("test_school", school))
            await scenario(b, "test_organizer", persona("test_organizer", organizer))
            await scenario(b, "test_admin", persona("test_admin", admin))
            await scenario(b, "test_member", persona("test_member", member))
    finally:
        chrome.terminate()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
