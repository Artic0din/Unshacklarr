"""Keyboard focus survives a redraw: the real helpers and call sites, on a small fake DOM (no browser)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"

HARNESS = r"""
const fs = require("fs"), vm = require("vm"), path = require("path");
const read = (file) => fs.readFileSync(path.join(process.argv[1], file), "utf8");
const fn = (src, name) => src.match(new RegExp(`^(async )?function ${name}\\b.*?^\\}`, "ms"))[0];
const line = (src, name) => src.match(new RegExp(`^(const|let) ${name} = .*$`, "m"))[0];
const core = read("core.js"), cdm = read("cookies-cdm.js"), activity = read("activity.js"), schedule = read("schedule.js"), navigation = read("navigation.js"), quality = read("quality.js");

let root;
const doc = { activeElement: null, listeners: {}, body: null, addEventListener(type, f) { (this.listeners[type] ||= []).push(f); },
  createElement: (tag) => new Node(tag), createElementNS: (_, tag) => new Node(tag) };
const isControl = (n) => ["button", "input", "select", "textarea", "summary"].includes(n.tag) || (n.tag === "a" && n.href) || n.tabIndex !== undefined;
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.parent = null; this.hidden = false;
    this.focusCalls = 0; this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false }; }
  get isConnected() { let n = this; while (n.parent) n = n.parent; return n === root; }
  append(...kids) { for (const k of kids) if (k instanceof Node) { k.parent = this; this.children.push(k); } }
  replaceChildren(...kids) {
    for (const old of this.children) { if (old.contains(doc.activeElement)) doc.activeElement = root; old.parent = null; }
    this.children = [];
    this.append(...kids);
  }
  contains(x) { for (let n = x; n; n = n.parent) if (n === this) return true; return false; }
  *walk() { for (const c of this.children) { yield c; yield* c.walk(); } }
  querySelectorAll() { return [...this.walk()].filter(isControl); }
  getClientRects() { return this.noBox ? [] : [{}]; }
  focus() { this.focusCalls++; if (this.isConnected && !this.disabled) doc.activeElement = this; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  setSelectionRange(a, b, direction) { this.selected = [a, b, direction]; }
  scrollIntoView() {}
}
root = new Node("body"); doc.body = root; doc.activeElement = root;
const page = () => { const n = new Node("div"); root.append(n); return n; };
const make = (tag, props = {}) => Object.assign(new Node(tag), props);
const named = (n) => n ? (n.fk ?? n.dataset.fk ?? n.textContent ?? n.tag) : null;
const find = (box, pick) => [...box.walk()].find(pick);

const ctx = { document: doc, matchMedia: () => ({ matches: false }), console };
vm.createContext(ctx);
const run = (code) => vm.runInContext(code, ctx);
run(fn(core, "el") + "\n" + line(core, "CONTROLS") + "\n" + fn(core, "keepFocus") + "\n" + fn(core, "focusHeading"));
const out = {};
const scenario = process.argv[2];

if (scenario === "helper") {
  const box = page();
  const row = (...keys) => keys.map((k) => ctx.el("button", { textContent: k, dataset: { fk: k } }));
  box.append(...row("a", "b", "c"));
  find(box, (n) => n.textContent === "b").focus();
  ctx.keepFocus(box, () => box.replaceChildren(...row("c", "b", "a")));  // reordered: found by its key
  out.byKey = named(doc.activeElement);

  const chips = () => ["x", "y", "z"].map((t) => ctx.el("button", { textContent: t }));
  box.replaceChildren(...chips());
  box.children[1].focus();
  ctx.keepFocus(box, () => box.replaceChildren(...chips()));  // no key: the same place
  out.byPlace = [named(doc.activeElement), doc.activeElement === box.children[1]];

  box.replaceChildren(...chips());
  box.children[2].focus();
  ctx.keepFocus(box, () => box.replaceChildren(...chips().slice(0, 2)));  // the last one went: the one before
  out.clamped = named(doc.activeElement);

  box.replaceChildren(...row("a"));
  box.children[0].focus();
  const kept = box.children[0];
  ctx.keepFocus(box, () => {});  // not redrawn: left alone
  out.untouched = [doc.activeElement === kept, kept.focusCalls];

  const outside = make("button"); root.append(outside); outside.focus();
  let drawn = false;
  ctx.keepFocus(box, () => { drawn = true; box.replaceChildren(...row("a")); });  // focus elsewhere: only drawn
  out.outside = [drawn, doc.activeElement === outside, box.children[0].focusCalls];

  box.replaceChildren(...row("a", "b"));
  const [one, two] = box.children; two.focus();
  ctx.keepFocus(box, () => box.replaceChildren(two, one));  // moved in the list: blurred, the same element
  out.moved = [doc.activeElement === two, two.focusCalls];

  box.replaceChildren(...row("a"));
  box.children[0].focus();
  const hidden = ctx.el("button", { dataset: { fk: "a" } }); hidden.noBox = true;
  const shown = ctx.el("button", { dataset: { fk: "a" } });
  ctx.keepFocus(box, () => box.replaceChildren(hidden, shown));  // the same key twice: the one in sight
  out.visibleCopy = doc.activeElement === shown;

  box.replaceChildren(...row("a"));
  box.children[0].focus();
  ctx.keepFocus(box, () => box.replaceChildren(...row("b")));  // its key is gone: nothing else takes the focus
  out.gone = doc.activeElement === root;

  const field = () => ctx.el("input", { type: "text", value: "answer", dataset: { fk: "prompt:1" } });
  const first = field(); Object.assign(first, { selectionStart: 3, selectionEnd: 3, selectionDirection: "none" });
  box.replaceChildren(first); first.focus();
  const second = field();
  ctx.keepFocus(box, () => box.replaceChildren(second));
  out.caret = [doc.activeElement === second, second.selected];

  const marked = field(); Object.assign(marked, { selectionStart: 2, selectionEnd: 5, selectionDirection: "backward" });  // typing replaces it
  box.replaceChildren(marked); marked.focus();
  const redrawn = field();
  ctx.keepFocus(box, () => box.replaceChildren(redrawn));
  out.range = [doc.activeElement === redrawn, redrawn.selected];

  const heading = ctx.el("h2", { textContent: "Title" }); root.append(heading);
  ctx.focusHeading(heading); ctx.focusHeading(null);
  out.heading = [doc.activeElement === heading, heading.tabIndex];
}

