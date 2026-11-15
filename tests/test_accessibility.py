import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"


def node(script):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", script, "--", str(JS / "core.js")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_errors_and_toasts_with_an_action_stay_until_dismissed():
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const timers = [], list = [];
const node = () => ({ children: [], attrs: {}, className: "", removed: false,
  setAttribute(k, v) { this.attrs[k] = v; }, append(...c) { this.children.push(...c); }, remove() { this.removed = true; }, matches: () => false });
const ctx = { document: { createElement: node }, el: (tag, props) => ({ tag, ...props }), $: () => ({ append: (t) => list.push(t) }),
  onTop() {}, getSelection: () => ({ containsNode: () => false }), setTimeout: (fn) => { timers.push(fn); return 0; } };
vm.createContext(ctx);
vm.runInContext(src.match(/^function toast\(.*?^\}/ms)[0], ctx);
const out = {};
ctx.toast("Saved");
out.plainGoesByItself = timers.length === 1;
out.plainButtons = list[0].children.length;
ctx.toast("Could not save", true);
out.errorGoesByItself = timers.length > 1;
const error = list[1];
out.errorDismiss = error.children.map((c) => c.textContent);
error.children[0].onclick();
out.errorRemoved = error.removed;
let undone = false;
ctx.toast("Hidden", false, ["Undo", () => { undone = true; }]);
const choice = list[2];
out.choiceGoesByItself = timers.length > 2;
out.choiceButtons = choice.children.map((c) => c.textContent);
choice.children[0].onclick();
out.choiceUndone = undone && choice.removed;
console.log(JSON.stringify(out));
""")
    assert shown == {
        "plainGoesByItself": True, "plainButtons": 0,
        "errorGoesByItself": False, "errorDismiss": ["Dismiss"], "errorRemoved": True,
        "choiceGoesByItself": False, "choiceButtons": ["Undo", "Dismiss"], "choiceUndone": True,
    }


def test_the_drawer_makes_the_page_inert_and_gives_focus_back():
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const drawer = { inert: true }, header = { inert: false }, main = { inert: false };
const focused = [];
const poster = { name: "poster", focus: () => focused.push("poster") };
const opener = (over) => ({ name: "opener", isConnected: true, getClientRects: () => [{}], focus: () => focused.push("opener"), ...over });
const ctx = { $: () => drawer, document: { querySelectorAll: () => [header, main], querySelector: (s) => s === '.poster[data-tvdb="7"]' ? poster : null } };
vm.createContext(ctx);
vm.runInContext(src.match(/^function drawerModal\(.*?^\}/ms)[0] + src.match(/^function returnFocus\(.*?^\}/ms)[0], ctx);
const out = {};
ctx.drawerModal(true);
out.open = [drawer.inert, header.inert, main.inert];
ctx.drawerModal(false);
out.closed = [drawer.inert, header.inert, main.inert];
const where = (o) => { focused.length = 0; ctx.returnFocus(o, 7); return focused[0]; };
out.back = where(opener());
out.gone = where(opener({ isConnected: false }));
out.hidden = where(opener({ getClientRects: () => [] }));
out.none = where(null);
console.log(JSON.stringify(out));
""")
    assert shown == {
        "open": [False, True, True], "closed": [True, False, False],
        "back": "opener", "gone": "poster", "hidden": "poster", "none": "poster",
    }
