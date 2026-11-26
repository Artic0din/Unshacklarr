"""Read Netscape cookie files and convert browser JSON exports on import."""

import html
import json
import re
import time
from decimal import Decimal, DecimalException
from pathlib import Path

from unshacklarr.files import shared_or_private, write_atomic

NAME = re.compile(r"[A-Za-z0-9][\w.-]{0,39}")  # a service tag or a profile: never a path
MAX_SIZE, MAX_DATE, HEADER, FLAGS = 1_000_000, Decimal("1e308"), "# Netscape HTTP Cookie File", {"TRUE", "FALSE"}
DOMAIN = re.compile(r"\.?[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+")
COOKIE_PATH = re.compile(r"/[A-Za-z0-9_.\-~%/:@&=+$,!*'()]*")
COOKIE_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
TIMESTAMP = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
MAX_INTEGER_DATE, WS = 10**308, {9: 32, 10: 32, 13: 32}
Row = tuple[str, str, str, str, str, int]
# Anti-bot, load balancer and analytics expiries are independent of the login lifetime.
NOISE = re.compile(r"^(ak_bmsc|bm_\w+|_abck|__cf_bm|cf_clearance|__cfruid|datadome|_ga\w*|_gid|_gat\w*|_gcl_\w+|_fbp|_fbc|AWSALB\w*|utsdc)$", re.IGNORECASE)

class CookieError(ValueError):
    """What is wrong with a cookie file, in words for the page."""

class CookieParseError(CookieError):
    def __init__(self, line_number: int, reason: str):
        self.line_number, self.reason = line_number, reason
        super().__init__(f"Line {line_number}: {reason}")

def check_name(name: str, what: str) -> str:
    if not NAME.fullmatch(name or "") or ".." in name:
        raise CookieError(f"Not a valid {what}: {name!r}")
    return name

def _timestamp(date: str) -> int:
    if len(date) < 20 and date.isascii() and (not date or date.isdigit()):
        return int(date or 0)
    if not TIMESTAMP.fullmatch(date):
        raise ValueError
    value = Decimal(date)
    if not value.is_finite() or (value and (value.adjusted() > 308 or value > MAX_DATE)):
        raise ValueError
    return max(1, int(value)) if value else 0

def _unescape(text: str) -> str:
    try:
        return html.unescape(text) if "&" in text else text
    except ValueError:
        return "\x00"

def _attributes(prefix: str, number: int, strict: bool) -> tuple[str, str, int, str]:
    fields = prefix.removeprefix("#HttpOnly_").split("\t")
    if len(fields) != 5:
        raise CookieParseError(number, "expected 7 tab-separated fields")
    domain, flag, path, secure, date = fields
    if len(domain) - domain.startswith(".") > 253 or not DOMAIN.fullmatch(domain):
        raise CookieParseError(number, "invalid cookie domain")
    if flag not in FLAGS:
        raise CookieParseError(number, "domain flag must be TRUE or FALSE")
    if strict and (flag == "TRUE") != domain.startswith("."):
        raise CookieParseError(number, "domain flag must match leading dot")
    decoded_path = path
    if path != "/" and (not path.startswith("/") or CONTROL.search(path) or not COOKIE_PATH.fullmatch(decoded_path := _unescape(path))):
        raise CookieParseError(number, "cookie path must start with '/'")
    if secure not in FLAGS:
        raise CookieParseError(number, "secure flag must be TRUE or FALSE")
    try:
        expires = _timestamp(date)
        rewritten = prefix.rsplit("\t", 1)[0] + f"\t{expires}" if strict and date and date != str(expires) else ""
        return domain, decoded_path, expires, rewritten
    except (ValueError, DecimalException):
        raise CookieParseError(number, "expiry date is not a valid timestamp") from None

def _raw(text: str) -> str:
    return text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n") if text.startswith("\ufeff") or "\r" in text else text

def _netscape_rows(raw: str, strict: bool) -> list[Row]:
    previous, domain, path, expires, rewritten = None, "", "", 0, ""
    clean = raw.isascii() and "&" not in raw and (not strict or raw.translate(WS).isprintable())
    rows = []
    for number, line in enumerate(raw.split("\n"), 1):
        try:
            if not clean and strict and not line.isascii():
                line.encode("utf-8")
            prefix = (fields := line.rsplit("\t", 2))[0]
            if len(fields) != 3 or prefix != previous:
                stripped = line.lstrip(" \t")
                if not line.strip(" ") or line == HEADER:
                    continue
                if stripped.startswith("#") and not line.startswith("#HttpOnly_"):
                    unescaped = _unescape(line.replace("\t", ""))
                    if strict and (unescaped.lstrip().startswith("#HttpOnly_") or (not clean and CONTROL.search(unescaped))):
                        raise CookieParseError(number, "unexpected leading whitespace before #HttpOnly_" if stripped.startswith("#HttpOnly_") else "invalid comment line")
                    rows.append((line, "", "", "", "", 0))
                    continue
                if len(fields) != 3:
                    raise CookieParseError(number, "expected 7 tab-separated fields")
                domain, path, expires, rewritten = _attributes(prefix, number, strict)
                previous = prefix
            _, name, value = fields
            if clean:
                decoded_name, decoded_value = name, value
                if not (name.isalnum() or (name.strip() and (not strict or COOKIE_NAME.fullmatch(name)))):
                    raise CookieParseError(number, "invalid cookie name" if name.strip() else "missing cookie name")
            else:
                decoded_name = _unescape(name)
                if not decoded_name.strip():
                    raise CookieParseError(number, "missing cookie name")
                if decoded_name == "\x00" or (strict and (CONTROL.search(name) or not COOKIE_NAME.fullmatch(decoded_name))):
                    raise CookieParseError(number, "invalid cookie name")
                decoded_value = _unescape(value)
                if decoded_value == "\x00" or (strict and (CONTROL.search(value) or CONTROL.search(decoded_value))):
                    raise CookieParseError(number, "invalid cookie value")
            rows.append((f"{rewritten}\t{name}\t{value}" if rewritten else line, domain, path, decoded_name, decoded_value, expires))
        except UnicodeEncodeError:
            raise CookieParseError(number, "invalid UTF-8 text") from None
        except CookieParseError:
            if strict:
                raise
    return rows

