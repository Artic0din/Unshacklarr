"""Gaps in the flows of Activity and the first-run setup (#280); each script runs the page's own code in Node."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from css_assets import load_css
from test_error_feedback import WIZARD
from test_error_feedback import node as wizard_node

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
JS = STATIC / "js"
CSS = re.sub(r"/\*.*?\*/", "", load_css(), flags=re.S)

PRELUDE = r"""
const fs = require("fs"), vm = require("vm");
const read = (file) => fs.readFileSync(file, "utf8");
const any = new Proxy(function () {}, { get: (_, k) => (k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : any), apply: () => any, construct: () => any, set: () => true });
const el = (tag, props = {}, ...kids) => ({ tag, ...props, kids });
function sandbox(named = {}) {
  const own = { el, ...named };
  return vm.createContext(new Proxy(own, { has: () => true, get: (t, k) => (k in t ? t[k] : k in globalThis ? globalThis[k] : any), set: (t, k, v) => ((t[k] = v), true) }));
}
const grab = (src, re) => { const m = src.match(re); if (!m) throw Error(`not in the source: ${re}`); return m[0]; };
const walk = (n, f) => { if (n && typeof n === "object") { f(n); (n.kids || []).forEach((k) => walk(k, f)); } };
const find = (n, test) => { let hit = null; walk(n, (x) => { if (!hit && test(x)) hit = x; }); return hit; };
"""


def node(body, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PRELUDE + body, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


SETTINGS_NAV = r"""
const listeners = {}, location = { hash: "#/settings/cdm" };
const window = { scrollY: 0, addEventListener: (name, fn) => { listeners[name] = fn; } };
function element() {
  const listeners = {};
  return {
    listeners, classList: { contains: () => false, toggle() {} }, setAttribute() {},
    addEventListener: (name, fn) => { listeners[name] = fn; },
  };
}
const body = element(), settingsTab = element(), settingsBack = element();
let cdmTop = 400, focused, finishServices, finishCdm, sectionResized, accountLoads = 0, keyPrompt = false, backCalls = 0;
let translating = process.argv[2] === "translated", finishTranslation;
const i18nReady = new Promise((resolve) => { finishTranslation = resolve; });
const frames = [];
const flushFrames = () => frames.splice(0).forEach((fn) => fn());
const heading = { id: "cdm-heading", getClientRects: () => [{}], closest: () => null };
const section = {};
const connectionsHeading = { id: "connections-heading" };
const hiddenLabel = { getClientRects: () => [], closest: () => null };
const visibleLabel = { getClientRects: () => [{}], closest: () => null };
const listItem = { focus: () => { focused = listItem; } };
const row = { id: "sv-HULU", closest: () => section, querySelectorAll: () => [], getClientRects: () => [{}],
  scrollIntoView: () => { window.scrollY = 1000; }, focus: () => { focused = row; } };
const servicesAnchor = { ...row, closest: (selector) => selector === ".set-sec" ? section : null,
  querySelectorAll: () => [], scrollIntoView: () => { window.scrollY = 400; } };
