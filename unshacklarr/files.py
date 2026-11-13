"""Files written whole or not at all: next to their target, then swapped in, so a reader or a crash
never meets half a file; and with the permissions the caller asks for, not the umask's."""

import json
import os
import re
import stat
import tempfile
from pathlib import Path

import requests

PRIVATE = 0o600  # its owner only: what anything holding a secret gets


def shared_or_private(folder: Path) -> int:
    """For a secret in a folder shared by group (setgid and group-writable, as a Samba share of
    Unshackle's config is): its group too, never other users; elsewhere its owner only."""
    return 0o660 if folder.stat().st_mode & 0o2020 == 0o2020 else PRIVATE


CREDENTIALS = re.compile(r"//[^/\s]+@")  # http://user:password@host, through the last @ before a path: a password may hold @, ? or #


def no_credentials(text) -> str:
    """Keep error details while masking credentials in URLs, headers and named fields."""
    text = CREDENTIALS.sub("//***@", str(text))
    text = re.sub(r"/api/webhooks/[^\s\"'<>]+", "/api/webhooks/***", text)
    text = re.sub(r"(?im)\b(?:authorization|cookie|set-cookie)\s*:[^\r\n]+", "[credentials hidden]", text)
    text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer ***", text)
    return re.sub(
        r'''(?ix)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|passphrase|secret|signature)\b["']?\s*[:=]\s*)
            (?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s&,;}\]\)]+)''',
        r"\1***", text)


def error_message(error: Exception, source: str) -> str:
    """An external failure names its source without guessing that every HTTP error is offline."""
    response = getattr(error, "response", None)
    if response is not None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        detail = payload.get("message") or payload.get("error") if isinstance(payload, dict) else None
        status = f"{source} returned HTTP {response.status_code}."
        return f"{status} {no_credentials(detail)}" if isinstance(detail, str) and detail.strip() else status
    if isinstance(error, requests.Timeout):
        return f"{source} did not answer in time. Check its connection and log."
    if isinstance(error, requests.ConnectionError):
        return f"{source} could not be reached. Check its address and whether it is running."
    if isinstance(error, requests.RequestException):
        return f"{source} failed. Check its log for details."
    if isinstance(error, OSError):
        return f"{source}: {no_credentials(error.strerror or 'File operation failed')}. Check the file path and permissions."
    if not isinstance(error, (ValueError, RuntimeError)):
        return f"{source} failed. Check its log for details."
    detail = no_credentials(error).strip()
    return f"{source}: {detail}" if detail else f"{source} failed. Check its log for details."


def read_json(path: Path, empty):
    """A JSON file's content, or `empty` when it is missing or unreadable (never half-written: see write_atomic)."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return empty


def write_atomic(path: Path, content: bytes | str, mode: int | None = None) -> None:
    """Write content to path. mode: these permissions; None: the file's own if it exists, else PRIVATE."""
    path = Path(path)
    if mode is None:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            mode = PRIVATE
    data = content.encode("utf8") if isinstance(content, str) else content
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")  # its own name: no clash
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())  # on disk before the rename: a power cut never leaves an empty file
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)  # nothing half-written left behind
        raise
