"""Gaps in the flows of Activity and the first-run setup (#280); each script runs the page's own code in Node."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_error_feedback import WIZARD
from test_error_feedback import node as wizard_node

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
JS = STATIC / "js"
CSS = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(), flags=re.S)

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
const select = { classList: { contains: () => false, toggle() {} }, setAttribute() {},
  addEventListener: (name, fn) => { listeners[name] = fn; } };
let cdmTop = 400, focused, finishServices, accountLoads = 0, keyPrompt = false;
const heading = { id: "cdm-heading" };
const anchors = {
  "services-sec": { compareDocumentPosition: (other) => other === anchors["cdm-sec"] ? 4 : 0 },
  "cdm-sec": {
    closest: () => null, querySelector: () => heading,
    scrollIntoView: () => { window.scrollY = cdmTop; },
    getBoundingClientRect: () => ({ top: cdmTop - window.scrollY }),
  },
  "region-sec": { closest: () => null, querySelector: () => null, scrollIntoView() {},
    getBoundingClientRect: () => ({ top: 100 - window.scrollY }) },
  "history-sec": { compareDocumentPosition: () => 0 },
  "account-sec": { compareDocumentPosition: () => 0 },
};
const ctx = sandbox({
  $, window, location, current: null, S: { config: {} }, termSocket: null,
  phoneLayout: () => true, Node: { DOCUMENT_POSITION_FOLLOWING: 4 },
  document: { querySelectorAll: () => [], body: select, getElementById: (id) => anchors[id] },
  history: { replaceState: (_, __, hash) => { location.hash = hash; } },
  focusHeading: (node) => { focused = node; },
  loadServices: () => new Promise((resolve) => {
    finishServices = () => { cdmTop += 6000; resolve(); };
  }),
  loadCdm: () => new Promise(() => {}),
  loadAccount: () => { accountLoads++; keyPrompt = false; },
  scrollTo: ({ top }) => { window.scrollY = top; },
});
function $(selector) {
  return selector === "#tab-settings" ? select : { ...select, addEventListener() {} };
}
const source = read(process.argv[1]);
vm.runInContext(source.slice(0, source.indexOf('showTab(parseRoute().tab')) +
  grab(source, /^showTab\(parseRoute\(\).tab.*\nif \(parseRoute\(\).sec\).*\nelse if .*$/m), ctx);
const enter = (hash) => { location.hash = hash; ctx.applyRoute(); };
const jump = (hash) => listeners.click({ preventDefault() {}, target: { closest: () => ({ hash }) } });
"""


@pytest.mark.parametrize("interruption", ["none", "layout", "before-state", "scroll", "route"])
def test_delayed_services_keep_the_cdm_heading_in_view_only_if_the_jump_is_still_active(interruption):
    seen = node(SETTINGS_NAV + r"""
(async () => {
  const before = cdmTop - window.scrollY;
  const focusedCdm = focused === heading;
  if (process.argv[2] === "before-state") {
    window.scrollY += 120;
    listeners.scroll?.();
  }
  const beforeState = window.scrollY;
  ctx.S.config.settings = {};
  ctx.applyRoute();
  const movedOnState = window.scrollY !== beforeState;
  if (process.argv[2] === "scroll") {
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
  finishServices();
  await new Promise(setImmediate);
  console.log(JSON.stringify({ before, focusedCdm, movedOnState, top: cdmTop - window.scrollY,
    moved: window.scrollY !== scrollBeforeRender }));
})();
""", str(JS / "navigation.js"), interruption)
    assert seen["before"] == 0
    assert seen["focusedCdm"]
    assert not seen["movedOnState"]
    if interruption in ("none", "layout"):
        assert seen["top"] == 0
    else:
        assert not seen["moved"]


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


def test_a_phone_keeps_a_finished_jobs_delete_when_the_bar_has_its_other_buttons():
    assert re.search(r"\.con-detail\.docked-acts \.cd-foot:has\(\[data-fk=\"delete\"\]\)\s*\{\s*display:\s*flex", CSS)
    assert re.search(r"\.con-detail\.docked-acts \.cd-foot \.btn:not\(\[data-fk=\"delete\"\]\)\s*\{\s*display:\s*none", CSS)


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
    css = (Path(__file__).parents[1] / "unshacklarr" / "static" / "app.css").read_text()
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
  + grab(src, /^function cardActs\b[\s\S]*?\n}\n/m) + grab(src, /^function runActs\b[\s\S]*?\n}\n/m), ctx);
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
const rows = new Set(["sv-HULU", "sv-HULU@vpn", "sv-HULU@eu"]), shown = [];
const ctx = sandbox({ S: { config: { service_defaults: { HULU: { backend: "eu" } } } }, SCROLL: "auto", CSS: { escape: (s) => s },
  document: { getElementById: (id) => (rows.has(id) ? { id, scrollIntoView() { shown.push(id); }, focus() {} } : null), querySelector: () => null } });
vm.runInContext("let servicesReveal = '';\n" + grab(src, /^function revealService\b[\s\S]*?\n}\n/m) + "globalThis.go = (s) => { servicesReveal = s; revealService(); };", ctx);
for (const s of ["HULU@vpn", "HULU@", "HULU"]) ctx.go(s);
console.log(JSON.stringify(shown));
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
