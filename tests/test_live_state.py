"""Lime marks what is live: a job's bar runs only while an episode downloads, and the terminal takes the theme's colours."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"


def node(script: str, *args: str):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", script, *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


GRAB = r"""
const fs = require("fs"), vm = require("vm");
const grab = (src, name) => { const at = src.indexOf(`function ${name}(`); let i = src.indexOf("{", at), depth = 0;
  for (; i < src.length; i++) { if (src[i] === "{") depth++; else if (src[i] === "}" && !--depth) break; } return src.slice(at, i + 1); };
"""


def test_a_job_bar_runs_only_while_an_episode_downloads():
    shown = node(GRAB + r"""
const src = fs.readFileSync(process.argv[1], "utf8");
const ctx = vm.createContext({});
const line = (re) => src.match(re)[0];  // the page's own isLive and FINISHING, not stand-ins
vm.runInContext(line(/^const isLive = .*$/m) + "\n" + line(/^const FINISHING = .*$/m) + "\n" + grab(src, "cardKind") + grab(src, "jobState"), ctx);
const run = (step, progress) => ({ outcome: "running", step, live: { progress } });
const queued = { cards: [run("queued"), run("queued")] };
const downloading = { cards: [run("video", 40), run("queued")] };
const finishing = { cards: [run("renaming"), run("importing")] };
const done = { cards: [{ outcome: "downloaded" }] };
console.log(JSON.stringify([queued, downloading, finishing, done].map((j) => ctx.jobState(j)).map((s) => [s.live, s.running, s.n.finishing])));
""", str(JS / "activity.js"))
    assert shown == [[True, False, 0], [True, True, 0], [True, True, 2], [False, False, 0]]


def test_the_dock_bar_is_lime_while_running_green_when_done_and_quiet_otherwise():
    shown = node(GRAB + r"""
const src = fs.readFileSync(process.argv[1], "utf8");
const classes = new Set(), bar = { className: "bar", firstElementChild: { style: {} } };
const line = [{}, { title: "" }, {}];
const dock = { hidden: true, firstChild: true, classList: { toggle: (c, on) => on ? classes.add(c) : classes.delete(c), contains: (c) => classes.has(c) },
  querySelector: (s) => s === ".bar" ? bar : s === ".d-l1" ? { children: line } : s === ".d-acts" ? { dataset: { key: "" }, children: [], replaceChildren() {} } : { hidden: false } };
const detail = { classList: { toggle() {} } };
const ctx = vm.createContext({ $: (s) => s === "#dock" ? dock : detail, closeSheet() {}, el() {} });
vm.runInContext(grab(src, "renderDock"), ctx);
const out = [];
for (const d of [{ running: true, tone: "" }, { running: false, tone: "" }, { running: false, tone: "ok" }]) {
  ctx.renderDock({ ep: "S01E01", line: "", pct: "", progress: 50, acts: [], ...d });
  out.push([bar.className, classes.has("running")]);
}
console.log(JSON.stringify(out));
""", str(JS / "activity.js"))
    assert shown == [["bar", True], ["bar idle", False], ["bar done", False]]


def test_the_terminal_takes_the_theme_colours():
    shown = node(GRAB + r"""
const src = fs.readFileSync(process.argv[1], "utf8");
let options;
class FakeTerminal { constructor(o) { options = o; } loadAddon() {} open() {} reset() {} }
const tokens = { "--term-bg": "#0a0b08", "--text": "#f3f4ee", "--text-selection": "#44501d", "--muted": "#aca9a6", "--err": "#ff8a75" };
const ctx = vm.createContext({ window: { Terminal: FakeTerminal }, Terminal: FakeTerminal, FitAddon: { FitAddon: class {} }, ResizeObserver: class { observe() {} },
  getComputedStyle: () => ({ getPropertyValue: (name) => ` ${tokens[name] || ""} ` }), document: { documentElement: {} },
  $: () => ({ textContent: "" }), term: null, termFit: null, fitTerminal() {} });
vm.runInContext("var term = null, termFit = null, termSocket = null;" + grab(src, "openTerm"), ctx);
ctx.openTerm();
const t = options.theme;
console.log(JSON.stringify([t.background, t.foreground, t.cursor, t.selectionBackground, t.brightBlack, t.red, t.brightRed]));
""", str(JS / "attempts.js"))
    # dim lines in --muted (xterm's own #555753 was 2.59:1), failures in --err rather than pure red
    assert shown == ["#0a0b08", "#f3f4ee", "#0a0b08", "#44501d", "#aca9a6", "#ff8a75", "#ff8a75"]
