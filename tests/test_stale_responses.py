"""A slow answer never draws over what the page shows now: the page's real functions run under node with answers released in a chosen order."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"

# Shared by every script: `grab(name)` is the source of a function or a one-line/arrow const of the page's script.
PRELUDE = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const read = (file) => fs.readFileSync(file, "utf8");
const grab = (name, text = src) => text.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n|const ${name} = [^\\n{]*\\n|const ${name} = [\\s\\S]*?\\n};?\\n`))[0];
"""


def node(script, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PRELUDE + script, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.parametrize("live, answered, shown_progress", [(60, 10, 60), (10, 60, 60)])
def test_history_answer_keeps_newer_live_progress(live, answered, shown_progress):
    shown = node(r"""
const card = (progress) => ({ id: "a", outcome: "running", step: "downloading", live: { status: "downloading", progress } });
let answer;
const ctx = { runCards: [card(10)], runsTimer: null, liveFeed: null, feedReloading: false, feedMissed: null, feedSeen: new Set(),
  $: () => ({ hidden: false, textContent: "" }), api: (path) => (path === "/api/runs" ? new Promise((resolve) => { answer = resolve; }) : Promise.resolve({ items: [] })),
  renderConsole() {}, followLive() {}, activityLater() {}, failed: () => null, setTimeout: () => 0, clearTimeout() {} };
vm.createContext(ctx);
vm.runInContext("let runsSeq = 0;" + ["isLive", "feedChanged", "further"].map((n) => grab(n)).join("") + grab("openActivity") + grab("liveTick"), ctx);
(async () => {
  const reload = ctx.openActivity();
  ctx.liveTick(JSON.stringify([card(Number(process.argv[2]))]));  // drawn while the history answer is on its way
  answer([card(Number(process.argv[3])), { id: "old", outcome: "downloaded" }]);  // the 60 case: produced before that message
  await reload;
  console.log(JSON.stringify({ progress: ctx.runCards[0].live.progress, history: ctx.runCards.map((c) => c.id) }));
})();
""", str(JS / "activity.js"), str(live), str(answered))
    assert shown == {"progress": shown_progress, "history": ["a", "old"]}


def test_history_answer_takes_card_when_no_live_message_came():
    shown = node(r"""
const card = (progress) => ({ id: "a", outcome: "running", step: "downloading", live: { status: "downloading", progress } });
const ctx = { runCards: [card(10)], runsTimer: null, liveFeed: null, feedReloading: false, feedMissed: null, feedSeen: new Set(),
  $: () => ({ hidden: false, textContent: "" }), api: async (path) => (path === "/api/runs" ? [card(30)] : { items: [] }),
  renderConsole() {}, followLive() {}, activityLater() {}, failed: () => null, setTimeout: () => 0, clearTimeout() {} };
vm.createContext(ctx);
vm.runInContext("let runsSeq = 0;" + ["isLive", "feedChanged", "further"].map((n) => grab(n)).join("") + grab("openActivity") + grab("liveTick"), ctx);
ctx.openActivity().then(() => console.log(JSON.stringify({ progress: ctx.runCards[0].live.progress })));
""", str(JS / "activity.js"))
    assert shown == {"progress": 30}


def test_episodes_of_a_library_switched_away_from_are_not_drawn():
    shown = node(r"""
const s = { tvdbId: 1, id: 10, title: "Show" }, drawn = [];
const wait = (ms, value) => new Promise((resolve) => setTimeout(() => resolve(value), ms));
const ctx = { S: { sonarrsOf: { 1: [{ name: "4K", id: 9 }] }, config: { series: {} } }, current: s, epSonarr: "4K", epSonarrOf: 1, mainKeys: null, epAvailRaw: null, picked: new Set(),
  $: () => ({ replaceChildren() {} }), loading: () => null, failed: () => null, updateEpBar() {}, refreshEpBusy() {}, sxxOf: () => "S01E01",
  api: (path) => path.startsWith("/api/series/9/") ? wait(30, [{ id: 900, seasonNumber: 1 }]) : path.startsWith("/api/series/10/") ? wait(0, [{ id: 100, seasonNumber: 1 }]) : wait(0, null),
  applyBroadcast() { drawn.push({ sonarr: ctx.epSonarr, ids: Object.values(ctx.epSeasons).flat().map((e) => e.id) }); throw new Error("past the guard"); } };
vm.createContext(ctx);
vm.runInContext("let epSeq = 0;" + grab("loadEpisodes"), ctx);
(async () => {
  const slow = ctx.loadEpisodes(s);  // the 4K library, slow
  ctx.epSonarr = "";
  const fast = ctx.loadEpisodes(s);  // the main library, picked right after
  (await Promise.allSettled([slow, fast])).forEach((r) => r.reason && r.reason.message !== "past the guard" && drawn.push({ error: r.reason.message }));
  console.log(JSON.stringify(drawn));
})();
""", str(JS / "series.js"))
    assert shown == [{"sonarr": "", "ids": [100]}]


def test_superseded_library_load_does_not_ask_for_the_main_library():
    asked = node(r"""
const s = { tvdbId: 1, id: 10, title: "Show" }, asked = [];
const wait = (ms, value) => new Promise((resolve) => setTimeout(() => resolve(value), ms));
const ctx = { S: { sonarrsOf: { 1: [{ name: "4K", id: 9 }] }, config: { series: {} } }, current: s, epSonarr: "4K", epSonarrOf: 1, mainKeys: null, epAvailRaw: null, picked: new Set(),
  $: () => ({ replaceChildren() {} }), loading: () => null, failed: () => null, updateEpBar() {}, refreshEpBusy() {}, sxxOf: () => "S01E01",
  api: (path) => { asked.push(path.split("?")[0]); return wait(path.startsWith("/api/series/9/") ? 30 : 0, path.startsWith("/api/series/") ? [] : null); },
  applyBroadcast() { throw new Error("past the guard"); } };
vm.createContext(ctx);
vm.runInContext("let epSeq = 0;" + grab("loadEpisodes"), ctx);
(async () => {
  const slow = ctx.loadEpisodes(s);
  ctx.epSonarr = "";
  await Promise.allSettled([slow, ctx.loadEpisodes(s)]);
  console.log(JSON.stringify(asked.filter((p) => p.startsWith("/api/series/"))));
})();
""", str(JS / "series.js"))
    assert asked == ["/api/series/9/episodes", "/api/series/10/episodes"]


def test_episodes_error_of_a_library_switched_away_from_is_not_drawn():
    shown = node(r"""
const s = { tvdbId: 1, id: 10, title: "Show" }, errors = [];
const wait = (ms, value) => new Promise((resolve) => setTimeout(() => resolve(value), ms));
const ctx = { S: { sonarrsOf: { 1: [{ name: "4K", id: 9 }] }, config: { series: {} } }, current: s, epSonarr: "4K", epSonarrOf: 1, mainKeys: null, epAvailRaw: null, picked: new Set(),
  $: () => ({ replaceChildren() {} }), loading: () => null, failed: (m) => errors.push(m), updateEpBar() {}, refreshEpBusy() {}, sxxOf: () => "S01E01",
  api: (path) => path.startsWith("/api/series/9/") ? wait(30).then(() => { throw new Error("Sonarr did not answer"); }) : path.startsWith("/api/series/10/") ? wait(0, []) : wait(0, null),
  applyBroadcast() { throw new Error("past the guard"); } };
vm.createContext(ctx);
vm.runInContext("let epSeq = 0;" + grab("loadEpisodes"), ctx);
(async () => {
  const slow = ctx.loadEpisodes(s);
  ctx.epSonarr = "";
  await Promise.allSettled([slow, ctx.loadEpisodes(s)]);
  console.log(JSON.stringify(errors));
})();
""", str(JS / "series.js"))
    assert shown == []


@pytest.mark.parametrize("library", ["", "4K"])
def test_downloading_marker_only_for_the_open_library(library):
    shown = node(r"""
const s = { tvdbId: 1, id: 10 }, library = process.argv[2];
const card = (episodeId, instance) => ({ id: `r${episodeId}`, tvdbId: 1, episodeId, outcome: "running", instance });
const ctx = { current: s, epSonarr: library, epBusy: new Map(), epBusyTimer: null, picked: new Set(), document: { hidden: false },
  isLive: (c) => c.outcome === "running", api: async () => [card(1, ""), card(2, "4K")], loadEpisodes() {}, $: () => null, updateEpBar() {}, setTimeout: () => 0, clearTimeout() {} };
vm.createContext(ctx);
vm.runInContext(grab("refreshEpBusy"), ctx);
ctx.refreshEpBusy(s).then(() => console.log(JSON.stringify([...ctx.epBusy.keys()])));
""", str(JS / "series.js"), library)
    assert shown == ([1] if library == "" else [2])


# Runs the page's real showMissing / showUpgrades (Catch up, Upgrades) with api answers delayed by request, and prints what was drawn or sent.
LIST_PANES = r"""
const [pane, scenario] = [process.argv[2], process.argv[3]];
const draws = [], posts = [], waits = [];
const wait = (ms, value) => new Promise((resolve) => setTimeout(() => resolve(value), ms));
const find = (node, test) => { if (!node || typeof node !== "object") return null; if (test(node)) return node; for (const k of node.kids || (Array.isArray(node) ? node : [])) { const f = find(k, test); if (f) return f; } return null; };
const items = (ids) => ids.map((episodeId) => ({ episodeId, tvdbId: 1, series: "Show", sxxeyy: `S01E0${episodeId}`, aired: "2026-01-01", running: false, file: "1080p", fileStep: 2, better: "4K", betterStep: 1, ladder: 3 }));
const boxes = {};
const ctx = { $: (sel) => (boxes[sel] ??= { classList: { add() {}, toggle() {} }, textContent: "", hidden: false, replaceChildren: (...kids) => { if (sel === "#cd-main") draws.push(kids); } }),
  document: { hidden: false, querySelectorAll: () => [] }, el: (tag, props = {}, ...kids) => ({ tag, ...props, kids }), loading: (t) => ({ loading: t }), failed: (t) => ({ failed: t }),
  S: { config: { settings: { sonarrs: [{ name: "A", quality_ladder: "x" }, { name: "B", quality_ladder: "x" }] } }, series: [] }, runCards: [], isLive: () => false, isQueued: () => false,
  renderDock() {}, posterSrc: () => "", posterFail: () => null, ago: () => "", episodeTitle: () => "", thumb: () => ({}), mainSonarr: () => "Main", URLSearchParams, toast() {}, setTimeout: () => 0, clearTimeout() {}, picked_run: null,
  api: (path, opts = {}) => {
    if (opts.method === "POST") { posts.push(JSON.parse(opts.body)); return wait(0, {}); }
    waits.push(opts.wait);
    const slow = pane === "missing" ? !path.includes("days=") && !path.includes("sonarr=B") : path.includes("sonarr=A") || path === "/api/upgrades";
    const slowIds = [1, 2, 3], fastIds = [1, 2];
    const ids = scenario === "click" ? slowIds : slow ? slowIds : fastIds;
    return wait(scenario === "click" ? 0 : slow ? 30 : 0, pane === "missing" ? { items: items(ids) } : { scan: { running: false }, items: items(ids), checked: null });
  } };
vm.createContext(ctx);
const lets = [/^let missingDays.*\n/m, /^let upgradeTimer.*\n/m, /^let upgradeLast\b.*\n/m].map((re) => src.match(re)[0]).join("");
vm.runInContext(lets + ["sonarrPicker", "unsetNote", "showMissing", "showUpgrades"].map((n) => grab(n)).join(""), ctx);
vm.runInContext("upgradePick.add(1); upgradePick.add(2); upgradePick.add(3);", ctx);
const show = (sonarr, days) => { vm.runInContext(pane === "missing" ? `missingSonarr = ${JSON.stringify(sonarr)}; missingDays = ${days};` : `upgradeSonarr = ${JSON.stringify(sonarr)};`, ctx); return pane === "missing" ? ctx.showMissing() : ctx.showUpgrades(); };
const goText = () => find(draws[draws.length - 1], (n) => n.className === "btn primary")?.textContent;
(async () => {
  if (scenario === "wait") {
    await show("", 30);
    console.log(JSON.stringify({ waits }));
  } else if (scenario === "overtaken") {  // the slow request first (All, or Sonarr A), the quick one picked right after (7 days, or Sonarr B)
    const slow = show(pane === "missing" ? "" : "A", 0), fast = show(pane === "missing" ? "" : "B", 7);
    await Promise.all([slow, fast]);
    console.log(JSON.stringify({ shown: goText() }));
  } else if (scenario === "check") {  // A's list is on screen, the picker moves to B, a tick redraws A's cached list, and its Check button is pressed
    await show("A", 0);
    vm.runInContext('upgradeSonarr = "B";', ctx);
    await ctx.showUpgrades(false);
    await find(draws[draws.length - 1], (n) => n.textContent === "Check now").onclick({ target: {} });
    console.log(JSON.stringify({ sent: posts.map((p) => p.sonarr ?? null) }));
  } else {  // the list for Sonarr A is on screen, the picker moves to B, and the button of A's list is pressed meanwhile
    await show("A", 0);
    const go = find(draws[draws.length - 1], (n) => n.className === "btn primary");
    const next = show("B", 0);
    await go.onclick({ target: {} });
    await next;
    console.log(JSON.stringify({ sent: posts.map((p) => p.sonarr ?? null) }));
  }
})();
"""


@pytest.mark.parametrize("pane, count", [("missing", "Download the 2"), ("upgrades", "Replace the 2 selected")])
def test_list_pane_shows_the_newest_request_not_the_slowest(pane, count):
    assert node(LIST_PANES, str(JS / "activity.js"), pane, "overtaken") == {"shown": count}


@pytest.mark.parametrize("pane", ["missing", "upgrades"])
def test_list_pane_buttons_send_the_sonarr_the_list_is_for(pane):
    assert node(LIST_PANES, str(JS / "activity.js"), pane, "click") == {"sent": ["A"]}


def test_cached_upgrades_list_checks_the_library_it_shows():
    assert node(LIST_PANES, str(JS / "activity.js"), "upgrades", "check") == {"sent": ["A"]}


# Runs the page's real "Test this series" click with the probe's answers released by hand.
PROBE = r"""
const A = { tvdbId: 1, id: 10, title: "A" }, B = { tvdbId: 2, id: 20, title: "B" };
const nodes = {}, drawn = [], release = {};
const node = (sel) => (nodes[sel] ??= { ariaDisabled: null, textContent: "", setAttribute(n, v) { if (n === "aria-disabled") this.ariaDisabled = v; }, removeAttribute() { this.ariaDisabled = null; },
  replaceChildren(...kids) { drawn.push([sel, kids.length]); } });
const ctx = { probeSeq: 0, current: A, S: { config: { series: { 1: { service: "X", title: "A" }, 2: { service: "X", title: "B" } } } }, $: node, loading: (t) => t, failed: (t) => ({ failed: t }),
  slowHint: () => 0, clearTimeout() {}, svcName: (t) => t, icon: () => "", dirty() {}, toast() {}, el: (tag, props = {}, ...kids) => ({ tag, ...props, kids }),
  api: (path, opts) => new Promise((resolve, reject) => { (release[JSON.parse(opts.body).title] ??= []).push({ resolve, reject }); }) };
vm.createContext(ctx);
const click = vm.runInContext(src.match(/\$\("#d-probe"\)\.onclick = (async \(\) => \{[\s\S]*?\n\});/)[1], ctx);
const answer = { seasons: [], checks: [], season_map: { 1: "2" }, count: 5, series: "Show" };
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
"""


def test_probe_answer_of_a_series_closed_meanwhile_is_not_drawn():
    shown = node(PROBE + r"""
(async () => {
  const first = click();  // series A is tested, then B is opened
  ctx.current = B;
  release.A[0].resolve(answer);
  await first;
  console.log(JSON.stringify({ drawnInB: drawn.filter(([sel, n]) => sel === "#d-probe-out" && n > 0), button: nodes["#d-probe"].ariaDisabled }));
})();
""", str(JS / "settings-services.js"))
    assert shown["drawnInB"] == []


def test_probe_failure_of_a_series_closed_meanwhile_is_not_drawn():
    shown = node(PROBE + r"""
(async () => {
  const first = click();
  ctx.current = B;
  release.A[0].reject(new Error("Sonarr is down"));
  await first;
  console.log(JSON.stringify({ state: drawn.filter(([sel, n]) => sel === "#d-probe-state" && n > 0).length }));
})();
""", str(JS / "settings-services.js"))
    assert shown == {"state": 1}  # only A's "Asking the service…"


def test_probe_ending_in_a_closed_series_leaves_the_open_one_testing():
    shown = node(PROBE + r"""
(async () => {
  const first = click();
  ctx.current = B;
  nodes["#d-probe"].ariaDisabled = null;  // opening B enables its button
  const second = click();  // B is tested too
  release.A[0].resolve(answer);
  await first;
  const whileBTests = nodes["#d-probe"].ariaDisabled;
  release.B[0].resolve(answer);
  await second;
  console.log(JSON.stringify({ whileBTests, afterwards: nodes["#d-probe"].ariaDisabled }));
})();
""", str(JS / "settings-services.js"))
    assert shown == {"whileBTests": "true", "afterwards": None}


def test_reopening_the_same_series_ignores_the_earlier_test():
    shown = node(PROBE + r"""
(async () => {
  const first = click();  // A is tested, closed and opened again: the same object, its button enabled
  nodes["#d-probe"].ariaDisabled = null;
  const second = click();
  const newer = { ...answer, series: "Newer" };
  release.A[1].resolve(newer);
  await second;
  const afterNewer = nodes["#d-probe"].ariaDisabled;
  nodes["#d-probe"].ariaDisabled = "true";  // a third test is under way
  drawn.length = 0;
  release.A[0].resolve({ ...answer, series: "Older", season_map: {} });
  await first;
  console.log(JSON.stringify({ afterNewer, drawnByOlder: drawn.filter(([sel, n]) => sel === "#d-probe-out" && n > 0), button: nodes["#d-probe"].ariaDisabled }));
})();
""", str(JS / "settings-services.js"))
    assert shown == {"afterNewer": None, "drawnByOlder": [], "button": "true"}


def test_opening_a_series_enables_its_test_button():
    shown = node(r"""
const button = { ariaDisabled: "true", removeAttribute() { this.ariaDisabled = null; } };
const box = { replaceChildren() {}, textContent: "", hidden: false };
const ctx = { current: null, $: (sel) => (sel === "#d-probe" ? button : box), showReleaseSeen() {}, S: { health: {}, config: { series: {} } }, el: () => ({}), drawerPushed: false, drawerTab: "", navigate() {} };
vm.createContext(ctx);
vm.runInContext(grab("openDrawer"), ctx);
ctx.openDrawer({ tvdbId: 2 }, "episodes", true).catch(() => {}).then(() => console.log(JSON.stringify({ ariaDisabled: button.ariaDisabled })));  // later steps need the whole page: only the first lines matter
""", str(JS / "core.js"))
    assert shown == {"ariaDisabled": None}


@pytest.mark.parametrize("slow_answer", ["not found", "error"])
def test_library_check_shows_the_newest_path_not_the_slowest(slow_answer):
    shown = node(r"""
const slowAnswer = process.argv[2], timers = [];
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const say = { className: "", textContent: "", replaceChildren(...kids) { this.textContent = kids.join(""); } };
const lib = {}, ctx = { libWho: "", libRoots: [], libCommon: "", libTimer: null, URLSearchParams, S: { config: { settings: {} } }, mainSonarr: () => "Sonarr", icon: () => "", el: () => ({}),
  libOf: () => lib, renderLibraryPicks() {}, $: () => say, clearTimeout() {}, setTimeout: (fn) => { timers.push(fn); return 1; },  // the 400 ms debounce, fired by hand
  api: async (path) => {
    if (path.includes("sonarr_root=%2Fmnt%2Ft&")) { await wait(30); if (slowAnswer === "error") throw new Error("Unshacklarr did not answer"); return { ok: false, local_path: "/mnt/t", roots: ["/mnt/old"] }; }
    return { ok: true, local_path: "/mnt/tv", roots: ["/mnt/tv"] };
  } };
vm.createContext(ctx);
vm.runInContext("let libSeq = 0;" + grab("checkLibrary"), ctx);
(async () => {
  lib.library_sonarr_root = "/mnt/t"; ctx.checkLibrary();
  const old = timers[0]();  // its request is on its way
  lib.library_sonarr_root = "/mnt/tv"; ctx.checkLibrary();  // typed on: the new check still waits out its debounce
  await old;
  const meanwhile = say.textContent;  // the old answer landed inside that debounce
  await timers[1]();
  console.log(JSON.stringify({ meanwhile, text: say.textContent, className: say.className, roots: ctx.libRoots }));
})();
""", str(JS / "quality.js"), slow_answer)
    assert shown == {"meanwhile": "Looking for one of your episode files…", "text": "Unshacklarr reads Sonarr's library: /mnt/tv", "className": "lib-check ok", "roots": ["/mnt/tv"]}


@pytest.mark.parametrize("view, key", [("week", "2026-11-09+7"), ("month", "2026-10-26+42")])
@pytest.mark.parametrize("loaded", [False, True])
def test_logos_redraw_the_schedule_only_once_its_range_has_loaded(view, key, loaded):
    shown = node(r"""
const [view, key, loaded] = [process.argv[2], process.argv[3], process.argv[4] === "true"];
const redraws = [];
const ctx = { networksById: {}, S: { series: [{ tvdbId: 1, tmdbId: 7 }] }, api: async () => ({ 7: { providers: [] } }), renderCalendar: () => redraws.push(1),
  cal: { date: "2026-11-09", month: "2026-11-01", fetched: new Set(loaded ? [key] : []) }, schedView: () => view, isoDay: (d) => d, weekStartOf: (d) => (d === "2026-11-01" ? "2026-10-26" : d) };
vm.createContext(ctx);
vm.runInContext(grab("fetchNetworks"), ctx);
ctx.fetchNetworks([{ tvdbId: 1 }]).then(() => console.log(JSON.stringify({ redraws: redraws.length, logos: Object.keys(ctx.networksById) })));
""", str(JS / "schedule.js"), view, key, str(loaded).lower())
    assert shown == {"redraws": 1 if loaded else 0, "logos": ["7"]}


def test_reopening_suggest_services_stops_the_previous_run():
    shown = node(r"""
const progress = [], asked = [];
let release; const gate = new Promise((resolve) => { release = resolve; });
const boxes = {};
const $ = (sel) => (boxes[sel] ??= sel === "#bulk-progress" ? { set textContent(t) { progress.push(t); } } : { open: true, showModal() {}, replaceChildren() {}, set disabled(v) {}, set textContent(t) {} });
const ctx = { $, S: { series: [1, 2, 3, 4].map((tvdbId) => ({ tvdbId, tmdbId: tvdbId, monitored: true, title: `S${tvdbId}`, status: "continuing" })), config: { series: {}, hidden_series: [] }, services: [] },
  el: (tag, props = {}, ...kids) => ({ tag, ...props, kids, dataset: {}, querySelector: () => ({ replaceChildren() {} }) }), loading: () => null, posterSrc: () => "", posterFail: () => null,
  svcName: (t) => t, document: { querySelectorAll: () => [] }, api: async (path) => { asked.push(path); await gate; return { links: [] }; } };
vm.createContext(ctx);
vm.runInContext("let bulkRun = 0;" + grab("openBulk"), ctx);
(async () => {
  const first = ctx.openBulk();   // two workers are asking TMDB, two series wait
  const second = ctx.openBulk();  // the dialog was closed and opened again
  release();
  await Promise.all([first, second]);
  console.log(JSON.stringify({ asked: asked.length, progress }));
})();
""", str(JS / "settings-services.js"))
    assert shown == {"asked": 6, "progress": [f"Checked {n} of 4" for n in range(1, 5)]}


# The server waits up to 120 s for Sonarr and 60 s for a series search: the page must wait longer, or a slow answer shows as "did not answer".
@pytest.mark.parametrize("pane", ["missing", "upgrades"])
def test_list_panes_wait_as_long_as_the_server_does_for_sonarr(pane):
    assert node(LIST_PANES, str(JS / "activity.js"), pane, "wait") == {"waits": [130]}


def test_episode_list_waits_as_long_as_the_server_does_for_sonarr():
    shown = node(r"""
const s = { tvdbId: 1, id: 10, title: "Show" }, waits = [];
const ctx = { S: { sonarrsOf: { 1: [{ name: "4K", id: 9 }] }, config: { series: {} } }, current: s, epSonarr: "4K", epSonarrOf: 1, mainKeys: null, epAvailRaw: null, picked: new Set(),
  $: () => ({ replaceChildren() {} }), loading: () => null, failed: () => null, updateEpBar() {}, refreshEpBusy() {}, sxxOf: () => "S01E01",
  api: async (path, opts = {}) => { if (/^\/api\/series\/\d+\/episodes/.test(path)) waits.push(opts.wait); return []; }, applyBroadcast() { throw new Error("past the guard"); } };
vm.createContext(ctx);
vm.runInContext("let epSeq = 0;" + grab("loadEpisodes"), ctx);
ctx.loadEpisodes(s).catch(() => {}).then(() => console.log(JSON.stringify({ waits })));
""", str(JS / "series.js"))
    assert shown == {"waits": [130, 130]}


def test_series_search_waits_as_long_as_the_server_does():
    shown = node(r"""
const waits = [], s = { tvdbId: 1 };
const field = { value: "Show", hidden: false, replaceChildren() {} };
const ctx = { current: s, S: { config: { series: { 1: { service: "X" } } } }, $: () => field, el: () => ({}), loading: () => null, svcName: (t) => t,
  api: async (path, opts = {}) => { waits.push(opts.wait); return { results: [] }; } };
vm.createContext(ctx);
const click = vm.runInContext(src.match(/\$\("#d-find-go"\)\.onclick = (async \(\) => \{[\s\S]*?\n\});/)[1], ctx);
click().then(() => console.log(JSON.stringify({ waits })));
""", str(JS / "core.js"))
    assert shown == {"waits": [70]}


def test_coming_back_to_the_tab_does_not_stream_an_old_run_into_the_serve_log():
    shown = node(r"""
const jsDir = process.argv[2], sockets = [], written = [];
class FakeSocket { constructor(url) { this.url = url; sockets.push(this); } close() {} }
class FakeTerminal { loadAddon() {} open() {} reset() {} resize() {} write(t) { written.push(typeof t === "string" ? t : "output"); } }
let hidden = false, onVisibility;
const box = { hidden: false, open: true, replaceChildren() {}, classList: { add() {} }, textContent: "" };
const ctx = { window: { Terminal: FakeTerminal }, Terminal: FakeTerminal, FitAddon: { FitAddon: class { proposeDimensions() {} } }, ResizeObserver: class { observe() {} },
  term: null, termFit: null, termSocket: null, termFor: null, termQuery: "", termResume: null, liveFeed: null, liveNext: null, picked_run: null, TERM_COLS: 110,
  $: () => box, el: () => ({}), termFilter: () => (b) => b, WebSocket: FakeSocket, location: { protocol: "http:", host: "x" }, api: async () => ({ log: "serve line" }), showTab() {},
  openActivity() {}, document: { get hidden() { return hidden; }, addEventListener: (_, fn) => { onVisibility = fn; }, querySelectorAll: () => [] } };
vm.createContext(ctx);
vm.runInContext(["fitTerminal", "openTerm", "streamTerm"].map((n) => grab(n)).join(""), ctx);
vm.runInContext(grab("showServeLog", read(jsDir + "/settings-services.js")), ctx);
vm.runInContext(`document.addEventListener("visibilitychange", ${read(jsDir + "/activity.js").match(/addEventListener\("visibilitychange", (\(\) => \{[\s\S]*?\n\})\);/)[1]});`, ctx);
(async () => {
  ctx.streamTerm("run:1", "run=1");  // a run's output is streaming
  await ctx.showServeLog();  // then the serve log is opened over it
  hidden = true; onVisibility();  // the tab is hidden, then back in sight
  hidden = false; onVisibility();
  console.log(JSON.stringify(sockets.map((s) => s.url.split("?")[1])));
})();
""", str(JS / "attempts.js"), str(JS))
    assert shown == ["run=1"]
