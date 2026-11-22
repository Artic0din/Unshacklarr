import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from css_assets import load_css

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"


def node(script):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", script, "--", str(JS / "core.js")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_errors_and_toasts_with_an_action_stay_until_dismissed():
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const timers = [], list = [];
const node = () => ({ children: [], attrs: {}, className: "", removed: false,
  setAttribute(k, v) { this.attrs[k] = v; }, append(...c) { this.children.push(...c); }, remove() { this.removed = true; }, matches: () => false });
const ctx = { document: { createElement: node }, el: (tag, props) => ({ tag, ...props }), $: () => ({ append: (t) => list.push(t) }),
  onTop() {}, getSelection: () => ({ containsNode: () => false }), setTimeout: (fn) => { timers.push(fn); return 0; } };
vm.createContext(ctx);
vm.runInContext(src.match(/^function toast\(.*?^\}/ms)[0], ctx);
const out = {};
ctx.toast("Saved");
out.plainGoesByItself = timers.length === 1;
out.plainButtons = list[0].children.length;
ctx.toast("Could not save", true);
out.errorGoesByItself = timers.length > 1;
const error = list[1];
out.errorDismiss = error.children.map((c) => c.textContent);
error.children[0].onclick();
out.errorRemoved = error.removed;
let undone = false;
ctx.toast("Hidden", false, ["Undo", () => { undone = true; }]);
const choice = list[2];
out.choiceGoesByItself = timers.length > 2;
out.choiceButtons = choice.children.map((c) => c.textContent);
choice.children[0].onclick();
out.choiceUndone = undone && choice.removed;
console.log(JSON.stringify(out));
""")
    assert shown == {
        "plainGoesByItself": True, "plainButtons": 0,
        "errorGoesByItself": False, "errorDismiss": ["Dismiss"], "errorRemoved": True,
        "choiceGoesByItself": False, "choiceButtons": ["Undo", "Dismiss"], "choiceUndone": True,
    }


def test_the_drawer_makes_the_page_inert_and_gives_focus_back():
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const drawer = { inert: true }, header = { inert: false }, main = { inert: false };
const focused = [];
let posterShown = true;
const poster = { name: "poster", isConnected: true, getClientRects: () => posterShown ? [{}] : [], focus: () => focused.push("poster") };
const tab = { focus: () => focused.push("tab") };
const opener = (over) => ({ name: "opener", isConnected: true, getClientRects: () => [{}], focus: () => focused.push("opener"), ...over });
const toasts = { matches: () => false };
drawer.append = (n) => { toasts.parent = "drawer"; };
const ctx = { onTop() {}, $: (sel) => sel === "#toasts" ? toasts : drawer, document: { body: { append: () => { toasts.parent = "body"; } },
  querySelectorAll: (s) => s === '[data-tvdb="7"]' ? [poster] : [header, main],
  querySelector: (s) => s === 'nav [aria-current="page"]' ? tab : null } };
vm.createContext(ctx);
vm.runInContext(src.match(/^function drawerModal\(.*?^\}/ms)[0] + src.match(/^function returnFocus\(.*?^\}/ms)[0], ctx);
const out = {};
ctx.drawerModal(true);
out.open = [drawer.inert, header.inert, main.inert, toasts.parent];
ctx.drawerModal(false);
out.closed = [drawer.inert, header.inert, main.inert, toasts.parent];
const where = (o) => { focused.length = 0; ctx.returnFocus(o, 7); return focused[0]; };
out.back = where(opener());
out.gone = where(opener({ isConnected: false }));
out.hidden = where(opener({ getClientRects: () => [] }));
out.none = where(null);
posterShown = false;  // opened from Schedule, its row redrawn, the Series page hidden: the current page's tab
out.nothingInSight = where(opener({ isConnected: false }));
console.log(JSON.stringify(out));
""")
    assert shown == {
        "open": [False, True, True, "drawer"], "closed": [True, False, False, "body"],
        "back": "opener", "gone": "poster", "hidden": "poster", "none": "poster", "nothingInSight": "tab",
    }