const notificationsHeading = { id: "notifications-heading", getClientRects: () => [{}], closest: () => null };
const audioTarget = {
  closest: (selector) => selector === ".set-sec" ? section : null,
  scrollIntoView: () => { window.scrollY = 500; },
  querySelector: () => hiddenLabel,
  querySelectorAll: () => process.argv[2] === "visible-label" ? [hiddenLabel, visibleLabel] : [hiddenLabel],
};
const anchors = {
  "services-sec": servicesAnchor, "sv-HULU": row,
  "unshackle-sec": { ...servicesAnchor, closest: () => null },
  "notifications-sec": { ...servicesAnchor, closest: () => null, querySelectorAll: () => [notificationsHeading] },
  "cdm-sec": {
    closest: (selector) => selector === ".set-sec" ? section : null,
    querySelector: () => heading, querySelectorAll: () => [heading],
    scrollIntoView: () => { window.scrollY = cdmTop; },
  },
  "region-sec": { closest: () => null, querySelector: () => null, querySelectorAll: () => [], scrollIntoView() {} },
  "account-sec": { closest: () => null, querySelector: () => heading, querySelectorAll: () => [heading],
    scrollIntoView: () => { window.scrollY = 1938; } },
};
const entries = [{ hash: location.hash, state: null }];
let index = 0;
const history = {
  get state() { return entries[index].state; },
  replaceState(state, _, hash = location.hash) { entries[index] = { state, hash }; location.hash = hash; },
  pushState(state, _, hash) { entries.splice(++index, Infinity, { state, hash }); location.hash = hash; },
  back() { backCalls++; traverse(-1); },
  forward() { traverse(1); },
};
function traverse(delta) {
  if (!entries[index + delta]) return;
  index += delta;
  location.hash = entries[index].hash;
  listeners.popstate({ state: history.state });
  flushFrames();
}
const ctx = sandbox({
  $, window, location, current: null, S: { config: {} }, termSocket: null, i18nReady,
  syncInboxRoute: () => false,
  requestAnimationFrame: (fn) => frames.push(fn),
  phoneLayout: () => true,
  ResizeObserver: class {
    constructor(callback) { this.callback = callback; }
    observe(node) { if (node === section) sectionResized = this.callback; }
    disconnect() { if (sectionResized === this.callback) sectionResized = null; }
  },
  document: { querySelector: (selector) => selector === ".up-mode" ? audioTarget : selector.startsWith(".set-nav ") ? listItem : anchors[selector.slice(1)],
    querySelectorAll: () => [], body, getElementById: (id) => anchors[id],
    get activeElement() { return focused || body; },
    documentElement: { classList: { contains: (name) => name === "i18n-wait" && translating } } },
  history,
  focusHeading: (node) => { if (node && !translating) focused = node; },
  loadServices: () => new Promise((resolve) => {
    finishServices = resolve;
  }),
  loadCdm: () => new Promise((resolve) => { finishCdm = resolve; }),
  loadAccount: () => { accountLoads++; keyPrompt = false; },
  scrollTo: ({ top }) => { window.scrollY = top; },
});
function $(selector) {
  if (selector === '.set-sec[data-sec="connections"] h2') return connectionsHeading;
  if (selector === '.set-sec[data-sec="notifications"] h2') return notificationsHeading;
  if (selector === "#tab-settings") return settingsTab;
  if (selector === "#set-back") return settingsBack;
  return element();
}
const source = read(process.argv[1]);
vm.runInContext(source.slice(0, source.indexOf('showTab(parseRoute().tab')) +
  grab(source, /^showTab\(parseRoute\(\).tab.*\nif \(parseRoute\(\).sec\).*\nelse if .*$/m), ctx);
const enter = (hash) => { history.replaceState(null, "", hash); ctx.applyRoute(); };
const jump = (hash) => settingsTab.listeners.click({ preventDefault() {}, target: { closest: () => ({ hash }) } });
const services = () => {
  const src = read(process.argv[2]);
  Object.assign(ctx, { CSS: { escape: (value) => value }, renderServices: () => ctx.revealService() });
  vm.runInContext(["serviceRow", "revealService", "openServiceRow"].map((name) =>
    grab(src, new RegExp(`^(async )?function ${name}\\b[\\s\\S]*?\\n}\\n`, "m"))).join("\n"), ctx);
};
"""


@pytest.mark.parametrize("interruption", [
    "none", "layout", "startup-scroll", "wheel", "touchmove", "keydown", "tab", "pointerdown", "route",
])
def test_delayed_services_keep_the_cdm_heading_in_view_only_if_the_jump_is_still_active(interruption):
    seen = node(SETTINGS_NAV + r"""
(async () => {
  const before = cdmTop - window.scrollY;
  const focusedCdm = focused === heading;
  if (process.argv[2] === "startup-scroll") {
    window.scrollY += 120;
    listeners.scroll?.();
  }
  const beforeState = window.scrollY;
  ctx.S.config.settings = {};
  ctx.applyRoute();
  const movedOnState = window.scrollY !== beforeState;
  const notifyResize = sectionResized;
  const interruption = process.argv[2];
  if (["wheel", "touchmove", "keydown", "tab", "pointerdown"].includes(interruption)) {
    const event = interruption === "tab" ? "keydown" : interruption;
    listeners[event]?.({ isTrusted: true, key: interruption === "tab" ? "Tab" : "PageDown" });
    window.scrollY += 120;
    listeners.scroll?.();
  }
  if (process.argv[2] === "layout") {
    cdmTop += 35;
    window.scrollY += 35;
    listeners.scroll?.();
  }
  if (process.argv[2] === "route") enter("#/schedule");
  const scrollBeforeRender = window.scrollY;
  cdmTop += 6000; // A health refresh can render the rows before the section's loader finishes.
  notifyResize?.();
  const topWhileLoading = cdmTop - window.scrollY;
  finishServices();
  finishCdm();
  await new Promise(setImmediate);
  const top = cdmTop - window.scrollY, moved = window.scrollY !== scrollBeforeRender;
  cdmTop += 250;
  notifyResize?.();
  console.log(JSON.stringify({ before, focusedCdm, movedOnState, topWhileLoading, top, moved,
    shiftAfterLoading: cdmTop - window.scrollY - top }));
})();
""", str(JS / "navigation.js"), interruption)
    assert seen["before"] == 0
    assert seen["focusedCdm"]
    assert not seen["movedOnState"]
    assert seen["shiftAfterLoading"] == 250
    if interruption in ("none", "layout", "startup-scroll"):
        assert seen["topWhileLoading"] == 0
        assert seen["top"] == 0
    else:
        assert not seen["moved"]


def test_settings_route_focuses_a_new_section_and_preserves_position_on_restore():
    seen = node(SETTINGS_NAV + r"""
enter("#/settings/account");
const accountScroll = window.scrollY;
enter("#/settings/connections");
const opened = { scroll: window.scrollY, focused: focused === connectionsHeading };
window.scrollY = 300;
ctx.applyRoute();
console.log(JSON.stringify({ accountScroll, opened, restored: window.scrollY }));
""", str(JS / "navigation.js"))
    assert seen == {"accountScroll": 1938, "opened": {"scroll": 0, "focused": True}, "restored": 300}


def test_service_row_jump_takes_priority_while_settings_loads():
    seen = node(SETTINGS_NAV + r"""
(async () => {
  services();
  enter("#/schedule");
  ctx.S.config.settings = {};
  await ctx.openServiceRow("HULU");
  sectionResized?.();
  finishServices();
  finishCdm();
  await new Promise(setImmediate);
  console.log(JSON.stringify({ scroll: window.scrollY, focused: focused === row }));
})();
""", str(JS / "navigation.js"), str(JS / "services.js"))
    assert seen == {"scroll": 1000, "focused": True}


def test_health_jump_from_schedule_goes_back_to_visible_settings_list():
    seen = node(SETTINGS_NAV + r"""
enter("#/settings");
enter("#/schedule");
ctx.openSettings("unshackle");
settingsBack.onclick();
console.log(JSON.stringify({ backCalls, hash: location.hash, focused: focused === listItem }));
""", str(JS / "navigation.js"))
    assert seen == {"backCalls": 0, "hash": "#/settings", "focused": True}


def test_phone_back_after_forward_does_not_duplicate_the_settings_list():
    seen = node(SETTINGS_NAV + r"""
enter("#/schedule");
ctx.showTab("settings");
const list = location.hash;
ctx.showSettingsSec("notifications");
traverse(-1);
history.forward();
settingsBack.onclick();
const appBack = location.hash;
traverse(-1);
console.log(JSON.stringify({ list, backCalls, appBack, browserBack: location.hash }));
""", str(JS / "navigation.js"))
    assert seen == {"list": "#/settings", "backCalls": 1, "appBack": "#/settings", "browserBack": "#/schedule"}


@pytest.mark.parametrize("target", ["service", "show-me"])
def test_forward_restores_the_exact_settings_target_with_its_scroll(target):
    seen = node(SETTINGS_NAV + r"""
(async () => {
  enter("#/schedule");
  services();
  const service = process.argv[3] === "service";
  const vpnRow = { ...row, id: "sv-HULU@vpn",
    scrollIntoView: () => { window.scrollY = 1200; }, focus: () => { focused = vpnRow; } };
  if (service) {
    anchors[vpnRow.id] = vpnRow;
    ctx.S.config.service_defaults = { HULU: { backend: "vpn" } };
    await ctx.openServiceRow("HULU");
  } else ctx.openSettings("downloads", ".up-mode");
  const expected = service ? vpnRow : audioTarget;
  const first = [window.scrollY, focused === expected];
  history.back();
  // Forward must restore the original row even if a fresh lookup would use the main server.
  if (service) delete ctx.S.config.service_defaults.HULU;
  focused = listItem;
  window.scrollY = 0;
  history.forward();
  console.log(JSON.stringify({ first, forward: [window.scrollY, focused === expected] }));
})();
""", str(JS / "navigation.js"), str(JS / "services.js"), target)
    expected = [1200 if target == "service" else 500, True]
    assert seen == {"first": expected, "forward": expected}


@pytest.mark.parametrize("interruption", ["devices", "wheel", "schedule"])
def test_late_service_row_does_not_override_newer_navigation_or_scroll(interruption):
    seen = node(SETTINGS_NAV + r"""
(async () => {
  enter("#/schedule");
  services();
  delete anchors["sv-HULU"];
  await ctx.openServiceRow("HULU");
  if (process.argv[3] === "schedule") {
    enter("#/schedule");
    window.scrollY = 600;
    listItem.focus();
  } else if (process.argv[3] === "devices") jump("#/settings/cdm");
  else {
    listeners.wheel({ isTrusted: true });
    window.scrollY = 250;
  }
  const before = focused;
  anchors["sv-HULU"] = row;
  ctx.renderServices();
  console.log(JSON.stringify({ hash: location.hash, scroll: window.scrollY, retainedFocus: before === focused }));
})();
""", str(JS / "navigation.js"), str(JS / "services.js"), interruption)
    route, scroll = {
        "devices": ("#/settings/cdm", 400),
        "wheel": ("#/settings/services", 250),
        "schedule": ("#/schedule", 600),
    }[interruption]
    assert seen == {"hash": route, "scroll": scroll, "retainedFocus": True}


@pytest.mark.parametrize("focus_taken", ["none", "user"])
def test_initial_settings_route_focuses_only_after_translations_reveal_it(focus_taken):
    seen = node(SETTINGS_NAV + r"""
(async () => {
  const hiddenFocus = Boolean(focused);
  translating = false;
  if (process.argv[3] === "user") listItem.focus();
  finishTranslation();
  await new Promise(setImmediate);
  flushFrames();
  console.log(JSON.stringify({ hiddenFocus, focused: focused === heading ? "devices" : focused === listItem ? "user" : "body" }));
})();
""", str(JS / "navigation.js"), "translated", focus_taken)
    assert seen == {"hiddenFocus": False, "focused": "devices" if focus_taken == "none" else "user"}


def test_leaving_downloading_marks_downloads_and_automation_news_seen():
    seen = node(SETTINGS_NAV + r"""
const news = read(process.argv[2]);
const marked = [];
Object.assign(ctx, {
  newsUnseen: () => [{ id: "audio", sec: "downloads" }, { id: "window", sec: "automation" }, { id: "device", sec: "cdm" }],
  markNews: (ids) => marked.push(...ids),
});
vm.runInContext(grab(news, /^function leaveNews\b[\s\S]*?\n}\n/m) +
  grab(news, /^function leaveSettingsNews\b[\s\S]*?\n}\n/m), ctx);
