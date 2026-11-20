"""Controls are named by what they act on, and say their state: the page's real code on a small fake DOM (no browser)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"
I18N = Path(__file__).parents[1] / "unshacklarr" / "static" / "i18n"

HARNESS = r"""
const fs = require("fs"), vm = require("vm"), path = require("path");
const read = (file) => fs.readFileSync(path.join(process.argv[1], file), "utf8");
// a function, or a one-line / multi-line const, of a script
const grab = (src, name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n|const ${name} = [^\\n{]*\\n|const ${name} = [\\s\\S]*?\\n};?\\n`))[0];
const core = read("core.js"), activity = read("activity.js"), options = read("settings-options.js"), services = read("settings-services.js");
const series = read("series.js"), schedule = read("schedule.js"), bulk = read("bulk.js");

const line = (src, name) => src.match(new RegExp(`^const ${name} = .*$`, "m"))[0] + "\n";
const kebab = (k) => k.replace(/^aria([A-Z])/, (_, c) => "aria-" + c.toLowerCase()).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.texts = []; this.attrs = {}; this.dataset = {}; this.className = ""; this.hidden = false;
    this.classList = { toggle: (c, on) => { const set = new Set(this.className.split(" ").filter(Boolean)); on ? set.add(c) : set.delete(c); this.className = [...set].join(" "); },
      add: () => {}, remove: () => {}, contains: (c) => this.className.split(" ").includes(c) }; }
  append(...kids) { this.children.push(...kids.filter((k) => k instanceof Node)); this.texts.push(...kids.filter((k) => typeof k === "string")); }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  after() {}
  prepend(...kids) { this.children.unshift(...kids); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  focus() {}
  *walk() { for (const c of this.children) { yield c; yield* c.walk(); } }
  querySelector(sel) { return this.querySelectorAll(sel)[0] ?? null; }
  querySelectorAll(sel) { const cls = sel.startsWith(".") ? sel.slice(1) : null; return [...this.walk()].filter((n) => cls ? n.classList.contains(cls) : n.tag === sel || sel === "input" && n.tag === "input"); }
  contains(x) { return x === this || [...this.walk()].includes(x); }
}
// the attribute a screen reader would read: set with setAttribute, or as the property el() assigns
const attr = (n, name) => n.attrs[name] ?? Object.entries(n).filter(([k]) => /^aria[A-Z]|^role$/.test(k)).map(([k, v]) => [kebab(k), v]).find(([k]) => k === name)?.[1] ?? null;
const find = (box, pick) => [...box.walk()].find(pick);
const doc = { listeners: {}, activeElement: null, addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }, createElement: (tag) => new Node(tag), querySelectorAll: () => [] };
const boxes = {};
const $ = (sel) => (boxes[sel] ||= new Node("div"));
const ctx = { document: doc, $, console, Object, String, Math, JSON, Promise, setTimeout, Set, Map, WeakMap, Date, Number, Array, Intl, LOCALE: "en", icon: () => new Node("svg"), keepFocus: (box, draw) => draw(), dirty() {}, tr: String,
  trWith: (t, ...fill) => (ctx.tr || String)(t).replace(/\{(\d+)\}/g, (_, i) => fill[i]) };  // as the page's: through the scenario's tr
vm.createContext(ctx);
const run = (code) => vm.runInContext(code, ctx);
run(grab(core, "el"));
const out = {};
const scenario = process.argv[2];

if (scenario === "options") {  // the option editor: each value named by its flag
  run(grab(core, "optionsEditor"));
  ctx.optionPicker = () => new Node("div");
  const specs = [{ flag: "--quality", help: "Resolutions", is_flag: false, choices: [] }, { flag: "--no-cache", help: "", is_flag: true, choices: [] }];
  const root = new Node("div");
  ctx.optionsEditor(root, specs, { "--quality": "1080", "--no-cache": true });
  const inputs = [...root.walk()].filter((n) => n.tag === "input");
  out.names = inputs.map((i) => [i.type, attr(i, "aria-label")]);
}

if (scenario === "lang") {  // the language corner: a disclosure, not a menu; its button named in the language
  Object.assign(ctx, { LANGS: { en: "English", de: "Deutsch" }, LANG: "de", setLang() {}, T: { "Language: {0}": "Sprache: {0}" } });
  ctx.tr = (t) => ctx.T[t] ?? t;
  run(grab(core, "langCorner"));
  const corner = ctx.langCorner();
  const [button, menu] = corner.children;
  const items = [...menu.walk()];
  out.translate = corner.attrs.translate ?? null;
  out.label = attr(button, "aria-label");
  out.roles = [attr(menu, "role"), ...items.map((n) => attr(n, "role")), attr(button, "aria-haspopup")];
  out.current = items.map((n) => [n.children.length, attr(n, "aria-current")]);
  out.expanded = [attr(button, "aria-expanded")];
  button.onclick(); out.expanded.push(button.attrs["aria-expanded"]);
}

if (scenario === "groups") {  // Suggest services: the radios of one series are a group named by its title
  Object.assign(ctx, { S: { series: [{ tvdbId: 1, tmdbId: 9, title: "Koh-Lanta", monitored: true, status: "continuing", poster: "" }], config: { series: {}, hidden_series: [] }, services: ["ITV"] },
    posterSrc: () => "", posterFail: () => null, loading: (t) => ({ textContent: t }), svcName: (t) => t, bulkRun: 0,
    api: async () => ({ links: [{ service: "ITV", url: "https://itv.test/x", name: "", country: "GB" }] }) });
  boxes["#bulk-dialog"] = Object.assign(new Node("dialog"), { showModal() { this.open = true; } });
  run("let bulkRun = 0;" + grab(services, "openBulk"));
  (async () => {
    await ctx.openBulk();
    const li = $("#bulk-rows").children[0], opts = find(li, (n) => n.className === "opts");
    out.group = [attr(opts, "role"), attr(opts, "aria-label"), [...opts.walk()].filter((n) => n.tag === "input").length];
    console.log(JSON.stringify(out));
  })();
}

if (scenario === "activity") {  // Activity: the running dot, the picked row, the output toggle
  Object.assign(ctx, { picked_run: "job:j1", hoverKey: null, S: { series: [] }, posterSrc: () => "", jobTotals: () => [], thumb: () => new Node("span"),
    jobState: () => ({ live: true, words: [], progress: 1, n: {} }), pickRun() {}, phase: () => "" });
  run(line(activity, "phase") + line(activity, "pulse") + line(activity, "posterOf") + line(activity, "hovering") + grab(activity, "jobRow"));
  const dot = run("pulse()");
  out.pulse = [attr(dot, "role"), attr(dot, "aria-label")];
  const job = (id) => ctx.jobRow({ job: id, cards: [{ series: "A", tvdbId: 1 }] });
  out.rows = [attr(job("j1"), "aria-current"), attr(job("j2"), "aria-current")];
  // the output toggle follows the dock
  const open = new Node("button"), dock = new Node("div"), raw = new Node("details");
  dock.querySelector = () => open; dock.prepend = () => {};
  let isOpen = false;
  dock.classList = { add: () => { isOpen = true; }, remove: () => { isOpen = false; }, contains: () => isOpen };
  boxes["#dock"] = dock; boxes["#cd-raw"] = raw; boxes["#cd-foot"] = Object.assign(new Node("div"), { before() {} });
  run(grab(activity, "openSheet") + grab(activity, "closeSheet"));
  ctx.openSheet(); out.opened = open.attrs["aria-expanded"];
  ctx.closeSheet(); out.closed = open.attrs["aria-expanded"];
}

if (scenario === "names") {  // the repeated Test / Remove / Download, told apart; the app picker without its badge letters
  Object.assign(ctx, { LEVEL_NAMES: { success: "Downloaded" }, ntTested: new Map(), S: { config: { notifications: { targets: [
    { url: "discord://a", levels: ["success"] }, { url: "discord://b", levels: [] }, { url: "ntfy://c", levels: [] }] } } },
    appOf: (u) => ({ discord: "Discord", ntfy: "ntfy" })[u.split(":")[0]], badgeOf: (a) => a.slice(0, 2), renderNotify() {}, testTargets() {}, hoverTip: (e) => e });
  run(grab(options, "renderTargets"));
  ctx.renderTargets();
  const buttons = () => [...$("#nt-targets").walk()].filter((n) => n.tag === "button" && !n.className.includes("nt-pick")).map((b) => [b.textContent, attr(b, "aria-label")]);
  out.targets = buttons();
  ctx.ntTested.set("ntfy://c", "…");
  ctx.renderTargets();
  out.sending = buttons().slice(-2);
  ctx.ntApp = "Discord"; ctx.BUILDERS = { Discord: { hint: "", fields: [] }, Telegram: { hint: "", fields: [] } };
  run("let ntApp = 'Discord';" + grab(options, "ntDraw"));
  ctx.ntDraw();
  out.apps = [...$("#nt-apps").children].map((b) => b.children.map((c) => [c.textContent, attr(c, "aria-hidden")]));
  // the saved backups
  ctx.S.backups = { saved: [{ name: "a.bak", at: Date.UTC(2026, 10, 17, 12), size: 2048 }], folder: "/data" };
  boxes["#bk-saved-head"] = new Node("h3");
  run(grab(options, "renderBackups"));
  ctx.renderBackups();
  const download = find($("#bk-list"), (n) => n.tag === "button");
  out.download = [download.textContent, /^Download backup from /.test(attr(download, "aria-label"))];
}

if (scenario === "columns") {  // Move up / down: the list is vertical
  Object.assign(ctx, { COLUMNS: [{ id: "a", label: "Res.", file: true }, { id: "b", label: "Video", file: true }], saveColPrefs() {}, renderSeason() {}, COLS_KEY: "k", colPrefs: () => [] });
  ctx.colsNow = [{ id: "a", on: true }, { id: "b", on: true }];
  boxes["#cols-dialog"] = Object.assign(new Node("dialog"), { showModal() {} });
  run("var colsNow = [{ id: 'a', on: true }, { id: 'b', on: true }];" + grab(series, "openColumns"));
  ctx.openColumns();
  out.moves = [...$("#col-rows").children].map((li) => li.children.filter((n) => n.tag === "button").map((b) => attr(b, "aria-label")));
}

if (scenario === "hidden") {  // the Schedule's hidden series: the name starts with the visible "In schedule"
  Object.assign(ctx, { S: { config: { hidden_series: [7] }, series: [{ tvdbId: 7, title: "Abbott", poster: "" }] }, posterSrc: () => "", posterFail: () => null, hideSeries: async () => {} });
  boxes["#hidden-dialog"] = Object.assign(new Node("dialog"), { showModal() {} });
  boxes["#hidden-open"] = new Node("button");
  run(schedule.match(/^\$\("#hidden-open"\)\.onclick = [\s\S]*?^\};/m)[0]);
  $("#hidden-open").onclick();
  const box = find($("#hidden-rows"), (n) => n.tag === "input");
  const label = find($("#hidden-rows"), (n) => n.className === "switch");
  out.hidden = [label.texts[0], attr(box, "aria-label")];
}

if (scenario === "select") {  // Series selection: the count is a status; the toggle keeps one name and says it is pressed
  const toggle = Object.assign(new Node("button"), { textContent: "Select" });
  Object.assign(ctx, { SEL: { on: false, ids: new Set() }, renderWall() {}, openSel() {} });
  boxes["#sel-toggle"] = toggle; boxes["#sel-edit"] = new Node("button"); boxes["#sel-count"] = new Node("span");
  let bar; boxes["#wall"] = Object.assign(new Node("div"), { after: (b) => { bar = b; } });
  run(bulk.slice(0, bulk.indexOf("let selOptions")));
  toggle.onclick();
  out.on = [toggle.textContent, toggle.attrs["aria-pressed"]];
  toggle.onclick();
  out.off = [toggle.textContent, toggle.attrs["aria-pressed"]];
  out.countRole = attr(find(bar, (n) => n.id === "sel-count"), "role");
}

if (scenario !== "groups") console.log(JSON.stringify(out));
"""


def run_scenario(name):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    result = subprocess.run(["node", "-e", HARNESS, "--", str(JS), name], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_each_option_value_is_named_by_its_flag():
    assert run_scenario("options")["names"] == [["text", "--quality value"], ["checkbox", "--no-cache"]]


def test_the_language_corner_is_a_disclosure_named_in_the_language():
    shown = run_scenario("lang")
    assert shown["translate"] == "no"  # as an attribute: the property would set "yes"
    assert shown["label"] == "Sprache: Deutsch"
    assert shown["roles"] == [None, None, None, None]  # no menu roles: the arrow keys are not wired
    assert shown["current"] == [[0, "false"], [0, "true"]]
    assert shown["expanded"] == ["false", "true"]


def test_the_suggested_services_of_a_series_are_a_group_named_by_its_title():
    assert run_scenario("groups")["group"] == ["group", "Koh-Lanta", 2]


def test_activity_names_the_running_dot_the_picked_row_and_the_output_state():
    shown = run_scenario("activity")
    assert shown["pulse"] == ["img", "Running"]
    assert shown["rows"] == ["true", "false"]
    assert shown["opened"] == "true" and shown["closed"] == "false"


def test_repeated_buttons_name_their_item_and_the_badge_letters_are_hidden():
    shown = run_scenario("names")
    assert shown["targets"] == [["Test", "Test Discord 1"], ["Remove", "Remove Discord 1"], ["Test", "Test Discord 2"], ["Remove", "Remove Discord 2"],
                                ["Test", "Test ntfy"], ["Remove", "Remove ntfy"]]
    assert shown["sending"] == [["Sending…", None], ["Remove", "Remove ntfy"]]  # while it sends, its own text is its name
    assert shown["apps"] == [[["Di", "true"]], [["Te", "true"]]]
    assert shown["download"] == ["Download", True]


def test_the_columns_move_up_and_down_in_a_vertical_list():
    assert run_scenario("columns")["moves"] == [["Move Res. up", "Move Res. down"], ["Move Video up", "Move Video down"]]


def test_a_hidden_series_switch_is_named_from_its_visible_label():
    label, name = run_scenario("hidden")["hidden"]
    assert label == "In schedule" and name.startswith(label)


def test_the_selection_count_is_a_status_and_the_toggle_keeps_one_name():
    shown = run_scenario("select")
    assert shown["on"] == ["Select", "true"] and shown["off"] == ["Select", "false"]
    assert shown["countRole"] == "status"


def test_every_language_translates_the_new_names_with_their_placeholders():
    texts = ["{0} value", "Download backup from {0}", "Test {0}", "Move {0} up", "Move {0} down", "In schedule: {0}", "Language: {0}"]
    english = json.loads((I18N / "en.json").read_text())
    for path in sorted(I18N.glob("*.json")):
        if path.name == "en.json":
            continue
        translated = json.loads(path.read_text())
        for text in texts:
            assert text in english and translated.get(text), f"{path.name}: {text!r}"
            assert "{0}" in translated[text], f"{path.name}: {text!r} lost its placeholder"
        for dropped in ["Move {0} left", "Move {0} right", "Show {0} in the schedule"]:
            assert dropped not in english and dropped not in translated, f"{path.name}: {dropped!r}"