def test_focus_outside_the_open_drawer_goes_back_to_a_control_in_sight():
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const focused = [];
const ctl = (name, over = {}) => ({ name, isConnected: true, disabled: false, getClientRects: () => [{}], focus() { focused.push(name); }, closest: () => null, ...over });
const back = ctl("back", { getClientRects: () => [] });  // the phone's Back, hidden on a desktop
const close = ctl("close");
const inside = new Set([back, close]);
const drawer = { inert: false, classList: { contains: (c) => c === "open" }, contains: (x) => inside.has(x), querySelectorAll: () => [back, close] };
const ctx = { $: () => drawer, document: { addEventListener() {} } };
vm.createContext(ctx);
vm.runInContext("let drawerLastFocus = null;\n" + src.match(/^function drawerFocusGuard\(.*?^\}/ms)[0], ctx);
const out = {};
const checkbox = ctl("checkbox");
inside.add(checkbox);
ctx.drawerFocusGuard({ target: checkbox });      // focus moves inside: remembered
inside.delete(checkbox); checkbox.isConnected = false;  // the episode list redraws it away
const toast = ctl("dismiss");
ctx.drawerFocusGuard({ target: toast });
out.redrawn = focused.splice(0);
const kept = ctl("kept"); inside.add(kept);
ctx.drawerFocusGuard({ target: kept });
ctx.drawerFocusGuard({ target: toast });
out.remembered = focused.splice(0);
ctx.drawerFocusGuard({ target: ctl("dialog button", { closest: () => ({}) }) });
out.dialog = focused.splice(0);
console.log(JSON.stringify(out));
""")
    assert shown == {"redrawn": ["close"], "remembered": ["kept"], "dialog": []}


def test_a_series_uses_a_service_through_its_own_or_a_seasons_page():
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src.match(/^const usesService = .*$/m)[0] + "; this.usesService = usesService;", ctx);
const seasonOnly = { service: "BINGE", season_pages: { 2: { url: "u", service: "STAN" } } };
console.log(JSON.stringify([ctx.usesService(seasonOnly, "BINGE"), ctx.usesService(seasonOnly, "STAN"), ctx.usesService(seasonOnly, "NF"), ctx.usesService(undefined, "NF")]));
""")
    assert shown == [True, True, False, False]


def test_a_service_row_link_reaches_the_backend_that_downloads_it():
    shown = node(r"""
const fs = require("fs"), vm = require("vm"), path = require("path");
const src = fs.readFileSync(path.join(path.dirname(process.argv[1]), "services.js"), "utf8");
const row = (id) => ({ id });
const rows = { "sv-HULU": row("sv-HULU"), "sv-HULU@vpn": row("sv-HULU@vpn"), "sv-NF": row("sv-NF") };
rows["sv-STAN@nas"] = row("sv-STAN@nas");  // a service only on another server, no backend set for it
const ctx = { CSS: { escape: (x) => x }, S: { config: { service_defaults: { HULU: { backend: "vpn" } } } },
  document: { getElementById: (id) => rows[id] || null, querySelector: (sel) => Object.values(rows).find((r) => sel.includes('^="') && r.id.startsWith(sel.split('^="')[1].split('"')[0])) || null } };
vm.createContext(ctx);
vm.runInContext(src.match(/^function serviceRow\(.*?^\}/ms)[0], ctx);
console.log(JSON.stringify(["HULU", "NF", "STAN"].map((service) => ctx.serviceRow({ service }).id)));
""")
    assert shown == ["sv-HULU@vpn", "sv-NF", "sv-STAN@nas"]