ctx.leaveSettingsNews("downloading");
console.log(JSON.stringify(marked));
""", str(JS / "navigation.js"), str(JS / "news.js"))
    assert seen == ["audio", "window"]


def test_notifications_opens_at_top_with_heading_focus():
    seen = node(SETTINGS_NAV + r"""
enter("#/settings");
window.scrollY = 300;
ctx.showSettingsSec("notifications");
console.log(JSON.stringify({ hash: location.hash, scroll: window.scrollY, focused: focused === notificationsHeading }));
""", str(JS / "navigation.js"))
    assert seen == {"hash": "#/settings/notifications", "scroll": 0, "focused": True}


@pytest.mark.parametrize("candidate", ["hidden-label", "visible-label"])
def test_settings_show_me_moves_focus_past_hidden_labels(candidate):
    seen = node(SETTINGS_NAV + r"""
ctx.openSettings("downloads", ".up-mode");
console.log(JSON.stringify({ scroll: window.scrollY, focused: focused ===
  (process.argv[2] === "visible-label" ? visibleLabel : audioTarget) }));
""", str(JS / "navigation.js"), candidate)
    assert seen == {"scroll": 500, "focused": True}


def test_settings_jump_keeps_the_api_key_prompt_open_but_reentering_loads_account_again():
    seen = node(SETTINGS_NAV + r"""
