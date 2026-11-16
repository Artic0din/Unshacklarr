"""A slow answer never draws over what the page shows now: the page's real functions run under node with answers released in a chosen order."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"

# Shared by every script: `grab(name)` is the source of a function or a one-line/arrow const of the page's script.
PRELUDE = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n|const ${name} = [\\s\\S]*?\\n};?\\n|const ${name} = [^\\n]*\\n`))[0];
"""


def node(script, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PRELUDE + script, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_history_answer_keeps_newer_live_progress():
    shown = node(r"""
const card = (progress) => ({ id: "a", outcome: "running", step: "downloading", live: { status: "downloading", progress } });
let answer;
const ctx = { runCards: [card(10)], runsTimer: null, liveFeed: null, feedReloading: false, feedMissed: null, feedSeen: new Set(),
  $: () => ({ hidden: false, textContent: "" }), api: (path) => (path === "/api/runs" ? new Promise((resolve) => { answer = resolve; }) : Promise.resolve({ items: [] })),
  renderConsole() {}, followLive() {}, activityLater() {}, failed: () => null, setTimeout: () => 0, clearTimeout() {} };
vm.createContext(ctx);
vm.runInContext("let runsSeq = 0;" + ["isLive", "feedChanged"].map(grab).join("") + grab("openActivity") + grab("liveTick"), ctx);
(async () => {
  const reload = ctx.openActivity();
  ctx.liveTick(JSON.stringify([card(60)]));  // drawn while the history answer is on its way
  answer([card(10), { id: "old", outcome: "downloaded" }]);  // produced before that message
  await reload;
  console.log(JSON.stringify({ progress: ctx.runCards[0].live.progress, history: ctx.runCards.map((c) => c.id) }));
})();
""", str(JS / "activity.js"))
    assert shown == {"progress": 60, "history": ["a", "old"]}


def test_history_answer_takes_card_when_no_live_message_came():
    shown = node(r"""
const card = (progress) => ({ id: "a", outcome: "running", step: "downloading", live: { status: "downloading", progress } });
const ctx = { runCards: [card(10)], runsTimer: null, liveFeed: null, feedReloading: false, feedMissed: null, feedSeen: new Set(),
  $: () => ({ hidden: false, textContent: "" }), api: async (path) => (path === "/api/runs" ? [card(30)] : { items: [] }),
  renderConsole() {}, followLive() {}, activityLater() {}, failed: () => null, setTimeout: () => 0, clearTimeout() {} };
vm.createContext(ctx);
vm.runInContext("let runsSeq = 0;" + ["isLive", "feedChanged"].map(grab).join("") + grab("openActivity") + grab("liveTick"), ctx);
ctx.openActivity().then(() => console.log(JSON.stringify({ progress: ctx.runCards[0].live.progress })));
""", str(JS / "activity.js"))
    assert shown == {"progress": 30}
