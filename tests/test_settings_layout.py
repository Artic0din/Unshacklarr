"""Settings stays readable between phone and desktop widths: no column squeezed to nothing, no page scrolling sideways."""
import re
import pytest

from css_assets import load_css

CSS = re.sub(r"/\*.*?\*/", "", load_css(), flags=re.S)


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


def test_service_actions_use_their_own_width_and_lines():
    assert "flex-wrap: wrap" in rule(".sv-ctl")
    assert not re.search(r"\.sv-(?:table|file|ctl)[^{]*\{[^}]*\b(?:min-width:\s*7\.125rem|flex-wrap:\s*nowrap)", CSS)
    assert "overflow-wrap: normal" in rule(".sv-name")
    assert "width: 25%" in rule(".sv-table thead th:first-child")


def test_the_services_table_stacks_before_a_column_would_hide_past_an_edge():
    assert "container-type: inline-size" in rule("#sv-list")
    stacks = re.search(r"@container \(max-width: (\d+)rem\) \{((?:[^{}]|\{[^{}]*\})*)\}", CSS)
    assert stacks and int(stacks.group(1)) >= 36  # four columns need about 576px inside the card
    assert ".sv-table thead { display: none; }" in stacks.group(2)
    assert "minmax(min(100%, 13rem), 1fr)" in stacks.group(2)  # one track at phone widths, with no forced minimum


def test_service_attention_colours_only_the_leading_edge():
    assert "--sv-edge: var(--err)" in rule(".sv-row[data-attention]")
    assert "border-inline-start: 1px solid var(--sv-edge" in rule(".sv-table tbody th")
    assert "border-inline-start: 1px solid var(--sv-edge" in rule(".sv-table tbody tr")
    assert not re.search(r"\.sv-row\[data-attention\][^{]*\{[^}]*box-shadow", CSS)


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


def test_settings_jump_chips_wrap_instead_of_clipping():
    jumps = rule(".ds-nav.set-jumps")
    assert "flex-wrap: wrap" in jumps
    assert "overflow: visible" in jumps
    assert "position: static" in jumps


def test_choice_tiles_put_their_titles_level_whatever_the_length_of_their_text():
    assert "align-content: start" in rule(".wz-tile")
