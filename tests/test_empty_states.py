"""An empty list names what it was asked for and offers the way back; each script run for real in Node with only the globals it reaches named."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"

# `any` stands in for every DOM object or helper a test does not look at; sandbox() hands it out for any global not named.
PRELUDE = r"""
const fs = require("fs"), vm = require("vm");
const read = (file) => fs.readFileSync(file, "utf8");
const any = new Proxy(function () {}, { get: (_, k) => (k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : any), apply: () => any, construct: () => any, set: () => true });
const el = (tag, props = {}, ...kids) => ({ tag, ...props, kids });
function sandbox(named = {}) {
  const own = { el, structuredClone, ...named };
  return vm.createContext(new Proxy(own, { has: () => true, get: (t, k) => (k in t ? t[k] : k in globalThis ? globalThis[k] : any), set: (t, k, v) => ((t[k] = v), true) }));
}
const grab = (src, re) => { const m = src.match(re); if (!m) throw Error(`not in the source: ${re}`); return m[0]; };
// a stand-in for an input, a list or a button the page reads and writes
const box = (extra = {}) => { const e = { value: "", checked: false, hidden: false, children: [], attrs: {}, dataset: {}, firstChild: { textContent: "" },
  focus() { focused.push(e); }, setAttribute(k, v) { e.attrs[k] = String(v); }, getAttribute: (k) => e.attrs[k] ?? null, removeAttribute() {},
  replaceChildren(...kids) { e.children = kids; }, querySelector: () => box(), ...extra }; return e; };
const focused = [];
const walk = (n, f) => { if (n && typeof n === "object") { f(n); (n.kids || []).forEach((k) => walk(k, f)); } };
const texts = (n) => { const out = []; walk(n, (x) => { if (typeof x.textContent === "string") out.push(x.textContent); }); return out; };
const button = (n, label) => { let hit = null; walk(n, (x) => { if (x.tag === "button" && x.textContent === label) hit = x; }); return hit; };
"""


def node(body, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PRELUDE + body, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_an_empty_series_wall_names_the_search_and_clears_every_filter():
    shown = node(r"""
const src = read(process.argv[1]);
const search = box({ value: " zzz " }), wall = box(), seg = box({ dataset: { managed: "" } }), pressed = { "": true };
const fields = { "#search": search, "#f-service": box({ value: "hbo" }), "#f-library": box({ value: "-" }), "#f-missing": box({ checked: true }),
  "#f-monitored": box({ checked: true }), "#f-sort": box({ value: "title" }), "#wall": wall };
const segButtons = [seg, box({ dataset: { managed: "*" } })];
const S = { series: [{ tvdbId: 1, title: "Alpha", missing: 0, monitored: true }], config: { series: {}, hidden_series: [], settings: {} }, health: {}, sonarrsOf: {} };
const stubs = { S, $: (sel) => fields[sel] ?? box(), SEL: { on: false, ids: new Set() },
  document: { querySelector: (sel) => (sel.includes("aria-pressed=true") ? seg : box()), querySelectorAll: () => segButtons.map((b) => ({ ...b, querySelector: () => box(), setAttribute: (k, v) => { pressed[b.dataset.managed] = v === true || v === "true"; } })) } };
const ctx = sandbox(stubs);
vm.runInContext(grab(src, /function clearWallFilters\b[\s\S]*?\n}\n/) + grab(src, /function renderWall\b[\s\S]*?\n}\n/), ctx);
ctx.renderWall();
const empty = wall.children[0];
const clear = button(empty, "Clear filters");
const before = { role: empty.role, texts: texts(empty), hasClear: Boolean(clear) };
ctx.renderWall = () => { before.redrawn = true; };  // the redraw itself is not under test
clear.onclick();
console.log(JSON.stringify({ ...before, search: search.value, service: fields["#f-service"].value, library: fields["#f-library"].value,
  missing: fields["#f-missing"].checked, monitored: fields["#f-monitored"].checked, pressed, focused: focused.includes(search) }));
