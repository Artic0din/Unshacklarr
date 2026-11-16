"""A control focused with Tab stops short of the bars pinned over the page, instead of hiding behind them."""
import re
from pathlib import Path

CSS = (Path(__file__).parents[1] / "unshacklarr" / "static" / "app.css").read_text()
PHONE = "@media (max-width: 700px) {"


def phone_blocks():
    """The bodies of every phone media block, nested braces included."""
    blocks, at = [], CSS.find(PHONE)
    while at != -1:
        depth, i = 1, at + len(PHONE)
        while depth:
            depth += {"{": 1, "}": -1}.get(CSS[i], 0)
            i += 1
        blocks.append(CSS[at + len(PHONE):i - 1])
        at = CSS.find(PHONE, i)
    return "\n".join(blocks)


def padding_rules(css):
    """(selector, declarations) of every rule that sets a scroll padding."""
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*scroll-padding[^{}]*)\}", css)]


def rule_for(css, *needles, side):
    return [body for sel, body in padding_rules(css) if all(n in sel for n in needles) and f"scroll-padding-{side}" in body]


def test_phone_page_keeps_focus_clear_of_header_and_tab_bar():
    page = [body for sel, body in padding_rules(phone_blocks()) if sel == "html"]
    assert page and "scroll-padding-top" in page[0] and "scroll-padding-bottom" in page[0]


def test_phone_page_makes_room_for_each_bar_over_the_tab_bar():
    phone = phone_blocks()
    for bar in ("#dock", ".sel-bar", "#savebar"):
        assert rule_for(phone, "html:has(", bar, side="bottom"), f"{bar}: no phone scroll padding"
    assert rule_for(phone, ".sel-bar", "#savebar", side="bottom"), "both bars showing: stacked"


def test_phone_series_page_clears_its_sticky_head_settings_shortcuts_and_download_bar():
    phone = phone_blocks()
    assert "--d-head" in " ".join(rule_for(phone, "body.drawer-open)", side="top"))
    assert "--d-head" in " ".join(rule_for(phone, "#dt-settings", side="top"))
    assert rule_for(phone, "#ep-bar", side="bottom")


def test_series_slide_out_clears_the_settings_shortcuts_it_scrolls_under():
    assert rule_for(CSS, ".d-body:has(#dt-settings", side="top")


def test_wide_screens_clear_the_dock_save_bar_and_select_bar():
    wide = CSS[CSS.index("@media (min-width: 701px) {  /* the page's floating bars"):]
    wide = wide[:wide.index("\n}\n")]
    for bar in ("#dock", "#savebar", ".sel-bar"):
        assert rule_for(wide, bar, side="bottom"), f"{bar}: no scroll padding on a wide screen"


def test_settings_end_clears_the_save_bar():
    assert re.search(r"body:has\(#savebar:not\(\[hidden\]\)\) main \{ padding-bottom: \d+px", CSS)


def test_shortcut_jumps_use_the_scroll_padding_not_a_second_margin():
    assert "scroll-margin-top" not in CSS
