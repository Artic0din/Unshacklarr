"""Activity's Stats and Waiting in downloads panes draw only their own answer; the output terminal says when it cannot connect."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"

# Runs the page's real showStats / showLeftovers with api answers released in a chosen order, and prints what the pane ended up showing.
PANES = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const [first, second] = JSON.parse(process.argv[2]);  // the pane opened first, then the one opened second
const main = { heading: null, replaceChildren(...k) { this.heading = JSON.stringify(k).match(/"textContent":"(Stats|Waiting in downloads)"/)?.[1] ?? "other"; } };
const title = { textContent: "" };
const stub = { textContent: "", hidden: false, classList: { add() {} }, replaceChildren() {} };
const pending = {};
const ctx = {
  $: (sel) => (sel === "#cd-main" ? main : sel === "#cd-top-title" ? title : stub),
  document: { querySelectorAll: () => [] },
  el: (tag, props = {}, ...kids) => ({ tag, ...props, kids }),
  failed: (t) => ({ failed: t }),
  api: (path) => new Promise((resolve) => { pending[path] = resolve; }),
  day: () => "", ago: () => "", duration: () => "", LOCALE: "en", S: { series: [] }, svcName: (tag) => tag, icon: () => ({}), COUNT: {}, posterSrc: () => "", posterFail: () => null, OUTCOME: {}, renderDock: () => {},
};
vm.createContext(ctx);
vm.runInContext(`var picked_run = null;\n${grab("markPicked")}\n${grab("showLeftovers")}\n${grab("showStats")}`, ctx);
const path = { stats: "/api/stats", left: "/api/leftovers" };
const answer = { stats: { month: {}, weeks: [], services: [], since: null }, left: { items: [], days: 0 } };
const open = { stats: ctx.showStats, left: ctx.showLeftovers };
(async () => {
  const a = open[first](), b = open[second]();
  for (const which of [second, first]) { pending[path[which]](answer[which]); await (which === second ? b : a); }
  console.log(JSON.stringify({ title: title.textContent, heading: main.heading }));
})();
"""

# Runs the page's real streamTerm against a fake socket and prints what was written into the terminal box.
TERMINAL = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const scenario = process.argv[2];
const written = [];
const sockets = [];
class FakeSocket { constructor() { sockets.push(this); } close() {} }
const ctx = { term: { write: (t) => written.push(typeof t === "string" ? t : "output") }, termSocket: null, termFor: null, termQuery: "",
  openTerm: () => true, termFilter: () => (b) => b, WebSocket: FakeSocket, location: { protocol: "http:", host: "x" } };
