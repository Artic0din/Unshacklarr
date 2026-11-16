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
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n|const ${name} = [\\s\\S]*?\\n};?\\n|const ${name} = [^\\n]*\\n`))[0];
"""


def node(script, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PRELUDE + script, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_history_answer_keeps_newer_live_progress():
    shown = node(r"""
const card = (progress) => ({ id: "a", outcome: "running", step: "downloading", live: { status: "downloading", progress } });
let answer;
const ctx = { runCards: [card(10)], runsTimer: null, liveFeed: null, feedReloading: false, feedMissed: null, feedSeen: new Set(),
  $: () => ({ hidden: false, textContent: "" }), api: (path) => (path === "/api/runs" ? new Promise((resolve) => { answer = resolve; }) : Promise.resolve({ items: [] })),
  renderConsole() {}, followLive() {}, activityLater() {}, failed: () => null, setTimeout: () => 0, clearTimeout() {} };
vm.createContext(ctx);
vm.runInContext("let runsSeq = 0;" + ["isLive", "feedChanged"].map(grab).join("") + grab("openActivity") + grab("liveTick"), ctx);
(async () => {
  const reload = ctx.openActivity();
  ctx.liveTick(JSON.stringify([card(60)]));  // drawn while the history answer is on its way
  answer([card(10), { id: "old", outcome: "downloaded" }]);  // produced before that message
  await reload;
  console.log(JSON.stringify({ progress: ctx.runCards[0].live.progress, history: ctx.runCards.map((c) => c.id) }));
})();
""", str(JS / "activity.js"))
    assert shown == {"progress": 60, "history": ["a", "old"]}


def test_history_answer_takes_card_when_no_live_message_came():
    shown = node(r"""
const card = (progress) => ({ id: "a", outcome: "running", step: "downloading", live: { status: "downloading", progress } });
const ctx = { runCards: [card(10)], runsTimer: null, liveFeed: null, feedReloading: false, feedMissed: null, feedSeen: new Set(),
  $: () => ({ hidden: false, textContent: "" }), api: async (path) => (path === "/api/runs" ? [card(30)] : { items: [] }),
  renderConsole() {}, followLive() {}, activityLater() {}, failed: () => null, setTimeout: () => 0, clearTimeout() {} };
vm.createContext(ctx);
vm.runInContext("let runsSeq = 0;" + ["isLive", "feedChanged"].map(grab).join("") + grab("openActivity") + grab("liveTick"), ctx);
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
const draws = [], posts = [];
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
    const slow = pane === "missing" ? !path.includes("days=") && !path.includes("sonarr=B") : path.includes("sonarr=A") || path === "/api/upgrades";
    const slowIds = [1, 2, 3], fastIds = [1, 2];
    const ids = scenario === "click" ? slowIds : slow ? slowIds : fastIds;
    return wait(scenario === "click" ? 0 : slow ? 30 : 0, pane === "missing" ? { items: items(ids) } : { scan: { running: false }, items: items(ids), checked: null });
  } };
vm.createContext(ctx);
const lets = [/^let missingDays.*\n/m, /^let upgradeTimer.*\n/m, /^let upgradeLast\b.*\n/m].map((re) => src.match(re)[0]).join("");
vm.runInContext(lets + ["sonarrPicker", "unsetNote", "showMissing", "showUpgrades"].map(grab).join(""), ctx);
vm.runInContext("upgradePick.add(1); upgradePick.add(2); upgradePick.add(3);", ctx);
const show = (sonarr, days) => { vm.runInContext(pane === "missing" ? `missingSonarr = ${JSON.stringify(sonarr)}; missingDays = ${days};` : `upgradeSonarr = ${JSON.stringify(sonarr)};`, ctx); return pane === "missing" ? ctx.showMissing() : ctx.showUpgrades(); };
const goText = () => find(draws[draws.length - 1], (n) => n.className === "btn primary")?.textContent;
(async () => {
  if (scenario === "overtaken") {  // the slow request first (All, or Sonarr A), the quick one picked right after (7 days, or Sonarr B)
    const slow = show(pane === "missing" ? "" : "A", 0), fast = show(pane === "missing" ? "" : "B", 7);
    await Promise.all([slow, fast]);
    console.log(JSON.stringify({ shown: goText() }));
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
