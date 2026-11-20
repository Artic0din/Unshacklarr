"""One fact, one answer: what the bell, Settings, Activity, the series drawer and the setup say about the same thing agree."""
import asyncio
import importlib
import json
import math
import shutil
import subprocess
import zoneinfo
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"


def fresh_web(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSHACKLARR_DATA", str(tmp_path))
    for name in ("SONARR_URL", "SONARR_API_KEY", "UNSHACKLE_URL", "UNSHACKLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    import unshacklarr.sync
    import unshacklarr.web
    importlib.reload(unshacklarr.sync)
    return importlib.reload(unshacklarr.web)


# ---- the bell ----

def test_a_cookie_alert_told_again_replaces_its_line_in_the_bell_and_names_its_service(tmp_path, monkeypatch):
    web = fresh_web(tmp_path, monkeypatch)
    monkeypatch.setattr(web.sonarr_sync.PUSH, "send", lambda *a, **k: 0)
    monkeypatch.setattr(web.sonarr_sync, "free_space_problem", lambda: None)
    monkeypatch.setattr(web, "remote_unsupported", lambda config: [])
    monkeypatch.setattr(web, "cdm_state", lambda: {"devices": []})
    now = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
    expires = (now + timedelta(days=5)).timestamp()
    monkeypatch.setattr(web, "cookie_state", lambda: {"used": ["HULU"], "files": {"HULU": [{"profile": "", "expires": expires}]}})
    web.check_alerts(now)
    web.check_alerts(now + timedelta(days=1))  # a day later: "4 days", told again
    items = web.sonarr_sync.read_inbox()["items"]
    assert [(i["title"], i.get("service")) for i in items] == [("HULU cookies expire in 4 days", "HULU")]


def test_a_notification_without_a_key_is_never_merged(tmp_path, monkeypatch):
    web = fresh_web(tmp_path, monkeypatch)
    web.sonarr_sync.inbox_add("error", "Failed: Show S01E01", "x")
    web.sonarr_sync.inbox_add("error", "Failed: Show S01E01", "x")
    assert len(web.sonarr_sync.read_inbox()["items"]) == 2


# ---- how many services ----

def test_settings_counts_the_services_as_the_setup_test_does(tmp_path, monkeypatch):
    web = fresh_web(tmp_path, monkeypatch)
    listed = [{"tag": "EXAMPLE"}, {"tag": "DSNP"}, {"tag": "HULU"}]
    monkeypatch.setattr(web.UNSHACKLE, "health", lambda: {"version": "5.5.0"})
    monkeypatch.setattr(web.UNSHACKLE, "services", lambda: listed)
    assert web.unshackle_health()["services"] == web.service_count(listed) == 2


# ---- the setup's country ----

@pytest.mark.skipif(not any((Path(p) / "zone.tab").exists() for p in zoneinfo.TZPATH), reason="no zone.tab on this system")
def test_the_setup_offers_the_time_zone_s_country_until_one_is_chosen(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    web = fresh_web(tmp_path, monkeypatch)

    async def setups():
        async with TestClient(TestServer(web.app)) as client:
            first = (await (await client.get("/api/session")).json())["setup"]
            web.write_config({**web.read_config(), "settings": {"country": "GB"}})
            return first, (await (await client.get("/api/session")).json())["setup"]

    first, chosen = asyncio.run(setups())
    assert first["zone_countries"]["Australia/Melbourne"] == "AU" and first["zone_countries"]["Europe/Paris"] == "FR"
    assert chosen["country"] == "GB" and "zone_countries" not in chosen


# ---- the page ----

PRELUDE = r"""
const fs = require("fs"), vm = require("vm");
const read = (file) => fs.readFileSync(file, "utf8");
const any = new Proxy(function () {}, { get: (_, k) => (k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : any), apply: () => any, construct: () => any, set: () => true });
const el = (tag, props = {}, ...kids) => ({ tag, ...props, kids, children: kids });
function sandbox(named = {}) {
  const own = { el, ...named };
  return vm.createContext(new Proxy(own, { has: () => true, get: (t, k) => (k in t ? t[k] : k in globalThis ? globalThis[k] : any), set: (t, k, v) => ((t[k] = v), true) }));
}
const grab = (src, re) => { const m = src.match(re); if (!m) throw Error(`not in the source: ${re}`); return m[0]; };
"""


def node(body, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PRELUDE + body, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_failed_attempt_never_shows_its_last_steps_done():
    shown = node(r"""
const ctx = sandbox({ afterTracks: () => false });
const src = read(process.argv[1]);
for (const re of [/^const STEPS = [^\n]*\n/m, /^function stepStates\(.*?^\}/ms]) vm.runInContext(grab(src, re), ctx);
console.log(JSON.stringify(["failed", "stopped", "interrupted", "unavailable", "downloaded"].map((outcome) => ctx.stepStates({ step: "done", outcome, parts: 2 }))));
""", str(JS / "activity.js"))
    for states in shown[:4]:
        assert states[:-1] == ["done"] * 5 and states[-1] in ("fail", "halt")
    assert shown[0][-1] == "fail" and shown[-1] == ["done"] * 6


def test_the_days_a_cookie_file_has_left_are_counted_as_the_bell_counts_them():
    lefts = [0.3, 1.5, 2.5, 4.6, 5.0, 6.4]
    shown = node(r"""
const ctx = sandbox({ Date: { now: () => 0 } });
vm.runInContext(grab(read(process.argv[1]), /^function cookieStatus\(.*?^\}/ms), ctx);
console.log(JSON.stringify(JSON.parse(process.argv[2]).map((d) => ctx.cookieStatus({ expires: d * 86400 })[1])));
""", str(JS / "cookies-cdm.js"), json.dumps(lefts))
    server = [max(1, math.floor(left + 0.5)) for left in lefts]  # web.check_alerts
    assert shown == [f"Expires in {d} day{'s' if d > 1 else ''}" for d in server]


SERVICES = r"""
const src = read(process.argv[1]);
const badges = () => nav.kids.filter((k) => !k.removed);
const nav = { kids: [], querySelector: (sel) => (sel === ":scope > .sv-attn" ? badges()[0]
  : { after: (x) => nav.kids.push(Object.assign(x, { remove() { x.removed = true; } })) }) };
const ctx = sandbox({
  svcName: (t) => t, usesService: (c, t) => c.service === t, ago: () => "now", servicesCookies: null,
  document: { querySelector: (sel) => (sel === '.set-nav [data-sec="services-devices"]' ? nav : null) },
  S: { config: { series: { 1: { service: "DSNP" }, 2: { service: "AMZN" } } }, authenticationLive: [],
    authentication: { DSNP: { state: "validated" }, AMZN: { state: "validated" }, ATVP: { state: "validated" }, HULU: { state: "validated" },
      MAX: { state: "unknown" }, TF1: { state: "needs_user_action" } },
    authenticationMethods: {},
    authenticationSetups: [
      { service: "DSNP", backend: "", state: "error", failure: "authentication_rejected" },
      { service: "AMZN", backend: "", state: "timed_out", method: "pairing" },
      { service: "HULU", backend: "", state: "fallback", method: "cookies", next_method: "credentials", failure: "network" },
      { service: "ATVP", backend: "", state: "cancelled", method: "pairing" },
      { service: "MAX", backend: "", state: "waiting", method: "pairing" }] },
});
for (const re of [/^const AUTH_METHOD_LABELS = .*?;$/m, /^const AUTH_FAILURE_LABELS = .*?;$/m, /^function authenticationLabel\(.*?^\}/ms,
  /^const SIGN_IN_FAILED = .*?;$/m, /^function serviceModels\(.*?^\}/ms, /^function needingText\(.*?^\}/ms, /^function paintServicesBadge\(.*?^\}/ms])
  vm.runInContext(grab(src, re), ctx);
"""


def test_every_service_whose_sign_in_failed_is_counted_as_needing_attention():
    shown = node(SERVICES + r"""
const models = ctx.serviceModels();
ctx.paintServicesBadge();
const [badge] = badges();
console.log(JSON.stringify({ needing: models.filter((m) => m.attention).map((m) => m.service).sort(), badge: badge?.textContent, title: badge?.title }));
""", str(JS / "services.js"))
    assert shown == {"needing": ["AMZN", "DSNP", "HULU", "TF1"], "badge": "4", "title": "4 services need attention"}


def test_the_settings_badge_goes_once_nothing_needs_attention():
    shown = node(SERVICES + r"""
ctx.paintServicesBadge();
ctx.S.authenticationSetups = [];
ctx.S.authentication = { DSNP: { state: "validated" } };
ctx.paintServicesBadge();
console.log(JSON.stringify(badges().length));
""", str(JS / "services.js"))
    assert shown == 0


def test_a_failing_series_says_why_on_its_episodes_and_links_its_sign_in():
    shown = node(r"""
const src = read(process.argv[1]);
const nodes = {};
const node = (id) => (nodes[id] ||= { id, hidden: true, kids: [], textContent: "", classList: { remove() {}, add() {} }, replaceChildren(...k) { this.kids = k; } });
const opened = [];
const ctx = sandbox({ $: (sel) => node(sel), current: { tvdbId: 7 }, svcName: (s) => s, renderSeriesLanguage() {},
  openServiceRow: (s) => opened.push(s), serviceModels: () => [{ service: "RMCBFM", attention: true }],
  S: { config: { series: { 7: { service: "RMCBFM", title: "x" } } }, health: { 7: { failing: 3, cause: "RMC BFM Play: your session has expired" } } } });
vm.runInContext(grab(src, /function renderSeriesState\b[\s\S]*?\n}\n/), ctx);
ctx.renderSeriesState();
const fix = node("#d-fail-fix").kids;
fix.find((k) => k.tag === "button")?.onclick();
console.log(JSON.stringify({ hidden: node("#d-fail").hidden, texts: [node("#d-fail-text").textContent, ...fix.map((k) => k.textContent)], opened }));
""", str(JS / "core.js"))
    assert shown == {"hidden": False, "texts": ["Its last 3 downloads from RMCBFM failed", "RMC BFM Play: your session has expired",
                                                "Check RMCBFM in Settings › Services & Devices › Services"], "opened": ["RMCBFM"]}


def test_a_failure_that_is_not_a_sign_in_does_not_send_you_to_the_services():
    shown = node(r"""
const src = read(process.argv[1]);
const nodes = {};
const node = (id) => (nodes[id] ||= { id, hidden: true, kids: [], textContent: "", classList: { remove() {}, add() {} }, replaceChildren(...k) { this.kids = k; } });
const ctx = sandbox({ $: (sel) => node(sel), current: { tvdbId: 7 }, svcName: (s) => s, renderSeriesLanguage() {}, openServiceRow() {},
  serviceModels: () => [{ service: "HULU", attention: false }],
  S: { config: { series: { 7: { service: "HULU", title: "x" } } }, health: { 7: { failing: 3, cause: "" } } } });
vm.runInContext(grab(src, /function renderSeriesState\b[\s\S]*?\n}\n/), ctx);
ctx.renderSeriesState();
console.log(JSON.stringify([node("#d-fail-text").textContent, ...node("#d-fail-fix").kids.map((k) => k.tag === "button" ? "button" : k.textContent)]));
""", str(JS / "core.js"))
    assert shown == ["Its last 3 downloads from HULU failed", "See the history in Activity for why."]


def test_a_notification_about_a_service_opens_its_row():
    shown = node(r"""
const src = read(process.argv[1]);
const opened = [];
const ctx = sandbox({ S: { series: [] }, svcName: (t) => `${t} name`, openServiceRow: (s) => opened.push(s), getSelection: () => "",
  trWith: (template, label) => template.replace("{0}", label),
  $: () => ({ close() {} }), ago: () => "now", LOCALE: "en", inboxSeenAt: "", history: { state: null } });
for (const re of [/^const INBOX_ICONS = \{[\s\S]*?^\};/m, /^function inboxGroups\(.*?^\}/ms, /^function inboxRow\(.*?^\}/ms, /^function closeInbox\(.*?^\}/ms]) vm.runInContext(grab(src, re), ctx);
const item = { id: "a", at: new Date().toISOString(), level: "warning", title: "HULU cookies expire in 4 days", message: "m", service: "HULU" };
const row = ctx.inboxRow(ctx.inboxGroups([item])[0], 0);
row.onclick();
console.log(JSON.stringify({ role: row.role ?? null, title: row.title ?? null, opened }));
""", str(JS / "inbox.js"))
    assert shown == {"role": "button", "title": "Open HULU name", "opened": ["HULU"]}


# ---- review follow-ups ----

def test_the_failing_series_can_be_asked_again_without_the_whole_state(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    web = fresh_web(tmp_path, monkeypatch)
    web.app._middlewares = type(web.app._middlewares)([web.same_origin_only])  # logged in, for this test
    failed = [{"tvdbId": 7, "outcome": "failed", "ended": f"2026-11-1{d}", "started": f"2026-11-1{d}", "cause": "expired"} for d in (3, 2, 1)]
    monkeypatch.setattr(web, "run_cards", lambda: failed)
    web.sonarr_sync.RUNS_DIR.mkdir(parents=True, exist_ok=True)

    async def ask():
        async with TestClient(TestServer(web.app)) as client:
            return await (await client.get("/api/health", headers={"X-Unshackle": "1"})).json()

    assert asyncio.run(ask()) == {"7": {"failing": 3, "cause": "expired", "since": "2026-11-11"}}


def test_a_finished_download_redraws_the_series_failure_from_fresh_health():
    shown = node(r"""
const src = read(process.argv[1]);
const drawn = [];
const s = { tvdbId: 7 };
const ctx = sandbox({ S: { health: { 7: { failing: 3 } } }, current: s, isLive: () => true, picked: new Set(), epSonarr: "", epBusy: new Map([[1, {}]]),
  document: { hidden: false }, loadEpisodes() {}, updateEpBar() {}, renderSeriesState: () => drawn.push(JSON.stringify(ctx.S.health)),
  setTimeout() {}, clearTimeout() {},
  api: async (path) => (path === "/api/health" ? {} : []) });
vm.runInContext(grab(src, /^async function refreshEpBusy\(.*?^\}/ms), ctx);
ctx.refreshEpBusy(s).then(() => setTimeout(() => console.log(JSON.stringify(drawn)), 10));
""", str(JS / "series.js"))
    assert shown == ["{}"]


def test_the_settings_badge_reads_the_cookie_files_once_from_any_page():
    shown = node(SERVICES + r"""
const asked = [];
ctx.api = async (path) => { asked.push(path); return { folder: "/c", files: { DSNP: [{ profile: "", expired: true }] } }; };
vm.runInContext(grab(src, /^let servicesCookiesAsked = .*$/m), ctx);
vm.runInContext(grab(src, /^function loadServiceCookies\(.*?^\}/ms), ctx);
vm.runInContext("servicesCookies = null", ctx);
Promise.all([ctx.loadServiceCookies(), ctx.loadServiceCookies()]).then(() => console.log(JSON.stringify({ asked, cookies: Object.keys(vm.runInContext("servicesCookies", ctx).files) })));
""", str(JS / "services.js"))
    assert shown == {"asked": ["/api/cookies"], "cookies": ["DSNP"]}


def test_the_setup_country_follows_the_time_zone_until_one_is_picked():
    shown = node(r"""
const ctx = sandbox();
vm.runInContext(grab(read(process.argv[1]), /^function countryFollowsZone\(.*?^\}/ms), ctx);
const country = Object.assign(new EventTarget(), { value: "AU" }), zone = Object.assign(new EventTarget(), { value: "Australia/Melbourne" });
let synced = 0;
ctx.countryFollowsZone(country, zone, { "Europe/Paris": "FR", "Asia/Tokyo": "JP" }, () => synced++);
zone.value = "Europe/Paris"; zone.dispatchEvent(new Event("change"));
const followed = country.value;
country.value = "GB"; country.dispatchEvent(new Event("input"));
zone.value = "Asia/Tokyo"; zone.dispatchEvent(new Event("change"));
console.log(JSON.stringify({ followed, kept: country.value, synced }));
""", str(JS / "setup.js"))
    assert shown == {"followed": "FR", "kept": "GB", "synced": 1}


def test_a_country_picked_before_a_reload_or_a_language_change_stays_picked():
    shown = node(r"""
const ctx = sandbox();
vm.runInContext(grab(read(process.argv[1]), /^function countryFollowsZone\(.*?^\}/ms), ctx);
const zones = { "Europe/Paris": "FR", "Asia/Tokyo": "JP" };
const make = (value) => [Object.assign(new EventTarget(), { value }), Object.assign(new EventTarget(), { value: "Australia/Melbourne" })];
// first time: the person picks Great Britain; the draft keeps what countryFollowsZone says
let [country, zone] = make("AU");
const picked = ctx.countryFollowsZone(country, zone, zones, () => {});
country.value = "GB"; country.dispatchEvent(new Event("input"));
const kept = picked();
// rebuilt from that draft: a time zone picked now leaves the country alone
[country, zone] = make("GB");
ctx.countryFollowsZone(country, zone, zones, () => {}, kept);
zone.value = "Asia/Tokyo"; zone.dispatchEvent(new Event("change"));
console.log(JSON.stringify({ kept, country: country.value }));
""", str(JS / "setup.js"))
    assert shown == {"kept": True, "country": "GB"}
