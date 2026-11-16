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