enter("#/settings/general");
const beforeState = accountLoads;
ctx.S.config.settings = {};
ctx.applyRoute();
const afterState = accountLoads;
keyPrompt = true;
jump("#/settings/region");
const openAfterJump = keyPrompt, afterJump = accountLoads;
enter("#/schedule");
enter("#/settings/general");
console.log(JSON.stringify({ beforeState, afterState, afterJump, openAfterJump, afterReturn: accountLoads }));
""", str(JS / "navigation.js"))
    assert seen == {"beforeState": 0, "afterState": 1, "afterJump": 1, "openAfterJump": True, "afterReturn": 2}


def test_a_jobs_bar_has_open_series_for_a_phone_whose_head_and_foot_are_hidden():
    seen = node(r"""
const src = read(process.argv[1]);
const DOCK = { play: "", pause: "", opts: "", retry: "", stop: "", series: "S" };
const opened = [];
const job = { job: "j1", cards: [{ id: "a", tvdbId: 7, series: "Alpha", sxxeyy: "S01E01", service: "x", kind: "series", started: "2026-01-01T10:00:00", outcome: "running" },
  { id: "b", tvdbId: 7, series: "Alpha", sxxeyy: "S01E02", service: "x", kind: "series", started: "2026-01-01T10:00:00", outcome: "running", waiting: true }] };