if (scenario === "cdm") {  // a device's test result reorders the list: the focus stays on the device it was on
  const nodes = {};
  const at = (sel) => nodes[sel] ||= page();
  const state = page(); state.querySelector = () => ({});
  Object.assign(ctx, { Date, Intl, Math, Set, Object, Map, LOCALE: "en-GB", S: { config: { series: {}, settings: {} } }, tr: String, ago: () => "now", svcName: String,
    hideTip() {}, onTop() {}, COUNT: new Proxy({}, { get: () => (n) => `${n}` }), api: async () => ({}), toast() {}, confirmClick: () => true,
    $: (sel) => sel === "#cdm-state" ? state : sel === "#cdm-devices" ? null : at(sel) });
  run([40, 41, 42, 109, 110].map((n) => cdm.split("\n")[n - 1]).join("\n") + "\n" + cdm.match(/^const cdmCard = [\s\S]*?\.\.\.body\);$/m)[0] + "\n"
    + ["cdmTitle", "cdmStatus", "cdmShort", "renderCdm"].map((n) => fn(cdm, n)).join("\n"));
  const device = (name) => ({ name, kind: "Widevine", folder: false, used_by: ["Netflix"], info: null, test: null, level: "L3" });
  run("cdmData = " + JSON.stringify({ folder: "/cdm", map: {}, services: [], remote: [], devices: [device("alpha"), device("bravo")] }));
  ctx.renderCdm();
  const list = at("#cdm-list");
  const rows = () => [...list.walk()].filter((n) => n.dataset.fk?.startsWith("row:")).map((n) => n.dataset.fk.split(":")[2]);
  const label = (n) => n?.ariaLabel ?? n?.dataset.fk;
  const menu = (who) => find(list, (n) => n.ariaLabel === `Actions for ${who}`);
  out.before = rows();
  menu("alpha").focus();
  run("cdmData.devices[1].test = { ok: false, error: 'refused', at: 1 }");  // bravo fails its test, so it sorts ahead of alpha
  ctx.renderCdm();
  out.menu = [rows(), label(doc.activeElement), doc.activeElement === menu("alpha")];
  menu("alpha").parent.focus();  // the row itself is a control too
  run("cdmData.devices[1].test = null");  // and back again
  ctx.renderCdm();
  out.row = [rows(), label(doc.activeElement)];
}

if (scenario === "chips") {  // a slide-out's chips are rebuilt at each pick
  run(fn(quality, "defaultChips"));
  const box = page();
  let own;
  const draw = () => ctx.defaultChips(box, [["1080", "1080p"], ["720", "720p"], ["480", "480p"]], own, "1080", (v) => { own = v; draw(); });
  draw();
  box.children[1].focus();
  box.children[1].onclick();
  out.after = [doc.activeElement === box.children[1], box.children.map((c) => c.ariaPressed)];
}

