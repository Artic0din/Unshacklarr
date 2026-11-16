"""Small fixes to the page's scripts (static/js, sw.js), each run for real in Node with only the globals it reaches named."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
JS = STATIC / "js"

# `any` stands in for every DOM object or helper a test does not look at; sandbox() hands it out for any global not named.
PRELUDE = r"""
const fs = require("fs"), vm = require("vm");
const read = (file) => fs.readFileSync(file, "utf8");
const any = new Proxy(function () {}, { get: (_, k) => (k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : any), apply: () => any, construct: () => any, set: () => true });
const el = (tag, props = {}, ...kids) => ({ tag, ...props, kids });
function sandbox(named = {}) {
  const own = { el, structuredClone, ...named };
  return vm.createContext(new Proxy(own, { has: () => true, get: (t, k) => (k in t ? t[k] : k in globalThis ? globalThis[k] : any), set: (t, k, v) => ((t[k] = v), true) }));
}
const grab = (src, re) => { const m = src.match(re); if (!m) throw Error(`not in the source: ${re}`); return m[0]; };
"""


def node(body, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", PRELUDE + body, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_service_defaults_still_draw_when_one_service_cannot_list_its_options():
    shown = node(r"""
const src = read(process.argv[1]);
let drawn = null;
const ctx = sandbox({
  S: { config: { service_defaults: { GONE: {} }, settings: {} }, dlOptions: [], services: ["GONE"] },
  loadServiceOptions: async () => { throw Error("502"); },
  $: (sel) => (sel === "#svc-defaults" ? { replaceChildren: (...kids) => { drawn = kids.map((k) => k.className ?? k.tag); } } : any),
});
vm.runInContext(grab(src, /async function renderServiceDefaults\b[\s\S]*?\n}\n/), ctx);
ctx.renderServiceDefaults().then(() => console.log(JSON.stringify(drawn)), (e) => console.log(JSON.stringify("threw: " + e.message)));
""", str(JS / "settings-options.js"))
    assert shown == ["svc-block"]