let docked = null;
const ctx = sandbox({ el: (tag, props = {}, ...kids) => ({ tag, ...props, kids, children: [], insertBefore() {}, cloneNode() { return this; } }), DOCK, S: { series: [{ tvdbId: 7 }] }, openDrawer: (s) => opened.push(s.tvdbId), $: () => ({ replaceChildren() {}, querySelector: () => null, open: false, hidden: false, textContent: "" }),
  signInAction: () => "", signInFailed: () => null,
  jobState: () => ({ live: true, paused: false, n: { queued: 1 }, progress: 0, words: [] }), renderDock: (d) => { docked = d; }, jobHidden: new Set(), jobCards: new Map(), openCards: new Set(),
  isLive: (c) => c.outcome === "running", isQueued: () => false, FINISHING: new Set(), thumb: () => any, posterOf: () => "", svcName: (s) => s, KIND: {}, day: () => "", time: () => "",
  icon: () => any, glideBars: () => {}, termFor: null, following: null });
vm.runInContext(grab(src, /^function renderJob\b[\s\S]*?\n}\n/m), ctx);
ctx.renderJob(job);
const open = docked.acts.find((a) => a.key === "open");
open.go();
console.log(JSON.stringify({ keys: docked.acts.map((a) => a.key), label: open.label, opened }));
""", str(JS / "activity.js"))
    assert seen == {"keys": ["open", "pause", "opts", "stop"], "label": "Open series", "opened": [7]}


def test_a_phone_keeps_finished_job_actions_that_are_not_in_the_dock():
    footer_actions = r'\[data-fk="delete"\], \[data-fk="sign-in"\]'
    assert re.search(rf"\.con-detail\.docked-acts \.cd-foot:has\(:is\({footer_actions}\)\)\s*\{{\s*display:\s*flex", CSS)
    assert re.search(rf"\.con-detail\.docked-acts \.cd-foot \.btn:not\({footer_actions}\)\s*\{{\s*display:\s*none", CSS)


def test_mobile_output_disclosure_is_neutral_when_sign_in_or_primary_retry_is_present():
    actions = r'\[data-fk="sign-in"\], \[data-fk="retry"\]\.primary'
    rule = re.search(rf'\.con-detail:has\(\.cd-foot :is\({actions}\)\) \.dock \.d-open\s*\{{([^}}]+)\}}', CSS)
    assert rule
    assert "background: var(--field-bg)" in rule[1]
    assert "color: var(--text)" in rule[1]


LIST_ROW = r"""
const src = read(process.argv[1]);
const ctx = sandbox({ isLive: (c) => c.outcome === "running", isQueued: () => false, svcName: (s) => s, afterTracks: () => "", speedOf: () => "1 MB/s", pulse: () => el("span", { className: "pulse" }),
  thumb: () => el("img"), posterOf: () => "", hovering: () => "", picked_run: null, pickRun() {}, day: () => "", time: () => "", duration: () => "" });
vm.runInContext(grab(src, /^function listRow\b[\s\S]*?\n}\n/m), ctx);
const row = (extra) => ctx.listRow({ id: "a", series: "Alpha", sxxeyy: "S01E01", service: "NF", step: "downloading", started: "2026-01-01T10:00:00", outcome: "running", live: { progress: 40 }, ...extra });
const describe = (r) => ({ pulse: !!find(r, (x) => x.className === "pulse"), bar: !!find(r, (x) => x.className === "bar"),
  chip: find(r, (x) => String(x.className).startsWith("chip"))?.textContent ?? null, sub: find(r, (x) => x.tag === "small")?.textContent });
"""


def test_an_activity_row_waiting_for_an_answer_says_so_in_words_and_does_not_look_like_a_running_download():
    seen = node(LIST_ROW + r"""
