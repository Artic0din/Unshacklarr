"""Small fixes to the page's scripts (static/js, sw.js), each run for real in Node with only the globals it reaches named."""
import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
JS = STATIC / "js"

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
"""


def node(body, *args, input_text=None):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PRELUDE + body, "--", *args], input=input_text, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_service_defaults_still_draw_when_one_service_cannot_list_its_options():
    shown = node(r"""
const src = read(process.argv[1]);
let drawn = null;
const ctx = sandbox({
  S: { config: { service_defaults: { GONE: {} }, settings: {} }, dlOptions: [], services: ["GONE"] },
  loadServiceOptions: async () => { throw Error("502"); },
  $: (sel) => (sel === "#svc-defaults" ? { replaceChildren: (...kids) => { drawn = kids.map((k) => k.className ?? k.tag); } } : any),
});
vm.runInContext(grab(src, /async function renderServiceDefaults\b[\s\S]*?\n}\n/), ctx);
ctx.renderServiceDefaults().then(() => console.log(JSON.stringify(drawn)), (e) => console.log(JSON.stringify("threw: " + e.message)));
""", str(JS / "settings-options.js"))
    assert shown == ["svc-block"]


def test_release_day_choices_are_every_day_the_server_accepts():
    from unshacklarr import sync

    days = node(r"""
const ctx = sandbox();
vm.runInContext(grab(read(process.argv[1]), /const RELEASE_DAYS = [^\n]*\n/), ctx);
console.log(JSON.stringify(vm.runInContext("RELEASE_DAYS", ctx)));
""", str(JS / "series.js"))
    assert days == list(range(-sync.EARLY_DAYS_MAX, 2))


def test_episode_subtitle_summary_prioritizes_required_languages_and_discloses_every_track():
    summary = node(r"""
const src = read(process.argv[1]), ctx = sandbox({ el: (tag, props, ...kids) => ({
  tag, ...props, kids, setAttribute(k, v) { this[k] = v; }, append(k) { kids.push(k); },
}), flagged: (text) => text,
  trWith: (key, count, episode) => key === "+{0}: Show subtitles for {1}" ? `+${count} : Sous-titres pour ${episode}` : key,
});
vm.runInContext(grab(src, /function setSubtitleExpanded\b[\s\S]*?function subtitleSummary\b[\s\S]*?\n}\n/), ctx);
const tracks = ["en", "ara", "cat", "cze", "fr", "fre-CA", ...Array(27).fill("es")];
const { cell, detail } = ctx.subtitleSummary(tracks, "fr-CA", "", 5, "E05", false);
const chip = cell.kids[1];
const closed = detail.hidden;
chip.onclick();
const opened = !detail.hidden && chip["aria-expanded"] === "true";
chip.onclick();
console.log(JSON.stringify({
  preview: cell.kids[0], chip: chip.textContent, name: chip.ariaLabel, closed, opened,
  collapsedAgain: detail.hidden && chip["aria-expanded"] === "false",
  detail: detail.textContent, short: ctx.subtitleSummary(["en"], "", "", 1, "E01", false).cell.kids,
}));
""", str(JS / "series.js"))
    assert summary == {
        "preview": "fre-CA, fr",
        "chip": "+31",
        "name": "+31 : Sous-titres pour E05",
        "closed": True,
        "opened": True,
        "collapsedAgain": True,
        "detail": ", ".join(["en", "ara", "cat", "cze", "fr", "fre-CA", *(["es"] * 27)]),
        "short": ["en"],
    }


EPISODE_SANDBOX = r"""
const src = read(process.argv[1]);
const hasClass = (node, name) => typeof node.className === "string" && node.className.split(" ").includes(name);
function* descendants(node) {
  for (const kid of node.kids ?? []) {
    if (typeof kid !== "object") continue;
    yield kid;
    yield* descendants(kid);
  }
}
const document = { querySelectorAll: () => [], querySelector: () => null, activeElement: null };
const list = { style: { setProperty() {} }, classList: { toggle(_, value) { list.compact = value; } },
  querySelectorAll: (sel) => sel === ".ep-subs-detail:not([hidden])"
    ? [...descendants(list)].filter(k => hasClass(k, "ep-subs-detail") && !k.hidden) : [],
  querySelector: (sel) => [...descendants(list)].find(k => k["aria-controls"] && sel === `[aria-controls="${k["aria-controls"]}"]`),
  replaceChildren(...kids) { list.kids = kids; document.activeElement = null; },
};
const ep = { id: 4, seasonNumber: 2, episodeNumber: 5, airDateUtc: "2099-11-21", title: "Future" };
const onDisk = { id: 5, seasonNumber: 2, episodeNumber: 6, title: "On disk",
  hasFile: true, file: { subtitles: ["en", "fr", "es"] } };
const ctx = sandbox({
  $: (sel) => sel === "#ep-list" ? list : sel === "#ep-avail" ? null : any,
  document,
  epSeasons: { 2: [ep] }, epSeason: 2, epBusy: new Map(), epQualities: {}, current: { tvdbId: 1 },
  S: { config: { series: {}, settings: {} } },
  hideOnDisk: false, epAvail: null, tipFor: null, isOutlier: () => false,
  state: (e) => e.file ? "disk" : "soon", stateIcon: () => ({ className: "ep-state" }),
  seasonNorm: () => null, fileTooltip: () => "", picked: new Set(), pad2: (x) => String(x).padStart(2, "0"),
  COLUMNS: [{ id: "subs", file: true, label: "Subtitles" }],
  colsNow: [{ id: "subs", on: true }],
  flagged: (text) => text,
  el: (tag, props, ...kids) => {
    const node = el(tag, props, ...kids);
    return Object.assign(node, {
      querySelector: () => null, append: (kid) => node.kids.push(kid),
      setAttribute: (key, value) => { node[key] = value; },
      getAttribute: (key) => node[key],
      closest: (sel) => sel.split(", ").some(part =>
        part === node.tag || (part.startsWith(".") && hasClass(node, part.slice(1)))) ? node : null,
      focus(options) { document.activeElement = node; node.focusOptions = options; },
      click() {
        if (node.type === "checkbox" && !node.disabled) {
          node.checked = !node.checked;
          node.onchange?.();
        }
      },
      style: { setProperty() {} },
      classList: { add: (name) => { node.className += ` ${name}`; } },
    });
  },
});
vm.runInContext(grab(src, /function setSubtitleExpanded\b[\s\S]*?function subtitleSummary\b[\s\S]*?\n}\n/), ctx);
vm.runInContext(grab(src, /function renderSeason\b[\s\S]*?\n}\n/), ctx);
"""


def test_episodes_without_file_specs_show_status_instead_of_empty_columns():
    rows = node(EPISODE_SANDBOX + r"""
const noFileRow = () => {
  const row = list.kids[1].kids[0].kids;
  return { compact: list.compact, status: row.find(k => hasClass(k, "ep-status"))?.textContent,
    blanks: row.filter(k => hasClass(k, "spec") && hasClass(k, "blank")).length };
};
const subtitles = () => {
  const [row, detail] = list.kids[2].kids;
  const cell = row.kids.find(k => hasClass(k, "subs"));
  const chip = cell?.kids.find(k => hasClass(k, "ep-subs-chip"));
  return { preview: cell?.kids[0], chip: chip?.textContent,
    detail: detail?.textContent, linked: !!detail && chip?.["aria-controls"] === detail.id,
    mobileCell: !!cell && hasClass(cell, "ep-mobile-subs"),
    mobileDetail: !!detail && hasClass(detail, "ep-mobile-subs") };
};
ctx.renderSeason();
const compact = noFileRow();
ctx.epSeasons[2].push(onDisk);
ctx.renderSeason();
const mixed = noFileRow(), column = subtitles();
ctx.colsNow[0].on = false;
ctx.renderSeason();
console.log(JSON.stringify({ compact, mixed, column, mobile: subtitles() }));
""", str(JS / "series.js"))
    assert rows["compact"] == {"compact": True, "status": "Not aired", "blanks": 0}
    assert rows["mixed"] == {"compact": False, "status": "Not aired", "blanks": 0}
    summary = {"preview": "en, fr", "chip": "+1", "detail": "en, fr, es", "linked": True}
    assert rows["column"] == {**summary, "mobileCell": False, "mobileDetail": False}
    assert rows["mobile"] == {**summary, "mobileCell": True, "mobileDetail": True}


def test_redrawing_the_season_keeps_subtitles_open_and_focus_on_the_new_chip():
    redraw = node(EPISODE_SANDBOX + r"""
const chip = () => [...descendants(list)].find(k => hasClass(k, "ep-subs-chip"));
ctx.epSeasons[2] = [onDisk];
ctx.renderSeason();
const original = chip();
original.onclick();
original.focus();
ctx.renderSeason();
const rebuilt = chip();
const detail = [...descendants(list)].find(k => k.id === rebuilt.getAttribute("aria-controls"));
console.log(JSON.stringify({ hidden: detail.hidden, expanded: rebuilt.getAttribute("aria-expanded"),
  focusRestored: rebuilt !== original && document.activeElement === rebuilt, focusOptions: rebuilt.focusOptions }));
""", str(JS / "series.js"))
    assert redraw == {
        "hidden": False, "expanded": "true", "focusRestored": True, "focusOptions": {"preventScroll": True},
    }


def test_clicking_an_episode_row_selects_it_without_the_subtitle_chip_changing_selection():
    clicks = node(EPISODE_SANDBOX + r"""
ctx.epSeasons[2] = [onDisk];
ctx.renderSeason();
const row = [...descendants(list)].find(k => hasClass(k, "ep"));
const chip = [...descendants(row)].find(k => hasClass(k, "ep-subs-chip"));
const box = [...descendants(row)].find(k => k.type === "checkbox");
const picks = () => ({ checked: box.checked, picked: ctx.picked.has(onDisk.id) });
const before = picks();
row.onclick({ target: row });
const afterRow = picks();
chip.onclick();
row.onclick({ target: chip });
const afterChip = { ...picks(), expanded: chip.getAttribute("aria-expanded") };
row.onclick({ target: row });
console.log(JSON.stringify({ before, afterRow, afterChip, afterSecondRow: picks() }));
""", str(JS / "series.js"))
    assert clicks == {
        "before": {"checked": False, "picked": False},
        "afterRow": {"checked": True, "picked": True},
        "afterChip": {"checked": True, "picked": True, "expanded": "true"},
        "afterSecondRow": {"checked": False, "picked": False},
    }


# Safari before 17.4 has no Object.groupBy
NO_GROUP_BY = "const NoGroupBy = Object.fromEntries(Object.getOwnPropertyNames(Object).filter((k) => k !== 'groupBy').map((k) => [k, Object[k]]));"


def test_catch_up_box_draws_on_a_browser_without_object_groupby():
    shown = node(NO_GROUP_BY + r"""