def test_an_icon_that_alone_carries_a_meaning_is_named():
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const svg = () => ({ attrs: { "aria-hidden": "true" }, setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; } });
const ctx = { document: { createElement: () => ({ set innerHTML(_) { this.content = { firstChild: svg() }; } }) } };
vm.createContext(ctx);
vm.runInContext(src.match(/^const ICON_PATHS = \{.*?^\};/ms)[0] + src.match(/^function icon\(.*?^\}/ms)[0], ctx);
console.log(JSON.stringify({ plain: ctx.icon("check", "inl").attrs, named: ctx.icon("check", "inl", "Delivered").attrs }));
""")
    assert shown == {"plain": {"aria-hidden": "true"}, "named": {"role": "img", "aria-label": "Delivered"}}


def test_no_name_in_the_page_hides_the_icon_helper():
    import re
    shadow = re.compile(r"[(,]\s*icon\s*[=,)]|\b(?:const|let|var)\s+icon\b|,\s*icon\s*=|\bicon\.\w+\s*=[^=]")
    found = [f"{path.name}:{n}" for path in JS.glob("*.js")
             for n, line in enumerate(path.read_text().splitlines(), 1) if shadow.search(line)]
    assert not found  # a parameter or variable named icon makes icon() "not a function" in its scope


def test_translations_add_no_glyph_their_english_lacks():
    glyph = ("✓ ", "✗ ")
    extra = [f"{path.name}: {key}" for path in (JS.parent / "i18n").glob("*.json") if path.name != "en.json"
             for key, text in json.loads(path.read_text()).items()
             if isinstance(text, str) and text.startswith(glyph) and not key.startswith(glyph)]
    assert not extra  # the page draws the tick as an icon: a translated one would show two


def test_hover_styles_apply_only_where_a_pointer_hovers():
    import re
    css = load_css()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    stack, start, sticky = [], 0, []
    for i, ch in enumerate(css):
        if ch == "{":
            stack.append(css[start:i].strip()); start = i + 1
        elif ch in "};":
            if ch == "}" and stack:
                stack.pop()
            start = i + 1
        if ch == "{" and ":hover" in stack[-1] and not any("hover: hover" in a for a in stack[:-1]):
            sticky.append(stack[-1])
    assert not sticky  # on a touch screen a :hover style sticks after the tap


def test_a_two_click_confirmation_is_taken_back_by_a_press_elsewhere():
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const target = () => { const l = {}; return { l, addEventListener(t, f) { (l[t] ||= []).push(f); }, removeEventListener(t, f) { l[t] = (l[t] || []).filter((x) => x !== f); },
  fire(t, e) { [...(l[t] || [])].forEach((f) => f({ type: t, ...e })); } }; };
const doc = target(), button = { ...target(), dataset: {}, textContent: "Delete", contains: (n) => n === button, closest: () => null };
const ctx = { document: doc, $: () => ({}) };
vm.createContext(ctx);
vm.runInContext(src.match(/^const sureSay.*?^function confirmClick\(.*?^\}/ms)[0], ctx);
const out = {};
ctx.confirmClick(button, "Delete RMCBFM.txt?");
out.asked = button.textContent;
doc.fire("pointerdown", { target: button });  // pressing the button again: still asking
out.onItself = button.textContent;
out.confirmed = ctx.confirmClick(button, "Delete RMCBFM.txt?");
ctx.confirmClick(button, "Delete RMCBFM.txt?");
doc.fire("pointerdown", { target: {} });  // a press anywhere else, no blur (Safari)
out.elsewhere = [button.textContent, button.dataset.sure ?? null, ctx.confirmClick(button, "Delete RMCBFM.txt?")];
console.log(JSON.stringify(out));
""")
    assert shown == {"asked": "Delete RMCBFM.txt?", "onItself": "Delete RMCBFM.txt?", "confirmed": True,
                     "elsewhere": ["Delete", None, False]}  # taken back: the next click only asks again


def test_per_service_clear_cache_requires_two_click_confirmation():
    shown = node(r"""
const fs = require("fs"), vm = require("vm"), path = require("path");
const core = fs.readFileSync(process.argv[1], "utf8");
const opts = fs.readFileSync(path.join(path.dirname(process.argv[1]), "settings-options.js"), "utf8");
const target = () => { const l = {}; return { l, addEventListener(t, f) { (l[t] ||= []).push(f); }, removeEventListener(t, f) { l[t] = (l[t] || []).filter((x) => x !== f); } }; };
const doc = target();
const calls = [], toasts = [];
let clearBtn = null;
const el = (tag, props = {}, ...kids) => {
  const n = { tag, dataset: {}, ...target(), ...props, kids, contains: (x) => x === n, closest: () => null, replaceChildren() {} };
  if (tag === "button" && props.textContent === "Clear cache") clearBtn = n;
  return n;
};
const ctx = {
  document: doc, el, $: () => ({ replaceChildren() {} }),
  S: { config: { settings: {}, service_defaults: { NF: { options: {}, service_options: {} } } }, services: ["NF"], dlOptions: [] },
  COUNT: { option: (n) => `${n} options` },
  svcName: (t) => t === "NF" ? "Netflix" : t,
  trWith: (template, label) => template.replace("{0}", label),
  optionsEditor() {}, ladderClash() {}, ladderNamed() {}, ladderChips() {}, field: () => ({}),
  loadServiceOptions: async () => [],
  renderCommands() {}, dirty() {}, toast: (m, err) => toasts.push([m, !!err]),
  api: async (url, o) => { calls.push([url, o?.method]); return { freed_bytes: 2048 }; },
  encodeURIComponent, Math, Object, Promise,
};
vm.createContext(ctx);
vm.runInContext(core.match(/^const sureSay.*?^function confirmClick\(.*?^\}/ms)[0], ctx);
vm.runInContext(opts.match(/^async function renderServiceDefaults\(\) \{.*?^\}/ms)[0], ctx);
(async () => {
  await ctx.renderServiceDefaults();
  await clearBtn.onclick({ target: clearBtn });
  const afterFirst = { calls: calls.length, label: clearBtn.textContent };
  await clearBtn.onclick({ target: clearBtn });
  const afterSecond = { calls, label: clearBtn.textContent, toasts };
  console.log(JSON.stringify({ afterFirst, afterSecond }));
})();
""")
    assert shown["afterFirst"]["calls"] == 0
    assert "Netflix" in shown["afterFirst"]["label"] and "?" in shown["afterFirst"]["label"]
    assert shown["afterSecond"]["calls"] == [["/api/unshackle/cache/NF/clear", "POST"]]
    assert shown["afterSecond"]["label"] == "Clear cache"


