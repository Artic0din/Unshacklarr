"""The light and dark looks: every text and edge colour readable on what it sits on, in both."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
CSS = (STATIC / "app.css").read_text()
FIXED = {"term-bg"}  # the download output stays dark in either look


def block(selector):
    start = CSS.index(selector) + len(selector) if selector.endswith("{") else CSS.index("{", CSS.index(selector)) + 1
    return CSS[start:CSS.index("}", start)]


def colours(text):
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\b", text))


DARK = colours(block(":root {"))
LIGHT = {**DARK, **colours(block(':root[data-theme="light"] {'))}


def luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


TEXT = [("text", "bg"), ("text", "panel"), ("text", "well"), ("text", "field-bg"), ("text", "accent-tint"),
        ("muted", "bg"), ("muted", "panel"), ("muted", "well"), ("accent", "bg"), ("accent", "panel"), ("accent", "accent-tint"),
        ("accent-ink", "accent"), ("ok", "panel"), ("warn", "bg"), ("warn", "panel"), ("warn-ink", "warn"),
        ("err", "bg"), ("err", "panel"), ("err-ink", "err"), ("tk-video", "panel"), ("tk-audio", "panel"), ("code-string", "bg")]
EDGES = [("field-line", "field-bg"), ("field-line", "panel")]


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_every_text_and_field_edge_meets_its_contrast(theme):
    tokens = DARK if theme == "dark" else LIGHT
    low = [f"{a} on {b}: {contrast(tokens[a], tokens[b]):.2f}" for pairs, need in ((TEXT, 4.5), (EDGES, 3))
           for a, b in pairs if contrast(tokens[a], tokens[b]) < need]
    assert not low


def test_the_light_look_sets_every_colour_and_follows_the_system_too():
    light = block(':root[data-theme="light"] {')
    assert set(DARK) - FIXED - {"net-chip"} <= set(colours(light)) | {"net-chip"}
    assert block('@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) {').strip() == light.strip()


def test_a_chosen_look_is_applied_before_the_first_paint():
    head = (STATIC / "index.html").read_text().split("</head>")[0]
    assert 'localStorage.getItem("theme")' in head and "dataset.theme" in head


def test_the_look_follows_the_choice_and_the_system():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const store = {}, meta = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } }, root = { dataset: {} };
const ctx = { localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; }, removeItem: (k) => { delete store[k]; } },
  document: { documentElement: root, querySelector: () => meta },
  getComputedStyle: () => ({ getPropertyValue: () => (root.dataset.theme === "light" ? " #f6f3ee" : " #171614") }) };
vm.createContext(ctx);
vm.runInContext(src.match(/^const THEMES = .*?^}\nfunction setTheme\(.*?^}/ms)[0], ctx);
const out = [];
for (const choice of ["light", "dark", "system"]) { ctx.setTheme(choice); out.push([ctx.themeChoice(), root.dataset.theme ?? null, meta.attrs.content, store.theme ?? null]); }
store.theme = "sepia";
out.push(ctx.themeChoice());
console.log(JSON.stringify(out));
"""
    out = subprocess.run(["node", "-e", script, "--", str(STATIC / "js" / "core.js")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ('[["light","light","#f6f3ee","light"],["dark","dark","#171614","dark"],'
                                  '["system",null,"#171614",null],"system"]')