""", str(JS / "core.js"))
    assert shown["role"] == "status"
    assert "No series match “zzz”." in shown["texts"]
    assert shown["hasClear"]
    assert shown["search"] == "" and shown["service"] == "" and shown["library"] == ""
    assert shown["missing"] is False and shown["monitored"] is False
    assert shown["pressed"][""] is True and shown["pressed"]["*"] is False
    assert shown["redrawn"] and shown["focused"]


@pytest.mark.parametrize("query, filter_, text, buttons", [
    ("zzz", "all", "No download matches “zzz”.", ["Clear search"]),
    ("", "failed", "No download under Failed.", ["Show all"]),
    ("zzz", "failed", "No download under Failed matches “zzz”.", ["Clear search", "Show all"]),
])
def test_an_empty_history_names_the_search_and_filter_and_offers_the_way_back(query, filter_, text, buttons):
    shown = node(r"""
const src = read(process.argv[1]), [query, filter] = process.argv.slice(2);
const search = box({ value: query }), history = box(), all = box();
const ctx = sandbox({ runCards: [], conFilter: filter, runsShown: 50, landOnLive: false, picked_run: "serve", innerWidth: 500,
  isLive: () => false, jobsOf: () => [], glideBars() {},
  $: (sel) => ({ "#con-search": search, "#runs-history": history })[sel] ?? box(),
  document: { querySelector: (sel) => (sel.endsWith('data-f="all"]') ? all : box({ firstChild: { textContent: "Failed " } })), querySelectorAll: () => [] } });
vm.runInContext(grab(src, /function emptyHistory\b[\s\S]*?\n}\n/) + grab(src, /function renderConsole\b[\s\S]*?\n}\n(?=\/\* Episodes picked)/), ctx);
let shownFilter = null, redraws = 0;
ctx.setConFilter = (f) => { shownFilter = f; };
ctx.renderConsole();
const empty = history.children[0];
const labels = []; walk(empty, (x) => { if (x.tag === "button") labels.push(x.textContent); });
const out = { role: empty.role, texts: texts(empty), labels };
const clear = button(empty, "Clear search"), showAll = button(empty, "Show all");
ctx.renderConsole = () => { redraws++; };
if (clear) { clear.onclick(); out.cleared = search.value === "" && redraws === 1 && focused.includes(search); }
if (showAll) { showAll.onclick(); out.all = shownFilter === "all" && focused.includes(all); }
console.log(JSON.stringify(out));
""", str(JS / "activity.js"), query, filter_)
    assert shown["role"] == "status"
    assert text in shown["texts"]
    assert shown["labels"] == buttons
    assert shown.get("cleared", "Clear search" not in buttons) and shown.get("all", "Show all" not in buttons)


def test_no_download_at_all_says_where_downloads_start():
    texts = node(r"""
const src = read(process.argv[1]);
const history = box();
const ctx = sandbox({ runCards: [], conFilter: "all", runsShown: 50, landOnLive: false, picked_run: "serve", innerWidth: 500,
  isLive: () => false, jobsOf: () => [], glideBars() {}, $: (sel) => (sel === "#runs-history" ? history : sel === "#con-search" ? box() : box()), document: { querySelectorAll: () => [] } });
vm.runInContext(grab(src, /function emptyHistory\b[\s\S]*?\n}\n/) + grab(src, /function renderConsole\b[\s\S]*?\n}\n(?=\/\* Episodes picked)/), ctx);
ctx.renderConsole();
console.log(JSON.stringify(texts(history.children[0])));
""", str(JS / "activity.js"))
    assert texts == ["No download yet. Downloads start from a series, or with Run sync now."]


def test_upgrades_names_the_search_that_matched_no_series_and_clears_it():
    shown = node(r"""
const src = read(process.argv[1]);
const find = box({ value: "zzz" }), list = box();
const ctx = sandbox({ S: { series: [{ tvdbId: 1, title: "Alpha" }], config: { series: { 1: { service: "ALL4" } } } },
  $: (sel) => ({ "#ug-find": find, "#ug-series": list })[sel] ?? box(), upgradeSay() {}, dirty() {} });
