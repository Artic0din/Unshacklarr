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


def rules_of(selector, *, within=None):
    """The declarations of every rule whose selector list names `selector` exactly (a media query's rules too)."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    return [body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
            if selector in [part.strip() for part in sel.split(",")]]


def test_a_link_drawn_as_a_button_takes_the_buttons_colour_not_the_browsers_link_blue():
    assert any(re.search(r"(?<![\w-])color:\s*inherit", body) for body in rules_of(".btn"))
    assert any("text-decoration: none" in body for body in rules_of("a.btn"))


def test_a_text_fields_focus_is_a_2px_ring_on_every_field_rule():
    """The old 1px accent edge plus a 16% halo was 2.4:1 (dark) and 1.6:1 (light) against the resting edge."""
    focus = [".remote-form input:focus", ".remote-form select:focus", "input[type=time]:focus:not(.bad)"]
    for selector in focus:
        assert any("outline: 2px solid var(--accent)" in body for body in rules_of(selector)), selector
    general = [body for body in rules_of("textarea):focus:not(.bad)") + rules_of(":is(input[type=text], input[type=url], input[type=search], input[type=number], input[type=password], select, textarea):focus:not(.bad)")]
    assert any("outline: 2px solid var(--accent)" in body for body in general)
    for selector in (".card input:focus", ".remote-form input:focus"):
        assert not any("outline: none" in body or "box-shadow" in body for body in rules_of(selector)), selector


def test_the_other_pill_carries_a_ring_because_its_input_has_no_edge():
    assert any("outline: 2px solid var(--accent)" in body for body in rules_of(".rt-custom:focus-within"))
    assert any("outline: none !important" in body for body in rules_of(".rt-custom input"))  # not a second ring inside the pill


@pytest.mark.parametrize("selector", [".jx.again:focus-visible", ".jx:focus-visible", ".jact.primary:focus-visible", ".jact.danger:focus-visible"])
def test_an_activity_icon_button_keeps_the_page_focus_ring(selector):
    bodies = rules_of(selector)
    assert bodies and not any("outline" in body for body in bodies)  # the global :focus-visible ring shows


def test_the_segmented_controls_ring_is_drawn_inside_its_scroller():
    assert any(re.search(r"outline-offset:\s*-2px", body) for body in rules_of(".seg button:focus-visible"))


def test_a_choice_chips_edge_is_a_field_edge():
    assert any("border: 1.5px solid var(--field-line)" in body for body in rules_of(".ax-seg button"))


def test_a_pressed_control_scales_to_96_percent():
    pressed = [body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if ".btn:active" in sel]
    assert pressed and all("scale(.96)" in body for body in pressed)


def test_remote_cdm_fields_are_16px_on_a_phone_so_ios_does_not_zoom():
    assert re.search(r"@media \(max-width: 700px\) \{ \.remote-form input, \.remote-form select \{ font-size: 16px; \} \}", CSS)


def test_every_dialog_or_menu_scroller_stays_put_at_its_end():
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    contained = {part.strip() for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if "overscroll-behavior: contain" in body for part in sel.split(",")}
    panes = {".con-list", ".con-detail"}  # columns of a page, not a dialog or a menu
    scrollers = {part.strip() for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
                 if re.search(r"(?<![\w-])overflow(?:-y)?:\s*(?:auto|scroll)", body) for part in sel.split(",")}
    assert scrollers - contained - panes == set()
    assert {".modal", ".news-rels"} <= contained


def test_the_series_load_error_spans_the_whole_wall_like_the_empty_message():
    assert any("grid-column: 1 / -1" in body for body in rules_of(".failed")) and any("grid-column: 1 / -1" in body for body in rules_of(".empty"))


def test_the_loading_boxes_show_on_the_page_ground_and_the_wall_says_it_is_loading():
    assert any("background: var(--well)" in body for body in rules_of(".skeleton"))
    page = (STATIC / "index.html").read_text()
    wall = re.search(r'<div class="wall" id="wall" aria-busy="true">(.*?)<div class="skeleton">', page, flags=re.S).group(1)
    assert 'role="status"' in wall and "Loading series…" in wall


def test_the_country_list_is_no_wider_than_its_input():
    assert any("max-width: 420px" in body and ".wz-main .cp-list" in sel
               for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS))
    assert re.search(r"\.wz-main \.cp-input, \.wz-main \.cp-list, \.wz-tiles,[^{}]*\{ max-width: none; \}", CSS)  # a phone: the full width of both