const box = { hidden: true, classList: { toggle() {} }, replaceChildren(...kids) { this.kids = kids; } };
const ctx = sandbox({ Object: NoGroupBy, pad2: (n) => String(n).padStart(2, "0"), $: () => box, current: { tvdbId: 1 }, S: { config: { series: { 1: { service: "BINGE" } } } },
  epSeasons: { 7: [{ id: 2, seasonNumber: 7, hasFile: false, sonarrAir: "2999-01-01T00:00:00Z" }] }, epAvail: { 2: { service: "S07E02" } },
  epBusy: new Map(), epPages: {}, epElsewhere: { 7: { service: "NINE", count: 5, url: "https://9now/show" } }, state: () => "miss", belowAsked: () => false, seriesSvcs: () => "BINGE", seasonSvc: () => "BINGE",
  COUNT: { episode: String, upgrade: String, missingEpisode: String } });
vm.runInContext(grab(read(process.argv[1]), /function renderCatchUp\b[\s\S]*?\n}\n/), ctx);
ctx.renderCatchUp();
console.log(JSON.stringify(JSON.stringify(box.kids)));
""", str(JS / "series.js"))
    assert "S07 (1)" in shown


def test_live_track_list_draws_parts_on_a_browser_without_object_groupby():
    classes = node(NO_GROUP_BY + r"""
const tracks = [{ label: "Part 1 · video 1080p", progress: 100 }, { label: "Part 2 · video 1080p", progress: 40 }];
const ctx = sandbox({ Object: NoGroupBy, isLive: () => false, stepStates: () => [], STEPS: [], STEPS_SHORT: [], tracksOpen: new Set() });
vm.runInContext(grab(read(process.argv[1]), /function runBody\b[\s\S]*?\n}\n/), ctx);
const names = [];
(function walk(n) { if (!n || typeof n !== "object") return; if (typeof n.className === "string") names.push(n.className); (n.kids || []).forEach(walk); })({ kids: ctx.runBody({ id: "r1", outcome: "failed", started: "2026-01-01T00:00:00Z", tracks }) });
console.log(JSON.stringify(names));
""", str(JS / "activity.js"))
    assert [c for c in classes if c in ("tpart", "tpart done")] == ["tpart done", "tpart"]


@pytest.mark.parametrize("viewing,asked", [("sonarr-4k", ("sonarr-4k", 40)), ("", ("sonarr-2", 20)), ("gone", ("sonarr-2", 20))])
def test_whats_on_asks_the_sonarr_being_viewed_for_a_series_in_no_main_sonarr(viewing, asked):
    body = node(r"""
const [file, viewing] = process.argv.slice(1);
let sent = null;
const s = { tvdbId: 1, title: "Show" };  // no id: in no main Sonarr
const ctx = sandbox({ savedSonarr: (name) => name, epSonarr: viewing, current: null, S: { services: ["IV"], config: { series: { 1: {} } }, sonarrsOf: { 1: [{ name: "sonarr-2", id: 20 }, { name: "sonarr-4k", id: 40 }] } },
  api: async (path, opts) => { sent = JSON.parse(opts.body); return { elsewhere: {}, available: {} }; } });
vm.runInContext(grab(read(file), /async function askService\b[\s\S]*?\n}\n/), ctx);
ctx.askService(s).then(() => console.log(JSON.stringify(sent)));
""", str(JS / "series.js"), viewing)
    assert (body["sonarr"], body["seriesId"]) == asked


@pytest.mark.parametrize("file,name", [("settings-options.js", "renderInterface"), ("quality.js", "renderLearnWindow")])
def test_settings_screens_wait_for_the_config_instead_of_throwing(file, name):
    threw = node(r"""
const [file, name] = process.argv.slice(1);
const ctx = sandbox({ S: {} });  // reloaded on #/settings/...: drawn before the config arrives
vm.runInContext(grab(read(file), new RegExp(`function ${name}\\b[\\s\\S]*?\\n}\\n`)), ctx);
try { ctx[name](); console.log("false"); } catch (e) { console.log("true"); }
""", str(JS / file), name)
    assert threw is False


# The save bar stays up for the "Saved" tick (1.6 s) after a save: only unsaved changes make Download and Sync wait
@pytest.mark.parametrize("unsaved,goes", [(False, True), (True, False)])
def test_download_goes_while_the_save_bar_shows_saved(unsaved, goes):
    calls = node(r"""
const calls = [];
const ctx = sandbox({ unsaved: process.argv[2] === "true", current: { tvdbId: 1 }, S: { config: { series: { 1: { service: "BINGE", title: "Show" } } } },
  epSeasons: {}, picked: new Set([1]), epSonarr: "", $: (sel) => (sel === "#savebar" ? { hidden: false } : any),
  api: async (path) => { calls.push(path); return {}; }, toast() {} });
vm.runInContext(grab(read(process.argv[1]), /async function startDownload\b[\s\S]*?\n}\n/), ctx);
ctx.startDownload().then(() => console.log(JSON.stringify(calls)));
""", str(JS / "series.js"), str(unsaved).lower())
    assert calls == (["/api/download"] if goes else [])


@pytest.mark.parametrize("unsaved,goes", [(False, True), (True, False)])
def test_sync_goes_while_the_save_bar_shows_saved(unsaved, goes):
    calls = node(r"""
const calls = [], sync = {};
const ctx = sandbox({ unsaved: process.argv[2] === "true", $: (sel) => (sel === "#savebar" ? { hidden: false } : sel === "#sync" ? sync : any),
  api: async (path) => { calls.push(path); return {}; }, toast() {}, showTab() {} });
vm.runInContext(grab(read(process.argv[1]), /\$\("#sync"\)\.onclick = async [\s\S]*?\n};\n/), ctx);
sync.onclick().then(() => console.log(JSON.stringify(calls)));
""", str(JS / "attempts.js"), str(unsaved).lower())
    assert calls == (["/api/sync"] if goes else [])


BACKUP_ENTRY = {
    "download": ("async function backupFile\\b[\\s\\S]*?\\n}\\n", 'ctx.backupFile("b.yaml")'),
    "save": ('\\$\\("#bk-save"\\)\\.onclick = async [\\s\\S]*?\\n};\\n', 'nodes["#bk-save"].onclick()'),
    "restore": ('\\$\\("#bk-file"\\)\\.onchange = async [\\s\\S]*?\\n};\\n', 'nodes["#bk-file"].onchange({ target: { files: [{ text: async () => "yaml" }], value: "" } })'),
}


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("entry", BACKUP_ENTRY)
def test_backup_password_is_cleared_once_the_backup_is_done_with_it(entry, fails):
    pattern, call = BACKUP_ENTRY[entry]
    left = node(r"""
const [file, pattern, call, fails] = process.argv.slice(1);
const nodes = {};
const $ = (sel) => (nodes[sel] ??= { value: "", hidden: false, focus() {}, select() {}, replaceChildren() {}, click() {} });
$("#bk-pass").value = "secret";
const ctx = sandbox({ $, el: (tag, props) => ({ ...props, click() {} }), bkPassword: () => true, bkSay() {}, toast() {}, errorDetail: (e) => e.message, setTimeout() {}, location: { reload() {} },
  api: async () => { if (fails === "true") throw Error("Server said no"); return { text: "yaml", name: "b.yaml", series: 3 }; } });
vm.runInContext(grab(read(file), new RegExp(pattern)), ctx);
Promise.resolve(eval(call)).then(() => console.log(JSON.stringify($("#bk-pass").value)));
""", str(JS / "settings-options.js"), pattern, call, str(fails).lower())
    assert left == ("secret" if fails else "")


DOWNLOAD_ENTRY = {
    "backup file": ("settings-options.js", BACKUP_ENTRY["download"]),
    "backup": ("settings-options.js", BACKUP_ENTRY["save"]),
    "diagnostic": ("activity.js", ("async function downloadDiagnostic\\b[\\s\\S]*?\\n}\\n", 'ctx.downloadDiagnostic({ id: "r1" })')),
}


@pytest.mark.parametrize("entry", DOWNLOAD_ENTRY)
def test_a_download_keeps_its_file_for_30_seconds_for_safari(entry):
    file, (pattern, call) = DOWNLOAD_ENTRY[entry]
    seen = node(r"""
const [file, pattern, call] = process.argv.slice(1);
const nodes = {}, revoked = [], timers = [];
const $ = (sel) => (nodes[sel] ??= { value: "pw", hidden: false, focus() {}, select() {}, replaceChildren() {}, click() {} });
const ctx = sandbox({ $, el: (tag, props) => ({ ...props, click() {} }), bkPassword: () => true, bkSay() {}, toast() {}, errorDetail: (e) => e.message,
  URL: { createObjectURL: () => "blob:file", revokeObjectURL: (u) => revoked.push(u) }, setTimeout: (fn, ms) => timers.push([fn, ms]),
  fetch: async () => ({ ok: true, blob: async () => ({}) }), api: async () => ({ text: "yaml", name: "b.yaml" }) });
vm.runInContext(grab(read(file), new RegExp(pattern)), ctx);
Promise.resolve(eval(call)).then(() => {
  const before = [...revoked];
  timers.forEach(([fn]) => fn());
  console.log(JSON.stringify({ before, delays: timers.map(([, ms]) => ms), after: revoked }));
});
""", str(JS / file), pattern, call)
    assert seen == {"before": [], "delays": [30000], "after": ["blob:file"]}


@pytest.mark.parametrize("navigates,opened", [(True, []), (False, ["/#/inbox"])])
def test_tapping_a_notification_opens_the_bell_even_for_a_window_the_worker_cannot_navigate(navigates, opened):
    seen = node(r"""
const handlers = {}, opened = [];
const win = { url: "https://app.example/", focus() { return Promise.resolve(this); }, navigate: async () => { if (process.argv[2] !== "true") throw new TypeError("not controlled"); } };
const self = { location: { origin: "https://app.example" }, addEventListener: (type, fn) => (handlers[type] = fn),
  clients: { matchAll: async () => [win], openWindow: async (url) => { opened.push(url); }, claim() {} }, registration: {}, skipWaiting() {} };
