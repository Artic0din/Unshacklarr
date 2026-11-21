"""The dark palette: every text and edge colour readable on what it sits on."""
import json
import math
import re
from pathlib import Path

import pytest

from css_assets import STYLESHEET_LINK, load_css
from test_ui_misc import JS, node

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
CSS = load_css()


def test_split_stylesheets_load_in_cascade_order():
    links = STYLESHEET_LINK.findall((STATIC / "index.html").read_text())
    assert [path for path, _ in links] == [
        f"/css/{name}.css"
        for name in ("base", "shell", "series", "settings", "activity", "schedule", "responsive", "controls")
    ]


def block(selector):
    start = CSS.index(selector) + len(selector) if selector.endswith("{") else CSS.index("{", CSS.index(selector)) + 1
    return CSS[start:CSS.index("}", start)]


def colours(text):
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\b", text))


DARK = colours(block(":root {"))
for name, target in re.findall(r"--([\w-]+):\s*var\(--([\w-]+)\)", block(":root {")):
    DARK[name] = DARK[target]


def luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


TEXT = [("text", "bg"), ("text", "panel"), ("text", "well"), ("text", "field-bg"), ("text", "accent-tint"),
        ("muted", "bg"), ("muted", "panel"), ("muted", "well"), ("accent", "bg"), ("accent", "panel"), ("accent", "accent-tint"),
        ("accent-ink", "accent"), ("ok", "panel"), ("ok", "bg"), ("ok", "well"), ("ok", "ok-tint"), ("accent-ink", "ok"), ("warn", "bg"), ("warn", "panel"), ("warn-ink", "warn"), ("warn", "warn-tint"),
        ("err", "err-tint"), ("muted", "well"), ("ok", "accent-tint"), ("muted", "bg"),
        ("text", "ok-tint"), ("muted", "ok-tint"), ("warn", "ok-tint"),
        ("err", "bg"), ("err", "panel"), ("err-ink", "err"), ("tk-video", "panel"), ("tk-audio", "panel"), ("code-string", "bg"),
        ("text", "text-selection"), ("muted", "term-bg"), ("err", "term-bg"), ("text", "term-bg"), ("text", "bar"), ("muted", "bar"), ("muted", "well"), ("err", "err-tint")]
EDGES = [("field-line", "field-bg"), ("field-line", "panel"), ("field-line", "bg"), ("accent", "panel"), ("ok", "panel"), ("ok", "bg"),
         ("field-line", "bar"), ("accent", "bar"), ("err", "err-tint"), ("warn", "warn-tint"), ("accent", "accent-tint"), ("field-line", "well")]  # a control's edge, the marks of a chosen one, and a success dot (WCAG 1.4.11)


def test_every_text_and_field_edge_meets_its_contrast():
    low = [f"{a} on {b}: {contrast(DARK[a], DARK[b]):.2f}" for pairs, need in ((TEXT, 4.5), (EDGES, 3))
           for a, b in pairs if contrast(DARK[a], DARK[b]) < need]
    assert not low


def blend(top, under, share):
    return "#" + "".join(f"{round(int(top[i:i + 2], 16) * share + int(under[i:i + 2], 16) * (1 - share)):02x}" for i in (1, 3, 5))


def hue(hex_colour):
    """OKLCH hue in degrees (Ottosson's OKLab)."""
    r, g, b = [((c / 12.92) if c <= .04045 else ((c + .055) / 1.055) ** 2.4) for c in (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))]
    l, m, s = (x ** (1 / 3) for x in (.4122214708 * r + .5363325363 * g + .0514459929 * b,
                                      .2119034982 * r + .6806995451 * g + .1073969566 * b,
                                      .0883024619 * r + .2817188376 * g + .6299787005 * b))
    return math.degrees(math.atan2(.0259040371 * l + .7827717662 * m - .8086757660 * s,
                                   1.9779984951 * l - 2.4285922050 * m + .4505937099 * s)) % 360


def test_success_is_a_green_apart_from_the_lime_accent():
    gap = abs(hue(DARK["ok"]) - hue(DARK["accent"]))
    assert min(gap, 360 - gap) >= 15  # one hue cannot mean both "running" and "healthy"


def test_ok_text_on_its_own_tint_is_readable():
    # the pills, notes and rows tint their ground with up to 14% of --ok
    low = [f"{ground}: {contrast(DARK['ok'], blend(DARK['ok'], DARK[ground], .14)):.2f}" for ground in ("bg", "panel", "well")
           if contrast(DARK["ok"], blend(DARK["ok"], DARK[ground], .14)) < 4.5]
    assert not low


