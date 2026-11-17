"""A control focused with Tab stops short of the bars pinned over the page, instead of hiding behind them."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
CSS = (STATIC / "app.css").read_text()
BAR_MIN = 64  # the shortest pinned bar with its gap to the edge: a 44px control row, 20px off the edge
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


def test_phone_page_keeps_focus_clear_of_the_measured_header_and_bars():
    page = [body for sel, body in padding_rules(phone_blocks()) if sel == "html"]
    assert page and "var(--head-h" in page[0] and "var(--bars-h" in page[0]


def measured(bars):
    """--head-h and --bars-h as navigation.js sets them, for bars given as (offsetHeight, computed bottom)."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    src = (STATIC / "js" / "navigation.js").read_text()
    code = src[src.index("const BOTTOM_BARS"):src.index("const barsSeen")]
    out = subprocess.run(["node", "-e", r"""
const vm = require("vm"), [code, bars] = process.argv.slice(1), set = {};
const nodes = { header: { offsetHeight: 65, style: {} }, "#con-detail": { bottom: "auto", pad: "20px" } };
for (const [sel, [h, bottom]] of Object.entries(JSON.parse(bars))) nodes[sel] = { offsetHeight: h, bottom };
const ctx = vm.createContext({ $: (sel) => nodes[sel], getComputedStyle: (n) => ({ bottom: n.bottom, paddingBottom: n.pad || "0px" }), Math, parseFloat,
  document: { documentElement: { style: { setProperty: (k, v) => { set[k] = v; } } } } });
vm.runInContext(code + "\nmeasureBars();", ctx);
console.log(JSON.stringify(set));
""", code, json.dumps(bars)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


NONE = {"#savebar": [0, "auto"], "#sel-bar": [0, "auto"], "#dock": [0, "auto"], "#ep-bar": [0, "auto"]}


def test_phone_bars_reach_as_far_up_as_the_highest_one():
    tab = {'nav[aria-label="Main"]': [72, "0px"]}
    assert measured({**NONE, **tab}) == {"--head-h": "65px", "--save-h": "0px", "--bars-h": "80px", "--dock-h": "28px"}
    # the save bar over the tab bar, and the selection bar wrapped to two rows over both: the highest one counts
    shown = {**NONE, **tab, "#savebar": [56, "76px"], "#sel-bar": [104, "140px"]}
    assert measured(shown)["--bars-h"] == "252px"


def test_phone_expanded_dock_and_series_download_bar_are_measured_as_they_are():
    tab = {'nav[aria-label="Main"]': [72, "0px"]}
    assert measured({**NONE, **tab, "#dock": [320, "84px"]})["--bars-h"] == "412px"  # expanded, with its output
    # the series page: no tab bar (its header is hidden), the download bar at the bottom
    assert measured({**NONE, 'nav[aria-label="Main"]': [0, "0px"], "#ep-bar": [60, "0px"]})["--bars-h"] == "68px"


def test_every_bottom_bar_is_watched_for_size():
    src = (STATIC / "js" / "navigation.js").read_text()
    assert "new ResizeObserver(measureBars)" in src and "...BOTTOM_BARS].forEach((n) => barsSeen.observe(n))" in src


def test_phone_series_page_clears_its_sticky_head_and_settings_shortcuts():
    phone = phone_blocks()
    assert "--d-head" in " ".join(rule_for(phone, "body.drawer-open)", side="top"))
    assert "--d-head" in " ".join(rule_for(phone, "#dt-settings", side="top"))


def test_series_slide_out_clears_the_settings_shortcuts_it_scrolls_under():
    assert rule_for(CSS, ".d-body:has(#dt-settings", side="top")


def test_wide_screens_clear_the_dock_save_bar_and_select_bar():
    wide = CSS[CSS.index("@media (min-width: 701px) {  /* the page's floating bars"):]
    wide = wide[:wide.index("\n}\n")]
    for bar in ("#savebar", ".sel-bar"):
        rules = rule_for(wide, bar, side="bottom")
        assert rules and int(re.search(r"scroll-padding-bottom: (\d+)px", rules[0])[1]) >= BAR_MIN, f"{bar}: no room on a wide screen"
    assert "var(--dock-h" in " ".join(rule_for(wide, "#dock", side="bottom"))


def test_settings_end_clears_the_save_bar():
    room = re.search(r"body:has\(#savebar:not\(\[hidden\]\)\) main \{ padding-bottom: (\d+)px", CSS)
    assert room and int(room[1]) >= BAR_MIN


def test_shortcut_jumps_use_the_scroll_padding_not_a_second_margin():
    assert "scroll-margin-top" not in CSS


def test_wide_activity_pane_clears_the_dock_it_scrolls_under():
    """Activity scrolls inside .con-detail on a wide screen: padding on the page alone does not reach it."""
    rules = rule_for(CSS, ".con-detail:has(#dock", side="bottom")
    assert rules and "var(--dock-h" in rules[0]  # measured: the dock grows when its output opens


def test_wide_dock_is_measured_as_tall_as_it_is():
    tab = {'nav[aria-label="Main"]': [0, "0px"]}  # a wide screen: the tab bar is the header's nav, not pinned
    # the pane's 20px bottom padding counts: the dock sticks 12px above it
    assert measured({**NONE, **tab, "#dock": [56, "12px"]})["--dock-h"] == "96px"
    assert measured({**NONE, **tab, "#dock": [549, "12px"]})["--dock-h"] == "589px"  # expanded, with its output


def test_phone_page_top_follows_the_header_when_a_status_row_makes_it_taller():
    assert '"--head-h"' in (STATIC / "js" / "navigation.js").read_text()


def test_a_phone_bar_over_the_save_bar_stands_on_it_as_tall_as_it_is():
    """The save bar wraps to two rows on a narrow phone: the dock and the selection bar go above it, not under it (#298)."""
    tab = {'nav[aria-label="Main"]': [72, "0px"]}
    assert measured({**NONE, **tab, "#savebar": [119, "76px"]})["--save-h"] == "119px"
    phone = phone_blocks()
    for bar in (".sel-bar", ".dock"):
        rules = re.findall(r"body:has\(#savebar:not\(\[hidden\]\)\) ([^{]+)\{ bottom: ([^}]+); \}", phone)
        assert any(bar in sel and "var(--save-h" in bottom for sel, bottom in rules), f"{bar}: not stacked on the save bar"