vm.createContext(ctx);
vm.runInContext(grab("streamTerm"), ctx);
ctx.streamTerm("run", "run=1");
const sock = sockets[0];
if (scenario === "output first") sock.onmessage({ data: new ArrayBuffer(1) });
if (scenario === "replaced") { ctx.termSocket = {}; }
sock.onclose?.(scenario === "clean" ? { code: 1000 } : { code: 1006 });
console.log(JSON.stringify(written));
"""


def node(script, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", script, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


SWITCHER = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8"), html = fs.readFileSync(process.argv[2], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const line = (name) => src.match(new RegExp(`^const ${name} = .*;$`, "m"))[0];
const node = (props = {}) => ({
  children: [], attrs: {}, dataset: {}, classList: { toggle() {}, add() {}, remove() {} },
  setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
  replaceChildren(...children) { this.children = children; }, get childElementCount() { return this.children.length; },
  ...props,
});
const elements = { "#con-search": node({ value: "" }) };
const buttons = [...html.matchAll(/id="(con-[^"]+)" data-con-view="([^"]+)" aria-pressed="([^"]+)"/g)].map(([, id, conView, pressed]) =>
  elements[`#${id}`] = node({ dataset: { conView }, attrs: { "aria-pressed": pressed } }));
const $ = (s) => s.startsWith("#cd-main > ")
  ? $("#cd-main").children.find((n) => [`.${n.className}`, `#${n.id}`].includes(s.slice(11)))
  : elements[s] ??= node();
let detail = null;
const pending = {};
const strip = $("#con-running"), classes = new Set();
let scroll = () => {}, resize = () => {};
Object.assign(strip, { scrollLeft: 0, scrollWidth: 800, clientWidth: 300,
  addEventListener: (event, listener) => { if (event === "scroll") scroll = listener; },
  classList: { toggle: (name, on) => on ? classes.add(name) : classes.delete(name) },
});
const ctx = { $, innerWidth: 1000, el: (tag, props) => node(props),
  CSS: { supports: () => process.argv[3] !== "chip-overflow" },
  ResizeObserver: class { constructor(callback) { resize = callback; } observe() {} },
  document: { querySelectorAll: (s) => ({
    ".con-views [data-con-view]": buttons, "#con-running .chip": $("#con-running").children,
    "#con .crow": [...$("#runs-live").children, ...$("#runs-history").children],
  })[s] || [] }, glideBars() {}, emptyHistory: () => node(),
  itemRow: (item) => node({ dataset: { hk: `row:${ctx.keyOf(item)}` }, onclick: () => ctx.pickRun(ctx.keyOf(item)) }),
  renderDetail: (card) => { detail = card.id; }, renderJob: (job) => { detail = `job:${job.job}`; },
  nothingPicked: () => { detail = null; $("#cd-main").replaceChildren(); }, keepFocus: (_, draw) => draw(),
  loading: () => node({ className: "loading" }), renderDock() {}, failed: (textContent) => node({ textContent }),
  clearTimeout() {}, setTimeout() {}, activityLater() {}, forgetGoneRuns() {}, followLive() {},
  api: (path) => new Promise((resolve, reject) => { pending[path] = { resolve, reject }; }),
};
vm.createContext(ctx);
if (src.includes("function watchRunningChipEdge")) {
  vm.runInContext(grab("watchRunningChipEdge") + "\n" + line("syncRunningChipEdge"), ctx);
}
vm.runInContext(`let picked_run = null, runBackKey, landOnLive = false, conFilter = "all", runCards = [], runsShown = 50, runsSeq = 0, runsTimer, liveFeed;\n` +
  ["itemKey", "isLive", "isQueued"].map(line).join("\n") + "\n" +
  ["openActivity", "renderConsole", "drawRunningChips", "drawConsole", "jobsOf", "markPicked", "pickRun", "openActivityTool", "showStats"].map(grab).join("\n") +
  '\nthis.keyOf = itemKey;\n' + src.match(/^\$\("#con-stats"\)\.onclick = .*;$/m)[0] + "\n" +
  src.match(/^\$\("#con-downloads"\)\.onclick = .*?^\};/ms)[0], ctx);
const pressed = () => buttons.filter((b) => b.attrs["aria-pressed"] === "true").map((b) => b.dataset.conView);
const snapshot = () => [pressed(), $("#con-running").hidden, detail];
const addRuns = (cards, liveOnly = false) => {
  ctx.cards = cards;
  vm.runInContext(`runCards = cards; renderConsole(${liveOnly})`, ctx);
};
const active = { id: "live", series: "Show", sxxeyy: "S01E01", outcome: "running", step: "downloading", batch: "batch" };
const queued = { ...active, id: "queued", sxxeyy: "S01E02", waiting: true, step: "queued" };
const history = { id: "old", series: "Older", outcome: "downloaded" };
async function lateRuns(selection) {
  // On phones opening Activity from the menu would automatically open the first live download.
  ctx.innerWidth = 500;
  ctx.scrollTo = ctx.focusHeading = () => {};
  if (selection !== "stats") addRuns([active, history]); // Cached rows remain available during a refresh.
  vm.runInContext("landOnLive = true", ctx);
  const request = ctx.openActivity();
  if (selection === "stats") $("#con-stats").onclick();
  if (selection === "downloads") $("#con-downloads").onclick({ currentTarget: $("#con-downloads") });
  if (selection === "run") $("#runs-history").children[0].onclick();
  pending["/api/runs"].resolve([active, history]);
  await request;
  console.log(JSON.stringify([pressed(), detail]));
}
async function failedRuns(selection) {
  const request = ctx.openActivity();
  if (selection === "stats") $("#con-stats").onclick();
  else {
    const id = html.match(/id="cd-main"><div ([^>]+)/)[1].match(/\bid="([^"]+)"/)?.[1];
    $("#cd-main").replaceChildren(node({ className: "loading", id }));
  }
  const loader = $("#cd-main").children[0];
  pending["/api/runs"].reject(Error("network offline"));
  await request;
  console.log(JSON.stringify([pressed(), $("#cd-main").children[0] === loader, $("#runs-live").children[0].textContent]));
}
function switchViews() {
const states = [pressed()];
addRuns([queued, history]);
states.push(snapshot());
addRuns([active, queued, history]);
const chip = $("#con-running").children[0];
const chipCount = $("#con-running").childElementCount;
addRuns([{ ...active, live: { progress: 10 } }, queued, history], true);
const steady = chip === $("#con-running").children[0];
$("#con-stats").onclick();
states.push(snapshot());
$("#runs-history").children[0].onclick();
states.push(snapshot());
$("#con-stats").onclick();
$("#runs-live").children[0].onclick();
states.push(snapshot());
$("#runs-history").children[0].onclick();
chip.onclick();
states.push(snapshot(), chip.attrs["aria-current"]);
vm.runInContext('picked_run = "serve"; markPicked(picked_run); landOnLive = true; renderConsole()', ctx);
states.push(snapshot());
$("#con-downloads").onclick({ currentTarget: $("#con-downloads") });
states.push(snapshot());
addRuns([history]);
states.push($("#con-running").hidden);
console.log(JSON.stringify({ states, chipCount, steady }));
}
const scenario = process.argv[3];
if (scenario === "chip-overflow") {
  const cue = () => classes.has("more-chips");
  addRuns([active]);
  const atStart = cue();
  strip.scrollLeft = 500; scroll();
  const atEnd = cue();
  strip.scrollLeft = 0; scroll();
  const backAtStart = cue();
  strip.clientWidth = 800; resize();
  console.log(JSON.stringify([atStart, atEnd, backAtStart, cue()]));
}
else if (scenario === "fail-stats" || scenario === "fail-downloads") failedRuns(scenario.slice(5));
else if (scenario) lateRuns(scenario);
else switchViews();
"""


