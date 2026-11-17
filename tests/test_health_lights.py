"""The header's lights show the server's last check as soon as the page opens, not after the slow loads."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"

PAINT = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const fn = src.match(/function paintLights\b[\s\S]*?\n}\n/)[0];
const light = () => ({ dataset: {}, title: "", dot: { className: "" }, small: { textContent: "" },
  querySelector(sel) { return sel === ".dot" ? this.dot : this.small; } });
const lights = { unshackle: light(), sonarr: light() };
const ctx = { document: { querySelector: (sel) => lights[sel.match(/data-health=(\w+)/)[1]] } };
vm.createContext(ctx);
vm.runInContext(fn, ctx);
ctx.paintLights({ unshackle: { ok: true, version: "6.1" }, sonarr: { ok: false, error: "Sonarr is unreachable" } });
console.log(JSON.stringify(Object.fromEntries(Object.entries(lights).map(([k, l]) => [k, [l.dataset.state, l.dot.className, l.small.textContent, l.ariaLabel]]))));
"""


def test_lights_paint_from_a_status_answer():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PAINT, "--", str(JS / "schedule.js")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    # the name says the state: a phone shows only the dot
    assert json.loads(out.stdout) == {"unshackle": ["ok", "dot ok", "", "Unshackle: running"],
                                      "sonarr": ["down", "dot down", "Unreachable", "Sonarr: unreachable"]}


def test_page_asks_the_cached_lights_before_waiting_for_its_state():
    boot = (JS / "setup.js").read_text(encoding="utf8")
    logged_in = boot.index("if (!session.logged_in) return showLogin();")
    lights = re.search(r'api\("/api/status"\)\.then\(\(h\) => \{ if \(!\$\("\[data-health=unshackle\]"\)\.dataset\.state\) paintLights\(h\)', boot)
    assert lights, "the page never asks the plain, cached /api/status, or paints it over a newer answer"
    assert logged_in < lights.start() < boot.index("await stateAsked")


def test_cached_lights_never_paint_over_a_newer_answer():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = r"""
const fs = require("fs"), vm = require("vm");
const boot = fs.readFileSync(process.argv[1], "utf8");
const then = boot.match(/api\("\/api\/status"\)\.then\((\(h\) => \{[^\n]*?\}),/)[1];
const painted = [], light = { dataset: {} };
const ctx = { $: () => light, paintLights: (h) => painted.push(h.from) };
vm.createContext(ctx);
const onCached = vm.runInContext(then, ctx);
onCached({ from: "cached-first" });
light.dataset.state = "down";  // the live check painted meanwhile
onCached({ from: "cached-late" });
console.log(JSON.stringify(painted));
"""
    out = subprocess.run(["node", "-e", script, "--", str(JS / "setup.js")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["cached-first"]