console.log(JSON.stringify({ asking: describe(row({ prompt: { id: "p", text: "Code?" } })), running: describe(row({})) }));
""", str(JS / "activity.js"))
    assert seen["asking"] == {"pulse": False, "bar": False, "chip": "Waiting for your answer", "sub": "NF"}
    assert seen["running"] == {"pulse": True, "bar": True, "chip": None, "sub": "NF · 1 MB/s"}


def test_the_waiting_for_an_answer_chip_is_in_the_warning_colour():
    assert re.search(r"\.chip\.miss, \.chip\.ask \{ color: var\(--warn\); \}", CSS)
    assert re.search(r"\.chip\.ask,[^{]*\{ color: var\(--warn\); background: var\(--warn-tint\); \}", CSS)


SET_LANG = r"""
const src = read(process.argv[1]);
const calls = [];
const run = async (draft, answer) => {
  calls.length = 0;
  const ctx = sandbox({ setupDraft: draft, askToConfirm: async (...q) => { calls.push(["ask", q[0], q[1], q[2]]); return answer; }, api: async () => { calls.push(["api"]); },
    localStorage: { setItem: (k, v) => calls.push(["lang", v]) }, sessionStorage: { setItem: (k, v) => calls.push(["draft", k, JSON.parse(v).step]) }, location: { reload: () => calls.push(["reload"]) } });
  vm.runInContext(grab(src, /^async function setLang\b[\s\S]*?\n}\n/m), ctx);
  await ctx.setLang("fr");
  return calls.map((c) => c[0]);
};
"""


def test_switching_language_with_a_password_typed_asks_first_and_cancel_keeps_the_page():
    seen = node(SET_LANG + r"""
(async () => {
  const typed = () => ({ step: 2, secrets: true, values: {} }), none = () => ({ step: 0, secrets: false, values: {} });
  const out = { cancelled: await run(typed, false), warning: calls.find((c) => c[0] === "ask") };
  out.confirmed = await run(typed, true);
  out.nothingTyped = await run(none, false);  // nothing to lose: no question
  out.notInSetup = await run(null, false);
  console.log(JSON.stringify(out));
})();
""", str(JS / "core.js"))
    assert seen["cancelled"] == ["ask"]
    assert seen["warning"] == ["ask", "Switch the language?", "Switching language reloads the page: your password and keys are cleared.", "Switch language"]
    assert seen["confirmed"] == ["ask", "lang", "draft", "api", "reload"]
    assert seen["nothingTyped"] == ["lang", "draft", "api", "reload"]
    assert seen["notInSetup"] == ["lang", "api", "reload"]


def test_the_setup_never_writes_the_password_or_keys_to_the_tab():
    seen = wizard_node(WIZARD + r"""
const f = made.filter((n) => n.tag === "input");
f.forEach((n) => { n.value = "secret-" + (n.type || "text"); });
const draft = ctx.setupDraft();
console.log(JSON.stringify({ secrets: draft.secrets, stored: JSON.stringify(draft).includes("secret-password") }));
""", str(JS / "setup.js"))
    assert seen == {"secrets": True, "stored": False}


STEPS = WIZARD.replace("async () => { throw new Error(\"The setup code is wrong\"); }", "async () => ({ sonarr_api_key_set: true })") + r"""
Fake.prototype.closest = function (sel) { for (let n = this; n; n = n.parent) if (n.matches(sel)) return n; return null; };
Fake.prototype.scrollIntoView = function (o) { scrolled.push([[...this.classes][0], o.block]); };
const scrolled = [];
vm.runInContext(grab(read(process.argv[1]), /^function focusHeading[\s\S]*?\n}\n/m), ctx);  // core.js
const code = fieldOf("Setup code"), password = fieldOf("Password"), confirm = fieldOf("Confirm password");
code.value = "abc"; password.value = confirm.value = "longenough1";
"""


def test_moving_to_the_next_step_scrolls_the_card_to_the_top_and_focuses_its_heading():
    seen = wizard_node(STEPS + r"""
const heading = () => made.filter((n) => n.tag === "h2").at(-1);
const before = made.filter((n) => n.tag === "h2").length;
gateForm.onsubmit({ preventDefault() {} }).then(() => {
  const h = heading();
  console.log(JSON.stringify({ scrolled, focused: h.focused === true, tabIndex: h.tabIndex, newStep: made.filter((n) => n.tag === "h2").length > before }));
});
""", str(JS / "setup.js"))
    assert seen == {"scrolled": [["wz", "start"]], "focused": True, "tabIndex": -1, "newStep": True}


def test_a_key_found_in_the_environment_is_said_in_the_help_not_in_a_cut_off_placeholder():
    seen = wizard_node(STEPS.replace("ctx.showSetup({})", "ctx.showSetup({ sonarr_api_key_set: true })") + r"""
const sonarrKey = fieldOf("API key");
const help = made.find((n) => n.id === `${sonarrKey.id}-help`);
const found = help.querySelector(".env-found");
console.log(JSON.stringify({ placeholder: sonarrKey.placeholder ?? "", described: sonarrKey.getAttribute("aria-describedby") === help.id, hidden: found.hidden, text: found.textContent,
  unshackle: made.filter((n) => n.className === "env-found").map((n) => n.hidden) }));