if (scenario === "lang") {  // Escape closes the language menu and the focus goes back to its button
  Object.assign(ctx, { LANGS: { en: "English", fr: "Francais" }, LANG: "en", setLang() {} });
  run(fn(core, "langCorner"));
  const corner = ctx.langCorner(); root.append(corner);
  const [button, menu] = corner.children;
  button.onclick();
  menu.children[1].focus();
  const escape = (key) => doc.listeners.keydown.forEach((f) => f({ key }));
  escape("a");
  out.otherKey = [menu.hidden, doc.activeElement === menu.children[1]];
  escape("Escape");
  out.escaped = [menu.hidden, doc.activeElement === button, button.attrs["aria-expanded"]];
  doc.activeElement = root;
  escape("Escape");  // nothing open: nothing taken
  out.idle = doc.activeElement === root;
}

if (scenario === "settings") {  // a phone: a section opens on its heading, Back returns to its item in the list
  const nav = make("button", { dataset: { sec: "sonarr" } }); root.append(nav);
  const heading = make("h2"), sec = make("div"); sec.querySelector = () => heading; sec.append(heading); root.append(sec);
  Object.assign(ctx, { currentTab: "settings", phone: true, leaveNews() {}, navigate() {}, scrollTo() {}, S: { dlOptions: [] },
    $: () => ({ classList: { toggle() {} } }), phoneLayout: () => ctx.phone });
  doc.querySelector = (sel) => sel === '.set-nav [data-sec="sonarr"]' ? nav : sel === '.set-sec[data-sec="sonarr"]' ? sec : { scrollIntoView() {} };
  doc.querySelectorAll = () => [];
  run(line(navigation, "settingsSec").replace("let ", "var ") + "\n" + line(navigation, "inSettingsSec") + "\n" + fn(navigation, "showSettingsList") + "\n" + fn(navigation, "showSettingsSec"));
  run("settingsList = true");
  ctx.showSettingsSec("sonarr");
  out.opened = [doc.activeElement === heading, heading.tabIndex, run("settingsList")];
  doc.activeElement = root;
  ctx.showSettingsList(true);
  out.back = [doc.activeElement === nav, run("settingsList")];
  doc.activeElement = root; ctx.phone = false; run("settingsList = false");
  ctx.showSettingsSec("sonarr"); ctx.showSettingsList(true);
  out.wide = doc.activeElement === root;  // a wide screen keeps both: nothing moves
}

if (scenario === "activity") {
  const con = page(), title = make("h3"), rows = page();
  root.append(title);
  let picked = null;
  const drawRows = () => rows.replaceChildren(...["job:j1", "r1"].map((k) => ctx.el("button", { className: "crow", dataset: { fk: `row:${k}` } })));
  const lookup = (sel) => { const m = /^\[data-fk="(.*)"\]$/.exec(sel); return m ? find(rows, (n) => n.dataset.fk === m[1]) : sel === "#con" ? con : title; };
  Object.assign(ctx, { $: lookup, innerWidth: 500, scrollTo() {}, renderConsole: drawRows, picked_run: null });
  doc.getElementById = () => null;
  drawRows();
  run(fn(activity, "pickRun") + "\n" + "let picked_run = null;");
  con.classList.add = () => {};
  const back = {};
  ctx.$ = (sel) => sel === "#cd-back" ? back : lookup(sel);
  run((activity.match(/^\$\("#cd-back"\)\.onclick = .*\};$/m) || activity.match(/^\$\("#cd-back"\)\.onclick = .*?^\};/ms))[0]);
  rows.children[0].focus();
  ctx.pickRun("job:j1");
  out.phoneOpen = [doc.activeElement === title, title.tabIndex];
  ctx.innerWidth = 1280; doc.activeElement = root; title.tabIndex = undefined;
  ctx.pickRun("r1");
  out.wideOpen = doc.activeElement === root;
  run("picked_run = 'job:j1'");
  back.onclick();
  out.back = [named(doc.activeElement), doc.activeElement === rows.children[0]];
}

if (scenario === "tick") {  // the live feed redraws a job's actions: the one in use is found again by its key
  const con = page();
  run(fn(activity, "renderConsole"));
  Object.assign(ctx, { $: () => con, drawConsole: () => con.replaceChildren(...["open", "pause", "stop"].map((k) => ctx.el("button", { textContent: k, dataset: { fk: k } }))) });
  ctx.drawConsole();
  con.children[1].focus();
  ctx.renderConsole(true);
  out.pause = [named(doc.activeElement), doc.activeElement === con.children[1]];
  ctx.renderConsole(true);
  out.again = named(doc.activeElement);
}

