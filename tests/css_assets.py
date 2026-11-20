import re
from pathlib import Path

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
STYLESHEET_LINK = re.compile(r'<link rel="stylesheet" href="(/css/[^"]+\.css)(?:\?v=([0-9a-f]+))?">')


def load_css() -> str:
    """Read the app stylesheets in the order the browser applies them."""
    return "".join((STATIC / path.lstrip("/")).read_bytes().decode("utf-8")
                   for path, _ in STYLESHEET_LINK.findall((STATIC / "index.html").read_text()))