""", str(JS / "setup.js"))
    assert seen["placeholder"] == ""
    assert seen["described"] is True
    assert seen["hidden"] is False
    assert seen["text"] == "Unshacklarr already has a key for the URL filled in above, saved or from SONARR_API_KEY. Leave this empty to use it."
    assert seen["unshackle"] == [False, True]  # Sonarr's found, the remote Unshackle's not


def test_the_setup_gate_leaves_the_confirm_dialog_visible():
    """The gate hides the page behind setup; the language switch asks through #confirm-dialog, a child of the body."""
    css = load_css()
    hiding = re.search(r"body\.gated > ([^{]+)\{ display: none !important; \}", css)
    assert hiding and ":not(#confirm-dialog)" in hiding[1]
    html = (Path(__file__).parents[1] / "unshacklarr" / "static" / "index.html").read_text()
    assert re.search(r"<body[^>]*>[\s\S]*<dialog[^>]*id=\"confirm-dialog\"", html)


def test_a_phone_dock_with_four_buttons_or_more_puts_them_under_the_status():
    """Open series makes four (Open, Pause, Options, Stop) or five with Retry: on one row at 320 px they overlapped the episode."""
    phone = CSS[CSS.index("@media (max-width: 700px)"):]
    dock = re.search(r"\n  \.dock \{[^}]*\}", phone)[0]
    assert "flex-wrap: wrap" in dock
    assert re.search(r"\.dock:has\(\.d-acts > :nth-child\(4\)\) \.d-mid \{ flex-basis: 100%; \}", phone)
    assert re.search(r"\.dock \.d-mid, \.dock \.d-l1 \{ min-width: max-content; \}", phone)


RUN_ACTS = r"""
const src = read(process.argv[1]);
const opened = [];
const ctx = sandbox({ isLive: () => false, setupButton: () => "", svcName: (s) => `${s}+`, openServiceRow: (...a) => opened.push(a),
  el: (tag, props = {}, ...kids) => ({ tag, ...props, kids, set innerHTML(v) {} }) });
vm.runInContext(grab(src, /^function signInFailed\b[\s\S]*?\n}\n/m) + grab(src, /^const fixSignIn = .*$/m) + "\n" + grab(src, /^const ACT_ICONS = [\s\S]*?\n};\n/m)
  + grab(src, /^function signInAction\b[\s\S]*?\n}\n/m) + grab(src, /^function cardActs\b[\s\S]*?\n}\n/m) + grab(src, /^function runActs\b[\s\S]*?\n}\n/m), ctx);
const card = (extra) => ({ id: "a", episodeId: 1, service: "HULU", backend: "", outcome: "failed", ...extra });
const acts = (extra) => ctx.runActs(card(extra)).map((b) => ({ text: b.textContent, title: b.title, primary: b.className.includes("primary"), go: b.onclick }));
const icons = (extra) => ctx.cardActs(card(extra)).map((b) => [b.ariaLabel, b.className.includes("primary"), b.onclick]);
const refused = acts({ auth_failures: { HULU: "2026-11-17T00:00:00Z" }, auth_failure_backends: { HULU: "vpn" } }), plain = acts({}), old = acts({ auth_failure: true, backend: "eu" });
refused[0].go();
old[0].go();
const grouped = icons({ auth_failures: { HULU: "2026-11-17T00:00:00Z" } });
grouped[0][2]({ ...card({ auth_failures: { HULU: "x" } }) });
console.log(JSON.stringify({ refused: refused.map(({ text, primary }) => [text, primary]), plain: plain.map(({ text, primary }) => [text, primary]),
  title: refused[0].title, old: old[0].text, opened, grouped: grouped.map(([l, p]) => [l, p]), groupedPlain: icons({}).map(([l, p]) => [l, p]) }));
"""


def test_an_attempt_its_sign_in_failed_offers_the_sign_in_first_and_retry_after():
    seen = node(RUN_ACTS, str(JS / "activity.js"))
    # a retry would fail the same way: the service's row in Settings, where its sign-in is renewed, comes first
    assert seen["refused"][:2] == [["Fix sign-in", True], ["Retry", False]]
    assert seen["title"] == "Check HULU+ in Settings › Services & Devices › Services"  # where it leads, short enough for a phone's bar
    # the server it failed on, not the one set for the service now; a card of the first schema: its own backend
    assert seen["opened"][:2] == [["HULU", "vpn"], ["HULU", "eu"]]
    assert seen["plain"][0] == ["Retry", True]  # any other failure: retrying is still the thing to do
    assert seen["old"] == "Fix sign-in"
    # an attempt in a job (its icon buttons) too, on the main server when that is where it failed
    assert seen["grouped"][:2] == [["Fix sign-in", True], ["Retry", False]] and seen["opened"][2] == ["HULU", ""]
    assert seen["groupedPlain"][0] == ["Retry", True]