def switcher(*args):
    return node(SWITCHER, str(JS / "activity.js"), str(JS.parent / "index.html"), *args)


def test_running_strip_keeps_overflow_cue_without_scroll_timeline():
    assert switcher("chip-overflow") == [True, False, True, False]
    css = (JS.parent / "app.css").read_text()
    assert re.search(r"@supports not \(animation-timeline: scroll\(\)\)\s*\{\s*"
                     r"\.con-running\.more-chips\s*\{[^}]*mask-image:", css)


def test_switcher_follows_run_selection_and_only_shows_chips_for_running_downloads():
    shown = switcher()
    assert shown == {
        "chipCount": 1,
        "steady": True,
        "states": [
            ["downloads"], [["downloads"], True, "queued"], [["stats"], True, "queued"],
            [["downloads"], False, "old"], [["downloads"], False, "job:batch"],
            [["downloads"], False, "job:batch"], "true", [[], True, "job:batch"],
            [["downloads"], False, "job:batch"], True,
        ],
    }


@pytest.mark.parametrize(("selection", "expected"), [
    ("stats", [["stats"], None]),
    ("downloads", [["downloads"], None]),
    ("run", [["downloads"], "old"]),
])
def test_pending_runs_do_not_override_an_explicit_selection(selection, expected):
    assert switcher(selection) == expected


def test_failed_runs_leave_a_pending_tool_loader_in_place():
    assert switcher("fail-stats") == [["stats"], True, "Could not load the downloads: network offline"]
    assert switcher("fail-downloads") == [["downloads"], False, "Could not load the downloads: network offline"]


@pytest.mark.parametrize("suggestions", [{"2": {"service": "SBS", "count": 8}}, {}])
@pytest.mark.parametrize("failure", [False, True])
def test_series_refresh_displays_new_search_before_a_slower_saved_result(suggestions, failure):
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8"), suggestions = JSON.parse(process.argv[2]);
const failure = JSON.parse(process.argv[3]), errors = [];
const s = { tvdbId: 1, id: 10, title: "Show" }, stub = { replaceChildren() {}, setAttribute() {}, removeAttribute() {} };
let rendered;
const pages = Object.fromEntries(Array.from({length: 10}, (_, i) => [i + 1, {url: `https://iview/season-${i + 1}`} ]));
const ctx = { S: { services: ["IV", "SBS", "NF"], config: { series: { 1: {season_pages: pages} } } }, current: s, epElsewhere: { 3: { service: "NF" } }, epElsewhereFresh: false,
  $: () => stub, el: () => ({}), seriesSvcs: () => "IV", slowHint: () => 0, clearTimeout() {},
  api: async (path, opts) => {
    if (opts.wait < 1100) throw Error("No answer before slow season pages and services finish");
    return { elsewhere: suggestions, elsewhere_error: failure ? "Search failed" : undefined, available: {}, checked: "2026-11-13T02:00:00Z" };
  },
  viewAvail: (x) => x, localTitles() {}, renderSeason: () => { rendered = ctx.epElsewhere; },
  renderPreview() {}, renderCatchUp() {}, checkLabel() {}, renderSeriesLanguage() {}, toast: (message) => { errors.push(message); } };
