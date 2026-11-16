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
    assert seen["text"] == "Found in the environment for the URL above. Leave empty to use it"
    assert seen["unshackle"] == [False, True]  # Sonarr's found, the remote Unshackle's not


def test_the_setup_gate_leaves_the_confirm_dialog_visible():
    """The gate hides the page behind setup; the language switch asks through #confirm-dialog, a child of the body."""
    css = (Path(__file__).parents[1] / "unshacklarr" / "static" / "app.css").read_text()
    hiding = re.search(r"body\.gated > ([^{]+)\{ display: none !important; \}", css)
    assert hiding and ":not(#confirm-dialog)" in hiding[1]
    html = (Path(__file__).parents[1] / "unshacklarr" / "static" / "index.html").read_text()
    assert re.search(r"<body[^>]*>[\s\S]*<dialog[^>]*id=\"confirm-dialog\"", html)
