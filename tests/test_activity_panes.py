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
sock.onclose?.(scenario === "clean" ? { code: 1000 } : { code: 1006 });
console.log(JSON.stringify(written));
"""


def node(script, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", script, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.parametrize("suggestions", [{"2": {"service": "SBS", "count": 8}}, {}])
@pytest.mark.parametrize("failure", [False, True])
def test_series_refresh_displays_new_search_before_a_slower_saved_result(suggestions, failure):
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8"), suggestions = JSON.parse(process.argv[2]);
const failure = JSON.parse(process.argv[3]), errors = [];
const s = { tvdbId: 1, id: 10, title: "Show" }, stub = { replaceChildren() {} };
let rendered;
const pages = Object.fromEntries(Array.from({length: 10}, (_, i) => [i + 1, {url: `https://iview/season-${i + 1}`} ]));
const ctx = { S: { services: ["IV", "SBS", "NF"], config: { series: { 1: {season_pages: pages} } } }, current: s, epElsewhere: { 3: { service: "NF" } }, epElsewhereFresh: false,
  $: () => stub, el: () => ({}), seriesSvcs: () => "IV", slowHint: () => 0, clearTimeout() {},
  api: async (path, opts) => {
    if (opts.wait < 1100) throw Error("No answer before slow season pages and services finish");
    return { elsewhere: suggestions, elsewhere_error: failure ? "Search failed" : undefined, available: {}, checked: "2026-11-13T02:00:00Z" };
  },
  viewAvail: (x) => x, localTitles() {}, renderSeason: () => { rendered = ctx.epElsewhere; },
  renderPreview() {}, renderCatchUp() {}, checkLabel() {}, toast: (message) => { errors.push(message); } };
vm.createContext(ctx);
vm.runInContext(src.match(/async function askService\b[\s\S]*?\n}\n/)[0], ctx);
(async () => {
  await ctx.askService(s);
  const cache = src.match(/api\(`\/api\/probe\/\$\{s.tvdbId\}`\)\.then\((\(hit\) => \{[\s\S]*?)\n    }\)\.catch/)[1] + "\n}";
  ctx.s = s;
  vm.runInContext(`(${cache})({elsewhere: {4: {service: "STAN"}}, checked: "2026-11-13T03:00:00Z", elsewhere_checked: "2026-11-12T02:00:00Z"})`, ctx);
  console.log(JSON.stringify({ rendered, kept: ctx.epElsewhere, errors }));
})();
""", str(JS / "series.js"), json.dumps(suggestions), json.dumps(failure))
    assert shown == {"rendered": suggestions, "kept": suggestions,
                     "errors": ["Availability refreshed, but the search on other services failed: Search failed"] if failure else []}


def test_other_service_suggestions_are_visible_when_every_aired_episode_is_on_disk():
    shown = node(r"""
const fs = require("fs"), vm = require("vm"), src = fs.readFileSync(process.argv[1], "utf8");
const box = { hidden: true, classList: {toggle() {}}, replaceChildren(...kids) { this.kids = kids; } };
const ctx = { $: () => box, current: {tvdbId: 1}, S: {config: {series: {1: {service: "BINGE"}}}},
  epSeasons: {7: [{id: 1, seasonNumber: 7, hasFile: true}, {id: 2, seasonNumber: 7, hasFile: false}]},
  epAvail: {}, epBusy: new Map(), epPages: {}, epElsewhere: {7: {service: "NINE", count: 5, url: "https://9now/paramedics"}},
  state: (e) => e.hasFile ? "disk" : "soon", belowAsked: () => false, seriesSvcs: () => "BINGE", seasonSvc: () => "BINGE",
  document: {querySelectorAll: () => []}, el: (tag, props = {}, ...kids) => ({tag, ...props, kids}) };
vm.createContext(ctx);
vm.runInContext(src.match(/function renderCatchUp\b[\s\S]*?\n}\n/)[0], ctx);
ctx.renderCatchUp();
console.log(JSON.stringify({hidden: box.hidden, content: JSON.stringify(box.kids || [])}));
""", str(JS / "series.js"))
    assert shown["hidden"] is False
    assert "Season 7 is on NINE (5 episodes)" in shown["content"]


@pytest.mark.parametrize("first,second,heading", [("stats", "left", "Waiting in downloads"), ("left", "stats", "Stats")])
def test_a_late_answer_does_not_fill_the_pane_of_the_one_picked_since(first, second, heading):
    shown = node(PANES, str(JS / "activity.js"), json.dumps([first, second]))
    assert shown == {"title": heading, "heading": heading}


def test_terminal_says_so_when_it_closes_before_any_output():
    written = node(TERMINAL, str(JS / "attempts.js"), "silent")
    assert len(written) == 1 and "WebSocket" in written[0]


def test_terminal_stays_quiet_when_it_closes_after_output():
    assert node(TERMINAL, str(JS / "attempts.js"), "output first") == ["output"]


def test_terminal_stays_quiet_when_the_server_ends_it_cleanly_with_no_output():
    assert node(TERMINAL, str(JS / "attempts.js"), "clean") == []  # a cancelled episode has no log


def test_terminal_ignores_the_close_of_a_socket_it_already_replaced():
    assert node(TERMINAL, str(JS / "attempts.js"), "replaced") == []
