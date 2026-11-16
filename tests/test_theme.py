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
EDGES = [("field-line", "field-bg"), ("field-line", "panel"), ("field-line", "bg"), ("accent", "panel")]  # a control's edge, and the marks of a chosen one (WCAG 1.4.11)


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


def rule(selector):
    """The bodies of every rule whose selector list holds exactly this selector."""
    found = [body for names, body in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))
             if selector in [n.strip() for n in re.split(r",(?![^()]*\))", names)]]
    assert found, f"no rule for {selector}"
    return " ".join(found)


def test_a_toggle_pill_has_an_edge_you_can_see_and_a_tick_when_on():
    assert "var(--field-line)" in rule(".pill")  # off: an edge at 3:1, not the faint divider
    on = rule(".pill:has(input:checked)::before")
    assert "clip-path" in on and rule("#sel-toggle[aria-pressed=\"true\"]::before").count("clip-path") == 1  # the Select toggle's tick


def test_the_active_country_option_has_an_accent_bar_not_only_a_tint():
    assert "inset 3px 0 0 var(--accent)" in rule(".cp-list li.on")


def test_a_failed_or_stopped_step_has_a_mark_and_the_word_is_there_for_everyone():
    assert "\\2715" in rule(".steps .fail :is(.l, .s)::before") and "\\25A0" in rule(".steps .halt :is(.l, .s)::before")
    assert "clip" in rule(".sr-only")


def test_a_phone_widens_the_header_only_for_a_service_with_something_to_say():
    phone = CSS[CSS.index("@media (max-width: 700px) {"):]
    assert "small:not(:empty)" not in phone  # "Checking…" is brief: it must not make the header jump on every load
    assert "[data-state=warn], [data-state=down]" in phone

FADED_TEXT = [".sched-card.other", ".cal-cell.out", ".inbox-filters b", ".seg button span", ".toolbar .pill span", ".con-filters button span",
              ".job-counts button.off", ".tools span.optional-missing", ".oneoff-preview .file", ".wall.selecting .poster:not(.picked)"]


@pytest.mark.parametrize("selector", FADED_TEXT)
def test_text_is_never_faded_with_opacity(selector):
    # opacity composites the text with what is behind it, below 4.5:1 (WCAG 1.4.3); a quieter look takes a colour token instead
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))
    faded = [sel.strip() for sel, body in rules if re.search(r"(?<![\w-])opacity\s*:\s*0?\.\d", body)
             and any(name.strip().split(":hover")[0].split(":focus-within")[0] == selector for name in sel.split(","))]
    assert not faded

def test_reduced_motion_also_stills_what_before_and_after_draw():
    """`*` matches elements only: a looping ::before (the running step's shimmer) kept moving."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)  # a commented-out rule does nothing
    moving = [sel.strip() for sel, body in re.findall(r"([^{}]*::(?:before|after)[^{}]*)\{([^{}]*)\}", css)
              if re.search(r"animation:\s*(?!none)[\w-]+", body)]
    assert moving, "no animated ::before/::after left to check"
    stilled = [{part.strip() for part in sel.split(",")} for sel in
               re.findall(r"@media \(prefers-reduced-motion: reduce\) \{ ([^{]+)\{[^}]*animation: none !important", css)]
    assert any({"*", "::before", "::after"} <= parts for parts in stilled), moving


def css_at(width):
    """The text of every @media block whose min-width / max-width conditions hold at `width` px."""
    css, out = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S), []
    for match in re.finditer(r"@media ([^{]+)\{", css):
        depth, end = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        conditions = re.findall(r"\((min|max)-width:\s*(\d+)px\)", match.group(1))
        if conditions and all((width >= int(px)) if kind == "min" else (width <= int(px)) for kind, px in conditions):
            out.append(css[match.end():end - 1])
    return "\n".join(out)


@pytest.mark.parametrize("width", [701, 800, 1024, 1130, 1240])
def test_a_tablet_header_gives_up_its_words_to_stay_on_one_row(width):
    # the nav, the status buttons and the sync button together need more than a tablet has: it wrapped to two rows
    rules = css_at(width)
    assert re.search(r"#sync \.sync-text \{ position: absolute", rules)  # the sync button as an icon, named by its aria-label
    assert re.search(r"\.health span:not\(\.dot\) \{ position: absolute", rules)  # the status buttons as dots, named for a screen reader
    assert re.search(r"\.update-pill span \{ display: none; \}", rules)  # the update pill as an icon, named by its aria-label
    assert 'id="sync" aria-label="Run sync now"' in (STATIC / "index.html").read_text()


@pytest.mark.parametrize("width", [701, 941, 1024, 1041, 1130, 1240])
def test_a_status_with_words_takes_its_own_row_wherever_the_words_cannot_fit(width):
    # "Unreachable" and "Update available" need about 130 px each: at 941 one pushed the sync button alone onto a second row
    assert re.search(r"\.health \{ order: 10; flex-basis: 100%", css_at(width))
    assert "#bell { margin-left: auto; }" in css_at(width)


@pytest.mark.parametrize("width", [941, 1041, 1100])
def test_the_header_with_an_update_pill_is_tight_enough_for_one_row(width):
    # brand, version, nav, dots, pill, bell and sync need about 995 px with the tablet gap, and about 905 with the name out of sight
    assert "gap: var(--sp-3)" in css_at(width)
    assert (width > 1040) or ".brand span { position: absolute" in css_at(width)


def test_a_compact_sync_button_keeps_its_last_sync_time_for_assistive_tech():
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert "#sync span { display: none; }" not in css  # display: none dropped "Last sync …" and "Sync running…" from the tree
    assert 'aria-describedby="last-sync"' in (STATIC / "index.html").read_text()
    for width in (701, 1024, 600):  # the phone too: nothing hides the time with display: none
        assert not re.search(r"\.last-sync \{ display: none; \}", css_at(width))
    assert re.search(r"\(prefers-reduced-motion: reduce\) \{ #sync\.spin \{ box-shadow", css)  # still running when nothing spins


def test_a_wide_desktop_header_keeps_its_words():
    wide = css_at(1441)
    assert "#sync .sync-text" not in wide and ".health span:not(.dot)" not in wide and ".update-pill span" not in wide
    assert ".health { order: 10" not in wide
