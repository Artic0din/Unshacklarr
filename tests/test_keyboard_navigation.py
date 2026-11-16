"""Escape, focus return and page titles: the page's own functions run in Node with only the globals they reach named."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
JS = STATIC / "js"

PRELUDE = r"""
const fs = require("fs"), vm = require("vm");
const read = (file) => fs.readFileSync(file, "utf8");
const any = new Proxy(function () {}, { get: (_, k) => (k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : any), apply: () => any, construct: () => any, set: () => true });
function sandbox(named = {}) {
  return vm.createContext(new Proxy({ ...named }, { has: () => true, get: (t, k) => (k in t ? t[k] : k in globalThis ? globalThis[k] : any), set: (t, k, v) => ((t[k] = v), true) }));
}
const grab = (src, re) => { const m = src.match(re); if (!m) throw Error(`not in the source: ${re}`); return m[0]; };
"""


def node(body, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PRELUDE + body, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_escape_with_unsaved_changes_opens_the_question_and_keeps_it_open():
    shown = node(r"""
const src = read(process.argv[1]);
let handler = null, closed = 0, prevented = 0, drawerOpen = true, dialogOpen = false;
const ctx = sandbox({
  document: { addEventListener: (type, fn) => { if (type === "keydown") handler = fn; }, querySelector: (sel) => (sel === "dialog[open]" && dialogOpen ? {} : null) },
  $: () => ({ classList: { contains: () => drawerOpen } }),
  closeDrawer: () => { closed++; },
});
vm.runInContext(grab(src, /document\.addEventListener\("keydown", \(e\) => \{  \/\/ a dialog's Escape[\s\S]*?\n\}\);/), ctx);
const press = (key) => { prevented = closed = 0; handler({ key, preventDefault: () => { prevented++; } }); return [closed, prevented]; };
const out = { escape: press("Escape"), other: press("a") };
dialogOpen = true; out.insideDialog = press("Escape");
dialogOpen = false; drawerOpen = false; out.drawerShut = press("Escape");
console.log(JSON.stringify(out));
""", str(JS / "series.js"))
    # the Escape that opens the question must not also cancel it: the browser's own handling is stopped
    assert shown == {"escape": [1, 1], "other": [0, 0], "insideDialog": [0, 0], "drawerShut": [1, 0]}


def test_closing_a_series_opened_from_a_schedule_card_returns_to_that_card_after_a_redraw():
    shown = node(r"""
const src = read(process.argv[1]);
const focused = [];
const seen = { isConnected: true, getClientRects: () => [{}] };
const button = (name) => ({ ...seen, focus: () => focused.push(name) });
const newCard = { dataset: { key: "false|7|S01E04" }, querySelector: () => button("card") };
const otherCard = { dataset: { key: "false|7|S01E05" }, querySelector: () => button("other card") };
const goneOpener = { isConnected: false, getClientRects: () => [{}], focus: () => focused.push("opener") };
const ctx = sandbox({ document: {
  querySelectorAll: (sel) => (sel === ".sched-card" ? [otherCard, newCard] : []),
  querySelector: (sel) => (sel === 'nav [aria-current="page"]' ? button("tab") : null) } });
vm.runInContext(grab(src, /^function returnFocus\(.*?^\}/ms), ctx);
const back = (...args) => { focused.length = 0; ctx.returnFocus(...args); return focused[0]; };
console.log(JSON.stringify({ byKey: back(goneOpener, 7, "false|7|S01E04"), noKey: back(goneOpener, 7), unknownKey: back(goneOpener, 7, "true|7|S01E04") }));
""", str(JS / "core.js"))
    assert shown == {"byKey": "card", "noKey": "tab", "unknownKey": "tab"}


def test_a_series_opened_from_a_card_remembers_which_card():
    core = (JS / "core.js").read_text()
    assert 'drawerOpener?.closest(".sched-card")?.dataset.key' in core
    assert "returnFocus(drawerOpener, id, drawerOpenerCard)" in core


def test_the_tab_title_names_the_page_a_series_or_a_settings_section_in_the_pages_language():
    shown = node(r"""
const src = read(process.argv[1]);
const seen = [];
const doc = { title: "Unshacklarr", body: { classList: { contains: () => doc.gated } } };
const ctx = sandbox({
  document: doc, tr: (text) => { seen.push(text); return text; },
  currentTab: "schedule", current: null, settingsList: false, settingsSec: "sonarr",
  $: (sel) => ({ textContent: sel.includes('"sonarr"') ? "Sonarr" : "Services" }),
});
vm.runInContext(grab(src, /^const PAGE_NAME = .*$/m) + "\n" + grab(src, /^function updateTitle\(\) \{.*?^\}/ms), ctx);
const titleFor = (set) => { Object.assign(ctx, set); ctx.updateTitle(); return doc.title; };
const out = {};
for (const tab of ["schedule", "series", "log", "yaml"]) out[tab] = titleFor({ currentTab: tab });
out.settingsList = titleFor({ currentTab: "settings", settingsList: true });
out.section = titleFor({ currentTab: "settings", settingsList: false });
out.aSeries = titleFor({ currentTab: "schedule", current: { title: "Abbott Elementary" } });
doc.gated = true; doc.title = "Welcome";
out.gated = titleFor({ current: null });
out.asked = seen.slice(-3);
console.log(JSON.stringify(out));
""", str(JS / "navigation.js"))
    assert shown == {
        "schedule": "Schedule · Unshacklarr", "series": "Series · Unshacklarr", "log": "Activity · Unshacklarr",
        "yaml": "unshackle.yaml · Unshacklarr", "settingsList": "Settings · Unshacklarr",
        "section": "Settings: Sonarr · Unshacklarr", "aSeries": "Abbott Elementary · Unshacklarr",
        "gated": "Welcome", "asked": ["Settings · Unshacklarr", "Settings: Sonarr · Unshacklarr", "Abbott Elementary · Unshacklarr"],
    }


def test_every_route_change_updates_the_title():
    nav, core = (JS / "navigation.js").read_text(), (JS / "core.js").read_text()
    assert len(re.findall(r"\bupdateTitle\(\)", nav)) >= 5  # the tab, a section, back to the list, the route, itself
    assert core.count("updateTitle();") == 2  # a series opened, a series closed
    assert "document.title" in (JS / "setup.js").read_text()  # each setup step


def test_the_find_on_a_service_button_says_whether_its_results_are_shown_and_how_many():
    shown = node(r"""
const src = read(process.argv[1]);
const nodes = {};
const make = (id) => (nodes[id] ??= { id, hidden: true, textContent: "", attrs: {}, value: "Show", children: [],
  setAttribute(k, v) { this.attrs[k] = v; }, replaceChildren(...k) { this.children = k; }, dispatchEvent() {} });
const ctx = sandbox({
  $: (sel) => make(sel.slice(1)), S: { config: { series: { 5: { service: "HULU" } } } }, current: { tvdbId: 5, title: "Show" },
  svcName: (t) => t, loading: (t) => t, toast() {}, el: (tag, props, ...kids) => ({ tag, ...props, kids }),
  api: async () => ({ results: [{ title: "A", url: "u1" }, { title: "B", url: "u2" }] }),
});
vm.runInContext(grab(src, /^function showFind\(.*?^\}/ms) + "\n" + grab(src, /\$\("#d-find-go"\)\.onclick = async \(\) => \{.*?^\};/ms), ctx);
(async () => {
  const out = {};
  ctx.showFind(true); out.open = [nodes["d-find"].hidden, nodes["d-find-open"].attrs["aria-expanded"]];
  ctx.showFind(false); out.shut = [nodes["d-find"].hidden, nodes["d-find-open"].attrs["aria-expanded"]];
  make("d-find-q").value = "Show";
  await nodes["d-find-go"].onclick();
  out.count = nodes["d-find-count"].textContent;
  console.log(JSON.stringify(out));
})();
""", str(JS / "core.js"))
    assert shown == {"open": [False, "true"], "shut": [True, "false"], "count": "Results on HULU: 2"}
    page = (STATIC / "index.html").read_text()
    assert re.search(r'<div class="sr-only" id="d-find-count" role="status">', page)
    assert re.search(r'id="d-find-open" type="button" aria-expanded="false" aria-controls="d-find"', page)


def test_the_yaml_editor_says_how_to_leave_it():
    page = (STATIC / "index.html").read_text()
    foot = re.search(r'<div class="uy-foot" id="uy-foot".*?</div>', page)
    assert foot and "Esc, then Tab, leaves the editor." in foot.group(0)