def parse(text: str, *, strict: bool = False) -> list[dict]:
    """Read Netscape cookie metadata, tolerating damaged stored files by default."""
    if strict:
        _validate_text(text)
    result, previous, clean_dom = [], "", ""
    for _, domain, _, name, _, expires in _netscape_rows(_raw(text), strict):
        if domain:
            if domain != previous:
                previous, clean_dom = domain, domain.lstrip(".")
            result.append({"domain": clean_dom, "name": name, "expires": expires})
    return result

def _validate_text(text: str) -> None:
    if not isinstance(text, str):
        raise CookieError("Neither a Netscape cookie file nor a JSON export")
    if len(text) > MAX_SIZE:
        raise CookieError("That file is too large to be cookies")

def _json_expiry(cookie: dict, idx: int) -> int:
    if type(raw := cookie.get("expirationDate")) is int and 0 <= raw <= MAX_INTEGER_DATE and "expires" not in cookie and not cookie.get("session"):
        return raw
    expiry, session, allow_sentinel = 0, cookie.get("session") is True, cookie.get("session") is not False
    for key in ("expirationDate", "expires"):
        if (raw := cookie.get(key)) is None or raw == "":
            continue
        try:
            if isinstance(raw, bool) or not isinstance(raw, (str, Decimal, float, int)):
                raise TypeError
            if isinstance(raw, str) and not (TIMESTAMP.fullmatch(raw) or (allow_sentinel and raw == "-1")):
                raise ValueError
            date = raw if isinstance(raw, Decimal) else Decimal(str(raw))
            if not date.is_finite() or (date and (date.adjusted() > 308 or date.copy_abs() > MAX_DATE)):
                raise ValueError
        except (TypeError, ValueError, OverflowError, DecimalException):
            raise CookieError(f"Cookie #{idx}: expiry date is not a valid timestamp") from None
        if (session and date not in (0, -1)) or (expiry and date == -1 and allow_sentinel):
            raise CookieError(f"Cookie #{idx}: session cookie cannot have an expiry date")
        if date < 0 and not (allow_sentinel and date == -1):
            raise CookieError(f"Cookie #{idx}: expiry date must not be negative")
        session, expiry = session or date == -1, expiry or (max(1, int(date)) if date > 0 else 0)
    return expiry

def _load_json(text: str) -> list:
    _validate_text(text)
    try:
        if not text.isascii():
            text.encode("utf-8")
        options: dict = {"parse_constant": int} if "N" in text or "I" in text else {}
        if r"\u" in text:
            options["object_pairs_hook"] = lambda pairs: json.dumps(pairs, ensure_ascii=False, default=str).encode("utf-8") and dict(pairs)
        data = json.loads(text, parse_float=Decimal, **options)
        if r"\u" in text:
            json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    except (ValueError, RecursionError, DecimalException):
        raise CookieError("Neither a Netscape cookie file nor a JSON export") from None
    if isinstance(data, dict) and not isinstance(data := data.get("cookies"), list):
        raise CookieError("Invalid JSON cookie export: expected a cookies list")
    if not isinstance(data, list):
        raise CookieError("Invalid JSON cookie export: expected a cookie list")
    return data

