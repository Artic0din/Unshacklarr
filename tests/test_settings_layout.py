"""Settings stays readable between phone and desktop widths: no column squeezed to nothing, no page scrolling sideways."""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
CSS = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(), flags=re.S)


def rule(selector):
    """The body of the one rule whose selector list is exactly `selector`, wherever it sits."""
    bodies = [body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS) if selector in [s.strip() for s in sel.split(",")]]
    assert bodies, selector
    return " ".join(bodies)


def media_width(selector):
    """The max-width of the media query holding the rule that starts with `selector` (None when outside any)."""
    for width, inner in re.findall(r"@media \(max-width: (\d+)px\) \{((?:[^{}]|\{[^{}]*\})*)\}", CSS):
        if re.search(rf"(?:^|\}}|\s){re.escape(selector)}\s*[,{{]", inner):
            return int(width)
    return None


def test_a_cookie_file_keeps_room_for_its_name_at_every_width():
    assert "minmax(9.5rem, 1fr) auto" in rule(".sv-file")
    wide = re.search(r"@media \(min-width: 1440px\) \{(.*?)\n", CSS).group(1)
    assert ".sv-file" not in wide  # the room is not something only a wide window gets


def test_the_services_table_stacks_before_a_column_would_hide_past_an_edge():
    assert media_width(".sv-table, .sv-table tbody") >= 1180  # its columns need about 825px beside the sidebar


def test_a_ladder_step_stacks_before_its_selects_collapse():
    assert media_width(".ql-step") >= 1100  # four controls in a row need about 1100px beside the sidebar
    assert media_width(".ql-h") == media_width(".ql-step")


@pytest.mark.parametrize("selector", [".sx", ".nt-wide", ".ux-more", ".st-sect", ".st-cmds"])
def test_a_settings_grid_lets_its_one_column_shrink_below_its_content(selector):
    # an auto track is as wide as its widest unbreakable child: a command or a pair of time fields pushed the page sideways
    assert "grid-template-columns: minmax(0, 1fr)" in rule(selector)


def test_the_quiet_hours_fields_shrink_to_the_card():
    assert "min-width: 0" in rule(".nt-quiet")
    assert "min-width: 0" in rule(".nt-quiet input")


def test_the_unshackle_card_may_be_narrower_than_its_commands():
    assert "min-width: 0" in rule(".ux-more")


def test_interface_and_region_cards_stay_side_by_side():
    assert "repeat(auto-fill" in rule(".sx.sx-tiles")  # .sx's one column comes later and would win over .sx-tiles alone


def test_choice_tiles_put_their_titles_level_whatever_the_length_of_their_text():
    assert "align-content: start" in rule(".wz-tile")