PAGE = JS.parent / "index.html"
I18N = JS.parent / "i18n"


def test_a_skip_link_comes_first_and_moves_the_focus_without_changing_the_route():
    page = PAGE.read_text(encoding="utf8")
    body = page[page.index("<body>"):]
    first = re.search(r"<(a|button|input|select|textarea)\b[^>]*>", body).group(0)
    assert first == '<a class="skip" href="#main">' and body.startswith('<body>\n<a class="skip" href="#main">Skip to content</a>')
    assert '<main id="main" tabindex="-1">' in page
    nav = (JS / "navigation.js").read_text(encoding="utf8")
    assert '$(".skip").onclick = (e) => { e.preventDefault(); $("main").focus(); };' in nav  # "#main" is not a route


def test_the_main_tabs_are_links_to_their_routes():
    page = PAGE.read_text(encoding="utf8")
    nav = page[page.index('<nav aria-label="Main">'):page.index("</nav>")]
    assert "<button" not in nav
    assert re.findall(r'<a href="(#/[\w.]+)" data-tab="(\w+)"', nav) == [
        ("#/schedule", "schedule"), ("#/series", "series"), ("#/activity", "log"), ("#/settings", "settings")]
    js = (JS / "navigation.js").read_text(encoding="utf8")
    assert 'querySelectorAll("nav button")' not in js
    assert "if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;" in js  # a new tab: the browser's


def test_a_series_poster_is_named_by_its_title_before_its_service():
    core = (JS / "core.js").read_text(encoding="utf8")
    card = core[core.index('const card = el("button", { className: "poster"'):]
    card = card[:card.index("card.dataset.tvdb")]
    assert card.index('className: "name"') < card.index("art);")
    art = core[core.index('const art = el("span", { className: "art" });'):core.index('const card = el("button", { className: "poster"')]
    assert art.index('className: "sick"') < art.index('className: "svc"')  # its state, then where it comes from


def test_the_unshackle_mode_is_a_radio_group_the_arrows_move_through():
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const grab = (name) => src.match(new RegExp(`^function ${name}\\(.*?^\\}`, "ms"))[0];
let handler = null, focused = null, value = "local";
const tile = (v) => ({ dataset: { value: v }, ariaChecked: null, tabIndex: 0, focus() { focused = v; }, click() { value = v; ctx.pickTile(group, v); } });
const tiles = [tile("local"), tile("remote")];
const group = { querySelectorAll: () => tiles, addEventListener: (type, fn) => { handler = fn; } };
const ctx = {};
vm.createContext(ctx);
vm.runInContext(grab("pickTile") + grab("arrowPicks"), ctx);
ctx.pickTile(group, "local");
const state = () => tiles.map((t) => [t.ariaChecked, t.tabIndex]);
const out = { start: state() };
ctx.arrowPicks(group);
const press = (key, target) => { let stopped = false; handler({ key, target, preventDefault() { stopped = true; } }); return stopped; };
out.right = [press("ArrowRight", tiles[0]), value, focused, state()];
out.wraps = [press("ArrowDown", tiles[1]), value];
out.other = press("Enter", tiles[0]);
console.log(JSON.stringify(out));
""")
    assert shown == {"start": [["true", 0], ["false", -1]],
                     "right": [True, "remote", "remote", [["false", -1], ["true", 0]]],
                     "wraps": [True, "local"], "other": False}
    page = PAGE.read_text(encoding="utf8")
    assert '<div class="wz-tiles ux-tiles" role="radiogroup" aria-label="Unshackle runs">' in page
    assert 'role: "radiogroup", ariaLabel: "Unshackle runs"' in (JS / "setup.js").read_text(encoding="utf8")


def test_activity_pane_titles_follow_the_page_heading_without_a_skip():
    for name in ["activity.js", "settings-services.js"]:
        assert 'className: "cd-head" }, el("div", {}, el("h3"' not in (JS / name).read_text(encoding="utf8"), name
    assert '<h2 id="cd-top-title"></h2>' in PAGE.read_text(encoding="utf8")


def test_every_language_translates_the_skip_link_and_the_light_states():
    texts = ["Skip to content", "{0}: running", "{0}: update available", "{0}: unreachable", "{0}: checking"]
    english = json.loads((I18N / "en.json").read_text(encoding="utf8"))
    for path in sorted(I18N.glob("*.json")):
        translated = json.loads(path.read_text(encoding="utf8"))
        for text in texts:
            assert text in english, text
            if path.name != "en.json":
                assert translated.get(text), f"{path.name}: {text!r}"
                assert ("{0}" in translated[text]) == ("{0}" in text), f"{path.name}: {text!r} placeholder"


def test_interface_audit_accessibility_guards():
    page = PAGE.read_text(encoding="utf8")
    core = (JS / "core.js").read_text(encoding="utf8")
    nav = (JS / "navigation.js").read_text(encoding="utf8")
    series = (JS / "series.js").read_text(encoding="utf8")
    css = load_css()
    assert '<div class="sr-only" id="wall-count" role="status"></div>' in page
    assert '$("#wall-count")' in core
    assert 'el("button", { type: "button", className: `${className} spoiler`' in core
    assert 'textContent: " (switched off)"' in core
    assert 'ariaDescribedBy' in series or 'aria-describedby' in series
    assert 'matches(":hover, :focus-within")' in core and ', 5000);' in core
    assert 'Settings › Connections › Unshackle' in core
    assert "confirm(" not in nav
    for bad in ("order: 10", "order: 5", "order: 1;"):
        assert bad not in css, bad
    assert not re.search(r"\.dock\.open > \.cd-raw[^{]*\{[^}]*order:", css)
    assert not re.search(r"\.modal-actions[^{]*\{[^}]*column-reverse", css)
    for name in ("quality.js", "setup.js", "settings-options.js"):
        assert "markInvalid(" in (JS / name).read_text(encoding="utf8"), name


def test_quality_height_validation_leaves_bitrate_valid_and_wall_count_announces_empty():
    shown = node(r"""
