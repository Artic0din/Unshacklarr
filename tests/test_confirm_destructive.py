"""Actions that delete data ask first: each one run for real in Node, with the server call watched."""
import pytest

from test_ui_misc import JS, STATIC, node

# `$` hands out one recording object per selector, so a handler the script assigns can be found and called
NODES = r"""
const nodes = {};
const node$ = (sel) => (nodes[sel] ||= new Proxy({ dataset: {}, textContent: "", classList: { add() {}, remove() {}, toggle() {}, contains: () => false } },
  { get: (t, k) => (k in t ? t[k] : any), set: (t, k, v) => ((t[k] = v), true) }));
const button = () => ({ dataset: {}, textContent: "Delete", classList: { contains: () => false }, disabled: false, contains() { return true; }, closest: () => null, addEventListener() {}, removeEventListener() {} });
const calls = [];
const api = async (url, opts = {}) => { calls.push(`${opts.method || "GET"} ${url}`); return { deleted: 3, series: 2, freed_bytes: 0 }; };
const settle = () => new Promise((done) => setTimeout(done, 5));
"""


def test_the_question_is_spoken_and_escape_takes_it_back_without_closing_the_window_around_it():
    shown = node(NODES + r"""
const listeners = [];
const document = { addEventListener: (t, f, c) => listeners.push([t, f, c]), removeEventListener(t, f) { const i = listeners.findIndex((l) => l[0] === t && l[1] === f); if (i >= 0) listeners.splice(i, 1); } };
const ctx = sandbox({ $: node$, document });
vm.runInContext(grab(read(process.argv[1]), /^const sureSay.*?^function confirmClick\(.*?^\}/ms), ctx);
const b = button(), out = {};
out.first = ctx.confirmClick(b, "Delete 3 episodes?");
out.label = b.textContent; out.spoken = nodes["#sure-say"].textContent;
const key = { type: "keydown", key: "Escape", prevented: false, stopped: false, preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
listeners.filter(([t]) => t === "keydown").forEach(([, f]) => f(key));
out.escape = [b.textContent, b.dataset.sure ?? null, nodes["#sure-say"].textContent, key.prevented, key.stopped, listeners.length];
out.again = ctx.confirmClick(b, "Delete 3 episodes?");
console.log(JSON.stringify(out));
""", str(JS / "core.js"))
    assert shown == {"first": False, "label": "Delete 3 episodes?", "spoken": "Delete 3 episodes?",
                     "escape": ["Delete", None, "", True, True, 0], "again": False}


def test_clearing_the_notifications_asks_first_and_names_how_many():
    shown = node(NODES + r"""
const asked = [];
const ctx = sandbox({ $: node$, api, toast() {}, renderInbox() {}, refreshInbox() {}, setInterval() {}, document: { addEventListener() {} },
  COUNT: { notification: (n) => `${n} notifications` },
  confirmClick: (b, question) => (asked.push(question), asked.length > 1) });
vm.runInContext(read(process.argv[1]), ctx);
vm.runInContext('inboxData = { items: [{ title: "a" }, { title: "b" }, { title: "c", action: { kind: "input" } }] }', ctx);  // the script's own let
(async () => {
  const click = { currentTarget: button() };
  await nodes["#inbox-clear"].onclick(click); const first = calls.slice();
  await nodes["#inbox-clear"].onclick(click);
  console.log(JSON.stringify({ first, asked: asked[0], calls }));
})();
""", str(JS / "inbox.js"))
    assert shown == {"first": [], "asked": "Clear 2 notifications? They cannot be brought back", "calls": ["POST /api/inbox/clear"]}


@pytest.mark.parametrize("answer, sent", [(False, []), (True, ["DELETE /api/jobs/j1"])])
def test_deleting_a_job_waits_for_the_answer_and_names_its_episodes(answer, sent):
    shown = node(NODES + r"""
let question = null;
const ctx = sandbox({ $: node$, api, toast() {}, openActivity() {}, COUNT: { episode: (n) => `${n} episodes` },
  askToConfirm: async (...q) => ((question = q), JSON.parse(process.argv[2])) });
vm.runInContext(grab(read(process.argv[1]), /async function deleteJob\b[\s\S]*?\n}\n/), ctx);
(async () => {
  const b = button();
  await ctx.deleteJob({ job: "j1", cards: [{}, {}, {}] }, b);
  console.log(JSON.stringify({ calls, disabled: b.disabled && !calls.length, title: question[0], verb: question[2] }));
})();
""", str(JS / "attempts.js"), "true" if answer else "false")
    assert shown == {"calls": sent, "disabled": False, "title": "Delete this job's 3 episodes from the history?", "verb": "Delete 3 episodes"}