@pytest.mark.parametrize("badge", [
    ".ck-pill.ok", ".sched-st.ok", ".chip.disk", ".chip.o-downloaded", ".rg-chip.ok",
    ".ep-on", ".ep-on.other", ".res.r1080", ".poster.on:not(:has(.sick)) .svc",
])
def test_a_done_or_healthy_badge_is_green_not_the_accent(badge):
    rules = rules_of(badge)
    assert rules, f"{badge} has no status colour"
    last = rules[-1]  # the later rule wins
    assert "color: var(--ok)" in last
    assert "background: var(--ok-tint)" in last


def test_region_country_chips_are_neutral():
    last = rules_of(".rg-chip")[-1]
    assert "color: var(--muted)" in last
    assert "background: var(--well)" in last


def test_complete_season_counts_are_green():
    rules = rules_of(".seasons button small.complete")
    assert rules and "color: var(--ok)" in rules[-1]


def test_catch_up_status_colours_win_on_renumbered_lines():
    assert "color: var(--ok)" in rules_of(".ep-catchup .ok")[-1]
    assert "color: var(--warn)" in rules_of(".ep-catchup .warn")[-1]
    # The more specific small.renum rule must not override either status colour.
    assert all(not re.search(r"\bcolor\s*:", body) for body in rules_of(".ep-catchup small.renum"))


def test_managed_schedule_cards_have_a_neutral_border():
    assert "border-color: var(--line-strong)" in rules_of(".sched-card.mine")[-1]


def test_schedule_service_chip_is_neutral():
    last = [body for body in rules_of(".sched-card .svc") if re.search(r"\bcolor\s*:", body)][-1]
    assert "color: var(--muted)" in last
    assert "background: var(--well)" in last


def test_late_schedule_status_is_amber_like_waiting_for_import():
    last = rules_of(".sched-st.late")[-1]
    assert last == rules_of(".sched-st.wait")[-1]
    assert "color: var(--warn)" in last
    assert "background: var(--warn-tint)" in last


def test_a_poster_with_a_failure_icon_has_no_green_service_chip_or_frame():
    assert any("color: var(--muted)" in body for body in rules_of(".poster .svc"))
    assert not any("var(--ok)" in body for body in rules_of(".poster .svc"))
    # a series being downloaded is the normal state: its art gets no ring at all (the accent means selected)
    assert not any("var(--ok)" in body for body in rules_of(".poster.on .art") + rules_of(".poster.on:not(:has(.sick)) .art"))


@pytest.mark.parametrize("badge", [".cal-count i.mine"])
def test_managed_month_groups_use_neutral_colours(badge):
    last = rules_of(badge)[-1]
    assert "color: var(--text)" in last
    assert "background: var(--well)" in last


def test_an_import_needed_chip_has_the_same_attention_colour_as_kept():
    import_rules = rules_of(".chip.o-import")
    assert import_rules, "Import needed has no status colour"
    assert import_rules[-1] == rules_of(".chip.o-kept")[-1]
    assert "color: var(--warn)" in import_rules[-1]
    assert "background: var(--warn-tint)" in import_rules[-1]


@pytest.mark.parametrize("badge", [".ep-off", ".chip.o-unavailable", ".ck-pill.absent"])
def test_an_absent_status_badge_is_muted_and_outlined_without_fill(badge):
    last = rules_of(badge)[-1]
    assert "color: var(--muted)" in last
    assert "background: transparent" in last
    assert "border-width: 1px" in last
    assert "border-style: solid" in last
    assert "border-color: var(--line)" in last


def test_browser_chrome_and_installed_app_match_the_dark_background():
    html = (STATIC / "index.html").read_text()
    manifest = json.loads((STATIC / "manifest.webmanifest").read_text())
    assert f'<meta name="theme-color" content="{DARK["bg"]}">' in html
    assert manifest["theme_color"] == manifest["background_color"] == DARK["bg"]


def test_a_tick_stands_out_on_its_fill():
    stroke = "#" + re.search(r"--tick: url\(.*?stroke='%23([0-9a-fA-F]{6})'", block(":root {")).group(1)
    assert stroke == DARK["accent-ink"]
    for fill in ("accent", "text"):
        assert contrast(stroke, DARK[fill]) >= 3  # a meaningful graphic: WCAG 1.4.11


def test_icons_drawn_in_a_colour_take_it_from_a_token():
    # A data-URI icon can't read a variable; inline icons with a fixed colour should be masks.
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


def test_the_active_country_option_is_outlined_all_round_not_barred_on_one_edge():
    on = rule(".cp-list li.on")
    assert "background: var(--accent-tint)" in on and "box-shadow: inset 0 0 0 1px var(--accent)" in on


def test_a_failed_or_stopped_step_has_a_mark_and_the_word_is_there_for_everyone():
    assert "\\2715" in rule(":is(.steps .fail .l, .step-caption.fail)::before")
    assert "\\25A0" in rule(":is(.steps .halt .l, .step-caption.halt)::before")
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
    """A solid 2px ring replaces the old 1px accent edge with a faint halo."""
    focus = [".remote-form input:focus", ".remote-form select:focus",
             "input[type=time]:focus:not(.bad)", "input[type=date]:focus:not(.bad)"]
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