const fs = require("fs"), vm = require("vm"), path = require("path");
const core = fs.readFileSync(process.argv[1], "utf8");
const qual = fs.readFileSync(path.join(path.dirname(process.argv[1]), "quality.js"), "utf8");
const mk = (tag, props = {}, ...kids) => {
  const attrs = {}, cls = new Set((props.className || "").split(" ").filter(Boolean));
  return { tag, ...props, kids, attrs, dataset: props.dataset || {},
    classList: { toggle: (c, on) => on ? cls.add(c) : cls.delete(c), contains: (c) => cls.has(c) },
    setAttribute(k, v) { attrs[k] = String(v); }, getAttribute(k) { return attrs[k] ?? null; },
    removeAttribute(k) { delete attrs[k]; } };
};
const ctx = { el: mk, CODECS: [["", "Any"]], RANGES: [["", "Any"]], qlId: () => 1, dirty() {}, renderQuality() {}, qlFocus() {} };
vm.createContext(ctx);
vm.runInContext(core.match(/let messageIds = 0;[\s\S]*?^function markInvalid[\s\S]*?^\}/m)[0] + "\n" + qual.match(/^function stepRow\([\s\S]*?^\}/m)[0], ctx);
const st = { codec: "", range: "SDR", min: 720, max: 1080, max_kbps: 5000 };
const row = ctx.stepRow({ steps: [st] }, st, 0);
const inputs = [];
const walk = (n) => { if (n && typeof n === "object") { if (n.tag === "input") inputs.push(n); (n.kids || []).forEach(walk); } };
walk(row);
inputs[0].oninput({ target: { value: "2160" } });
const invalidAfterBad = inputs.map((i) => [i.ariaLabel, i.getAttribute("aria-invalid"), Boolean(i.getAttribute("aria-describedby"))]);
inputs[0].oninput({ target: { value: "720" } });
const invalidAfterFix = inputs.map((i) => [i.ariaLabel, i.getAttribute("aria-invalid"), Boolean(i.getAttribute("aria-describedby"))]);
console.log(JSON.stringify({ invalidAfterBad, invalidAfterFix }));
""")
    assert shown["invalidAfterBad"] == [
        ["Lowest height", "true", True],
        ["Highest height", "true", True],
        ["Highest bitrate, kbps", None, False],
    ]
    assert shown["invalidAfterFix"] == [
        ["Lowest height", None, False],
        ["Highest height", None, False],
        ["Highest bitrate, kbps", None, False],
    ]
    core_src = (JS / "core.js").read_text(encoding="utf8")
    assert 'if (wc) wc.textContent = cards.length ? (cards.length === 1 ? "1 series" : `${cards.length} series`) : emptyTitle;' in core_src


def test_leaving_dirty_yaml_editor_completes_navigation_after_confirmation():
    shown = node(r"""