@pytest.mark.parametrize("answer, sent", [(False, []), (True, ["DELETE /api/runs/r1"])])
def test_deleting_a_run_waits_for_the_answer(answer, sent):
    shown = node(NODES + r"""
let question = null;
const ctx = sandbox({ $: node$, api, toast() {}, openActivity() {}, picked_run: null,
  askToConfirm: async (...q) => ((question = q), JSON.parse(process.argv[2])) });
vm.runInContext(grab(read(process.argv[1]), /async function deleteRun\b[\s\S]*?\n}\n/), ctx);
(async () => {
  const b = button();
  await ctx.deleteRun({ id: "r1", series: "Silo", sxxeyy: "S01E02" }, b);
  console.log(JSON.stringify({ calls, disabled: b.disabled && !calls.length, title: question[0], verb: question[2] }));
})();
""", str(JS / "attempts.js"), "true" if answer else "false")
    assert shown == {"calls": sent, "disabled": False, "title": "Delete Silo S01E02 from the history?", "verb": "Delete this attempt"}


@pytest.mark.parametrize("answer, sent", [(False, []), (True, ["POST /api/unshackle/maintenance/clear-temp"])])
def test_deleting_partial_downloads_waits_for_the_answer_and_looks_like_a_danger(answer, sent):
    shown = node(NODES + r"""
const made = [];
let question = null;
const ctx = sandbox({ $: node$, api, toast() {}, loadUnshackleStatus() {}, loadServices() {}, svcName: String, icon: () => "",
  S: { config: { settings: {} } }, el: (tag, props = {}, ...kids) => { const e = { tag, ...props, kids }; made.push(e); return e; },
  askToConfirm: async (...q) => ((question = q), JSON.parse(process.argv[2])) });
vm.runInContext(grab(read(process.argv[1]), /function renderUnshackleStatus\b[\s\S]*?\n}\n/), ctx);
ctx.renderUnshackleStatus({ mode: "local", ok: true, caps: [], tools: [] });
const partial = made.find((e) => e.textContent === "Delete partial downloads");
(async () => {
  await partial.onclick({ target: { disabled: false } });
  console.log(JSON.stringify({ calls, title: question[0], className: partial.className }));
})();
""", str(JS / "settings-services.js"), "true" if answer else "false")
    assert shown == {"calls": sent, "title": "Delete the partial downloads?", "className": "btn small danger"}


@pytest.mark.parametrize("answer, sent", [(False, []), (True, ["POST /api/restore"])])
def test_picking_a_backup_replaces_nothing_until_confirmed(answer, sent):
    shown = node(NODES + r"""
let question = null;
const ctx = sandbox({ $: node$, api, toast() {}, bkSay() {}, errorDetail: String, location: { reload() {} }, setTimeout: () => 0,
  askToConfirm: async (...q) => ((question = q), JSON.parse(process.argv[2])) });
vm.runInContext(grab(read(process.argv[1]), /\$\("#bk-file"\)\.onchange = async \(e\) => \{[\s\S]*?\n\};\n/), ctx);
(async () => {
  const input = { files: [{ name: "backup.yaml", text: async () => "series: {}" }], value: "backup.yaml" };
  await nodes["#bk-file"].onchange({ target: input });
  console.log(JSON.stringify({ calls, title: question[0], text: question[1], verb: question[2] }));
})();
""", str(JS / "settings-options.js"), "true" if answer else "false")
    assert shown["calls"] == sent
    assert shown["title"] == "Restore the settings from backup.yaml?" and shown["verb"] == "Replace the settings"
    assert "series, addresses, passwords and keys" in shown["text"]


