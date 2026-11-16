"""Small fixes to the page's scripts (static/js, sw.js), each run for real in Node with only the globals it reaches named."""
import json
import shutil
import subprocess
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


def node(body, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PRELUDE + body, "--", *args], capture_output=True, text=True)
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
const ctx = sandbox({ S: { config, dlOptions: [] }, savedConfig: JSON.stringify(saved), $: (sel) => sel,
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


def test_the_save_bar_offers_discard_and_announces_itself():
    page = (STATIC / "index.html").read_text()
    bar = page[page.index('<div class="savebar"'):].split("</div>", 1)[0]
    assert 'role="status"' in bar.split(">", 1)[0]
    assert bar.index('id="discard"') < bar.index('id="save"')


def test_the_header_says_an_update_or_a_check_in_words_not_by_the_dot_alone():
    shown = node(r"""
const buttons = Object.fromEntries(["unshackle", "sonarr"].map((n) => [n, { dataset: {}, title: "", dot: { className: "" }, small: { textContent: "" },
  querySelector(sel) { return sel === ".dot" ? this.dot : this.small; } }]));
const ctx = sandbox({ S: {}, document: { querySelector: (sel) => buttons[sel.match(/data-health=(\w+)/)[1]] }, unshackleDetails: null });
vm.runInContext(grab(read(process.argv[1]), /^function renderHealth\(.*?^\}/ms), ctx);
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
const ctx = sandbox({ el: made, ladders: () => [{ name: "UHD" }, { name: "HD" }] });
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
