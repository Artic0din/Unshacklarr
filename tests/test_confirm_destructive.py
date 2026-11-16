"""Actions that delete data ask first: each one run for real in Node, with the server call watched."""
import pytest

from test_ui_misc import JS, node

# `$` hands out one recording object per selector, so a handler the script assigns can be found and called
NODES = r"""
const nodes = {};
const node$ = (sel) => (nodes[sel] ||= new Proxy({ dataset: {}, textContent: "", classList: { add() {}, remove() {}, contains: () => false } },
  { get: (t, k) => (k in t ? t[k] : any), set: (t, k, v) => ((t[k] = v), true) }));
const button = () => ({ dataset: {}, textContent: "Delete", classList: { contains: () => false }, disabled: false, contains() { return true; }, addEventListener() {}, removeEventListener() {} });
const calls = [];
const api = async (url, opts = {}) => { calls.push(`${opts.method || "GET"} ${url}`); return { deleted: 3, series: 2, freed_bytes: 0 }; };
const settle = () => new Promise((done) => setTimeout(done, 5));
"""


def test_the_question_is_spoken_and_escape_takes_it_back_without_closing_the_window_around_it():
    shown = node(NODES + r"""
const listeners = [];
const document = { addEventListener: (t, f, c) => listeners.push([t, f, c]), removeEventListener(t, f) { const i = listeners.findIndex((l) => l[0] === t && l[1] === f); if (i >= 0) listeners.splice(i, 1); } };
const ctx = sandbox({ $: node$, document });
vm.runInContext(grab(read(process.argv[1]), /^function confirmClick\(.*?^\}/ms), ctx);
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
