"""Narrow screens: nothing clipped or overlapping at 320 px or 400% zoom (WCAG 1.4.10), read from the stylesheet and the scripts."""
import re
from pathlib import Path

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
CSS = (STATIC / "app.css").read_text()


def media(query):
    """The text inside every `@media (query) { ... }` block, braces matched."""
    blocks, start = [], 0
    while (at := CSS.find(f"@media ({query})", start)) != -1:
        open_at = CSS.index("{", at)
        depth, i = 1, open_at + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(CSS[i], 0)
            i += 1
        blocks.append(CSS[open_at + 1:i - 1])
        start = i
    assert blocks, f"no @media ({query}) block"
    return "\n".join(blocks)


def squash(text):
    return re.sub(r"\s+", " ", text)


def has(text, rule):
    assert squash(rule) in squash(text), rule


def test_a_runs_buttons_wrap_instead_of_running_off_the_screen():
    has(media("max-width: 700px"), ".cd-foot { display: flex; flex-wrap: wrap; gap: 10px; }")


def test_a_live_card_stacks_speed_and_time_under_the_episode_while_narrow():
    narrow = media("max-width: 800px")
    has(narrow, ".jcard:not(.queued):not(.cancelled) .jhead { grid-template-columns: minmax(0, 1fr) auto;")
    has(narrow, ".jcard:not(.queued):not(.cancelled) .jhead .mid { grid-row: 2; grid-column: 1 / -1; }")


def test_a_finished_card_names_its_whole_line_when_it_is_cut_short():
    js = (STATIC / "js" / "activity.js").read_text()
    assert "el(\"small\", { textContent: tookLine(c, live), title: tookLine(c, live) })" in js


def test_the_series_filter_goes_to_a_second_row_instead_of_overflowing_its_buttons():
    phone = media("max-width: 700px")
    has(phone, ".seg { display: grid; grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));")
    assert "overflow-wrap: anywhere" in squash(phone[phone.index(".seg button {"):][:200])


def test_the_setup_error_wraps_inside_the_card_when_it_sits_under_its_field():
    has(media("max-width: 1180px"), "transform: none; margin-top: 8px; width: auto; max-width: 100%; }")


def test_the_notifications_heading_keeps_its_own_width_and_the_row_may_wrap():
    has(CSS, ".inbox-head { display: flex; flex-wrap: wrap;")
    has(CSS, ".inbox-head div { flex: 1 1 auto; min-width: min-content; }")
    has(media("max-width: 340px"), "#inbox-clear { order: 1; margin-left: auto; }")


def test_a_phone_shows_the_apps_name_whole_or_its_labelled_logo_never_a_cut_name():
    phone = media("max-width: 700px")
    has(phone, ".version-chip { display: none; }")  # Settings has the version and what's new
    has(phone, "header h1 { font-size: var(--fs-headline); flex: 1; min-width: 0; container-type: inline-size; }")
    has(CSS, "@container (width < 9.25rem) { .brand span { display: none; } }")
    assert "text-overflow: ellipsis" not in squash(phone[phone.index("header h1 {"):][:400])
    assert 'id="home" aria-label="Unshacklarr, schedule"' in (STATIC / "index.html").read_text()
    assert 'id="set-version"' in (STATIC / "index.html").read_text()


def test_every_small_control_on_a_phone_is_44px_to_the_finger():
    phone = media("max-width: 700px")
    slop = phone[phone.index(":where(.brand a, #update, .btn.small"):]
    has(slop, "::after { content: \"\"; position: absolute; inset: min(0px, (100% - 44px) / 2); }")
    for target in ("#update", ".btn.small", ".seg.small button", ".pill", ".icon-hide", ".sc-open", "#d-meta a", ".ds-nav a", ".ax-seg button"):
        assert target in slop[:slop.index("{")], target
    has(phone, ".health button { min-width: 44px; min-height: 44px; padding: 0 8px;")
    has(phone, ".seg button { min-height: 44px; }")
    has(phone, ".ep-sel button { min-width: 44px; min-height: 44px; }")


def test_the_series_back_button_sits_in_the_page_gutter_clear_of_the_notch():
    phone = media("max-width: 700px")
    has(phone, ".d-head { padding: calc(8px + env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) 0 max(16px, env(safe-area-inset-left));")
    has(phone, "#d-back { display: grid; margin-left: 0; }")


def test_the_series_shortcuts_stay_pinned_below_the_head_except_on_a_short_screen():
    has(media("max-width: 700px"), ".ds-nav { top: var(--d-head, 118px); }")
    has(media("max-width: 700px"), "html:has(body.drawer-open #dt-settings:not([hidden])) { scroll-padding-top: calc(var(--d-head, 118px) + 64px); }")
    short = media("max-width: 700px) and (max-height: 480px")
    has(short, ".d-head, .ds-nav { position: static; }")
    has(short, "html:has(body.drawer-open), html:has(body.drawer-open #dt-settings:not([hidden])) { scroll-padding-top: 8px; }")


def test_lighting_a_shortcut_scrolls_only_the_bar_sideways_and_counts_only_what_is_pinned():
    js = (STATIC / "js" / "series.js").read_text()
    light = js[js.index("function dsLight()"):js.index('addEventListener("scroll", dsLight')]
    assert "scrollIntoView" not in light, "it scrolled the page or the drawer under the person"
    assert "nav.scrollLeft +=" in light
    has(light, 'getComputedStyle(box).position === "sticky" ? box.getBoundingClientRect().bottom : 0')
    has(light, "Math.max(pinned($(\".d-head\")), pinned(nav))")


def test_the_late_banner_puts_its_sentence_under_the_count_and_button_on_a_phone():
    phone = media("max-width: 700px")
    has(phone, ".late-banner { display: grid; grid-template-columns: 1fr auto;")
    has(phone, ".late-banner span { grid-row: 2; grid-column: 1 / -1; }")


def test_a_posters_service_badge_stays_inside_its_poster_and_names_itself():
    has(CSS, ".poster .svc { display: block; max-width: calc(100% - 12px); overflow: hidden; text-overflow: ellipsis; }")
    assert "title: svcName(conf.service)" in (STATIC / "js" / "core.js").read_text()


def test_activitys_history_filters_and_clear_are_big_enough_to_tap_on_a_phone():
    phone = media("max-width: 700px")
    has(phone, ".btn.small, .con-filters button { min-height: 36px; }")
    has(phone, ".gh-act { min-height: 36px;")
    has(CSS, ".con-gh { display: flex; justify-content: space-between; align-items: center;")  # its label level with Clear…