@pytest.mark.parametrize("selector", [".jx.again:hover", ".jx:hover", ".jact.primary:hover", ".jact.danger:hover"])
def test_an_activity_icon_button_keeps_its_ring_while_hovered_and_focused(selector):
    bodies = rules_of(selector)
    assert bodies and not any("outline" in body for body in bodies)  # hover must not take the ring off a focused button


def test_the_segmented_controls_ring_is_drawn_inside_its_scroller():
    assert any(re.search(r"outline-offset:\s*-2px", body) for body in rules_of(".seg button:focus-visible"))


def test_the_subtitle_chip_focus_ring_fits_inside_the_clipped_cell():
    assert any(re.search(r"outline-offset:\s*-2px", body) for body in rules_of(".ep-subs-chip:focus-visible"))


def test_expanded_subtitles_span_the_episode_row_without_contributing_to_column_widths():
    assert any(
        "grid-column: 1 / -1" in body and "contain: inline-size" in body
        for body in rules_of(".ep-subs-detail")
    )


def test_the_lime_focus_ring_stands_out_on_dark_surfaces_and_selection():
    assert "outline: 2px solid var(--accent)" in rule(":focus-visible")
    # a selected segment draws its ring inside its accent outline: there the ring is in the text colour
    assert "outline-color: var(--text)" in rule('.seg button[aria-pressed="true"]:focus-visible')
    for fill in ("bg", "panel", "well", "bar", "accent-tint", "warn-tint", "term-bg"):
        assert contrast(DARK["accent"], DARK[fill]) >= 3, fill
    assert contrast(DARK["text"], DARK["accent-tint"]) >= 3


SELECTED = ['.seg button[aria-pressed="true"]', '.d-tabs button[aria-pressed="true"]', '.set-nav button[aria-current="true"]',
            '.ax-seg button[aria-pressed=true]', '.rt-custom.on', '.con-filters button[aria-pressed="true"]', 'button.pill[aria-pressed="true"]',
            '.pill:has(input:checked)', '.ds-nav a[aria-current="true"]', '.seasons button[aria-pressed="true"]', '.wz-tile[aria-checked=true]',
            '.wz-steps li.on button', '.bc-days button[aria-pressed="true"]', '#sel-toggle[aria-pressed="true"]', '.inbox-filters button[aria-pressed="true"]']


def test_every_pick_one_control_has_the_one_selected_look_and_grey_is_gone():
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    shared = [body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if "accent-tint" in body and ":is(" in sel
              and all(s in " ".join(sel.split()) for s in SELECTED)]
    assert shared, "one rule names every selected control"
    for decl in ("background: var(--accent-tint)", "border-color: var(--accent)", "color: var(--text)", "font-weight: 600"):
        assert decl in shared[-1], decl
    assert "--select" not in CSS and "#3c3e38" not in CSS  # the grey selection fill is retired


def test_an_option_row_is_one_segmented_track_that_scrolls_rather_than_wraps():
    track = rules_of(".ax-seg")[0]
    assert "flex-wrap: nowrap" in track and "overflow-x: auto" in track and "border: 1px solid var(--line)" in track
    assert any("border: 1px solid transparent" in body for body in rules_of(".ax-seg button"))  # the track draws the edge; selected adds the accent


def test_a_pressed_control_scales_to_96_percent():
    pressed = [body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if ".btn:active" in sel]
    assert pressed and all("scale(.96)" in body for body in pressed)


def test_remote_cdm_fields_are_16px_on_a_phone_so_ios_does_not_zoom():
    assert re.search(r"@media \(max-width: 700px\) \{ \.remote-form input, \.remote-form select \{ font-size: 16px; \} \}", CSS)


def test_every_dialog_or_menu_scroller_stays_put_at_its_end():
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    contained = {part.strip() for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if "overscroll-behavior: contain" in body for part in sel.split(",")}
    panes = {".con-list", ".con-detail", ".ug-list"}  # parts of a page, not a dialog or a menu: at their end the page scrolls on
    scrollers = {part.strip() for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
                 if re.search(r"(?<![\w-])overflow(?:-y)?:\s*(?:auto|scroll)", body) for part in sel.split(",")}
    assert scrollers - contained - panes == set()
    assert {".modal", ".news-rels"} <= contained
    assert not panes & contained


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