vm.runInNewContext(read(process.argv[1]), { self, URL, Promise });
let waiting;
handlers.notificationclick({ notification: { close() {}, data: { url: "/#/inbox" } }, waitUntil: (p) => (waiting = p) });
waiting.then(() => console.log(JSON.stringify(opened)), (e) => console.log(JSON.stringify("rejected: " + e.message)));
""", str(STATIC / "sw.js"), str(navigates).lower())
    assert seen == opened


def test_activity_forgets_a_run_once_the_list_no_longer_has_it():
    kept = node(r"""
const src = read(process.argv[1]);
const ctx = sandbox({ api: async () => [{ id: "a", batch: "J1" }] });
vm.runInContext("let runCards = [], runsSeq = 0;", ctx);
for (const re of [/const speedLog = \{\};/, /const barWidths = new Map\(\);/, /const thumbs = new Map\(\);/, /const muxLog = \{\};/, /const tracksOpen = new Set\(\);/, /function forgetGoneRuns\b[\s\S]*?\n}\n/, /async function openActivity\b[\s\S]*?\n}\n/])
  vm.runInContext(grab(src, re), ctx);
vm.runInContext(`
  for (const id of ["a", "b"]) { speedLog[id] = [[1, 2]]; muxLog[id] = [[1, 2]]; tracksOpen.add(id); }
  const keys = ["detail", "up:9", "lang:5", "row:a", "row:b", "row:job:J1", "row:job:J2", "job:J1", "job:J2", "mux:a", "mux:b", "t:a:Part 1 \\u00b7 video", "t:b:video"];
  for (const k of keys) { barWidths.set(k, "10%"); thumbs.set(k, {}); }`, ctx);
ctx.openActivity().then(() => console.log(vm.runInContext(`JSON.stringify({ speedLog: Object.keys(speedLog), muxLog: Object.keys(muxLog), tracksOpen: [...tracksOpen],
  barWidths: [...barWidths.keys()].sort(), thumbs: [...thumbs.keys()].sort() })`, ctx)));
""", str(JS / "activity.js"))
    # "detail", "up:" and "lang:" are not a run's: kept
    still = ["detail", "job:J1", "lang:5", "mux:a", "row:a", "row:job:J1", "t:a:Part 1 \u00b7 video", "up:9"]
    assert kept == {"speedLog": ["a"], "muxLog": ["a"], "tracksOpen": ["a"], "barWidths": still, "thumbs": still}


def test_series_search_redraws_the_wall_once_the_typing_pauses():
    seen = node(r"""
let draws = 0, next = 1;
const pending = new Map(), search = {};
const ctx = sandbox({ $: (sel) => (sel === "#search" ? search : any), renderWall: () => { draws++; },
  setTimeout: (fn, ms) => { pending.set(next, [fn, ms]); return next++; }, clearTimeout: (id) => pending.delete(id) });
vm.runInContext(grab(read(process.argv[1]), /(?:let wallTimer[^\n]*\n)?\$\("#search"\)\.oninput = [^\n]*\n/), ctx);
for (let i = 0; i < 3; i++) search.oninput();  // three keys
const waiting = [...pending.values()], drawnWhileTyping = draws;
waiting.forEach(([fn]) => fn());
console.log(JSON.stringify({ drawnWhileTyping, waiting: waiting.map(([, ms]) => ms), draws }));
""", str(JS / "navigation.js"))
    assert seen == {"drawnWhileTyping": 0, "waiting": [150], "draws": 1}


def test_series_filter_disclosure_keeps_filters_open_but_returns_focus_for_actions():
    seen = node(r"""
const events = [], listeners = {};
const toggle = {
  attributes: { "aria-expanded": "false" },
  getAttribute(name) { return this.attributes[name]; },
  setAttribute(name, value) { this.attributes[name] = String(value); },
  focus: () => events.push("focus: filters"),
};
const search = {}, sort = {}, library = {};
const controls = {
  contains: (target) => target === sort || target === library,
  addEventListener: (name, fn, capture) => { listeners[name] = { fn, capture }; },
};
const narrow = { matches: false, addEventListener: (name, fn) => { listeners[name] = { fn }; } };
const ctx = sandbox({ $: (sel) => sel === "#series-options-toggle" ? toggle : controls, matchMedia: () => narrow });
const nav = read(process.argv[1]);
vm.runInContext(nav.slice(nav.indexOf("function bindSeriesOptions("), nav.indexOf("function renderServiceFilter(")), ctx);
const controlled = [toggle.getAttribute("aria-controls")];
for (const matches of [true, false]) {
  narrow.matches = matches;
  listeners.change?.fn();
  controlled.push(toggle.getAttribute("aria-controls"));
}
const expanded = () => toggle.getAttribute("aria-expanded") === "true";
const click = (id) => listeners.click.fn({ target: { closest: (selector) => selector.split(", ").includes(id) } });
const press = () => toggle.onclick();
press();
events.push(expanded());
press();
events.push(expanded());
press();
click("#f-sort");
events.push(expanded());
listeners.keydown.fn({ key: "Escape", target: sort, preventDefault() {} });
events.push(expanded());
press();
listeners.focusout.fn({ target: toggle, relatedTarget: sort });
listeners.focusout.fn({ target: sort, relatedTarget: library });
events.push(`inside: ${expanded() ? "open" : "closed"}`);
listeners.focusout.fn({ target: library, relatedTarget: search });
events.push(`outside: ${expanded() ? "open" : "closed"}`);
for (const action of ["#bulk-open", "#sel-toggle"]) {
  press();
  click(action);
  events.push(`${action}: ${expanded() ? "open" : "closed"}`);
}
console.log(JSON.stringify([controlled, listeners.click.capture, ...events]));
""", str(JS / "navigation.js"))
    assert seen == [
        ["series-actions", "series-options", "series-actions"],
        True, True, False, True, "focus: filters", False,
        "inside: open", "outside: closed",
        "focus: filters", "#bulk-open: closed", "focus: filters", "#sel-toggle: closed",
    ]


@pytest.mark.parametrize("title,asks", [("Show", 1), (None, 0)])
def test_change_and_download_only_asks_the_service_for_a_series_with_a_main_page(title, asks):
    asked = node(r"""
const [title] = process.argv.slice(2);
let asked = 0;
const node_ = { before() {}, append() {}, replaceChildren() {}, showModal() {} };
const conf = { service: "BINGE", season_pages: { 1: { url: "https://x/1" } }, ...(title ? { title } : {}) };
const ctx = sandbox({ $: () => node_, current: { tvdbId: 1, title: "Show" }, S: { config: { series: { 1: conf } } }, NUMBERING: [], epSeasons: {}, picked: new Set(), epTitles: null, epPagesListed: {},
  elsewhere: () => false, askService: () => { asked++; } });
vm.runInContext(grab(read(process.argv[1]), /\$\("#ep-go-edit"\)\.onclick = \(\) => \{[\s\S]*?\n\};\n/), ctx);
node_.onclick();
console.log(JSON.stringify(asked));
""", str(JS / "series.js"), title or "")
    assert asked == asks


def test_typing_in_the_device_search_keeps_the_search_box_and_redraws_only_the_list():
    seen = node(r"""
const src = read(process.argv[1]);
const nodes = {}, replaced = [];
const $ = (sel) => (nodes[sel] ??= { value: "", hidden: false, textContent: "", focus() {}, select() {}, classList: { toggle() {} },
  querySelector: () => ({ textContent: "" }), replaceChildren: (...kids) => replaced.push([sel, JSON.stringify(kids)]), replaceWith: (n) => replaced.push([sel, JSON.stringify(n)]) });
const device = (name, kind) => ({ name, kind, used_by: [], info: {} });
const ctx = sandbox({ $, cdmData: { folder: "/cdm", devices: [device("alpha", "Widevine"), device("beta", "PlayReady")], remote: [], services: [], map: {} },
  cdmFilter: "all", cdmQuery: "", cdmTesting: false, cdmShowUnused: true, cdmRunning: new Set(), cdmOpen: new Set(), S: { config: { series: {}, settings: {} } },
  COUNT: { device: String, problem: String, moreDevice: String }, svcName: String, cdmShort: (d) => d.name });
for (const name of ["cdmTitle", "cdmStatus"]) vm.runInContext(grab(src, new RegExp(`function ${name}\\b[\\s\\S]*?\\n}\\n`)), ctx);
vm.runInContext(grab(src, /const cdmCard = [\s\S]*?\.\.\.body\);\n/), ctx);
vm.runInContext(grab(src, /function renderCdm\b[\s\S]*?\n}\n/), ctx);
let box = null;  // the search input, caught as it is made
const made = ctx.el;
ctx.el = (tag, props, ...kids) => { const n = made(tag, props, ...kids); if (props?.className === "con-search") box = n; return n; };
ctx.renderCdm();
replaced.length = 0;
ctx.cdmQuery = "alpha"; box.value = "alpha";
box.oninput();
const after = replaced.map(([sel, json]) => [sel, /alpha\.wvd/.test(json), /beta\.prd/.test(json)]);
console.log(JSON.stringify({ listRedrawn: after.some(([sel]) => sel === "#cdm-list"), shown: after.filter(([, a]) => a).length > 0, hidden: after.every(([, , b]) => !b) }));
""", str(JS / "cookies-cdm.js"))
    assert seen == {"listRedrawn": False, "shown": True, "hidden": True}


def test_discard_puts_the_settings_back_as_saved_and_draws_them_again():
    shown = node(r"""
const saved = { settings: { timezone: "Europe/Paris" }, notifications: { targets: [{ url: "ntfy://a" }, { url: "ntfy://b" }] }, defaults: { quality: "1080" },
  series: { 1: { service: "BINGE", title: "Kept" } } };
