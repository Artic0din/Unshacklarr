"""Content past a scroll edge shows a cue, and a name is wrapped, not cut off with no way to read it."""
import re
from pathlib import Path

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
CSS = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(), flags=re.S)
CUT_OFF = re.compile(r"text-overflow\s*:\s*ellipsis|white-space\s*:\s*nowrap")


def rule(selector):
    """The declarations of every rule whose selector list holds `selector` exactly, joined."""
    bodies = [body for names, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS)
              if selector in [name.strip() for name in names.split(",")]]
    assert bodies, f"no rule for {selector}"
    return " ".join(bodies)


def test_the_country_list_shows_part_of_the_next_row_so_it_reads_as_scrollable():
    rows = float(re.search(r"max-height:\s*calc\(([\d.]+) \* 38px", rule(".cp-list")).group(1))
    assert rows % 1 == .5  # a half row, never a whole number of rows that ends on the edge


def test_the_stats_table_shows_a_shadow_at_an_edge_that_hides_columns():
    body = rule(".svc-scroll")
    assert "overflow-x: auto" in body
    assert body.count("local") == 2 and body.count("scroll;") + body.count("scroll,") == 2  # a cover and a shadow per edge
    assert 'className: "svc-scroll"' in (STATIC / "js" / "activity.js").read_text()
    assert "--cover: var(--panel)" in body  # desktop Stats sits on .con's panel: a --bg cover left a strip at a reached edge


def test_names_and_help_text_wrap_instead_of_being_cut_with_an_ellipsis():
    for selector in (".hidden-rows .n", ".picker-list li span", ".nt-who b", ".cdm-to b", ".cdm-to small"):
        body = rule(selector)
        assert not CUT_OFF.search(body), selector
        assert "overflow-wrap: anywhere" in body, selector
