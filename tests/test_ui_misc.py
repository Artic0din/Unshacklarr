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
const ctx = sandbox({ epSonarr: viewing, current: null, S: { services: ["IV"], config: { series: { 1: {} } }, sonarrsOf: { 1: [{ name: "sonarr-2", id: 20 }, { name: "sonarr-4k", id: 40 }] } },
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