vm.runInContext(grab(src, /function upgradeSeries\b[\s\S]*?\n}\n/) + grab(src, /function renderUpgradeSeries\b[\s\S]*?\n}\n/), ctx);
ctx.renderUpgradeSeries();
const empty = list.children[0];
const out = { role: empty.role, texts: texts(empty) };
button(empty, "Clear search").onclick();
out.find = find.value; out.focused = focused.includes(find); out.after = texts(list.children[0]);
console.log(JSON.stringify(out));
""", str(JS / "quality.js"))
    assert shown["role"] == "status"
    assert "No series matches “zzz”." in shown["texts"]
    assert shown["find"] == "" and shown["focused"]
    assert shown["after"] == ["Alpha"] or "Alpha" in shown["after"]


@pytest.mark.parametrize("query, filter_, text, buttons", [
    ("", "problems", "No device under Problems.", ["Show all"]),
    ("zzz", "all", "No device matches “zzz”.", ["Clear search"]),
    ("zzz", "used", "No device under In use matches “zzz”.", ["Clear search", "Show all"]),
])
def test_an_empty_device_list_names_the_search_and_filter_and_offers_the_way_back(query, filter_, text, buttons):
    shown = node(r"""
const src = read(process.argv[1]), [query, filter] = process.argv.slice(2);
const ctx = sandbox({ cdmQuery: query, cdmFilter: filter, $: () => box() });
vm.runInContext(grab(src, /function emptyDevices\b[\s\S]*?\n}\n/), ctx);
let redraws = 0;
ctx.renderCdm = () => { redraws++; };
const empty = ctx.emptyDevices(3);
const labels = []; walk(empty, (x) => { if (x.tag === "button") labels.push(x.textContent); });
const out = { role: empty.role, texts: texts(empty), labels, none: texts(ctx.emptyDevices(0)) };
const clear = button(empty, "Clear search"), showAll = button(empty, "Show all");
if (clear) { clear.onclick(); out.query = ctx.cdmQuery; }
if (showAll) { showAll.onclick(); out.filter = ctx.cdmFilter; }
out.redraws = redraws;
console.log(JSON.stringify(out));
""", str(JS / "cookies-cdm.js"), query, filter_)
    assert shown["role"] == "status"
    assert text in shown["texts"]
    assert shown["labels"] == buttons
    assert shown["redraws"] == len(buttons)
    assert shown.get("query", "") == "" and shown.get("filter", "all") == "all"
    assert shown["none"] == ["No device yet: add a .wvd or .prd file."]


def test_a_series_sonarr_lists_no_episode_for_has_a_refresh_that_asks_again():
    shown = node(r"""
const src = read(process.argv[1]);
const s = { tvdbId: 1, id: 7 }, list = box();
let asked = 0;
const ctx = sandbox({ S: { sonarrsOf: {}, config: { series: { 1: {} } } }, current: s, $: (sel) => (sel === "#d-episodes" ? list : box()),
  api: async () => { asked++; return []; }, epSonarrOf: null, epSonarr: "", epSeq: 0, picked: new Set(), epAvailRaw: null });
vm.runInContext(grab(src, /let epSeq = 0;[^\n]*\nasync function loadEpisodes\b[\s\S]*?\n}\n/), ctx);
ctx.current = s;
ctx.loadEpisodes(s).then(() => {
  const empty = list.children;
  const out = { texts: empty.map((n) => n.textContent), labels: empty.filter((n) => n.tag === "button").map((n) => n.textContent) };
  const before = asked;
  empty.find((n) => n.tag === "button").onclick();
  setTimeout(() => { out.asked = asked > before; console.log(JSON.stringify(out)); }, 20);
});
""", str(JS / "series.js"))
    assert shown["texts"][0] == "Sonarr lists no episode for this series."
    assert shown["labels"] == ["Refresh"]
    assert shown["asked"]