def _from_json_rows(text: str) -> list[Row]:
    data = _load_json(text)
    clean = text.isascii() and "\\" not in text and "&" not in text and text.translate(WS).isprintable()
    rows, prev_dom, flag = [], "", ""
    for idx, c in enumerate(data, 1):
        if not isinstance(c, dict):
            raise CookieError(f"Cookie #{idx}: expected an object")
        domain, name = c.get("domain"), c.get("name")
        if domain != prev_dom or not flag:
            if not isinstance(domain, str) or len(domain) - domain.startswith(".") > 253 or not DOMAIN.fullmatch(domain):
                raise CookieError(f"Cookie #{idx}: missing or invalid domain or name")
            prev_dom, flag = domain, "TRUE" if domain.startswith(".") else "FALSE"
        if not isinstance(name, str):
            raise CookieError(f"Cookie #{idx}: missing or invalid domain or name")
        decoded_name = name if clean else _unescape(name)
        if not (name.isascii() and name.isalnum() or (not CONTROL.search(name) and COOKIE_NAME.fullmatch(decoded_name))):
            raise CookieError(f"Cookie #{idx}: missing or invalid domain or name")
        path = decoded_path = "/" if (path := c.get("path")) in (None, "") else path
        if path != "/" and (not isinstance(path, str) or not path.startswith("/") or CONTROL.search(path)
                            or not COOKIE_PATH.fullmatch(decoded_path := _unescape(path))):
            raise CookieError(f"Cookie #{idx}: invalid cookie path")
        value = decoded_value = c.get("value")
        if not isinstance(value, str):
            raise CookieError(f"Cookie #{idx}: missing or invalid cookie value")
        http_only, secure, session = c.get("httpOnly"), c.get("secure"), c.get("session")
        if (http_only is not None and type(http_only) is not bool or secure is not None and type(secure) is not bool
                or session is not None and type(session) is not bool):
            raise CookieError(f"Cookie #{idx}: boolean flag must be true or false")
        if not clean:
            decoded_value = _unescape(value)
            if CONTROL.search(value) or (decoded_value is not value and CONTROL.search(decoded_value)):
                raise CookieError(f"Cookie #{idx}: a tab or a line break in it would break the cookie file")
        expires = _json_expiry(c, idx)
        line = "\t".join([("#HttpOnly_" if http_only else "") + prev_dom,
            flag, path, "TRUE" if secure else "FALSE", str(expires), name, value])
        _validate_text(line)
        rows.append((line, domain, decoded_path, decoded_name, decoded_value, expires))
    return rows

def from_json(text: str) -> str:
    return "\n".join([HEADER, *(row[0] for row in _from_json_rows(text)), ""])

def _require_login(rows: list[Row], now: float) -> None:
    found = live_login = expired_login = False
    dead: set[tuple[str, str, str]] = set()
    for _, domain, path, name, value, expires in reversed(rows):
        found = found or bool(domain)
        if not domain or NOISE.match(name):
            continue
        if expires and not expires > now:
            expired_login = True
            continue
        live_login = True
        if value and (value[0].isalnum() or value.strip().strip('"').strip()):
            if not dead or (domain.lower(), path, name) not in dead:
                return
        else:
            dead.add((domain.lower(), path, name))
    if not found:
        raise CookieError("No cookie found: export them in the Netscape (cookies.txt) or JSON format")
    if live_login or not expired_login:
        raise CookieError("No usable login cookies found: sign in to the service and export its cookies again")
    raise CookieError("All cookies in this export have expired: sign in again and export fresh cookies")

def normalise(text: str, now: float | None = None) -> str:
    _validate_text(text)
    raw = _raw(text)
    rows = _from_json_rows(raw) if raw.lstrip().startswith(("[", "{", '"')) else _netscape_rows(raw, True)
    now = time.time() if now is None else now
    _require_login(rows, now)
    return "\n".join([HEADER] + [row[0] for row in rows if not row[5] or row[5] > now]) + "\n"

def summary(path: Path, now: float | None = None) -> dict:
    now = now or time.time()
    cookies = parse(path.read_text(errors="replace"))
    expiries = [c["expires"] for c in cookies if not NOISE.match(c["name"])]
    session, last = expiries.count(0), max(expiries, default=0)
    return {
        "count": len(cookies), "updated": path.stat().st_mtime,
        "expires": last or None,  # when the last dated one runs out
        "session": session,  # no date: they last as long as the service's own session, unknown here
        "expired": bool(last) and last < now and not session,
    }

def _listed(path: Path) -> dict:
    try:
        return summary(path)
    except OSError:  # one file it may not read is shown as such, not the whole list lost
        return {"count": 0, "updated": None, "expires": None, "session": 0, "expired": False, "unreadable": True}

def list_all(folder: Path) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for entry in sorted(folder.iterdir()) if folder.is_dir() else ():
        if entry.is_file() and entry.suffix == ".txt":
            found.setdefault(entry.stem, []).append({"profile": "", **_listed(entry)})
        elif entry.is_dir():
            for f in sorted(entry.glob("*.txt")):
                found.setdefault(entry.name, []).append({"profile": f.stem, **_listed(f)})
    return found

def path_for(folder: Path, service: str, profile: str) -> Path:
    check_name(service, "service")
    return folder / f"{service}.txt" if not profile else folder / service / f"{check_name(profile, 'profile')}.txt"

def save(folder: Path, service: str, profile: str, text: str) -> dict:
    path = path_for(folder, service, profile)
    content = normalise(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, content, shared_or_private(path.parent))  # session secrets: never other users
    return {"profile": profile, **summary(path)}

def delete(folder: Path, service: str, profile: str) -> None:
    if not (path := path_for(folder, service, profile)).exists():
        raise CookieError("No such cookie file")
    path.unlink()