def test_the_question_is_spoken_in_the_window_the_button_is_in_not_the_inert_page():
    shown = node(NODES + r"""
const region = { textContent: "" }, dialog = { querySelector: (sel) => (sel === ".sure-say" ? region : null) };
const ctx = sandbox({ $: node$, document: { addEventListener() {}, removeEventListener() {} } });
vm.runInContext(grab(read(process.argv[1]), /^const sureSay.*?^function confirmClick\(.*?^\}/ms), ctx);
const b = button(); b.closest = (sel) => (sel === "dialog" ? dialog : null);
ctx.confirmClick(b, "Clear 2 notifications?");
const spoken = [region.textContent, nodes["#sure-say"]?.textContent ?? ""];
ctx.confirmClick(b, "Clear 2 notifications?");
console.log(JSON.stringify({ spoken, after: region.textContent }));
""", str(JS / "core.js"))
    assert shown == {"spoken": ["Clear 2 notifications?", ""], "after": ""}


def test_the_page_has_a_live_region_inside_the_notifications_window_and_the_question_window_is_described():
    html = (STATIC / "index.html").read_text()
    inbox = html[html.index('id="inbox-dialog"'):html.index("</dialog>", html.index('id="inbox-dialog"'))]
    assert 'class="sr-only sure-say"' in inbox and 'role="status"' in inbox
    assert 'id="confirm-dialog" aria-labelledby="confirm-title" aria-describedby="confirm-text"' in html


@pytest.mark.parametrize("answer, focused", [("cancel", ["delete:r1"]), ("go", [])])
def test_cancelling_after_the_page_redrew_the_button_focuses_its_new_copy(answer, focused):
    shown = node(NODES + r"""
const focused = [];
const dialog = { returnValue: "", showModal() {}, addEventListener(t, f) { this.close = f; } };
const copy = (visible) => ({ getClientRects: () => (visible ? [{}] : []), focus: () => focused.push("delete:r1") });
const document = { querySelectorAll: (sel) => (sel === '[data-focus-key="delete:r1"]' ? [copy(false), copy(true)] : []) };
const ctx = sandbox({ $: (sel) => (sel === "#confirm-dialog" ? dialog : node$(sel)), document, CSS: { escape: String } });
vm.runInContext(grab(read(process.argv[1]), /^function askToConfirm\b.*?^\}/ms), ctx);
const trigger = { dataset: { focusKey: "delete:r1" }, isConnected: false };  // replaced by the page's redraw
const asked = ctx.askToConfirm("Delete?", "text", "Delete", trigger);
dialog.returnValue = process.argv[2];
dialog.close();
asked.then((yes) => console.log(JSON.stringify({ yes, focused })));
""", str(JS / "core.js"), answer)
    assert shown == {"yes": answer == "go", "focused": focused}


def test_the_clear_question_is_taken_back_when_the_number_it_names_changed():
    shown = node(NODES + r"""
const cancelled = [];
const ctx = sandbox({ $: node$, api, toast() {}, refreshInbox() {}, setInterval() {}, document: { addEventListener() {} },
  COUNT: { notification: (n) => `${n} notifications` }, confirmCancel: (b) => cancelled.push(b) });
vm.runInContext(read(process.argv[1]), ctx);
const items = (n) => Array.from({ length: n }, (_, i) => ({ title: `n${i}`, at: "2026-01-01", level: "info" }));
const run = (asked, now) => {
  nodes["#inbox-clear"].dataset = { sure: "1", asked };
  vm.runInContext(`inboxData = { items: ${JSON.stringify(items(now))}, read_at: "" }`, ctx);
  ctx.renderInbox();
  return cancelled.length;
};
console.log(JSON.stringify({ same: run("5", 5), grew: run("5", 6) }));
""", str(JS / "inbox.js"))
    assert shown == {"same": 0, "grew": 1}


def test_clear_cannot_be_pressed_before_the_notifications_have_been_read():
    shown = node(NODES + r"""
const ctx = sandbox({ $: node$, api: () => new Promise(() => {}), toast() {}, setInterval() {}, document: { addEventListener() {} }, loading: () => ({}),
  phoneLayout: () => false });
vm.runInContext(read(process.argv[1]), ctx);
nodes["#inbox-clear"].hidden = false;
ctx.openInbox("menu");  // never answered: the data is not there
console.log(JSON.stringify({ hidden: nodes["#inbox-clear"].hidden }));
""", str(JS / "inbox.js"))
    assert shown == {"hidden": True}
