"""The page's translations (static/i18n/<lang>.json), for what the server sends itself: notifications.

A text is matched whole, as the page does: "Downloaded: {0}" takes "Downloaded: Silo S02E03", and what
fills {0} is translated in turn when it is a known text too.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

FOLDER = Path(__file__).parent / "static" / "i18n"
HOLE = re.compile(r"\{(\d+)\}")


def plural_category(lang: str, n: int | None) -> str:
    """The CLDR plural category of a whole number, for the languages the page has (what Intl.PluralRules gives it);
    a text with no number is "other"."""
    if n is None:
        return "other"
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        return "few" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "many"
    if lang in ("fr", "pt-BR"):
        return "one" if n in (0, 1) else "other"
    if lang in ("de", "en", "es", "it"):
        return "one" if n == 1 else "other"
    return "other"


def pick(to: str | dict[str, str], lang: str, found: list[str] | None) -> str:
    """A text is one string, or one string per plural category: the first number it is filled with picks it."""
    if isinstance(to, str):
        return to
    first = found[0].strip() if found else ""
    return to.get(plural_category(lang, int(first) if first.isdigit() else None)) or to["other"]


def languages() -> list[str]:
    return sorted(p.stem for p in FOLDER.glob("*.json"))


@lru_cache
def catalog(lang: str) -> tuple[dict, list]:
    """A language's texts, and its templates as patterns, the most specific first."""
    path = FOLDER / f"{lang}.json"
    if lang == "en" or not path.is_file():
        return {}, []
    exact = json.loads(path.read_text())
    patterns = []
    for key, to in exact.items():
        parts = HOLE.split(key)[::2]
        anchor = max(parts, key=len)
        if len(parts) > 1 and re.search(r"[^\W\d_]", anchor):
            # "{0} ago", "{0} of {1}", "{0} episode{1}{2}": one short piece of text, short fillers only
            weak = len(re.sub(r"[^\w]|[\d_]", "", "".join(parts))) < 10 and sum(1 for p in parts if p.strip()) < 2
            patterns.append((len("".join(parts)), anchor, parts, to, weak))
    patterns.sort(key=lambda p: -p[0])
    return exact, patterns


def holes(parts: list[str], key: str) -> list[str] | None:
    """What fills each hole of a template whose fixed pieces are parts, or None. Linear: each piece is
    looked for once, in order (no regular expression, so no text can make it slow)."""
    head, tail = parts[0], parts[-1]
    if len(key) < len(head) + len(tail) or not key.startswith(head) or not key.endswith(tail):
        return None
    pos, end, found = len(head), len(key) - len(tail), []
    for piece in parts[1:-1]:
        at = key.find(piece, pos, end)
        if at < 0:
            return None
        found.append(key[pos:at])
        pos = at + len(piece)
    return found + [key[pos:end]]


def tr(text: str, lang: str, depth: int = 0) -> str:
    exact, patterns = catalog(lang)
    key = " ".join(text.split())
    if not exact or not key:
        return text
    if key in exact:
        return pick(exact[key], lang, None)
    if " · " in key:  # pieces joined by " · ": each its own text
        return " · ".join(tr(part, lang, depth + 1) for part in key.split(" · "))
    for _, anchor, parts, to, weak in patterns if depth < 3 else []:
        if anchor in key and (found := holes(parts, key)) is not None and not (weak and any(
                len(g) > 24 or not (re.search(r"\d", g) or g.strip() in exact or not g.strip()) for g in found)):
            return HOLE.sub(lambda h: tr(found[int(h[1])], lang, depth + 1) if int(h[1]) < len(found) else "", pick(to, lang, found))
    return text


def tr_lines(text: str, lang: str) -> str:
    """A message line by line: each line is its own text."""
    return "\n".join(tr(line, lang) for line in text.split("\n"))