const config = JSON.parse(JSON.stringify(saved));
Object.assign(config, { versions: { settings: "7" }, hidden_series: [9] });
config.settings.timezone = "UTC";                                   // an edited field
config.settings.sonarr_api_key = "typed";                           // a key typed, never saved
config.notifications.targets.splice(0, 1);                          // an address staged for removal
config.series[1].title = "Edited"; config.series[2] = { service: "STAN", title: "Added" };
config.series[3] = { title: "No service: not part of a save" };
config.extra = true;
const calls = [];
const ctx = sandbox({ S: { config, dlOptions: [] }, savedConfig: JSON.stringify(saved), savedSonarrsOf: "{}", $: (sel) => sel,
  optionsEditor: (...a) => calls.push("options"), renderSettings: () => calls.push("settings"), renderServiceFilter: () => calls.push("filter"),
  renderWall: () => calls.push("wall"), dirty: () => calls.push("dirty"), toast: (t) => calls.push(t) });
vm.runInContext(grab(read(process.argv[1]), /function discardChanges\b[\s\S]*?\n}\n/), ctx);
ctx.discardChanges();
console.log(JSON.stringify({ config, calls }));
""", str(JS / "settings-options.js"))
    config = shown["config"]
    assert config["settings"] == {"timezone": "Europe/Paris"}
    assert [t["url"] for t in config["notifications"]["targets"]] == ["ntfy://a", "ntfy://b"]
    assert "extra" not in config
    assert config["series"] == {"1": {"service": "BINGE", "title": "Kept"}, "3": {"title": "No service: not part of a save"}}
    assert config["versions"] == {"settings": "7"} and config["hidden_series"] == [9]  # not changes of a save: left as they are
    assert shown["calls"] == ["options", "settings", "filter", "wall", "dirty", "Changes discarded"]


def test_discard_draws_the_controls_settings_does_not_so_a_later_toggle_still_counts():
    shown = node(r"""
const saved = { settings: { upgrade_other_groups: false, upgrade_check_new: false, spoiler_free: false }, series: { 1: { service: "BINGE", title: "A" } } };
const config = JSON.parse(JSON.stringify(saved));
config.series[1].skip_upgrades = true;
Object.assign(config.settings, { upgrade_other_groups: true, upgrade_check_new: true, spoiler_free: true });
const nodes = {};
const $ = (sel) => (nodes[sel] ??= { value: "", checked: false, hidden: false, disabled: false, className: "", textContent: "", replaceChildren(...k) { this.kids = k; },
  querySelector: () => ({ textContent: "" }), querySelectorAll: () => [], setAttribute() {} });
const ctx = sandbox({ S: { config, dlOptions: [], series: [] }, savedConfig: JSON.stringify(saved), savedSonarrsOf: "{}", $, dirty() {}, toast() {},
  optionsEditor() {}, renderSettings() {}, renderServiceFilter() {}, renderWall() {}, LANGS: {}, LANG: "en" });
const quality = read(process.argv[2]), options = read(process.argv[1]);
vm.runInContext("let ugGroups = { groups: [], none: [] };", ctx);
for (const re of [/function upgradeSeries\b[\s\S]*?\n}\n/, /function renderUpgradeSeries\b[\s\S]*?\n}\n/, /function upgradeSay\b[\s\S]*?\n}\n/, /async function renderUpgradeGroups\b[\s\S]*?\n}\n/])
  vm.runInContext(grab(quality, re), ctx);
for (const re of [/function renderInterface\b[\s\S]*?\n}\n/, /function discardChanges\b[\s\S]*?\n}\n/]) vm.runInContext(grab(options, re), ctx);
const box = () => nodes["#ug-series"].kids[0].kids[0];  // the one series' checkbox, as drawn now
ctx.renderUpgradeSeries();
const before = box().checked;
ctx.discardChanges();
const after = box();
after.onchange({ target: { checked: false } });  // ticked off again after the discard
console.log(JSON.stringify({ before, after: after.checked, skip: ctx.S.config.series[1].skip_upgrades, other: nodes["#ug-other"].checked,
  fresh: nodes["#ug-new"].checked, spoiler: nodes["#rg-spoiler"].checked }));
""", str(JS / "settings-options.js"), str(JS / "quality.js"))
    # the box shows the series ticked again, and the next toggle reaches the live config, not an object the discard replaced
    assert shown == {"before": False, "after": True, "skip": True, "other": False, "fresh": False, "spoiler": False}


def test_discard_puts_the_libraries_a_renamed_sonarr_moved_back_under_its_saved_name():
    shown = node(r"""
const saved = { settings: { sonarrs: [{ name: "Anime", url: "http://a" }] }, series: {} };
const config = JSON.parse(JSON.stringify(saved));
const ctx = sandbox({ S: { config, dlOptions: [], sonarrsOf: { 7: [{ name: "Anime", id: 1 }] } }, savedConfig: JSON.stringify(saved), savedSonarrsOf: "", $: (sel) => sel,
  optionsEditor() {}, renderSettings() {}, renderServiceFilter() {}, renderWall() {}, dirty() {}, toast() {}, renderUpgradeSeries() {}, renderUpgradeGroups() {}, renderInterface() {} });
vm.runInContext(grab(read(process.argv[2]), /const sonarrSavedName = new WeakMap\(\);[\s\S]*?const savedSonarr = .*\n/), ctx);
vm.runInContext(grab(read(process.argv[3]), /function moveSonarrRefs\b[\s\S]*?\n}\n/), ctx);
vm.runInContext(grab(read(process.argv[1]), /function discardChanges\b[\s\S]*?\n}\n/), ctx);
ctx.savedSonarrsOf = JSON.stringify(ctx.S.sonarrsOf);
vm.runInContext("keepSonarrNames(sonarrNames())", ctx);
ctx.S.config.settings.sonarrs[0].name = "Anime 2";  // an unsaved rename, as the Sonarr editor does it
ctx.moveSonarrRefs("Anime", "Anime 2");
const renamed = ctx.S.sonarrsOf[7][0].name, requestWhileRenamed = vm.runInContext('savedSonarr("Anime 2")', ctx);
ctx.discardChanges();
const request = vm.runInContext('savedSonarr("Anime")', ctx);
ctx.S.config.settings.sonarrs[0].name = "Anime 3";  // renamed again after the discard, still unsaved
console.log(JSON.stringify({ renamed, requestWhileRenamed, libraries: ctx.S.sonarrsOf[7].map((o) => o.name), request,
  requestAfter: vm.runInContext('savedSonarr("Anime 3")', ctx) }));
""", str(JS / "settings-options.js"), str(JS / "core.js"), str(JS / "quality.js"))
    # the restored entry is a new object: requests still name the Sonarr as the server knows it
    assert shown == {"renamed": "Anime 2", "requestWhileRenamed": "Anime", "libraries": ["Anime"], "request": "Anime", "requestAfter": "Anime"}


def test_discard_before_the_release_groups_are_looked_up_asks_nothing_and_still_resets_the_switch():
    shown = node(r"""
const saved = { settings: { upgrade_other_groups: false }, series: {} };
const config = JSON.parse(JSON.stringify(saved));
config.settings.upgrade_other_groups = true;  // switched on, not saved; the lookup not done (or failed)
const nodes = {}, $ = (sel) => (nodes[sel] ??= { checked: false, disabled: false, replaceChildren() {} });
$("#ug-other").checked = true;
let asked = 0;
const ctx = sandbox({ S: { config, dlOptions: [], series: [] }, savedConfig: JSON.stringify(saved), savedSonarrsOf: "{}", $,
  api: async () => { asked++; return { groups: [], none: [] }; }, optionsEditor() {}, renderSettings() {}, renderServiceFilter() {}, renderWall() {}, dirty() {}, toast() {},
  renderUpgradeSeries() {}, renderInterface() {}, keepSonarrNames() {}, sonarrNames: () => [], configUnits: () => ({}) });
vm.runInContext("let ugGroups = null;", ctx);
vm.runInContext(grab(read(process.argv[2]), /async function renderUpgradeGroups\b[\s\S]*?\n}\n/), ctx);
vm.runInContext(grab(read(process.argv[1]), /function discardChanges\b[\s\S]*?\n}\n/), ctx);
ctx.discardChanges();
setTimeout(() => console.log(JSON.stringify({ asked, switchOn: nodes["#ug-other"].checked })));
""", str(JS / "settings-options.js"), str(JS / "quality.js"))
    # the groups are looked up when Upgrades opens, not on every Discard; the switch shows the saved value either way
    assert shown == {"asked": 0, "switchOn": False}


def test_discard_leaves_the_next_save_sending_no_series_it_restored():
    shown = node(r"""
const core = read(process.argv[2]);
const loaded = { settings: {}, series: { 1: { title: "A", service: "BINGE" } } };  // as the server sends it: not in key order
const ctx = sandbox({ S: { config: JSON.parse(JSON.stringify(loaded)), dlOptions: [] }, savedSonarrsOf: "{}", $: (sel) => sel,
  optionsEditor() {}, renderSettings() {}, renderServiceFilter() {}, renderWall() {}, dirty() {}, toast() {}, renderUpgradeSeries() {}, renderInterface() {} });
for (const re of [/const stableJSON = .*\n/, /const NUMBERED = .*\n/, /function cleanSeries\([\s\S]*?\n\}\n/, /const configKey = .*\n/, /let savedUnits = \{\};\nconst configUnits = [\s\S]*?\]\)\]\);\n/, /const sonarrSavedName = new WeakMap\(\);[\s\S]*?const savedSonarr = .*\n/])
  vm.runInContext(grab(core, re), ctx);
vm.runInContext("var savedConfig = configKey(S.config); savedUnits = configUnits(S.config);", ctx);  // as the page loads it
vm.runInContext(grab(read(process.argv[1]), /function discardChanges\b[\s\S]*?\n}\n/), ctx);
ctx.S.config.series[1].title = "B";
ctx.discardChanges();
const now = vm.runInContext("configUnits(S.config)", ctx), before = vm.runInContext("savedUnits", ctx);
console.log(JSON.stringify(Object.keys(now).filter((u) => now[u] !== before[u])));
""", str(JS / "settings-options.js"), str(JS / "core.js"))
    assert shown == []  # what a Save would send as changed: nothing


def test_discard_waits_for_a_save_in_flight():
    shown = node(r"""
