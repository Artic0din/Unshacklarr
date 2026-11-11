"""Activity's Stats and Waiting in downloads panes draw only their own answer; the output terminal says when it cannot connect."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"

# Runs the page's real showStats / showLeftovers with api answers released in a chosen order, and prints what the pane ended up showing.
PANES = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const [first, second] = JSON.parse(process.argv[2]);  // the pane opened first, then the one opened second
const main = { heading: null, replaceChildren(...k) { this.heading = JSON.stringify(k).match(/"textContent":"(Stats|Waiting in downloads)"/)?.[1] ?? "other"; } };
const title = { textContent: "" };
const stub = { textContent: "", hidden: false, classList: { add() {} }, replaceChildren() {} };
const pending = {};
const ctx = {
  $: (sel) => (sel === "#cd-main" ? main : sel === "#cd-top-title" ? title : stub),
  document: { querySelectorAll: () => [] },
  el: (tag, props = {}, ...kids) => ({ tag, ...props, kids }),
  failed: (t) => ({ failed: t }),
  api: (path) => new Promise((resolve) => { pending[path] = resolve; }),
  day: () => "", ago: () => "", duration: () => "", LOCALE: "en", S: { series: [] }, posterSrc: () => "", posterFail: () => null, OUTCOME: {},
};
vm.createContext(ctx);
vm.runInContext(`var picked_run = null;\n${grab("showLeftovers")}\n${grab("showStats")}`, ctx);
const path = { stats: "/api/stats", left: "/api/leftovers" };
const answer = { stats: { month: {}, weeks: [], services: [], since: null }, left: { items: [], days: 0 } };
const open = { stats: ctx.showStats, left: ctx.showLeftovers };
(async () => {
  const a = open[first](), b = open[second]();
  for (const which of [second, first]) { pending[path[which]](answer[which]); await (which === second ? b : a); }
  console.log(JSON.stringify({ title: title.textContent, heading: main.heading }));
})();
"""

# Runs the page's real streamTerm against a fake socket and prints what was written into the terminal box.
TERMINAL = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const scenario = process.argv[2];
const written = [];
const sockets = [];
class FakeSocket { constructor() { sockets.push(this); } close() {} }
const ctx = { term: { write: (t) => written.push(typeof t === "string" ? t : "output") }, termSocket: null, termFor: null, termQuery: "",
  openTerm: () => true, termFilter: () => (b) => b, WebSocket: FakeSocket, location: { protocol: "http:", host: "x" } };
vm.createContext(ctx);
vm.runInContext(grab("streamTerm"), ctx);
ctx.streamTerm("run", "run=1");
const sock = sockets[0];
if (scenario === "output first") sock.onmessage({ data: new ArrayBuffer(1) });
if (scenario === "replaced") { ctx.termSocket = {}; }
sock.onclose?.();
console.log(JSON.stringify(written));
"""


def node(script, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", script, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.parametrize("first,second,heading", [("stats", "left", "Waiting in downloads"), ("left", "stats", "Stats")])
def test_a_late_answer_does_not_fill_the_pane_of_the_one_picked_since(first, second, heading):
    shown = node(PANES, str(JS / "activity.js"), json.dumps([first, second]))
    assert shown == {"title": heading, "heading": heading}


def test_terminal_says_so_when_it_closes_before_any_output():
    written = node(TERMINAL, str(JS / "attempts.js"), "silent")
    assert len(written) == 1 and "WebSocket" in written[0]


def test_terminal_stays_quiet_when_it_closes_after_output():
    assert node(TERMINAL, str(JS / "attempts.js"), "output first") == ["output"]


def test_terminal_ignores_the_close_of_a_socket_it_already_replaced():
    assert node(TERMINAL, str(JS / "attempts.js"), "replaced") == []
