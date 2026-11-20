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
const main = { children: [], replaceChildren(...children) { this.children = children; },
  get heading() { return JSON.stringify(this.children).match(/"textContent":"(Stats|Waiting in downloads)"/)?.[1] ?? "other"; } };
const title = { textContent: "" };
const stub = { textContent: "", hidden: false, classList: { add() {} }, replaceChildren() {} };
const pending = {};
const ctx = {
  $: (sel) => (sel === "#cd-main" ? main : sel === "#cd-top-title" ? title : stub),
  document: { querySelectorAll: () => [] },
  el: (tag, props = {}, ...kids) => ({ tag, ...props, kids }),
  failed: (t) => ({ failed: t }),
  clearTimeout() {},
  api: (path) => new Promise((resolve, reject) => { pending[path] = { resolve, reject }; }),
  day: () => "", ago: () => "", duration: () => "", LOCALE: "en", S: { series: [] }, svcName: (tag) => tag, icon: () => ({}), COUNT: {}, posterSrc: () => "", posterFail: () => null, OUTCOME: {}, renderDock: () => {},
};
vm.createContext(ctx);
vm.runInContext(`let picked_run = null, langTimer, langLast;\n` +
  ["markPicked", "showLeftovers", "showStats", "showLanguages"].map(grab).join("\n"), ctx);