REVEAL = r"""
const src = read(process.argv[1]);
const rows = new Set(["sv-HULU", "sv-HULU@vpn", "sv-HULU@eu"]);
const ctx = sandbox({ S: { config: { service_defaults: { HULU: { backend: "eu" } } } }, CSS: { escape: (s) => s },
  document: { getElementById: (id) => (rows.has(id) ? { id } : null), querySelector: () => null } });
vm.runInContext(grab(src, /^function serviceRow\b[\s\S]*?\n}\n/m), ctx);
console.log(JSON.stringify(["vpn", "", undefined].map((backend) => ctx.serviceRow({ service: "HULU", backend }).id)));
"""


def test_the_services_row_opened_for_a_failed_sign_in_is_the_server_it_failed_on():
    # a backend named: that row ("" the main server's); none: the one set for the service, as before
    assert node(REVEAL, str(JS / "services.js")) == ["sv-HULU@vpn", "sv-HULU", "sv-HULU@eu"]


MONTH_TIME = r"""
const src = read(process.argv[1]);
const ctx = sandbox({ isoDay: (d) => d.toISOString().slice(0, 10), time: (d) => d.toISOString().slice(11, 16), LOCALE: "en-GB" });
vm.runInContext(grab(src, /^const triesAt = .*\n/m) + grab(src, /^const whenOf = .*\n/m) + grab(src, /^const monthTime = .*\n/m) + "globalThis.monthTime = monthTime;", ctx);
const ep = { managed: true, hasFile: false, airDateUtc: "2099-01-05T23:30:00Z" };
console.log(JSON.stringify({ nextDay: ctx.monthTime({ ...ep, firstTry: "2099-01-06T00:00:00Z" }, "2099-01-05"),
  sameDay: ctx.monthTime({ ...ep, firstTry: "2099-01-05T23:45:00Z" }, "2099-01-05") }));
"""


def test_a_month_cell_names_the_day_of_a_try_after_midnight():
    seen = node(MONTH_TIME, str(JS / "schedule.js"))
    # filed under the day it airs: "00:00" alone would put the sync a day early
    assert seen == {"nextDay": "Tue 00:00", "sameDay": "23:45"}


WHEN_TEXT = r"""
const src = read(process.argv[1]);
const ctx = sandbox({ isoDay: (d) => d.toISOString().slice(0, 10), day: (d) => `day${d.getUTCDate()}`, time: (d) => d.toISOString().slice(11, 16), until: () => "soon" });
vm.runInContext(grab(src, /^const triesAt = .*\n/m) + grab(src, /^const whenText = [\s\S]*?\n};\n/m) + "globalThis.whenText = whenText;", ctx);  // a const is not on the context
const text = (d) => { const n = ctx.whenText({ managed: true, hasFile: false, airDateUtc: "2099-01-05T12:00:00Z", ...d }); return [n.kids[0], n.kids[1].textContent]; };
console.log(JSON.stringify({
  sync: text({ firstTry: "2099-01-05T13:00:00Z" }),
  nextDay: text({ firstTry: "2099-01-06T00:00:00Z" }),
  aired: text({ airDateUtc: "2000-01-05T12:00:00Z" }),
  onDisk: text({ hasFile: true, firstTry: "2099-01-05T13:00:00Z" }),
}));
"""


def test_a_schedule_card_without_a_release_time_shows_the_sync_that_tries_it_and_when_it_airs():
    seen = node(WHEN_TEXT, str(JS / "schedule.js"))
    # not the airing labelled "next sync", which read as the sync's own time
    assert seen["sync"] == ["13:00", "airs 12:00"]
    assert seen["nextDay"] == ["day6 00:00", "airs 12:00"]
    assert seen["aired"] == ["12:00", "airs"]  # aired, not tried yet: its pill says "Tries at the next sync"
    assert seen["onDisk"] == ["12:00", "airs"]


def test_activity_detail_says_it_is_loading_until_the_history_is_in():
    page = (STATIC / "index.html").read_text()
    detail = re.search(r'<div id="cd-main">(.*?)</div></div>', page).group(1)
    assert 'class="loading" role="status"' in detail and "Loading the downloads…" in detail
    assert "Nothing picked" not in detail  # the empty state only once the history is in and nothing is picked
