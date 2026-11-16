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
        ("accent-ink", "accent"), ("ok", "panel"), ("warn", "bg"), ("warn", "panel"), ("warn-ink", "warn"), ("warn", "warn-tint"),
        ("err", "err-tint"), ("muted", "well"),
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
vm.runInContext("themePicked = null", ctx);
store.theme = "sepia";
out.push(ctx.themeChoice());
ctx.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
vm.runInContext("localStorage = this.localStorage", ctx);
ctx.setTheme("light"); out.push([ctx.themeChoice(), root.dataset.theme]);  // storage blocked: the pick still holds this visit
console.log(JSON.stringify(out));
"""
    out = subprocess.run(["node", "-e", script, "--", str(STATIC / "js" / "core.js")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ('[["light","light","#f6f3ee","light"],["dark","dark","#171614","dark"],'
                                  '["system",null,"#171614",null],"system",["light","light"]]')


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_a_tick_on_the_accent_fill_stands_out_in_both_looks(theme):
    text = block(":root {") if theme == "dark" else block(':root[data-theme="light"] {')
    stroke = "#" + re.search(r"--tick: url\(.*?stroke='%23([0-9a-fA-F]{6})'", text).group(1)
    accent = (DARK if theme == "dark" else LIGHT)["accent"]
    assert contrast(stroke, accent) >= 3  # a meaningful graphic: WCAG 1.4.11


def test_icons_drawn_in_a_colour_take_it_from_a_token():
    # a data-URI icon can't read a variable: one with a fixed colour is a mask (black) or a per-look token
    rules = re.sub(r"--[\w-]+: url\(\"data:image/svg\+xml[^)]*\)\)?;", "", CSS)
    assert set(re.findall(r"stroke='%23([0-9a-fA-F]{3,6})'", rules)) <= {"000"}


def test_no_later_rule_reshapes_a_tag():
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))
    shared = next(i for i, (_, body) in enumerate(rules) if "text-transform: none" in body and "var(--well)" in body)
    names = [name.strip() for name in rules[shared][0].split(",")]
    shaping = re.compile(r"(?:^|;)\s*(?:padding|border|border-radius|font-size|text-transform)\s*:")
    late = [sel.strip() for i, (sel, body) in enumerate(rules) if i > shared and shaping.search(body)
            and any(name in [s.strip() for s in sel.split(",")] for name in names)]
    assert not late  # the shared shape is the last word for every tag


FADED_TEXT = [".sched-card.other", ".cal-cell.out", ".inbox-filters b", ".seg button span", ".toolbar .pill span", ".con-filters button span",
              ".job-counts button.off", ".tools span.optional-missing", ".oneoff-preview .file", ".wall.selecting .poster:not(.picked)"]


@pytest.mark.parametrize("selector", FADED_TEXT)
def test_text_is_never_faded_with_opacity(selector):
    # opacity composites the text with what is behind it, below 4.5:1 (WCAG 1.4.3); a quieter look takes a colour token instead
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))
    faded = [sel.strip() for sel, body in rules if re.search(r"(?<![\w-])opacity\s*:\s*0?\.\d", body)
             and any(name.strip().split(":hover")[0].split(":focus-within")[0] == selector for name in sel.split(","))]
    assert not faded