const path = { stats: "/api/stats", left: "/api/leftovers" };
const answer = { stats: { month: {}, weeks: [], services: [], since: null }, left: { items: [], days: 0 } };
const open = { stats: ctx.showStats, left: ctx.showLeftovers };
(async () => {
  if (first === "languages") {
    const languages = ctx.showLanguages(), replacement = open[second]();
    pending[path[second]].resolve(answer[second]);
    await replacement;
    const content = main.children;
    pending["/api/languages"].reject(Error("network offline"));
    await languages;
    console.log(JSON.stringify({ title: title.textContent, heading: main.heading, unchanged: main.children === content }));
    return;
  }
  const a = open[first](), b = open[second]();
  for (const which of [second, first]) { pending[path[which]].resolve(answer[which]); await (which === second ? b : a); }
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


ACTIVITY_ACTIONS = r"""
const fs = require("fs"), vm = require("vm");
const [dir, scenario, ...args] = process.argv.slice(1);
const src = fs.readFileSync(`${dir}/activity.js`, "utf8");
const series = fs.readFileSync(`${dir}/series.js`, "utf8");
const grab = (name, text = src) => text.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const line = (name, text = src) => text.match(new RegExp(`^const ${name} = .*?;(?:  //.*)?$`, "m"))[0];
const elements = {};
const el = (tag, props = {}, ...children) => ({ tag, children, classList: { add() {} },
  replaceChildren(...kids) { this.children = kids; }, querySelector: () => null,
  insertBefore(child) { this.children.push(child); }, cloneNode() { return { ...this }; }, ...props });
const $ = (sel) => elements[sel] ??= el(sel);
const walk = (n) => n?.tag ? [n, ...n.children.flatMap(walk)] : [];
const posts = [], toasts = [], opened = [];
const target = args[0] || "";
const sonarrs = [{ name: "4K", quality_ladder: ["2160"] }, { name: "Unset" }];
const ctx = { $, el, URLSearchParams, LOCALE: "en", KIND: {}, DOCK: {},
  S: { config: { settings: { sonarrs }, series: { 72: { service: "NF", season_pages: { 2: { service: "DSNP" } } } } },
    serviceNames: { NF: "Netflix", DSNP: "Disney+" }, series: [] },
  savedSonarr: (n) => n === "4K" ? "4K Saved" : n, mainSonarr: () => "Main",
  markPicked() {}, renderDock() {}, loading() {}, posterSrc() {}, posterFail() {}, ago: () => "yesterday",
  toast: (...data) => toasts.push(data), episodeTitle: (_, __, title) => title, trWith: (key) => key,
  api: async (path, options) => {
    if (options.method === "POST") {
      posts.push({ path, body: JSON.parse(options.body) });
      if (args[1] === "refused") throw Error("read-only proxy");
      return;
    }
    return { items: [
      { episodeId: 123, tvdbId: 72, series: "Example", sxxeyy: "S01E05" },
      { episodeId: 456, tvdbId: 72, series: "Example", sxxeyy: "S02E01" },
    ] };
  },
  FINISHING: new Set(), jobHidden: new Set(), jobCards: new Map(), openCards: new Set(),
  following: null, isLive: () => false, thumb() {}, posterOf() {}, day() {}, time() {},
  outcomeOf: (c) => c.outcome, hovering: () => "", stepStates: () => [], icon() {}, glideBars() {}, jobDone: () => el("div"),
  openServiceRow: (...data) => opened.push(data),
};
vm.createContext(ctx);
vm.runInContext(`let picked_run, missingDays = 30, missingSonarr = "", missingSeq = 0;\n` +
  [line("svcName", series), grab("seasonTag", series), line("fixSignIn"),
    ...["sonarrPicker", "unsetNote", "showMissing", "signInFailed", "signInAction", "cardKind", "jobState", "renderJob"].map((n) => grab(n))
  ].join("\n"), ctx);
(async () => {
  if (scenario === "job") {
    const card = { tvdbId: 72, series: "Example", outcome: "failed", started: "2026-01-01", service: "NF" };
    const auth = target === "classified" ? { auth_failures: { DSNP: "expired" }, auth_failure_backends: { DSNP: "secondary" } }
      : { cause: "Login failed" };
    ctx.renderJob({ job: "job1", cards: [{ ...card, id: "a", episodeId: 123 }, { ...card, ...auth, id: "b", episodeId: 456 }] });
    const buttons = $("#cd-foot").children;
    buttons.find((b) => b.textContent === "Fix sign-in")?.onclick();
    console.log(JSON.stringify({ primary: buttons.filter((b) => b.className.includes("primary")).map((b) => b.textContent), opened }));
    return;
  }
  await ctx.showMissing();
  if (target) {
    walk($("#cd-main")).find((n) => n.tag === "button" && n.textContent === target).onclick();
    await new Promise(setImmediate);
  }
  const all = walk($("#cd-main"));
  const rows = all.filter((n) => n.className?.split(" ").includes("left-row"));
  const buttons = rows.map((r) => walk(r).find((n) => n.tag === "button" && n.textContent === "Download"));
  const bulk = all.find((n) => n.tag === "button" && n.textContent === "Download the 2");
  const click = (b) => b?.onclick({ currentTarget: b, target: b });
  for (const action of scenario.split("-")) await click(action === "row" ? buttons[1] : bulk);
  console.log(JSON.stringify({ posts, toasts, bulkHidden: bulk.hidden, chips: rows.map((r) =>
    walk(r).find((n) => n.className === "sv-chip")?.textContent),
    buttons: buttons.map((b) => b && { primary: b.className.includes("primary"), disabled: !!b.disabled }) }));
})();
"""


@pytest.mark.parametrize(("target", "sonarr"), [("", {}), ("4K", {"sonarr": "4K Saved"})])
def test_catch_up_row_download_uses_same_sonarr_as_bulk(target, sonarr):
    row = node(ACTIVITY_ACTIONS, str(JS), "row", target)
    bulk = node(ACTIVITY_ACTIONS, str(JS), "bulk", target)
    assert row["posts"] == [{"path": "/api/download", "body": {"episodeIds": [456], **sonarr}}]
    assert bulk["posts"] == [{"path": "/api/download", "body": {"episodeIds": [123, 456], **sonarr}}]
    assert row["chips"] == ["Netflix", "Disney+"]
    assert row["buttons"] == [{"primary": False, "disabled": False}, {"primary": False, "disabled": True}]


@pytest.mark.parametrize("action", ["row", "bulk"])
def test_catch_up_never_queues_when_sonarr_quality_is_unset(action):
    result = node(ACTIVITY_ACTIONS, str(JS), action, "Unset")
    assert result["posts"] == []
    assert result["bulkHidden"] is True
    assert all(b and b["disabled"] for b in result["buttons"])


def test_catch_up_download_error_allows_retry():
    result = node(ACTIVITY_ACTIONS, str(JS), "row", "", "refused")
    assert result["toasts"] == [["read-only proxy", True]]
    assert result["buttons"][1]["disabled"] is False


@pytest.mark.parametrize(("order", "sent"), [("row-bulk", [[456], [123]]), ("bulk-row", [[123, 456]])])
def test_catch_up_row_and_bulk_do_not_queue_the_same_episode(order, sent):
    result = node(ACTIVITY_ACTIONS, str(JS), order)
    assert [request["body"]["episodeIds"] for request in result["posts"]] == sent
    assert all(b["disabled"] for b in result["buttons"])


@pytest.mark.parametrize(("classification", "primary", "opened"), [
    ("classified", ["Fix sign-in"], [["DSNP", "secondary"]]),
    ("unclassified", ["Retry 2 failed"], []),
])
def test_failed_job_footer_offers_sign_in_only_for_classified_failure(classification, primary, opened):
    result = node(ACTIVITY_ACTIONS, str(JS), "job", classification)
    assert result == {"primary": primary, "opened": opened}


SWITCHER = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8"), html = fs.readFileSync(process.argv[2], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const line = (name) => src.match(new RegExp(`^const ${name} = .*;$`, "m"))[0];
const handler = (id) => src.match(new RegExp(`^\\$\\("#${id}"\\)\\.onclick = .*?^\\};`, "ms"))[0];
const doc = { activeElement: null };
const node = (props = {}) => ({
  children: [], attrs: {}, dataset: {}, classList: { toggle() {}, add() {}, remove() {} },
  setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
  replaceChildren(...children) { this.children = children; }, get childElementCount() { return this.children.length; },
  focus() { doc.activeElement = this; },
  getBoundingClientRect: () => ({ left: 0, right: 100, width: 100 }),
  ...props,
});
const elements = { "#con-search": node({ value: "" }) };
const buttons = [...html.matchAll(/id="(con-[^"]+)" data-con-view="([^"]+)" aria-pressed="([^"]+)"/g)].map(([, id, conView, pressed]) =>
  elements[`#${id}`] = node({ dataset: { conView }, attrs: { "aria-pressed": pressed } }));
const $ = (s) => {
  if (s.startsWith("#cd-main > ")) return $("#cd-main").children.find((n) => [`.${n.className}`, `#${n.id}`].includes(s.slice(11)));
  const chip = s.match(/^#con-running \[data-fk="([^"]+)"\]$/);
  if (chip) return $("#con-running").children.find((n) => n.dataset.fk === chip[1]);
  if (s.startsWith("[data-fk=")) return undefined;
  return elements[s] ??= node();
};
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
  document: Object.assign(doc, { getElementById: (id) => elements[`#${id}`], querySelectorAll: (s) => ({
    ".con-views [data-con-view]": buttons, "#con-running .chip": $("#con-running").children,
    "#con .crow": [...$("#runs-live").children, ...$("#runs-history").children],
  })[s] || [] }), glideBars() {}, emptyHistory: () => node(),
  scrollTo() {}, focusHeading: (heading) => heading.focus(), getComputedStyle: () => ({ scrollPaddingInlineEnd: "0px" }),
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
  ["con-downloads", "cd-back"].map(handler).join("\n"), ctx);
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
else if (scenario === "back-to-chip") {
  ctx.innerWidth = 500;
  addRuns([active, history]);
  const chip = strip.children[0], back = $("#cd-back");
  chip.onclick();
  const opened = detail;
  back.focus();
  back.onclick();
  console.log(JSON.stringify([opened, detail, doc.activeElement === chip]));
}
else if (scenario === "downloads-width") {
  addRuns([active, history]);
  $("#runs-history").children[0].onclick();
  const downloads = $("#con-downloads"), list = $("#runs-history"), row = list.children[0];
  const state = () => [detail, downloads.getAttribute("aria-pressed"), list.children[0] === row];
  const before = state();
  const click = () => downloads.onclick({ currentTarget: downloads });
  click();
  const wide = state();
  ctx.innerWidth = 500;
  click();
  console.log(JSON.stringify([before, wide, state()]));
}
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


def test_back_from_a_running_download_returns_focus_to_its_chip():
    assert switcher("back-to-chip") == ["live", None, True]


def test_pressed_downloads_keeps_wide_detail_but_returns_to_the_narrow_list():
    assert switcher("downloads-width") == [["old", "true", True], ["old", "true", True], [None, "true", False]]


def test_late_languages_error_does_not_replace_stats_content():
    assert node(PANES, str(JS / "activity.js"), '["languages", "stats"]') == {
        "title": "Stats", "heading": "Stats", "unchanged": True,
    }


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