def test_a_compact_episode_check_button_keeps_its_name_when_the_text_is_hidden():
    assert re.search(r"\.ep-check-label(?:,\s*[^{}]+)?\s*\{\s*display:\s*none;", css_at(390))
    rendered = node(r"""
const check = { attrs: {}, setAttribute(key, value) { this.attrs[key] = value; },
  append(...kids) { this.kids = kids; },
};
const ctx = sandbox({ $: (sel) => sel === ".ep-check" ? check : null, epChecked: null });
vm.runInContext(grab(read(process.argv[1]), /^function checkLabel\b.*?^\}/ms), ctx);
ctx.checkLabel("Check ABC iview");
console.log(JSON.stringify({
  name: check.attrs["aria-label"], text: check.kids.find(k => k.className === "ep-check-label")?.textContent,
}));
""", str(JS / "series.js"))
    assert rendered == {"name": "Check ABC iview", "text": "Check ABC iview"}


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


def test_a_link_drawn_as_a_button_centres_its_text_and_still_hides():
    """A display on a.btn itself would beat the browser's [hidden] and show "Open Sonarr" with nowhere to go."""
    assert not any("display" in body for body in rules_of("a.btn"))
    assert any("display: inline-flex" in body and "align-items: center" in body for body in rules_of("a.btn:not([hidden])"))


def test_glow_paints_once_on_the_root_never_tiled_by_a_short_body():
    # A background on body alone spreads to the whole canvas but keeps body's size, so on a short page
    # (a list still loading) the glow repeats down the screen in bands.
    body = block("\nbody {")
    root = block("\nhtml {")
    assert "gradient" not in body and "background" not in body
    assert "radial-gradient" in root and "no-repeat" in root and "var(--bg)" in root
    glow_height = float(re.search(r"ellipse [\d.]+rem ([\d.]+)rem", root)[1])
    tile_height = float(re.search(r"/\s*100%\s+([\d.]+)rem", root)[1])
    assert tile_height > glow_height, "the tile must reach past the glow's fade, or its bottom edge shows as a line"


@pytest.mark.parametrize("track", [".wz-steps li + li::before", ".wz-progress i"])
def test_the_setup_wizard_tracks_show_on_its_sidebar(track):
    # the sidebar is --well; --line is the same colour there, so an empty track or connector would vanish
    rules = [body for body in rules_of(track) if "background:" in body]
    ground = re.search(r"background: var\(--([\w-]+)\)", rules[-1]).group(1)
    assert DARK[ground] != DARK["well"] and contrast(DARK[ground], DARK["well"]) >= 1.5


def test_every_corner_comes_from_a_radius_token():
    # a corner says what a thing is (field, tile, card, pill); a stray pixel value drifts from the design system
    values = re.findall(r"border-radius:\s*([^;}]+)", CSS) + re.findall(r'borderRadius: "([^"]+)"', "".join(f.read_text() for f in JS.glob("*.js")))
    stray = sorted({v.strip() for v in values if re.search(r"\d+px|--r-", v)})
    assert not stray
    assert set(re.findall(r"var\((--radius-[\w-]+)\)", CSS)) <= set(re.findall(r"(--radius-[\w-]+):", block(":root {")))


def test_corner_tokens_keep_their_sizes_and_roles():
    root = block(":root {")
    sizes = dict(re.findall(r"--radius-([\w-]+):\s*([^;]+);", root))
    assert sizes == {"field": "10px", "tile": "16px", "card": "28px", "bar": "36px", "pill": "999px", "inline": "6px"}
    # a container that can wrap, or text that can, takes the card corner: a pill on one line, never a blob on three
    roles = {".seg {": "card", ".ep-sonarr {": "card", ".toast {": "card", ".poster .art {": "tile", ".sched-card {": "tile",
             ".modal {": "card", ".sx-card {": "card", ".btn {": "pill", ".sd code {": "field"}
    # every rule that sets the corner, desktop and phone alike, not only the one that wins at some width
    corners = {sel: [b for b in rules_of(sel.rstrip(" {")) if "border-radius:" in b] for sel in roles}
    wrong = {sel: role for sel, role in roles.items()
             if not corners[sel] or any(f"border-radius: var(--radius-{role})" not in b for b in corners[sel])}
    assert not wrong
    nav = [b for b in rules_of("nav a") if "border-radius:" in b]
    assert "var(--radius-pill)" in nav[0] and "var(--radius-card)" in nav[-1]  # header nav pills; a phone's tabs, blocks as in the TabBar card


def test_forced_colors_show_the_systems_checkbox_and_the_chosen_segment():
    forced = re.search(r"@media \(forced-colors: active\) \{\s*input\[type=checkbox\]:not\(\.switch\) \{([^}]*)\}", CSS)
    assert forced and "appearance: auto" in forced[1] and "background: none" in forced[1]  # the system draws tick and dash itself
    chosen = re.search(r"@media \(forced-colors: active\) \{\s*:is\(\.d-tabs, \.seg, \.ax-seg\) button\[aria-pressed=\"true\"\] \{([^}]*)\}", CSS)
    assert chosen and "text-decoration: underline" in chosen[1]  # the fill is gone in system colours