const nodes = {}, $ = (sel) => (nodes[sel] ??= { disabled: false, hidden: false, classList: { add() {}, remove() {} }, replaceChildren() {} });
let release, during;
const ctx = sandbox({ $, save: () => new Promise((resolve) => { release = resolve; }), toast() {}, icon: () => "", unsaved: false, setTimeout() {} });
vm.runInContext(grab(read(process.argv[1]), /async function saveHere\b[\s\S]*?\n}\n/), ctx);
const done = ctx.saveHere($("#save"), $("#savebar"));
during = nodes["#discard"].disabled;
release();
done.then(() => console.log(JSON.stringify({ during, after: nodes["#discard"].disabled })));
""", str(JS / "settings-options.js"))
    assert shown == {"during": True, "after": False}


def test_the_save_bar_offers_discard_and_announces_itself():
    page = (STATIC / "index.html").read_text()
    bar = page[page.index('<div class="savebar"'):].split("</div>", 1)[0]
    assert 'role="status"' in bar.split(">", 1)[0]
    assert bar.index('id="discard"') < bar.index('id="save"')

@pytest.mark.parametrize("poster", ["", "https://img.example/p.jpg"])
def test_a_series_wall_card_draws_initials_for_a_missing_or_failed_poster(poster):
    seen = node(r"""
const [poster] = process.argv.slice(2);
const src = read(process.argv[1]);
let drawn = [];
const stub = (value = "") => ({ value, checked: false, textContent: "", removeAttribute() {}, replaceChildren: (...kids) => { drawn = kids; } });
const fields = { "#f-sort": stub("title") };
const withAppend = (tag, props = {}, ...kids) => ({ tag, dataset: {}, ...props, kids, append(...more) { this.kids.push(...more); } });
const ctx = sandbox({ el: withAppend, $: (sel) => fields[sel] ?? stub(), S: { series: [{ tvdbId: 1, title: "Dark Matter", poster }], config: { series: {}, hidden_series: [] }, health: {} }, SEL: { on: false, ids: new Set() },
  keepFocus: (box, draw) => draw() });
vm.runInContext(grab(src, /function initialsOf[\s\S]*?\nconst posterFail[^\n]*\n/), ctx);
vm.runInContext(grab(src, /function renderWall\(\) \{[\s\S]*?\n\}\n/), ctx);
ctx.renderWall();
const img = drawn[0].kids.find((k) => k.className === "art").kids.find((k) => k.tag === "img");
const initials = ctx.posterSrc("", "Dark Matter");
const failing = { target: { src: img.src, getAttribute() { return this.src; } } };
img.onerror(failing);
console.log(JSON.stringify({ src: img.src === (poster || initials), initials: initials.includes("DM"), afterFail: failing.target.src === initials }));
""", str(JS / "core.js"), poster)
    assert seen == {"src": True, "initials": True, "afterFail": True}


def test_a_duration_names_the_unit_of_each_part():
    shown = node(r"""
const src = read(process.argv[1]);
const ctx = sandbox();
vm.runInContext(grab(src, /^function duration\(.*?^\}/ms) + "\nthis.duration = duration;", ctx);
console.log(JSON.stringify([25000, 144000, 3900000].map((ms) => ctx.duration(ms))));
""", str(JS / "activity.js"))
    assert shown == ["25 s", "2 min 24 s", "1 h 05 min"]


def test_the_server_names_the_unit_of_each_part_of_a_duration_too():
    from unshacklarr import sync
    assert [sync.human_time(s) for s in (25, 144, 3900)] == ["25 s", "2 min 24 s", "1 h 05 min"]


def test_the_logo_goes_to_the_schedule_and_is_named_from_its_text():
    import re
    page = (STATIC / "index.html").read_text()
    link = re.search(r'<a href="([^"]+)" id="home" aria-label="([^"]+)"', page)
    assert link and link.group(1) == "#/schedule"  # the app opens on the schedule
    assert link.group(2).startswith("Unshacklarr")  # the visible name starts the accessible one (and the narrowest phones hide the text)


def test_a_failing_series_says_so_once_with_its_fix():
    page = (STATIC / "index.html").read_text()
    assert 'id="d-sick"' not in page and "#d-sick" not in (JS / "core.js").read_text()
    shown = node(r"""
const src = read(process.argv[1]);
const box = { classList: { remove() {}, add() {} } }, fix = { hidden: true, kids: [] }, text = { textContent: "" };
const sels = { "#ds-state": box, "#ds-state-text": text, "#ds-fix": { ...fix, set hidden(v) { fix.hidden = v; }, replaceChildren: (...k) => { fix.kids = k; } } };
const ctx = sandbox({ $: (sel) => sels[sel] || any, current: { tvdbId: 7 }, svcName: (s) => s, renderSeriesLanguage() {}, openServiceRow() {},
  S: { config: { series: { 7: { service: "HULU", title: "x" } } }, health: { 7: { failing: 3, cause: "Session expired" } } } });
vm.runInContext(grab(src, /function renderSeriesState\b[\s\S]*?\n}\n/) + "\nthis.renderSeriesState = renderSeriesState;", ctx);
ctx.renderSeriesState();
console.log(JSON.stringify({ state: text.textContent, fix: fix.kids.map((k) => k.textContent) }));
""", str(JS / "core.js"))
    assert shown == {"state": "Its last 3 downloads from HULU failed", "fix": [
        "Session expired", "Test this series below: a URL the service no longer knows, or a sign-in to renew in Settings › Services & Devices › Services.",
        "Check HULU in Settings › Services & Devices › Services"]}


def test_an_empty_choice_of_episodes_is_hidden_not_greyed():
    shown = node(r"""
const src = read(process.argv[1]);
const out = {};
for (const onService of [0, 2]) {
  const pick = { hidden: false, disabled: false, textContent: "" };
  const list = [{ id: 1 }, { id: 2 }];
  const ctx = sandbox({ $: (sel) => (sel === "#ep-avail" ? pick : any), list, state: () => (onService ? "miss" : "disk"), epAvail: { 1: 1, 2: 1 }, seasonSvc: () => "HULU", epSeason: 1 });
  vm.runInContext(grab(src, /if \(\$\("#ep-avail"\)\) \{[\s\S]*?\n  \}\n/), ctx);
  out[onService] = pick.hidden;
}
console.log(JSON.stringify(out));
""", str(JS / "series.js"))
    assert shown == {"0": True, "2": False}


def test_a_phones_back_button_is_named_for_the_page_it_returns_to():
    shown = node(r"""
const src = read(process.argv[1]);
const ctx = sandbox();
vm.runInContext(grab(src, /^const BACK_NAME = .*$/m) + "\nthis.BACK_NAME = BACK_NAME;", ctx);
console.log(JSON.stringify([ctx.BACK_NAME.schedule, ctx.BACK_NAME.log, ctx.BACK_NAME.yaml, ctx.BACK_NAME.series ?? null]));
""", str(JS / "core.js"))
    assert shown == ["Back to the schedule", "Back to Activity", "Back to unshackle.yaml", None]  # the editor too, from Notifications or a deep link  # the series wall is the default: "Back to all series"
    assert 'BACK_NAME[currentTab] || "Back to all series"' in (JS / "core.js").read_text()


def test_the_page_draws_no_emoji():
    from html import unescape
    import re

    emoji = re.compile(r"[\U0001F000-\U0001FFFF\u23e9-\u23ff\u26a0\u2700-\u27bf]")
    status_marks = str.maketrans("", "", "\u2713\u2717")
    found = [f"{path.name}:{n}" for path in [STATIC / "index.html", *JS.glob("*.js")]
             for n, line in enumerate(path.read_text().splitlines(), 1) if emoji.search(unescape(line).translate(status_marks))]
    assert not found


def test_an_inbox_job_shows_six_episode_chips_and_counts_the_rest():
    short, long, full = node(r"""
const ctx = sandbox({ LOCALE: "en", ago: () => "Now" });
vm.runInContext(read(process.argv[1]).split("const clearable")[0], ctx);
const at = new Date().toISOString();
const chips = (count, cap) => {
  const eps = Array.from({ length: count }, (_, i) => `S01E${String(count - i).padStart(2, "0")}`);
  const row = ctx.inboxRow({ name: "Show", level: "error", eps, items: [{ at }] }, 0, cap);
  return row.kids[1].kids[0].kids[1].kids.map((chip) => chip.textContent);
};
console.log(JSON.stringify([chips(6), chips(12), chips(12, Infinity).length]));
""", str(JS / "inbox.js"))
    first_six = [f"S01E0{i}" for i in range(1, 7)]
    assert short == first_six
    assert long == [*first_six, "+6"]
    assert full == 12  # the full Inbox names every episode: touch and keyboard users cannot read a tooltip


def test_the_inbox_menu_caps_a_job_at_six_episodes_and_the_full_inbox_names_them_all():
    menu, full = node(r"""
let menu = true;
const list = { classList: { toggle() {} }, replaceChildren(...kids) { this.kids = kids; } };
const ctx = sandbox({ LOCALE: "en", ago: () => "Now", S: { series: [] }, keepFocus: (_box, draw) => draw(),
  $: (sel) => sel === "#inbox-dialog" ? { classList: { contains: () => menu } } : sel === "#inbox-list" ? list : any });
vm.runInContext(read(process.argv[1]).split("/* The bell opens")[0], ctx);  // the renderer, not the page's event wiring
const at = new Date().toISOString();
const items = Array.from({ length: 12 }, (_, i) => ({ title: `Failed: Show S01E${String(i + 1).padStart(2, "0")}`, at, level: "error", batch: "job1" }));
vm.runInContext(`inboxData = { items: ${JSON.stringify(items)}, read_at: "" }`, ctx);
const chips = () => { ctx.renderInbox(); return list.kids[1].kids[1].kids[0].kids[1].kids.map((chip) => chip.textContent); };
const inMenu = chips();
menu = false;
console.log(JSON.stringify([inMenu, chips()]));
""", str(JS / "inbox.js"))
    episodes = [f"S01E{i:02d}" for i in range(1, 13)]
    assert menu == [*episodes[:6], "+6"]
    assert full == episodes


def test_inbox_fetch_failure_preserves_unread_and_can_retry():
    result = node(r"""