const fs = require("fs"), vm = require("vm"), path = require("path");
const core = fs.readFileSync(process.argv[1], "utf8");
const nav = fs.readFileSync(path.join(path.dirname(process.argv[1]), "navigation.js"), "utf8");
const yaml = fs.readFileSync(path.join(path.dirname(process.argv[1]), "yaml-editor.js"), "utf8");
const attempts = fs.readFileSync(path.join(path.dirname(process.argv[1]), "attempts.js"), "utf8");

let docText = "a: 1\n", pendingSave = null, saveShouldFail = false;
let navTabs = [], sections = [], drawers = [], titleUpdates = [], destroyed = 0, modalThrows = 0;
const back = {};
const dialog = {
  open: false, returnValue: "", listeners: [],
  showModal() { if (this.open) { modalThrows++; throw new Error("already open"); } this.open = true; },
  close(val) {
    if (!this.open) return;
    this.open = false;
    this.returnValue = val ?? this.returnValue;
    // real HTML <dialog>.close() dispatches "close" asynchronously on a queued task
    setTimeout(() => { [...this.listeners].forEach((f) => f()); }, 0);
  },
  addEventListener(ev, fn) { if (ev === "close") this.listeners.push(fn); },
  removeEventListener(ev, fn) { if (ev === "close") this.listeners = this.listeners.filter((f) => f !== fn); },
};
const nodes = {
  "#uy-back": back, "#unsaved-dialog": dialog, "#unsaved-text": {},
  "#uy-save": { disabled: false }, "#uy-diff": { hidden: true }, "#uy-cm": { hidden: false },
  "#uy-auth": { hidden: true }, "#uy-editor": { hidden: false }, "#uy-tools": { hidden: false }, "#uy-foot": { hidden: false },
  "#uy-password": { value: "" }, "#uy-path": { textContent: "" }, "#uy-error": { textContent: "" }, "#uy-versions": { replaceChildren() {} },
  "#inbox-dialog": { open: false }, "#initial-state-error": { hidden: true },
};
const history = {
  state: null,
  pushState(s, _, h) { this.state = s; ctx.location.hash = h; navTabs.push([ctx.currentTab, true, h]); },
  replaceState(s, _, h) { this.state = s; ctx.location.hash = h; navTabs.push([ctx.currentTab, false, h]); },
};
const ctx = {
  currentTab: "yaml", routed: true, termSocket: null, landOnLive: false, current: null, settingsRoute: "connections", settingsTarget: null,
  S: { series: [{ tvdbId: 42, title: "Show" }] }, TAB_OF: { activity: "log", terminal: "log", defaults: "settings", "unshackle.yaml": "yaml" },
  HASH_OF: { log: "activity", yaml: "unshackle.yaml" },
  location: { hash: "#/unshackle.yaml" }, history,
  api: () => new Promise((resolve, reject) => {
    pendingSave = { resolve: () => saveShouldFail ? reject(new Error("fail")) : resolve({ base: "b2", saved: true, restart: false, versions: [] }) };
  }),
  toast() {}, uyVersions() {}, uyError() {},
  inSettingsSec: () => ctx.currentTab === "settings",
  settingsHref: (r) => `#/settings/${r}`,
  showSettingsSec: (sec) => sections.push([ctx.currentTab, sec]),
  openDrawer: (s, view) => drawers.push([ctx.currentTab, s.tvdbId, view]),
  showDrawerTab() {}, closeDrawer() {},
  showSettingsList() {}, closeDetails() {}, loadSettingsSec() {}, loadSchedule() {},
  updateTitle: () => titleUpdates.push(ctx.currentTab),
  syncInboxRoute: () => false, cancelSettingsJump() {}, syncActivityRoute() {}, openInbox() {},
  $: (sel) => nodes[sel] ?? { hidden: true, open: false },
  document: { querySelectorAll: () => [] },
};
vm.createContext(ctx);
vm.runInContext(
  core.match(/^let unsavedPending = null;[\s\S]*?^function askUnsaved\([\s\S]*?^\}/m)[0] + "\n"
  + yaml.match(/^const uy = [\s\S]*?^function uyReset\([\s\S]*?^\}/m)[0] + "\n"
  + yaml.match(/^async function uySave\([\s\S]*?^\}/m)[0] + "\n"
  + nav.match(/^function routeHash\([\s\S]*?^\}/m)[0] + "\n"
  + nav.match(/^function navigate\([\s\S]*?^\}/m)[0] + "\n"
  + nav.match(/^function parseRoute\([\s\S]*?^\}/m)[0] + "\n"
  + nav.match(/^function applyRoute\([\s\S]*?^\}/m)[0] + "\n"
  + nav.match(/^function showTab\([\s\S]*?^\}/m)[0] + "\n"
  + yaml.match(/^\$\("#uy-back"\)\.onclick = .*$/m)[0] + "\nthis.uy = uy; this.uyDirty = uyDirty;",
  ctx,
);
const tick = () => new Promise((r) => setTimeout(r, 10));
const resetState = async (hash = "#/unshackle.yaml") => {
  ctx.closeUnsaved();
  ctx.showTab.yamlPrompt = false;
  await tick();
  docText = "a: 2\n";
  Object.assign(ctx.uy, {
    password: "pw", base: "b1", original: "a: 1\n",
    view: { state: { doc: { toString: () => docText }, selection: {} }, dispatch() {}, destroy() { destroyed++; } },
  });
  ctx.currentTab = "yaml"; ctx.location.hash = hash;
  pendingSave = null; saveShouldFail = false;
  navTabs = []; sections = []; drawers = []; titleUpdates = []; destroyed = 0; modalThrows = 0;
};
(async () => {
  // 1. Cancel keeps yaml open, dirty, and restores route if hash pointed elsewhere
  await resetState("#/settings/notifications");
  ctx.showTab("series"); // fromRoute=false superseding leave
  dialog.close("keep"); await tick();
  const afterCancel = { tab: ctx.currentTab, dirty: ctx.uyDirty(), destroyed, hash: ctx.location.hash };

  // 2. Failed direct save with a displaced non-YAML URL keeps yaml open, dirty, and restores YAML hash
  await resetState("#/settings/notifications"); saveShouldFail = true;
  ctx.showTab("series"); dialog.close("save"); await tick(); pendingSave.resolve(); await tick();
  const afterFailedSave = { tab: ctx.currentTab, dirty: ctx.uyDirty(), destroyed, hash: ctx.location.hash };

  // 3. Edit typed while real uySave is in flight keeps yaml open with the new text
  await resetState();
  back.onclick(); dialog.close("save"); await tick();
  docText = "a: 3\n"; // edited while request is pending
  pendingSave.resolve(); await tick();
  const afterEditDuringSave = { tab: ctx.currentTab, dirty: ctx.uyDirty(), original: ctx.uy.original, text: docText, destroyed, hash: ctx.location.hash };

  // 4. Clean real uySave saves snapshot, resets editor, and updates route to settings
  await resetState();
  back.onclick(); dialog.close("save"); await tick(); pendingSave.resolve(); await tick();
  const afterSave = { tab: ctx.currentTab, dirty: ctx.uyDirty(), destroyed, hash: ctx.location.hash };

  // 5. Discard skips save, resets editor, and navigates to settings
  await resetState();
  back.onclick(); dialog.close("discard"); await tick();
  const afterDiscard = { tab: ctx.currentTab, dirty: ctx.uyDirty(), pendingSave: Boolean(pendingSave), destroyed, hash: ctx.location.hash };

  // 6. applyRoute deep link defers Settings section, destination drawer, AND title until confirmation resolves
  await resetState("#/settings/notifications/s/42/settings");
  ctx.applyRoute({ type: "popstate" });
  const whilePending = { tab: ctx.currentTab, dialogOpen: dialog.open, sections: [...sections], drawers: [...drawers], titleUpdates: [...titleUpdates] };
  dialog.close("discard"); await tick();
  const afterDeepLink = { tab: ctx.currentTab, dirty: ctx.uyDirty(), sections: [...sections], drawers: [...drawers], titleUpdates: [...titleUpdates] };

  // 7. History move back to YAML closes the stale YAML dialog, but leaves a drawer-owned dialog open
  await resetState("#/settings/notifications");
  ctx.applyRoute({ type: "popstate" });
  ctx.location.hash = "#/unshackle.yaml";
  ctx.applyRoute({ type: "popstate" });
  await tick();
  const afterStaleReturn = { tab: ctx.currentTab, dialogOpen: dialog.open, dirty: ctx.uyDirty(), destroyed, sections: [...sections], hash: ctx.location.hash };
  await resetState("#/unshackle.yaml");
  ctx.askUnsaved("Show"); // drawer-owned prompt (showTab.yamlPrompt is false)
  ctx.applyRoute({ type: "popstate" });
  const drawerPromptKept = dialog.open;

  // 8. Second non-YAML history move with async dialog close ignores stale close event and applies latest route
  await resetState("#/settings/notifications");
  ctx.applyRoute({ type: "popstate" });
  ctx.location.hash = "#/series";
  ctx.applyRoute({ type: "popstate" });
  await tick(); // let queued async close event from #1 fire while reopened dialog #2 is open
  const secondStillOpen = { dialogOpen: dialog.open, modalThrows, hashBeforeChoice: ctx.location.hash };
  dialog.close("discard"); await tick();
  const afterSecondRoute = { ...secondStillOpen, tab: ctx.currentTab, dirty: ctx.uyDirty(), sections: [...sections], hash: ctx.location.hash };

  // 9. Direct superseding showTab calls while dialog is open do not throw and latest choice wins
  await resetState();
  ctx.showTab("series");
  ctx.showTab("schedule");
  await tick();
  const directStillOpen = { dialogOpen: dialog.open, modalThrows };
  dialog.close("discard"); await tick();
  const afterDirectSupersede = { ...directStillOpen, tab: ctx.currentTab, dirty: ctx.uyDirty(), hash: ctx.location.hash };

  // 10. Returning to YAML while real uySave is pending aborts reset and navigation when save resolves
  await resetState("#/settings/notifications");
  ctx.applyRoute({ type: "popstate" });
  dialog.close("save"); await tick();
  ctx.location.hash = "#/unshackle.yaml";
  ctx.applyRoute({ type: "popstate" });
  pendingSave.resolve(); await tick();
  const afterReturnDuringSave = { tab: ctx.currentTab, destroyed, sections: [...sections], hash: ctx.location.hash };

  // 11. Clear history dialog distinguishes failed-only vs all finished downloads
  const cNodes = { "#hist-clear": {}, "#clear-text": {}, "#clear-failed": {}, "#clear-all": {}, "#clear-dialog": { showModal() {}, addEventListener() {} } };
  const aCtx = { $: (s) => cNodes[s], runCards: [{ outcome: "downloaded" }, { outcome: "failed" }, { outcome: "failed" }],
    isLive: () => false, COUNT: { download: (n) => `${n} downloads` }, toast() {} };
  vm.createContext(aCtx);
  vm.runInContext(attempts.match(/^\$\("#hist-clear"\)\.onclick = [\s\S]*?^\};/m)[0], aCtx);
  cNodes["#hist-clear"].onclick();
  const clearCopy = { text: cNodes["#clear-text"].textContent, failed: cNodes["#clear-failed"].textContent, all: cNodes["#clear-all"].textContent };

  console.log(JSON.stringify({
    afterCancel, afterFailedSave, afterEditDuringSave, afterSave, afterDiscard,
    whilePending, afterDeepLink, afterStaleReturn, drawerPromptKept, afterSecondRoute, afterDirectSupersede, afterReturnDuringSave, clearCopy,
  }));
})();
""")
    assert shown["afterCancel"] == {"tab": "yaml", "dirty": True, "destroyed": 0, "hash": "#/unshackle.yaml"}
    assert shown["afterFailedSave"] == {"tab": "yaml", "dirty": True, "destroyed": 0, "hash": "#/unshackle.yaml"}
    assert shown["afterEditDuringSave"] == {"tab": "yaml", "dirty": True, "original": "a: 2\n", "text": "a: 3\n", "destroyed": 0, "hash": "#/unshackle.yaml"}
    assert shown["afterSave"] == {"tab": "settings", "dirty": False, "destroyed": 1, "hash": "#/settings/connections"}
    assert shown["afterDiscard"] == {"tab": "settings", "dirty": False, "pendingSave": False, "destroyed": 1, "hash": "#/settings/connections"}
    assert shown["whilePending"] == {"tab": "yaml", "dialogOpen": True, "sections": [], "drawers": [], "titleUpdates": []}
    assert shown["afterDeepLink"] == {"tab": "settings", "dirty": False, "sections": [["settings", "notifications"]], "drawers": [["settings", 42, "settings"]], "titleUpdates": ["settings", "settings"]}
    assert shown["afterStaleReturn"] == {"tab": "yaml", "dialogOpen": False, "dirty": True, "destroyed": 0, "sections": [], "hash": "#/unshackle.yaml"}
    assert shown["drawerPromptKept"] is True
    assert shown["afterSecondRoute"] == {"dialogOpen": True, "modalThrows": 0, "hashBeforeChoice": "#/series", "tab": "series", "dirty": False, "sections": [], "hash": "#/series"}
    assert shown["afterDirectSupersede"] == {"dialogOpen": True, "modalThrows": 0, "tab": "schedule", "dirty": False, "hash": "#/schedule"}
    assert shown["afterReturnDuringSave"] == {"tab": "yaml", "destroyed": 0, "sections": [], "hash": "#/unshackle.yaml"}
    assert "Clear 2 failed" in shown["clearCopy"]["text"] and "only failed" in shown["clearCopy"]["text"]
    assert "Clear 3 downloads" in shown["clearCopy"]["text"] and "all finished downloads" in shown["clearCopy"]["text"]