vm.createContext(ctx);
vm.runInContext(src.match(/async function askService\b[\s\S]*?\n}\n/)[0], ctx);
(async () => {
  await ctx.askService(s);
  const cache = src.match(/api\(`\/api\/probe\/\$\{s.tvdbId\}`\)\.then\((\(hit\) => \{[\s\S]*?)\n    }\)\.catch/)[1] + "\n}";
  ctx.s = s;
  vm.runInContext(`(${cache})({elsewhere: {4: {service: "STAN"}}, checked: "2026-11-13T03:00:00Z", elsewhere_checked: "2026-11-12T02:00:00Z"})`, ctx);
  console.log(JSON.stringify({ rendered, kept: ctx.epElsewhere, errors }));
})();
""", str(JS / "series.js"), json.dumps(suggestions), json.dumps(failure))
    assert shown == {"rendered": suggestions, "kept": suggestions,
                     "errors": ["Availability refreshed, but the search on other services failed: Search failed"] if failure else []}


@pytest.mark.parametrize("on_service", ["none", "future", "aired"])
def test_other_service_suggestions_are_visible_when_every_aired_episode_is_on_disk(on_service):
    shown = node(r"""
const fs = require("fs"), vm = require("vm"), src = fs.readFileSync(process.argv[1], "utf8");
const box = { hidden: true, classList: {toggle() {}}, replaceChildren(...kids) { this.kids = kids; } };
const onService = process.argv[2];
const ctx = { $: () => box, svcName: (tag) => tag, COUNT: { episode: (n) => n === 1 ? "1 episode" : `${n} episodes`, upgrade: (n) => `${n}`, missingEpisode: (n) => `${n}` }, current: {tvdbId: 1}, S: {config: {series: {1: {service: "BINGE"}}}},
  epSeasons: {7: [{id: 1, seasonNumber: 7, hasFile: true, sonarrAir: "2000-01-01T00:00:00Z"}, {id: 2, seasonNumber: 7, hasFile: false, sonarrAir: "2999-01-01T00:00:00Z"}]},
  epAvail: onService === "none" ? {} : {[onService === "aired" ? 1 : 2]: {service: "S07E01"}}, epBusy: new Map(), epPages: {}, epElsewhere: {7: {service: "NINE", count: 5, url: "https://9now/paramedics"}},
  state: (e) => e.hasFile ? "disk" : "soon", belowAsked: () => false, seriesSvcs: () => "BINGE", seasonSvc: () => "BINGE",
  document: {querySelectorAll: () => []}, el: (tag, props = {}, ...kids) => ({tag, ...props, kids}) };
vm.createContext(ctx);
vm.runInContext(src.match(/function renderCatchUp\b[\s\S]*?\n}\n/)[0], ctx);
ctx.renderCatchUp();
console.log(JSON.stringify({hidden: box.hidden, content: JSON.stringify(box.kids || [])}));
""", str(JS / "series.js"), on_service)
    assert shown["hidden"] is (on_service == "aired")
    assert ("Season 7 is on NINE (5 episodes)" in shown["content"]) is (on_service != "aired")


@pytest.mark.parametrize("first,second,heading", [("stats", "left", "Waiting in downloads"), ("left", "stats", "Stats")])
def test_a_late_answer_does_not_fill_the_pane_of_the_one_picked_since(first, second, heading):
    shown = node(PANES, str(JS / "activity.js"), json.dumps([first, second]))
    assert shown == {"title": heading, "heading": heading}


def test_terminal_says_so_when_it_closes_before_any_output():
    written = node(TERMINAL, str(JS / "attempts.js"), "silent")
    assert len(written) == 1 and "WebSocket" in written[0]


def test_terminal_stays_quiet_when_it_closes_after_output():
    assert node(TERMINAL, str(JS / "attempts.js"), "output first") == ["output"]


def test_terminal_stays_quiet_when_the_server_ends_it_cleanly_with_no_output():
    assert node(TERMINAL, str(JS / "attempts.js"), "clean") == []  # a cancelled episode has no log


def test_terminal_ignores_the_close_of_a_socket_it_already_replaced():
    assert node(TERMINAL, str(JS / "attempts.js"), "replaced") == []


def test_opening_languages_clears_the_dock_of_the_download_shown_before():
    # The dock's Stop, Retry and Pause act on the download it was drawn for: Languages is no download
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const docks = [];
const stub = { textContent: "", hidden: false, classList: { add() {} }, replaceChildren() {} };
const ctx = { $: () => stub, document: { querySelectorAll: () => [] }, api: () => new Promise(() => {}),
  renderDock: (d) => docks.push(d), clearTimeout() {} };
vm.createContext(ctx);
vm.runInContext(`var picked_run = null, langTimer = null, langLast = null;\n${grab("markPicked")}\n${grab("showLanguages")}`, ctx);
ctx.showLanguages();
console.log(JSON.stringify(docks));
""", str(JS / "activity.js"))
    assert shown == [None]