const nodes = Object.fromEntries(["dialog", "list", "clear", "filters", "summary"].map((id) => [`#inbox-${id}`, {
  classList: { toggle() {}, contains: () => true }, dataset: {}, addEventListener() {}, replaceChildren(...kids) { this.kids = kids; },
}]));
Object.assign(nodes, {
  "#inbox-dialog": { ...nodes["#inbox-dialog"], style: {}, show() { this.open = true; } },
  "#bell": { getBoundingClientRect: () => ({}), setAttribute() {} }, "#bell-count": { hidden: false },
});
let unavailable = true, posts = 0;
const ctx = sandbox({
  $: (sel) => nodes[sel] || any, phoneLayout: () => true, setInterval() {},
  keepFocus: (_box, draw) => draw(), failed: (text, retry) => ({ text, retry }),
  api: async (path) => {
    if (path === "/api/inbox/read") posts++;
    if (unavailable) throw Error("503");
    return { items: [], unread: path === "/api/inbox" ? 1 : 0 };
  },
});
vm.runInContext(read(process.argv[1]), ctx);
(async () => {
  await ctx.openInbox("menu");
  const retry = nodes["#inbox-list"].kids[0]?.retry;
  let clearThrew = false;
  try { await nodes["#inbox-clear"].onclick({ currentTarget: nodes["#inbox-clear"] }); } catch { clearThrew = true; }
  const failed = [Boolean(retry), posts, nodes["#bell-count"].hidden, nodes["#inbox-clear"].hidden, clearThrew];
  unavailable = false;
  await retry?.();
  console.log(JSON.stringify({ failed, recovered: [posts, nodes["#bell-count"].hidden, nodes["#inbox-list"].kids[0]?.className] }));
})();
""", str(JS / "inbox.js"))
    assert result == {"failed": [True, 0, False, True, False], "recovered": [1, True, "inbox-empty"]}


def test_every_news_target_gets_a_new_badge():
    class Markup(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = [{"tag": "html", "kids": []}]

        def handle_starttag(self, tag, attrs):
            item = {"tag": tag, **dict(attrs), "kids": []}
            self.stack[-1]["kids"].append(item)
            if tag not in "area base br col embed hr img input link meta param source track wbr".split():
                self.stack.append(item)

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i]["tag"] == tag:
                    del self.stack[i:]
                    break

    markup = Markup()
    markup.feed((STATIC / "index.html").read_text())
    missing, advanced_summary_badged = node(r"""
const root = JSON.parse(fs.readFileSync(0, "utf8"));
const matches = (n, selector) => {
  const attr = /^(\w+)\[(\w+)(?:="([^"]+)")?\]$/.exec(selector);
  if (attr) return n.tag === attr[1] && (attr[3] === undefined ? attr[2] in n : n[attr[2]] === attr[3]);
  if (selector.startsWith("#")) return n.id === selector.slice(1);
  if (selector.startsWith(".")) return (n.class || n.className || "").split(" ").includes(selector.slice(1));
  return n.tag === selector;
};
function *walk(n) {
  yield n;
  for (const k of n.kids.filter((kid) => kid && typeof kid === "object")) yield* walk(k);
}
function setup(n, parent) {
  n.parent = parent;
  n.matches = (sel) => sel.split(", ").some((part) => matches(n, part));
  n.querySelector = (selectors) => [...walk(n)].slice(1).find((child) => selectors.split(", ").some((sel) => {
    if (sel.startsWith(":scope > ")) return child.parent === n && matches(child, sel.slice(9));
    const [outer, inner] = sel.split(" ");
    if (!inner) return matches(child, outer);
    if (!matches(child, inner)) return false;
    for (let p = child.parent; p && p !== n; p = p.parent) if (matches(p, outer)) return true;
    return false;
  }));
  n.append = (child) => {
    child.parentElement = n;
    child.remove = () => n.kids.splice(n.kids.indexOf(child), 1);
    n.kids.push(child);
  };
  n.addEventListener = () => {};
  n.removeEventListener = () => {};
  n.classList = { add() {}, remove() {} };
  n.replaceChildren = (...kids) => { n.kids = kids; for (const kid of kids) setup(kid, n); };
  for (const k of n.kids.filter((kid) => kid && typeof kid === "object")) setup(k, n);
}
setup(root);
const advanced = root.querySelector("#d-libs-adv");
const summary = advanced.querySelector("summary");
const nestedField = el("div", {}, el("label", { textContent: "Per-library option" }));
advanced.replaceChildren(nestedField, ...advanced.kids);
const ctx = sandbox({ S: { config: { settings: {} }, news: { seen: [] } }, document: {
  querySelector: (sel) => root.querySelector(sel), querySelectorAll: (sel) => [...walk(root)].filter((n) => matches(n, sel)),
}, IntersectionObserver: class { observe() {} unobserve() {} },
  $: (sel) => root.querySelector(sel), keepFocus: (_, draw) => draw(),
  ladders: () => [{ name: "Example", steps: [] }], ladderUse: () => [], qlId: () => 1,
});
const quality = read(process.argv[2]);
vm.runInContext(read(process.argv[1]).split("/* The What's new window")[0] + "\nglobalThis.options = NEWS;", ctx);
vm.runInContext("let fieldIds = 0;\n" + ["renderQuality", "ladderCard"].map((name) =>
  grab(quality, new RegExp(`^function ${name}\\b[\\s\\S]*?\\n}\\n`, "m"))).join("\n"), ctx);
ctx.renderQuality();
ctx.renderNews();
ctx.renderQuality();
const missing = ctx.options.filter(({ target }) => {
  const box = root.querySelector(target);
  return !box || [...walk(box)].filter((n) => matches(n, ".new-badge")).length !== 1;
}).map(({ id }) => id);
console.log(JSON.stringify([missing, Boolean(summary.querySelector(".new-badge"))]));
""", str(JS / "news.js"), str(JS / "quality.js"), input_text=json.dumps(markup.stack[0]))
    assert missing == []
    assert advanced_summary_badged


def test_options_sharing_a_title_have_one_badge_and_keep_each_unread_id():
    states = node(r"""
const badges = [], classes = new Set(), posts = [];
const title = {
  append(badge) {
    badge.parentElement = this;
    badge.remove = () => badges.splice(badges.indexOf(badge), 1);
    badges.push(badge);
  },
  querySelector: (selector) => badges.find((b) => selector === ".new-badge" || selector.includes(`"${b.dataset.news}"`)),
};
const box = {
  dataset: {},
  classList: { add: (name) => classes.add(name), remove: (...names) => names.forEach((name) => classes.delete(name)) },
  matches: () => false, querySelector: () => title,
  addEventListener: (_, fn) => { box.click = () => fn({ currentTarget: box }); box.listening = true; },
  removeEventListener() { box.listening = false; },
};
let unobserved = 0;
let intersect, finish;
const S = { news: { installed: "1.5.0", seen: [] } };
const ctx = sandbox({
  S, innerHeight: 800,
  document: {
    querySelector: (selector) => selector === "#dx-services-card" ? box : null,
    querySelectorAll: (selector) => selector === ".new-badge" ? [...badges] : classes.has("is-new") ? [box] : [],
  },
  IntersectionObserver: class { constructor(fn) { intersect = fn; } observe() {} unobserve() { unobserved += 1; } },
  setTimeout: (fn) => { finish = fn; return 1; }, clearTimeout() {},
  api: (_, { body }) => posts.push(JSON.parse(body).ids),
});
vm.runInContext(read(process.argv[1]).split("/* The What's new window")[0], ctx);
ctx.renderNews();
const initial = badges.map((b) => b.textContent);
ctx.markNews(["service-cache"]);
const stillUnread = badges.map((b) => b.textContent);
intersect([{ target: box, isIntersecting: true, intersectionRatio: 1 }]);
finish();
const cleared = badges.length;
S.news.seen = ["service-cache", "any-service-option"];
ctx.renderNews();
const watched = unobserved;
box.click();  // its last unread option seen: the box is not new any more
const released = [unobserved - watched, box.listening, classes.has("is-new")];  // no longer new: no observer, no click handler, no outline
console.log(JSON.stringify([initial, stillUnread, cleared, badges.length, posts, released]));
""", str(JS / "news.js"))
    assert states == [
        ["New"], ["New"], 0, 0,
        [["service-cache"], ["any-service-option", "ladder-chips"], ["ladder-chips"]],
        [1, False, False],
    ]

# A tiny stand-in for the DOM a pop-up touches: nodes that keep what is set on them and a shared "focused" node.
POP_DOM = r"""
let active = null;
const make = (tag, props = {}, ...kids) => ({ tag, ...props, kids, attrs: {}, handlers: {}, style: {}, isConnected: true,
  setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(type, fn) { this.handlers[type] = fn; }, focus() { active = this; }, remove() { this.removed = true; },
  getBoundingClientRect: () => ({ left: 0, right: 10, top: 0, bottom: 10, width: 10, height: 10 }),
  contains(n) { return n === this || this.kids.some((k) => k.contains?.(n)); },
  querySelectorAll() { const out = []; const walk = (n) => { for (const k of n.kids || []) { if ((k.tag === "button" && !k.disabled) || k.tag === "input") out.push(k); walk(k); } }; walk(this); return out; } });
const keys = (pop, key, shiftKey = false) => { let stopped = false; pop.handlers.keydown({ key, shiftKey, preventDefault: () => { stopped = true; } }); return stopped; };
const popDom = { make, document: { body: { append() {} }, addEventListener() {}, get activeElement() { return active; } }, innerWidth: 800, innerHeight: 600 };
"""


def test_a_popup_takes_focus_keeps_tab_and_arrows_inside_and_gives_focus_back():
    seen = node(POP_DOM + r"""
const series = read(process.argv[1]);
const ctx = sandbox({ ...popDom });
vm.runInContext(grab(series, /function popOpen\b[\s\S]*?\n}\n/) + grab(series, /function popClose\b[\s\S]*?\n}\n/), ctx);
const [first, off, last] = [make("button"), make("button", { disabled: true }), make("button")];
const pop = make("div", {}, make("b"), make("div", {}, first, off, last)), anchor = make("button"), elsewhere = make("button");
ctx.popOpen(pop, anchor, "Actions");
const out = { focused: active === first, role: pop.attrs.role, label: pop.attrs["aria-label"], popup: anchor.attrs["aria-haspopup"], open: anchor.attrs["aria-expanded"] };
out.tabLast = keys(pop, "Tab") && active === last;  // not the disabled one
out.tabWraps = keys(pop, "Tab") && active === first;
out.shiftTabWraps = keys(pop, "Tab", true) && active === last;
out.arrows = keys(pop, "ArrowUp") && active === first && keys(pop, "ArrowDown") && active === last;
out.otherKeysFree = !keys(pop, "a");
ctx.popClose(pop);
out.closed = anchor.attrs["aria-expanded"]; out.backOnButton = active === anchor;
active = elsewhere; ctx.popClose(pop);
out.focusKept = active === elsewhere;
const moved = make("button"), gone = make("button"), pop2 = make("div", {}, make("button"));  // the page drew the button again while the pop-up was open
ctx.popOpen(pop2, gone, "Actions", () => moved);
gone.isConnected = false;
ctx.popClose(pop2);
out.backOnItsReplacement = active === moved;
console.log(JSON.stringify(out));
""", str(JS / "series.js"))
    assert seen == {"focused": True, "role": "dialog", "label": "Actions", "popup": "dialog", "open": "true", "tabLast": True, "tabWraps": True,
                    "shiftTabWraps": True, "arrows": True, "otherKeysFree": True, "closed": "false", "backOnButton": True, "focusKept": True, "backOnItsReplacement": True}


def test_a_popup_with_every_action_off_holds_the_focus_itself_until_escape():
    seen = node(POP_DOM + r"""