if (scenario === "month") {
  const grid = page(), dayBox = make("div");
  Object.assign(ctx, { Date, Map, Math, Intl, cal: null, $: (sel) => sel === "#cal-grid" ? grid : dayBox, renderRange() {}, inScope: () => true, LOCALE: "en-GB",
    COUNT: { episode: (n) => `${n} episodes` }, time: () => "", day: () => "", schedCard: () => make("article"), syncDetails() {}, SCROLL: "auto" });
  run(["startOfDay", "addDays", "isoDay", "weekStartOf", "monthStartOf", "dayOfKey", "whenOf", "byWhen"].map((n) => line(schedule, n)).join("\n") + "\n"
    + line(schedule, "cal").replace("const ", "var ") + "\n" + fn(schedule, "pickDay") + "\n" + fn(schedule, "renderMonth"));
  run("cal.month = new Date(2026, 10, 1); cal.byDay = new Map(); cal.pick = null");
  ctx.renderMonth();
  const cells = () => grid.children.filter((c) => c.tag === "button");
  out.before = cells().filter((c) => c.ariaPressed === "true").length;
  cells()[10].focus();
  cells()[10].onclick();
  const now = cells();
  out.after = [doc.activeElement === now[10], now.filter((c) => c.ariaPressed === "true").length, now[10].ariaPressed];
}

if (scenario === "open-series") {  // "Open the series" in the popover: the card's own button is the opener
  const trigger = make("button", { closest: () => ({ getBoundingClientRect: () => ({ left: 100, right: 268, top: 300 }) }) });
  const pop = make("div", { offsetWidth: 380, scrollHeight: 300, style: {}, hidden: true }), dlg = make("dialog", { open: false, close() { this.open = false; } });
  root.append(trigger, pop, dlg);
  const opened = [];
  Object.assign(ctx, { Date, Math, innerWidth: 1280, innerHeight: 800, phoneLayout: () => false, S: { series: [{ tvdbId: 1 }] }, shellQuote: String,
    $: (sel) => sel === "#sched-pop" ? pop : dlg, openDrawer: () => opened.push(doc.activeElement === trigger ? "card" : doc.activeElement === root ? "body" : "other") });
  run(line(schedule, "det") + "\n" + ["detailsPlan", "detailsNode", "popoverPlace", "placeDetails", "openDetails", "closeDetails"].map((n) => fn(schedule, n)).join("\n"));
  ctx.openDetails(trigger, { tvdbId: 1, series: "Show", sxxeyy: "S01E01", managed: false }, "k");
  const button = find(pop, (n) => n.textContent === "Open the series");
  button.focus();
  button.onclick();
  out.openedFrom = opened;
}
console.log(JSON.stringify(out));
"""


def run_scenario(scenario: str) -> dict:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    done = subprocess.run(["node", "-e", HARNESS, "--", str(JS), scenario], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_redraw_gives_the_focus_back_to_the_same_control():
    assert run_scenario("helper") == {
        "byKey": "b",
        "byPlace": ["y", True],
        "clamped": "y",
        "untouched": [True, 1],
        "moved": [True, 2],
        "outside": [True, True, 0],
        "visibleCopy": True,
        "gone": True,
        "caret": [True, [3, 3, "none"]],
        "range": [True, [2, 5, "backward"]],
        "heading": [True, -1],
    }


def test_a_device_keeps_the_focus_when_a_test_result_reorders_the_devices():
    assert run_scenario("cdm") == {
        "before": ["alpha", "bravo"],
        "menu": [["bravo", "alpha"], "Actions for alpha", True],
        "row": [["alpha", "bravo"], "row:Widevine:alpha"],
    }


def test_a_chip_keeps_the_focus_when_the_chips_are_rebuilt():
    assert run_scenario("chips") == {"after": [True, ["false", "true", "false"]]}


def test_escape_closes_the_language_menu_and_returns_to_its_button():
    assert run_scenario("lang") == {
        "otherKey": [False, True],
        "escaped": [True, True, "false"],
        "idle": True,
    }


def test_a_phone_section_opens_on_its_heading_and_back_returns_to_its_item():
    assert run_scenario("settings") == {"opened": [True, -1, False], "back": [True, True], "wide": True}


def test_a_phone_download_opens_on_its_heading_and_back_returns_to_its_row():
    assert run_scenario("activity") == {"phoneOpen": [True, -1], "wideOpen": True, "back": ["row:job:j1", True]}


def test_the_live_tick_keeps_the_focus_on_the_control_in_use():
    assert run_scenario("tick") == {"pause": ["pause", True], "again": "pause"}


def test_a_picked_month_day_keeps_the_focus_and_says_it_is_pressed():
    assert run_scenario("month") == {"before": 0, "after": [True, 1, "true"]}


def test_the_series_opened_from_a_popover_returns_to_its_card():
    assert run_scenario("open-series") == {"openedFrom": ["card"]}