const series = read(process.argv[1]);
const ctx = sandbox({ ...popDom });
vm.runInContext(grab(series, /function popOpen\b[\s\S]*?\n}\n/) + grab(series, /function popClose\b[\s\S]*?\n}\n/), ctx);
const pop = make("div", {}, make("button", { disabled: true })), anchor = make("button");
ctx.popOpen(pop, anchor, "Actions");
const out = { onWindow: active === pop, focusable: pop.tabIndex === -1, tabKept: keys(pop, "Tab") && active === pop };
ctx.popClose(pop);
out.back = active === anchor;
console.log(JSON.stringify(out));
""", str(JS / "series.js"))
    assert seen == {"onWindow": True, "focusable": True, "tabKept": True, "back": True}

def test_the_device_menus_open_with_focus_inside_and_escape_returns_it_to_the_button():
    seen = node(POP_DOM + r"""
const series = read(process.argv[1]), src = read(process.argv[2]);
const ctx = sandbox({ ...popDom, el: make });
vm.runInContext(grab(series, /function popOpen\b[\s\S]*?\n}\n/) + grab(series, /function popClose\b[\s\S]*?\n}\n/), ctx);
vm.runInContext(grab(src, /let cdmPop = null;\nconst closeCdmPop = .*\n/) + grab(src, /function cdmPopAt\b[\s\S]*?\n}\n/), ctx);
const [test, del] = [make("button"), make("button", { disabled: true })], anchor = make("button", { dataset: { key: "dev:x" } });
const pop = ctx.cdmPopAt(anchor, make("b", { textContent: "Widevine device" }), make("div", {}, test, del));
const out = { focused: active === test, open: anchor.attrs["aria-expanded"], popup: anchor.attrs["aria-haspopup"], label: pop.attrs["aria-label"] };
vm.runInContext("closeCdmPop()", ctx);  // what Escape does
out.back = active === anchor; out.closed = anchor.attrs["aria-expanded"]; out.gone = pop.removed === true;
console.log(JSON.stringify(out));
""", str(JS / "series.js"), str(JS / "cookies-cdm.js"))
    assert seen == {"focused": True, "open": "true", "popup": "dialog", "label": "Widevine device", "back": True, "closed": "false", "gone": True}


def test_the_setup_popup_takes_focus_and_escape_returns_it_to_the_info_button():
    seen = node(POP_DOM + r"""
const series = read(process.argv[1]), src = read(process.argv[2]);
const copy = make("button");
const ctx = sandbox({ ...popDom, el: make, setupBox: () => [copy] });
vm.runInContext(grab(series, /function popOpen\b[\s\S]*?\n}\n/) + grab(series, /function popClose\b[\s\S]*?\n}\n/), ctx);
vm.runInContext(grab(src, /let setupPop = null;\nconst closeSetup = .*\n/) + grab(src, /function openSetup\b[\s\S]*?\n}\n/), ctx);
const info = make("button");
ctx.openSetup({ id: "job" }, info);
const out = { focused: active === copy, open: info.attrs["aria-expanded"] };
vm.runInContext("closeSetup()", ctx);  // what Escape does
out.back = active === info; out.closed = info.attrs["aria-expanded"];
console.log(JSON.stringify(out));
""", str(JS / "series.js"), str(JS / "activity.js"))
    assert seen == {"focused": True, "open": "true", "back": True, "closed": "false"}


def test_a_device_row_is_a_div_with_a_real_summary_button_beside_its_actions_button():
    seen = node(r"""
const src = read(process.argv[1]);
const nodes = {};
const $ = (sel) => (nodes[sel] ??= { value: "", hidden: false, textContent: "", focus() {}, select() {}, classList: { toggle() {} },
  querySelector: () => ({ textContent: "" }), replaceChildren() {}, replaceWith() {} });
const cdmOpen = new Set();
const ctx = sandbox({ $, cdmData: { folder: "/cdm", devices: [{ name: "alpha", kind: "Widevine", used_by: [], info: {} }], remote: [], services: [], map: {} },
  cdmFilter: "all", cdmQuery: "", cdmTesting: false, cdmShowUnused: true, cdmRunning: new Set(), cdmOpen, S: { config: { series: {}, settings: {} } },
  COUNT: { device: String, problem: String, moreDevice: String }, svcName: String, cdmShort: (d) => d.name });
for (const name of ["cdmTitle", "cdmStatus"]) vm.runInContext(grab(src, new RegExp(`function ${name}\\b[\\s\\S]*?\\n}\\n`)), ctx);
vm.runInContext(grab(src, /const cdmCard = [\s\S]*?\.\.\.body\);\n/), ctx);
vm.runInContext(grab(src, /function renderCdm\b[\s\S]*?\n}\n/), ctx);
let row = null;
const made = ctx.el;
ctx.el = (tag, props, ...kids) => { const n = made(tag, props, ...kids); if (/^cdm-dev /.test(props?.className || "")) row = n; return n; };
ctx.renderCdm();
const [summary, menu] = row.kids;
const buttonsIn = (n) => (n.kids || []).flatMap((k) => (k.tag === "button" ? [k] : []).concat(buttonsIn(k)));
summary.onclick();
console.log(JSON.stringify({ rowTag: row.tag, rowRole: row.role ?? null, rowTab: row.tabIndex ?? null, summary: [summary.tag, summary.type, summary.ariaExpanded],
  menu: [menu.tag, menu.className.includes("cdm-pop-btn")], nested: buttonsIn(summary).length, unfolds: cdmOpen.has("alpha") }));
""", str(JS / "cookies-cdm.js"))
    assert seen == {"rowTag": "div", "rowRole": None, "rowTab": None, "summary": ["button", "button", "false"], "menu": ["button", True], "nested": 0, "unfolds": True}


def test_local_and_remote_device_rows_show_service_names_and_keep_default():
    seen = node(r"""
const src = read(process.argv[1]), series = read(process.argv[2]);
const used_by = ["rmcbfm", "DEFAULT", "UNKNOWN"];  // a key in lower case names the same service
const rows = [];
let localVisible = false;
const collect = (tag, props, ...kids) => {
  if (props?.className === "used") rows.push(kids.map((kid) => kid.textContent));
  if (props?.className === "cdm-sum") localVisible = true;
  return el(tag, props, ...kids);
};
const ctx = sandbox({ el: collect, $: () => any, keepFocus: (_box, draw) => draw(),
  cdmData: { folder: "/cdm", devices: [{ name: "alpha", kind: "Widevine", used_by }], remote: [{ name: "remote", used_by }], services: [], map: {} },
  cdmFilter: "all", cdmQuery: "", cdmTesting: false, cdmShowUnused: false, cdmRunning: new Set(), cdmOpen: new Set(), cdmJust: new Set(),
  S: { config: { series: {}, settings: {} }, serviceNames: { RMCBFM: "RMC BFM Play" } },
  COUNT: { device: String }, cdmShort: (d) => d.name });
vm.runInContext(grab(series, /^const svcName = .*$/m)
  + "\n" + grab(src, /^const cdmUsageName = .*$/m)
  + "\n" + grab(src, /const cdmCard = [\s\S]*?\.\.\.body\);\n/)
  + ["cdmTitle", "cdmStatus", "renderCdm", "remoteRow"].map((name) => grab(src, new RegExp(`function ${name}\\b[\\s\\S]*?\\n}\\n`))).join("\n"), ctx);
ctx.renderCdm();
const labels = rows.splice(0);
const visible = (query) => {
  localVisible = false;
  ctx.cdmQuery = query;
  ctx.renderCdm();
  return localVisible;
};
console.log(JSON.stringify({ labels, byName: visible("rmc bfm play"), byCode: visible("rmcbfm") }));
""", str(JS / "cookies-cdm.js"), str(JS / "series.js"))
    assert seen == {"labels": [["RMC BFM Play", "default", "UNKNOWN"]] * 2, "byName": True, "byCode": True}



def test_cdm_alerts_name_services_not_their_codes():
    alerts = node(r"""
const src = read(process.argv[1]), series = read(process.argv[2]);
const text = (n) => typeof n === "string" ? n : [n.textContent || "", ...(n.kids || []).map(text)].join("");
const found = [];
const collect = (tag, props, ...kids) => {
  const node = el(tag, props, ...kids);
  if (props?.className === "cdm-alert") found.push(node);
  return node;
};
const failing = { name: "alpha", kind: "Widevine", used_by: ["rmcbfm"], test: { ok: false, error: "No license", at: "2026-11-20T00:00:00Z" } };
const ctx = sandbox({ el: collect, $: () => any, keepFocus: (_box, draw) => draw(), tr: (s) => s, ago: () => "now",
  cdmData: { folder: "/cdm", devices: [failing], remote: [], services: [], map: { RMCBFM: "ghost" } },  // a device no longer in the folder
  cdmFilter: "all", cdmQuery: "", cdmTesting: false, cdmShowUnused: false, cdmRunning: new Set(), cdmOpen: new Set(), cdmJust: new Set(),
  S: { config: { series: {}, settings: {} }, serviceNames: { RMCBFM: "RMC BFM Play" } },
  COUNT: { device: String, key: String, problem: String }, cdmShort: (d) => d.name });
vm.runInContext(grab(series, /^const svcName = .*$/m)
  + "\n" + grab(src, /^const cdmUsageName = .*$/m)
  + "\n" + grab(src, /const cdmCard = [\s\S]*?\.\.\.body\);\n/)
  + ["cdmTitle", "cdmStatus", "renderCdm", "remoteRow"].map((name) => grab(src, new RegExp(`function ${name}\\b[\\s\\S]*?\\n}\\n`))).join("\n"), ctx);
ctx.renderCdm();
console.log(JSON.stringify(found.map((a) => text(a).replace(/Pick a device$/, "").trim())));
""", str(JS / "cookies-cdm.js"), str(JS / "series.js"))
    assert alerts == ["RMC BFM Play uses ghost, which is not in the CDM folder", "alpha, used by RMC BFM Play: No license, tested now"]

def test_device_picker_finds_and_labels_devices_by_service_name():
    seen = node(r"""
const src = read(process.argv[1]), series = read(process.argv[2]);
let search, list;
const ctx = sandbox({ el: (tag, props, ...kids) => ({ ...el(tag, { value: "", ...props }, ...kids), replaceChildren(...k) { this.kids = k; }, append(...k) { this.kids.push(...k); }, get children() { return this.kids; } }), cdmPopAt: (_anchor, _title, q, box) => { [search, list] = [q, box]; return false; },
  cdmData: { devices: [{ name: "alpha", kind: "Widevine", used_by: ["RMCBFM"] }], remote: [], map: {} },
  S: { serviceNames: { RMCBFM: "RMC BFM Play" } }, cdmShort: (d) => d.name, trWith: (template, value) => template.replace("{0}", value) });
vm.runInContext(grab(series, /^const svcName = .*$/m) + "\n" + grab(src, /^const cdmUsageName = .*$/m) + "\n"
  + ["cdmTitle", "cdmPicker"].map((name) => grab(src, new RegExp(`function ${name}\\b[\\s\\S]*?\\n}\\n`))).join("\n"), ctx);
const shown = (text) => {
  search.value = text;
  search.oninput();
  return list.kids.filter((k) => k.className?.startsWith("cdm-opt")).map((k) => k.kids[1].textContent);
};
ctx.cdmPicker({}, "default", "");
console.log(JSON.stringify({ byName: shown("rmc bfm play"), byCode: shown("rmcbfm") }));
""", str(JS / "cookies-cdm.js"), str(JS / "series.js"))
    assert seen == {"byName": ["Used by RMC BFM Play"], "byCode": ["Used by RMC BFM Play"]}



def test_the_header_says_an_update_or_a_check_in_words_not_by_the_dot_alone():
    shown = node(r"""
const buttons = Object.fromEntries(["unshackle", "sonarr"].map((n) => [n, { dataset: {}, title: "", dot: { className: "" }, small: { textContent: "" },
  querySelector(sel) { return sel === ".dot" ? this.dot : this.small; } }]));
const ctx = sandbox({ S: {}, document: { querySelector: (sel) => buttons[sel.match(/data-health=(\w+)/)[1]] }, unshackleDetails: null });
vm.runInContext(grab(read(process.argv[1]), /^function renderHealth\(.*?^\}/ms), ctx);
vm.runInContext(grab(read(process.argv[1]), /^function paintLights\(.*?^\}/ms), ctx);
const say = (h) => { ctx.renderHealth(h); return ["unshackle", "sonarr"].map((n) => [buttons[n].small.textContent, buttons[n].dataset.state, buttons[n].dot.className.trim()]); };
console.log(JSON.stringify({
  running: say({ unshackle: { ok: true, version: "4.0.0" }, sonarr: { ok: true } }),
  update: say({ unshackle: { ok: true, version: "4.0.0", latest: "4.1.0" }, sonarr: { ok: true } }),
  unreachable: say({ unshackle: { ok: false }, sonarr: { ok: false } }),
  checking: say({ unshackle: { ok: null }, sonarr: {} }),
}));
""", str(JS / "schedule.js"))
    assert shown == {
        "running": [["", "ok", "dot ok"], ["", "ok", "dot ok"]],
        "update": [["Update available", "warn", "dot warn"], ["", "ok", "dot ok"]],
        "unreachable": [["Unreachable", "down", "dot down"], ["Unreachable", "down", "dot down"]],
        "checking": [["Checking…", "wait", "dot"], ["Checking…", "wait", "dot"]],
    }


def test_each_download_step_says_its_state_and_the_current_one_is_marked():
    shown = node(r"""
const ctx = sandbox({ afterTracks: () => false });
const src = read(process.argv[1]);
for (const re of [/^const OUTCOME = [^\n]*\n/m, /^const STEPS = [^\n]*\n/m, /^const STEPS_SHORT = [^\n]*\n/m, /^const STEP_STATE = [^\n]*\n/m,
  /^function stepStates\(.*?^\}/ms, /^function stepList\(.*?^\}/ms]) vm.runInContext(grab(src, re), ctx);
const read_ = (c) => ctx.stepList(c).kids.map((s) => [s.className, s.ariaCurrent ?? null, s.kids[2].textContent]);
console.log(JSON.stringify({
  running: read_({ step: "downloading", outcome: "running", parts: 1 }),
  failed: read_({ step: "renaming", outcome: "failed", parts: 1 }),
  stopped: read_({ step: "downloading", outcome: "stopped", parts: 1 }),
  interrupted: read_({ step: "downloading", outcome: "interrupted", parts: 1 }),
  unavailable: read_({ step: "searching", outcome: "unavailable", parts: 1 }),
  kept: read_({ step: "done", outcome: "kept", parts: 1 }),
}));
""", str(JS / "activity.js"))
    assert shown["running"] == [["done", None, "Done"], ["now", "step", "Running"], ["", None, "Waiting"], ["", None, "Waiting"], ["", None, "Waiting"]]
    assert [row[2] for row in shown["failed"]] == ["Done", "Done", "Done", "Failed", "Waiting"]
    assert [row[1] for row in shown["failed"]].count("step") == 1
    assert shown["stopped"][1] == ["halt", "step", "Stopped"]
    assert ["halt", "step", "Interrupted"] in shown["interrupted"]  # a halt says why, not always "Stopped"
    assert ["halt", "step", "Not out yet"] in shown["unavailable"]
    assert shown["kept"][-1] == ["warn", None, "Kept"]  # the outcome's own word, not a colour


def test_the_weekly_bars_come_with_their_numbers_as_a_table():
    shown = node(r"""
const weeks = [{ start: "2026-11-02", downloaded: 5, kept: 2, failed: 1 }, { start: "2026-11-09", downloaded: 0, kept: 0, failed: 0 }];
const find = (n, pred, out = []) => { if (n && typeof n === "object") { if (pred(n)) out.push(n); (n.kids || []).forEach((k) => find(k, pred, out)); } return out; };
let main = null;
const ctx = sandbox({ LOCALE: "en", picked_run: "stats", api: async () => ({ month: {}, weeks, services: [], since: null }), svcName: String,
  $: (sel) => (sel === "#cd-main" ? { replaceChildren: (...k) => { main = k; } } : { classList: { add() {} }, replaceChildren() {}, hidden: false, textContent: "" }),
  document: { querySelectorAll: () => [] }, day: String, ago: String, duration: String, failed: any, renderDock() {} });
vm.runInContext(grab(read(process.argv[1]), /^async function showStats\(.*?^\}/ms), ctx);
ctx.showStats().then(() => {
  const page = { kids: main };
  const chart = find(page, (n) => n.className === "weeks")[0];
  const table = find(page, (n) => n.tag === "table")[0];
  const rows = find(table, (n) => n.tag === "tr").map((r) => r.kids.map((c) => c.textContent));
  console.log(JSON.stringify({ chartHidden: chart.ariaHidden, chartRole: chart.role ?? null, caption: find(table, (n) => n.tag === "caption")[0].textContent, rows }));
});
""", str(JS / "activity.js"))
    assert shown["chartHidden"] == "true" and shown["chartRole"] is None  # the bars are the picture; the table has the data
    assert shown["caption"] == "Downloads per week, the last 8 weeks"
    assert shown["rows"] == [["Week", "Downloaded", "Failed", "Kept"], ["Nov 2", 5, 1, 2], ["Nov 9", 0, 0, 0]]


def test_the_quality_ladder_chips_say_which_is_chosen_and_the_edit_link_stays_outside_them():
    shown = node(r"""
const made = (tag, props = {}, ...kids) => ({ tag, ...props, kids, replaceChildren(...k) { this.kids = k; } });
const ctx = sandbox({ el: made, ladders: () => [{ name: "UHD" }, { name: "HD" }], keepFocus: (box, draw) => draw() });
vm.runInContext(grab(read(process.argv[1]), /^function ladderChips\(.*?^\}/ms), ctx);
const picked = [];
const root = ctx.ladderChips("HD", "UHD", (v) => picked.push(v));
const group = root.kids[0], state = () => group.kids.map((b) => [b.kids[0].textContent, b.ariaPressed, b.role ?? null, b.ariaChecked ?? null]);
const before = state();
group.kids[0].onclick();  // Off
console.log(JSON.stringify({ root: [root.className, root.kids.map((k) => k.tag)], group: [group.role, group.ariaLabel], before, after: state(), picked }));
""", str(JS / "quality.js"))
    assert shown["root"] == ["ladder-pick", ["div", "a"]]  # the link is beside the group, not one of its chips
    assert shown["group"] == ["group", "Quality ladder"]
    assert shown["before"] == [["Off", "false", None, None], ["UHD", "false", None, None], ["HD", "true", None, None]]
    assert shown["after"][0][1] == "true" and shown["after"][2][1] == "false"
    assert shown["picked"] == ["off"]


def test_settings_version_button_names_a_release_or_a_test_build_and_hides_without_a_version():
    shown = node(r"""
const src = read(process.argv[1]);
const block = grab(src, /const \[, branch, commit\] = [\s\S]*?\$\("#set-version"\)\.hidden = !data\.version;/);
const run = (data) => {
  const version = { textContent: "", beta: false, classList: { toggle(_, on) { version.beta = on; } } }, button = { hidden: false };
  const ctx = sandbox({ data, $: (selector) => selector === "#version" ? version : button });
  vm.runInContext(block, ctx);
  return [version.textContent, version.beta, button.hidden];
};
console.log(JSON.stringify([run({ version: "1.5.0", build: "" }), run({ version: "1.5.0", build: "feat-shell-abc1234" }), run({ version: "", build: "" })]));
""", str(JS / "setup.js"))
    assert shown == [["Unshacklarr 1.5.0", False, False], ["Unshacklarr feat-shell · abc1234", True, False], ["", False, True]]
