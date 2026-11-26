"""Unshackle's CDMs, from the web page: its Widevine (.wvd) and PlayReady (.prd) devices, and
which one each service uses.

The devices are files (a PlayReady device can also be a folder of certificates) in the WVDs
and PRDs folders; the choice per service is the cdm: section of unshackle.yaml, where only the
service's own entry changes: comments, quotes and indents stay as they are. Unshackle reads both anew for every
download, so a change applies to the next one. A device is never sent to the browser: it
holds a private key.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

import yaml

from unshacklarr.files import no_credentials, shared_or_private, write_atomic

NAME = re.compile(r"[A-Za-z0-9][\w.@ -]{0,150}")  # device names as seen: letters, digits, _ . - @ and spaces
SERVICE = re.compile(r"[A-Za-z0-9][\w-]{0,39}")
MAX_SIZE = 1_000_000
NO_CDM = "none"  # a service set to it uses no CDM at all (no DRM): Unshackle's cdm: section, as the fork reads it
# remote_cdm entries the page edits, by kind: {key: label}; custom_api and others stay in unshackle.yaml
REMOTE_KINDS = {
    "widevine": "Widevine, pywidevine serve", "playready": "PlayReady, remote", "decrypt_labs": "Decrypt Labs",
}
REMOTE_FIELDS = ("name", "type", "device_type", "system_id", "security_level", "host", "secret", "device_name")
KINDS = {".wvd": ("Widevine", b"WVD"), ".prd": ("PlayReady", b"PRD")}


UNSAFE_EDIT = "Could not change unshackle.yaml safely: change it by hand"
YAML_STR = yaml.resolver.BaseResolver.DEFAULT_SCALAR_TAG
YAML_MAP = yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG
YAML_NULL = "tag:yaml.org,2002:null"
YAML_MERGE = "tag:yaml.org,2002:merge"
ROUTE_LOCK = threading.RLock()
_ROUTE_LOCK = ROUTE_LOCK
_UNSET = object()
# This identifier is interpolated into the existing device-in-use message.
_REDACTED_RULE = "a-configured-rule".replace("-", " ")
DrmSystem = Literal["widevine", "playready"]
_RouteInventory = tuple[list[dict], list[dict], dict[str, dict], dict[str, str], dict[str, set[str]]]
_RouteValue = str | dict[str, str | None] | None


@dataclass(frozen=True)
class CdmRoute:
    service: str
    widevine: str | None = None
    playready: str | None = None
    preferred: DrmSystem | None = None
    advanced: bool = False
    no_cdm: bool = False
    devices: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "service": self.service, "widevine": self.widevine, "playready": self.playready,
            "preferred": self.preferred, "advanced": self.advanced, "no_cdm": self.no_cdm, "devices": list(self.devices),
        }


@dataclass(frozen=True)
class _RouteSection:
    key: yaml.ScalarNode
    node: yaml.Node
    node_refs: Counter[int]
    header: _RouteLine | None
    lines: tuple[str, ...]


class CdmError(ValueError):
    """What is wrong, in words for the page."""


class BrokenYaml(CdmError):
    """unshackle.yaml cannot be read: the panes say so, and its editor opens it to fix."""


class _MultipleDocuments(CdmError):
    """No single document can be treated as the Unshackle configuration."""


def directory(yaml_file: Path, key: str, default: str) -> Path:
    """A folder of Unshackle's, found next to unshackle.yaml: its directories: section names it for
    Unshackle's own filesystem, so only its last part is kept."""
    named = default
    try:
        docs = list(yaml.safe_load_all(regular(yaml_file).read_text(encoding="utf8"))) if yaml_file.exists() else []
        if len(docs) == 1 and isinstance(docs[0], dict) and isinstance(dirs := docs[0].get("directories"), dict):
            named = dirs.get(key) or default
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        raise BrokenYaml(f"unshackle.yaml has a syntax error{where}: fix it in Settings or in the file") from e
    name = Path(str(named)).name
    if name in ("", ".", ".."):  # "..", "/" or ".": not a folder next to unshackle.yaml
        raise CdmError(f"unshackle.yaml's directories: {key}: {named!r} is not a folder next to it")
    return yaml_file.parent / name


def folders(yaml_file: Path) -> tuple[Path, Path]:
    """The WVDs and PRDs folders."""
    return directory(yaml_file, "wvds", "WVDs"), directory(yaml_file, "prds", "PRDs")


def read(yaml_file: Path) -> dict:
    return yaml.safe_load(regular(yaml_file).read_text(encoding="utf8")) or {} if yaml_file.exists() else {}


def regular(path: Path) -> Path:
    """The file itself, never a link: a link put in a shared folder would make the page read, then write
    back in that folder, what it points to (DownStream's own config.yaml, say)."""
    if path.is_symlink():
        raise CdmError(f"{path.name} is a symbolic link: replace it with the file itself")
    return path


def describe(path: Path, kind: str) -> dict:
    """A device as the page shows it: its name (what unshackle.yaml calls it), kind and level."""
    level = kind_of = ""
    if path.is_file() and path.suffix.lower() == ".wvd":
        with path.open("rb") as f:
            head = f.read(6)  # "WVD", version, type, security level
        if head[:3] == b"WVD" and len(head) == 6:
            kind_of = {1: "Chrome", 2: "Android"}.get(head[4], "")
            level = f"L{head[5]}" if head[5] else ""
    if kind == "PlayReady":
        found = re.search(r"sl(\d{3,4})", path.name, re.IGNORECASE)  # the certificate is not read: its name says it
        level = f"SL{found.group(1)}" if found else ""
    folder = path.is_dir()
    suffix = ".wvd" if kind == "Widevine" else ".prd"
    return {"name": path.stem if not folder else path.name, "kind": kind, "level": level, "type": kind_of,
            "folder": folder, "size": path.stat().st_size if not folder else None,
            "routable": not folder and path.with_suffix(suffix).is_file()}


def devices(wvds: Path, prds: Path) -> list[dict]:
    found: dict[tuple[str, bool, str], dict] = {}
    for folder, kind, suffix in ((wvds, "Widevine", ".wvd"), (prds, "PlayReady", ".prd"), (wvds, "PlayReady", ".prd")):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir(), key=lambda p: (p.name.lower(), p.suffix != suffix)):
            is_device_file = path.is_file() and path.suffix.lower() == suffix
            is_prd_folder = kind == "PlayReady" and folder == prds and path.is_dir() and not path.name.startswith(".")
            if not (is_device_file or is_prd_folder):
                continue
            device = describe(path, kind)
            key = (kind, device["folder"], device["name"])
            # Only a resolvable primary PRD can shadow the fallback in WVDs.
            if key not in found or (device["routable"] and not found[key]["routable"]):
                found[key] = device
    return list(found.values())


def names_in(value) -> set[str]:
    """The devices a cdm: entry names: one, or several in a rule by profile, quality or DRM."""
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, dict):
        return set().union(*(names_in(v) for v in value.values())) if value else set()
    return set()


def route_of(service: str, raw_value: object, kind_by_name: dict[str, str]) -> CdmRoute:
    if raw_value is None or raw_value == "":
        return CdmRoute(service)
    if raw_value == NO_CDM:
        return CdmRoute(service, no_cdm=True)
    if isinstance(raw_value, str):
        kind = kind_by_name.get(raw_value)
        if kind == "PlayReady" or (kind is None and re.search(r"(?:^|[_\W])sl\d{3,4}\b", raw_value, re.IGNORECASE)):
            return CdmRoute(service, playready=raw_value, preferred="playready", devices=(raw_value,))
        return CdmRoute(service, widevine=raw_value, preferred="widevine", devices=(raw_value,))
    if isinstance(raw_value, dict) and all(isinstance(k, str) for k in raw_value):
        slots = {k.lower(): v for k, v in raw_value.items()}
        if (slots and len(slots) == len(raw_value) and slots.keys() <= {"widevine", "playready"}
                and all(v is None or isinstance(v, str) and v != NO_CDM for v in slots.values())):
            active = tuple(v for v in slots.values() if v)
            if active:
                first = next(iter(slots))
                if first == "playready" and not slots["playready"]:
                    return CdmRoute(service, widevine=slots["widevine"], devices=active)
                return CdmRoute(service, slots.get("widevine") or None, slots.get("playready") or None,
                                "widevine" if first == "widevine" and slots.get("widevine") else "playready",
                                devices=active)
            return CdmRoute(service)
    return CdmRoute(service, advanced=True, devices=tuple(sorted(names_in(raw_value))))


def _route_document(text: str) -> tuple[dict, _RouteSection | None]:
    # SafeLoader's constructor flattens merges in place, erasing the original source positions.
    try:
        docs = list(yaml.safe_load_all(text))
        if len(docs) > 1:
            raise _MultipleDocuments(UNSAFE_EDIT)
        loader = yaml.SafeLoader(text)
        try:
            root = loader.get_node() if loader.check_node() else None
        finally:
            loader.dispose()
    except yaml.YAMLError as exc:
        raise BrokenYaml("unshackle.yaml has a syntax error: fix it in Settings or in the file") from exc
    config = docs[0] if docs else None
    if config is not None and not isinstance(config, dict):
        raise CdmError(UNSAFE_EDIT)
    if not isinstance(root, yaml.MappingNode):
        return config or {}, None
    sections = [(k, v) for k, v in root.value if isinstance(k, yaml.ScalarNode) and k.value == "cdm"]
    if len(sections) > 1:
        raise CdmError(UNSAFE_EDIT)
    if not sections:
        return config or {}, None
    key, node = sections[0]
    node_refs = _node_references(root)
    lines = tuple(text.splitlines(keepends=True))
    header = None
    if key.tag == YAML_STR and node_refs[id(key)] == node_refs[id(node)] == 1:
        try:
            if isinstance(node, yaml.MappingNode) and node.tag == YAML_MAP:
                if not node.flow_style and not any(k.tag == YAML_MERGE for k, _ in node.value):
                    header = _route_line(lines, key)
                elif not node.value:
                    header = _route_line(lines, key, node)
            elif isinstance(node, yaml.ScalarNode) and node.tag == YAML_NULL:
                header = _route_line(lines, key, node)
        except CdmError:
            pass
    return config or {}, _RouteSection(key, node, node_refs, header, lines)


def _node_references(root: yaml.Node) -> Counter[int]:
    refs: Counter[int] = Counter()
    pending = [root]
    while pending:
        node = pending.pop()
        refs[id(node)] += 1
        if refs[id(node)] > 1:
            continue
        if isinstance(node, yaml.MappingNode):
            pending.extend(child for pair in node.value for child in pair)
        elif isinstance(node, yaml.SequenceNode):
            pending.extend(node.value)
    return refs


def _cdm_mapping(config: dict) -> dict:
    mapping = config.get("cdm")
    if mapping is None:
        return {}
    if not isinstance(mapping, dict):
        raise CdmError(UNSAFE_EDIT)
    return mapping


def _config_secrets(config: dict) -> set[str]:
    suffixes = ("secret", "apikey", "key", "token", "password", "passwd", "pwd", "pin",
                "clientid", "clientsecret", "authorization", "cookie", "bearer")

    def credential_field(key: object) -> bool:
        name = squash(key)
        return name in ("credentials", "auth", "headers") or name.endswith(suffixes)

    values: set[str] = set()
    serve = config.get("serve")
    if isinstance(serve, dict) and isinstance(users := serve.get("users"), dict):
        values.update(str(user) for user in users if type(user) in (str, int, float) and str(user))
        values.update(str(value) for value in users.values() if type(value) in (str, int, float) and str(value))

    seen: set[tuple[int, bool, bool]] = set()
    pending = [(value, credential_field(key), squash(key) == "auth") for key, value in config.items() if key != "cdm"]
    while pending:
        item, collect_all, auth_schema = pending.pop()
        visit = id(item), collect_all, auth_schema
        # A YAML alias can reach the same value through a credential-bearing field later.
        if visit in seen:
            continue
        seen.add(visit)
        if isinstance(item, dict):
            for key, child in item.items():
                name = squash(key)
                if (auth_schema and name in ("type", "headername", "method")
                        and isinstance(child, str) and no_credentials(child) == child):
                    continue
                pending.append((child, collect_all or credential_field(key), name == "auth"))
        elif isinstance(item, list):
            pending.extend((child, collect_all, False) for child in item)
        elif collect_all and type(item) in (str, int, float) and str(item):
            values.add(str(item))
    return values


def _text_secrets(text: str) -> set[str]:
    return set().union(*(_config_secrets(doc) for doc in yaml.safe_load_all(text) if isinstance(doc, dict)))


def file_secrets(yaml_file: Path) -> set[str]:
    """Collect configured credentials from every document in the YAML file."""
    if not yaml_file.exists():
        return set()
    return _text_secrets(regular(yaml_file).read_text(encoding="utf8"))


def _contains_secret_text(text: str, secrets: set[str]) -> bool:
    decoded = unquote(text)
    return any(part in secrets or any(len(value) >= 4 and value in part for value in secrets)
               for part in (text, decoded, unquote(decoded)))


def _mask_url_secrets(text: str, secrets: set[str]) -> str:
    if "://" not in text or not secrets:
        return text

    def mask(part: str) -> str:
        return "***" if part not in ("", "&", "=") and _contains_secret_text(part, secrets) else part

    def mask_url(token: str) -> str:
        bare = token.rstrip(".,;:!?)")
        try:
            url = urlsplit(bare)
        except ValueError:
            return token
        path = "/".join(map(mask, url.path.split("/")))
        query = "".join(map(mask, re.split(r"([&=])", url.query)))
        fragment = mask(url.fragment)
        if (path, query, fragment) == (url.path, url.query, url.fragment):
            return token
        return url._replace(path=path, query=query, fragment=fragment).geturl() + token[len(bare):]

    return re.sub(
        r"[A-Za-z][A-Za-z0-9+.-]*://(?:[^\s<>'\"`/@\]]*@)?(?:\[[^\s<>'\"`\]]+\][^\s<>'\"`\]]*|[^\s<>'\"`\]]+)",
        lambda match: mask_url(match[0]),
        text,
    )


def _contains_secret(text: str, secrets: set[str]) -> bool:
    return _contains_secret_text(text, secrets) or _mask_url_secrets(text, secrets) != text


def _has_secret(text: str, secrets: set[str]) -> bool:
    return _contains_secret(text, secrets) or no_credentials(text) != text


def _mask_secrets(text: str, secrets: set[str]) -> str:
    masked = no_credentials(text)
    if text in secrets:
        return "***"
    for value in sorted((value for value in secrets if len(value) >= 4), key=len, reverse=True):
        masked = masked.replace(value, "***")
    masked = _mask_url_secrets(masked, secrets)
    return "***" if _contains_secret_text(masked, secrets) else masked


def mask_diagnostic(text: str, secrets: set[str]) -> str:
    """Mask credentials in prose while keeping short values inside identifiers intact."""
    masked = _mask_secrets(text, secrets)
    short = sorted((value for value in secrets if 1 <= len(value) < 4), key=len, reverse=True)
    if not short:
        return masked
    alternatives = "|".join(map(re.escape, short))
    return re.sub(rf"(?<![\w-])(?<!\w\.)(?:{alternatives})(?!(?:[\w-]|\.\w))", "***", masked)


def _route_inventory(config: dict, wvds: Path, prds: Path, *, secrets: set[str]) -> _RouteInventory:
    local = devices(wvds, prds)
    entries = config.get("remote_cdm")
    remote = [{"name": r["name"], "kind": remote_system(r), **remote_view(r, secrets)}
              for r in (entries if isinstance(entries, list) else [])
              if isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"]]
    prd_files = [d for d in local if d["kind"] == "PlayReady" and not d["folder"]]
    other_local = sorted((d for d in local if d["kind"] == "Widevine" or d["folder"]), key=lambda d: d["folder"])
    winners: dict[str, dict] = {}
    all_kinds: dict[str, set[str]] = {}
    for d in remote + prd_files + other_local:
        if not d.get("routable", True):
            continue
        winners.setdefault(d["name"], d)
        all_kinds.setdefault(d["name"], set()).add(d["kind"])
    kinds = {name: d["kind"] for name, d in winners.items()}
    return local, remote, winners, kinds, all_kinds


def _configured_routes(
    config: dict, section: _RouteSection | None, kinds: dict[str, str], *, secrets: set[str] | None = None,
) -> dict[str, CdmRoute]:
    mapping = _cdm_mapping(config)
    source = section.node.value if section and isinstance(section.node, yaml.MappingNode) else []
    pairs = {k.value: (k, v) for k, v in source if isinstance(k, yaml.ScalarNode)}
    service_keys = Counter(str(k).lower() for k in mapping)
    source_keys = Counter(k.value.lower() for k, _ in source if isinstance(k, yaml.ScalarNode))
    secrets = _config_secrets(config) if secrets is None else secrets

    def safe_name(name: str) -> bool:
        return name != NO_CDM and bool(NAME.fullmatch(name)) and not _has_secret(name, secrets)

    routes = {}
    for key, value in mapping.items():
        service = str(key)
        if _has_secret(service, secrets):
            continue
        lower = service.lower()
        route = route_of(service, value, kinds)
        if (section is None or section.header is None or not isinstance(key, str) or not SERVICE.fullmatch(service)
                or service_keys[lower] > 1
                or source_keys[lower] > 1 or service not in pairs or _unsafe_route_nodes(section, *pairs[service])):
            route = replace(route, advanced=True)
        if (any(name != NO_CDM and not safe_name(name) for name in names_in(value))
                or (route.advanced and any(name is not None and not safe_name(name)
                                           for name in (route.widevine, route.playready, route.preferred)))):
            route = replace(route, advanced=True, widevine=None, playready=None, preferred=None, no_cdm=False)
        if route.advanced:
            route = replace(route, devices=tuple(name for name in route.devices if safe_name(name)))
        elif value is None or value == "":
            continue
        routes[service] = route
    return routes


def _unsafe_route_nodes(section: _RouteSection, key: yaml.Node, node: yaml.Node) -> bool:
    refs, lines = section.node_refs, section.lines
    if key.tag != YAML_STR or refs[id(key)] > 1 or refs[id(node)] > 1:
        return True
    try:
        if not isinstance(node, yaml.MappingNode):
            _route_line(lines, key, node)
            return False
        line = _route_line(lines, key, node if node.flow_style else None).index
        slots = set()
        for child, value in node.value:
            if (not isinstance(child, yaml.ScalarNode) or child.tag != YAML_STR
                    or refs[id(child)] > 1 or refs[id(value)] > 1):
                return True
            slot = child.value.lower()
            if slot in slots or (not node.flow_style and _route_line(lines, child, value).index <= line):
                return True
            slots.add(slot)
    except CdmError:
        return True
    return False


def state(yaml_file: Path, wvds: Path, prds: Path) -> dict:
    """Return devices, a normalized compatibility map, and structured routes."""
    return state_with_secrets(yaml_file, wvds, prds)[0]


def state_with_secrets(yaml_file: Path, wvds: Path, prds: Path) -> tuple[dict, set[str]]:
    """Read the public state and its metadata redaction rules from one config snapshot."""
    text = regular(yaml_file).read_bytes().decode("utf8") if yaml_file.exists() else ""
    try:
        config, section = _route_document(text)
    except _MultipleDocuments:
        secrets = _text_secrets(text)
        found = [
            {**device, "used_by": []}
            for device in devices(wvds, prds) if not _has_secret(device["name"], secrets)
        ]
        return {"devices": found, "remote": [], "map": {}, "routes": {}, "read_only": True}, secrets
    secrets = _config_secrets(config)
    payload, _ = _state_from(config, section, wvds, prds, text=text, secrets=secrets)
    return payload, secrets


def _rule_resolves(item: object, *, allow_quality: bool = True, allow_scalar_default: bool = False) -> bool:
    if isinstance(item, str):
        return item.strip() not in ("", NO_CDM)
    if not isinstance(item, dict) or not item:
        return False
    # A truthy quality match takes precedence over the outer DRM slots in Unshackle.
    if allow_quality and any(
        isinstance(key, str) and re.fullmatch(r"(?:>=|<=|>|<)?\d+", key) and value
        and _rule_resolves(value, allow_quality=False, allow_scalar_default=allow_scalar_default)
        for key, value in item.items()
    ):
        return True
    slots = {key.lower(): value for key, value in item.items() if isinstance(key, str)}
    first = next((key for key in slots if key in ("widevine", "playready")), None)
    if first is not None:
        selected = slots[first] or slots.get("playready")
        return isinstance(selected, str) and selected.strip() not in ("", NO_CDM)
    return (allow_scalar_default and not item.get("default")
            or any(_rule_resolves(value, allow_quality=False) for value in item.values()))


def _state_from(
    config: dict, section: _RouteSection | None, wvds: Path, prds: Path, *,
    text: str,
    inventory: _RouteInventory | None = None, redact_inventory: bool = True, secrets: set[str] | None = None,
) -> tuple[dict, dict[str, CdmRoute]]:
    mapping = _cdm_mapping(config)
    secrets = _config_secrets(config) if secrets is None else secrets
    found, remote, winners, kinds, _ = inventory if inventory is not None else _route_inventory(config, wvds, prds, secrets=secrets)
    routes = _configured_routes(config, section, kinds, secrets=secrets)
    for d in (*found, *remote):
        d["used_by"] = []
    for key, value in sorted(mapping.items(), key=lambda item: str(item[0])):
        service = str(key)
        if _has_secret(service, secrets):
            if redact_inventory:
                continue
            service = _REDACTED_RULE
        # Deletion still checks the original references even when public routes hide them.
        for name in names_in(value) - {NO_CDM}:
            if name in winners:
                winners[name]["used_by"].append(service)
    legacy = {}
    for key, value in mapping.items():
        name = str(key)
        route = routes.get(name)
        if route is None:
            if not _has_secret(name, secrets) and (value is None or value == ""):
                legacy[name] = None
            continue
        if isinstance(value, dict) and not value:
            legacy[name] = {}
        elif isinstance(value, list) and not value:
            legacy[name] = []
        elif not value:
            legacy[name] = None
        elif isinstance(value, str) and not route.advanced:
            legacy[name] = value
        elif isinstance(value, dict) and not route.advanced:
            slots = {"widevine": route.widevine, "playready": route.playready}
            first = next((str(key).lower() for key in value if str(key).lower() in slots), "widevine")
            legacy[name] = {first: slots[first], **slots, "preferred": route.preferred}
        elif _rule_resolves(value):
            legacy[name] = {"rule": list(route.devices)}
        elif _rule_resolves(value, allow_scalar_default=True):
            legacy[name] = {"rule": None}
        else:
            legacy[name] = {"rule": False}
    if redact_inventory:
        found = [d for d in found if not _has_secret(d["name"], secrets)]
        remote = [d for d in remote if not _has_secret(d["name"], secrets)]
    return {"devices": found, "remote": remote, "map": legacy,
            "routes": {name: route.to_dict() for name, route in routes.items()},
            "read_only": section.header is None if section is not None else not _can_create_section(text, config)}, routes


def get_route(yaml_file: Path, wvds: Path, prds: Path, service: str) -> CdmRoute:
    text = regular(yaml_file).read_bytes().decode("utf8") if yaml_file.exists() else ""
    config, section = _route_document(text)
    secrets = _config_secrets(config)
    _, _, _, kinds, _ = _route_inventory(config, wvds, prds, secrets=secrets)
    routes = _configured_routes(config, section, kinds, secrets=secrets)
    return next((route for name, route in routes.items() if name.lower() == service.lower()), CdmRoute(service))


def set_route(
    yaml_file: Path, wvds: Path, prds: Path, service: str, *,
    widevine: str | None | object = _UNSET, playready: str | None | object = _UNSET, preferred: str | None = None,
    no_cdm: bool = False,
) -> CdmRoute:
    return save_route(yaml_file, wvds, prds, service, widevine=widevine, playready=playready,
                      preferred=preferred, no_cdm=no_cdm)[0]


def save_route(
    yaml_file: Path, wvds: Path, prds: Path, service: str, *,
    widevine: str | None | object = _UNSET, playready: str | None | object = _UNSET, preferred: str | None = None,
    no_cdm: bool = False,
) -> tuple[CdmRoute, str | None]:
    saved, before, _ = save_route_state(yaml_file, wvds, prds, service, widevine=widevine, playready=playready,
                                        preferred=preferred, no_cdm=no_cdm)
    return saved, before


def save_route_state(
    yaml_file: Path, wvds: Path, prds: Path, service: str, *,
    widevine: str | None | object = _UNSET, playready: str | None | object = _UNSET, preferred: str | None = None,
    no_cdm: bool = False,
) -> tuple[CdmRoute, str | None, dict]:
    """Save a route and capture its API state from the same verified config and device inventory."""
    if not isinstance(service, str) or not SERVICE.fullmatch(service):
        raise CdmError("Choose a valid service")
    if (any(v is not _UNSET and v is not None and not isinstance(v, str) for v in (widevine, playready))
            or (preferred is not None and not isinstance(preferred, str))):
        raise CdmError("CDM slots and preferred DRM must be text or null")
    if not isinstance(no_cdm, bool):
        raise CdmError("No CDM must be true or false")
    if widevine is _UNSET and playready is _UNSET and preferred is None and not no_cdm:
        raise CdmError("Choose a slot, a preferred DRM, or No CDM")
    explicit_slots = {drm for drm, raw in (("widevine", widevine), ("playready", playready))
                      if isinstance(raw, str) and raw}
    with ROUTE_LOCK:
        if not regular(yaml_file).is_file():
            raise CdmError(f"No unshackle.yaml in {yaml_file.parent}")
        text = regular(yaml_file).read_bytes().decode("utf8")
        config, section = _route_document(text)
        if section is None and not _can_create_section(text, config):
            raise CdmError(UNSAFE_EDIT)
        mapping = _cdm_mapping(config)
        existing_name = next((str(k) for k in mapping if str(k).lower() == service.lower()), service)
        secrets = _config_secrets(config)
        if _has_secret(service, secrets) or _has_secret(existing_name, secrets):
            raise CdmError("Choose a valid service")
        inventory = _route_inventory(config, wvds, prds, secrets=secrets)
        _, _, _, kinds, all_kinds = inventory
        routes = _configured_routes(config, section, kinds, secrets=secrets)
        current = routes.get(existing_name, CdmRoute(existing_name))
        if current.advanced:
            raise CdmError(f"{service} has a rule by profile, quality or DRM: change it in unshackle.yaml")
        wv = current.widevine if not no_cdm and widevine is _UNSET else widevine
        pr = current.playready if not no_cdm and playready is _UNSET else playready
        slots = {drm: name for drm, name in (("widevine", wv), ("playready", pr)) if isinstance(name, str) and name}
        value: _RouteValue = _route_value(current, slots, preferred, no_cdm, kinds, all_kinds, explicit_slots)
        sole_slot = next(iter(slots), None)
        raw_slots = mapping.get(existing_name)
        if not no_cdm and sole_slot is not None and len(slots) == 1 and isinstance(raw_slots, dict):
            sibling, argument = ("playready", playready) if sole_slot == "widevine" else ("widevine", widevine)
            original_slots = {key.lower(): raw for key, raw in raw_slots.items()}
            if argument is _UNSET and (sole_slot in explicit_slots or preferred == sole_slot):
                if sibling in original_slots and original_slots[sibling] in (None, ""):
                    if sole_slot in original_slots and current.preferred == sole_slot and preferred is None:
                        value = {drm: slots.get(drm, raw) for drm, raw in original_slots.items()}
                    else:
                        # Put a newly effective slot first so Unshackle can select it without an explicit DRM.
                        value = {sole_slot: slots[sole_slot], sibling: original_slots[sibling]}
                elif original_slots.keys() == {sole_slot}:
                    value = slots
        edited = _edit_route(text, section, current, value, sole_slot)
        saved_config, saved_section, before = _write_route(yaml_file, text, edited, config, current.service, value, kinds)
        saved_state, saved_routes = _state_from(saved_config, saved_section, wvds, prds, text=edited, inventory=inventory)
        saved = CdmRoute(current.service) if value is None else saved_routes[current.service]
        if value is not None and saved.advanced:
            raise CdmError(UNSAFE_EDIT)
        return saved, before, saved_state


def _write_route(
    yaml_file: Path, text: str, edited: str, config: dict, service: str, value: _RouteValue,
    kinds: dict[str, str],
) -> tuple[dict, _RouteSection | None, str | None]:
    expected = _cdm_mapping(config).copy()
    if value is None:
        expected.pop(service, None)
    else:
        expected[service] = value
    try:
        edited_config, edited_section = _route_document(edited)
    except BrokenYaml as exc:
        raise CdmError(UNSAFE_EDIT) from exc
    if not _matches_config_with_ordered_route(edited_config, edited_section, config, expected, service, kinds):
        raise CdmError(UNSAFE_EDIT)
    if regular(yaml_file).read_bytes() != text.encode("utf8"):
        raise CdmError(UNSAFE_EDIT)
    if edited == text:
        return edited_config, edited_section, None
    write_atomic(yaml_file, edited)
    saved_text = regular(yaml_file).read_bytes().decode("utf8")
    try:
        saved_config, saved_section = _route_document(saved_text)
    except BrokenYaml as exc:
        raise CdmError(UNSAFE_EDIT) from exc
    if not _matches_config_with_ordered_route(saved_config, saved_section, config, expected, service, kinds):
        raise CdmError(UNSAFE_EDIT)
    return saved_config, saved_section, text


def _route_value(
    current: CdmRoute, slots: dict[str, str], preferred: str | None, no_cdm: bool, kinds: dict[str, str],
    all_kinds: dict[str, set[str]], explicit_slots: set[str],
) -> str | dict[str, str] | None:
    if preferred is not None and preferred not in slots:
        raise CdmError("Preferred DRM must have a device in its slot")
    if no_cdm:
        if slots:
            raise CdmError("No CDM cannot be combined with a device")
        if current.service.lower() == "default":
            raise CdmError("The default CDM cannot be none: set none on the services without DRM")
        return NO_CDM
    if not slots and current.service.lower() == "default":
        raise CdmError("The default CDM cannot be removed, only changed")
    for drm, name in slots.items():
        if drm not in explicit_slots and drm != preferred:
            continue
        label = "Widevine" if drm == "widevine" else "PlayReady"
        if name == NO_CDM or kinds.get(name) != label:
            if name != NO_CDM and label in all_kinds.get(name, set()):
                raise CdmError(f"{name} resolves to the {kinds[name]} device of the same name: rename one before using {label}")
            raise CdmError(f"Choose a {label} device for the {label} slot")
    if not slots:
        return None
    if len(slots) == 1:
        name = next(iter(slots.values()))
        return name if route_of(current.service, name, kinds) == route_of(current.service, slots, kinds) else slots
    first = preferred or current.preferred or "widevine"
    return {first: slots[first], **{drm: name for drm, name in slots.items() if drm != first}}


def _matches_config_with_ordered_route(
    parsed: dict, section: _RouteSection | None, original: dict, expected: dict, service: str, kinds: dict[str, str],
) -> bool:
    mapping = _cdm_mapping(parsed)
    expected_slots = expected.get(service)
    if isinstance(expected_slots, dict):
        parsed_slots = mapping.get(service)
        if not isinstance(parsed_slots, dict):
            return False
        ordered_lowercase_slots = [(str(slot).lower(), device) for slot, device in parsed_slots.items()]
        if not _ordered_equal(ordered_lowercase_slots, list(expected_slots.items())):
            return False
        mapping = {**mapping, service: expected_slots}
    return (_ordered_equal(mapping, expected)
            and _ordered_equal({k: v for k, v in parsed.items() if k != "cdm"},
                               {k: v for k, v in original.items() if k != "cdm"})
            and (service not in expected or not _configured_routes(parsed, section, kinds)[service].advanced))


def _ordered_equal(left: object, right: object) -> bool:
    pending = [(left, right)]
    compared: set[tuple[int, int]] = set()
    while pending:
        a, b = pending.pop()
        if type(a) is not type(b):
            return False
        if a is b:
            continue
        if isinstance(a, (dict, list, tuple)):
            if len(a) != len(b):
                return False
            pair = id(a), id(b)
            if pair in compared:
                continue
            compared.add(pair)
            if isinstance(a, dict):
                for (a_key, a_value), (b_key, b_value) in zip(a.items(), b.items()):
                    pending.extend(((a_key, b_key), (a_value, b_value)))
            else:
                pending.extend(zip(a, b))
        elif a != b:
            return False
    return True


@dataclass(frozen=True)
class _RouteLine:
    index: int
    prefix: str
    spacing: str
    raw: str
    suffix: str
    indent: str

    def render(self, value: str = "") -> str:
        return f"{self.prefix}{self.spacing if self.raw and value else ' ' if value else ''}{value}{self.suffix}"

    def comment(self) -> str:
        suffix = self.suffix.lstrip(" \t")
        return self.indent + suffix if suffix.startswith("#") else ""


def _route_line(lines: Sequence[str], key: yaml.Node, value: yaml.Node | None = None) -> _RouteLine:
    index, start, end = key.start_mark.line, key.start_mark.column, key.end_mark.column
    line = lines[index]
    colon = re.match(r"[ \t]*:", line[end:])
    if not colon or key.end_mark.line != index or line[:start].strip():
        raise CdmError(UNSAFE_EDIT)
    end += colon.end()
    tail = line[end:]
    if value is None or (isinstance(value, yaml.ScalarNode) and not value.value and not value.style):
        if tail.strip() and not tail.lstrip().startswith("#"):
            raise CdmError(UNSAFE_EDIT)
        return _RouteLine(index, line[:end], "", "", tail, line[:start])
    left, right = value.start_mark.column, value.end_mark.column
    inline = (isinstance(value, yaml.ScalarNode) and value.style not in ("|", ">")
              or isinstance(value, yaml.MappingNode) and value.flow_style)
    if (not inline or value.start_mark.line != index or value.end_mark.line != index
            or left < end or line[end:left].strip()):
        raise CdmError(UNSAFE_EDIT)
    return _RouteLine(index, line[:end], line[end:left], line[left:right], line[right:], line[:start])


def _yaml_string(device: str, old: _RouteLine | None = None) -> str:
    if device == NO_CDM:
        return NO_CDM
    raw = old.raw if old else ""
    try:
        if raw and yaml.safe_load(raw) == device:
            return raw
    except yaml.YAMLError:
        pass
    if raw.startswith("'"):
        return "'" + device.replace("'", "''") + "'"
    if raw.startswith('"'):
        return json.dumps(device, ensure_ascii=False)
    if device != "..." and re.fullmatch(r"[A-Za-z0-9_][\w.@-]*", device):
        try:
            if yaml.safe_load(device) == device:
                return device
        except yaml.YAMLError:
            pass
    return json.dumps(device, ensure_ascii=False)


def _render_flow_route(
    line: str, header: _RouteLine, node: yaml.MappingNode, value: _RouteValue, sole_slot: str | None,
) -> str:
    if value is None:
        return header.comment()
    keys = {}
    children = {}
    for key, child in node.value:
        drm = key.value.lower()
        if key.start_mark.line == key.end_mark.line == header.index:
            keys[drm] = line[key.start_mark.column:key.end_mark.column]
        if child.start_mark.line == child.end_mark.line == header.index:
            children[drm] = replace(header, raw=line[child.start_mark.column:child.end_mark.column])
    if isinstance(value, dict):
        slots = []
        for drm, name in value.items():
            prior = children.get(drm)
            raw = prior.raw if name in (None, "") and prior else _yaml_string(name or "", prior)
            key = keys.get(drm, drm)
            slots.append(f"{key}: {raw}" if raw else f"{key}:")
        return header.render("{" + ", ".join(slots) + "}")
    return header.render(_yaml_string(value, children.get(sole_slot) if sole_slot else None))


def _edit_route(
    text: str, section: _RouteSection | None, current: CdmRoute,
    value: _RouteValue, sole_slot: str | None,
) -> str:
    lines = list(section.lines) if section else text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in text else "\n"
    if section is None:
        if value is None:
            return text
        end = len(lines)
        while end and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        top = len(lines)
        if end and re.fullmatch(r"\.\.\.(?:\s+#.*|\s*)", lines[end - 1].rstrip("\r\n")):
            top = end - 1
        if top and not lines[top - 1].endswith("\n"):
            lines[top - 1] += newline
        lines.insert(top, "cdm:" + newline)
        siblings = []
    else:
        header = section.header
        if header is None:
            raise CdmError(UNSAFE_EDIT)
        node = section.node
        top = header.index
        if isinstance(node, yaml.MappingNode) and not node.flow_style:
            siblings = node.value
        else:
            if value is not None:
                lines[top] = header.render()
            siblings = []
    indent = " " * (siblings[0][0].start_mark.column if siblings else (section.key.start_mark.column + 2 if section else 2))
    pair = next(((k, v) for k, v in siblings
                 if isinstance(k, yaml.ScalarNode) and k.tag == YAML_STR and k.value == current.service), None)
    if pair is None:
        if value is None:
            return text
        at = section_end(lines, top)
        header = _RouteLine(at, f"{indent}{_yaml_string(current.service)}:", "", "", newline, indent)
        stop = at
        children = {}
    else:
        key, node = pair
        if isinstance(node, yaml.MappingNode) and node.flow_style:
            header = _route_line(lines, key, node)
            lines[header.index] = _render_flow_route(lines[header.index], header, node, value, sole_slot)
            return "".join(lines)
        header = _route_line(lines, key, None if isinstance(node, yaml.MappingNode) else node)
        children = ({k.value.lower(): _route_line(lines, k, v) for k, v in node.value}
                    if isinstance(node, yaml.MappingNode) else {})
        at, stop = header.index, max((item.index for item in children.values()), default=header.index) + 1
    return _replace_route_lines(lines, header, children, at, stop, newline, current, value, sole_slot)


def _replace_route_lines(
    lines: list[str], header: _RouteLine, children: dict[str, _RouteLine], at: int, stop: int,
    newline: str, current: CdmRoute, value: _RouteValue, sole_slot: str | None,
) -> str:
    if any(not (at < child.index < stop) for child in children.values()):
        raise CdmError(UNSAFE_EDIT)
    remaining = lines[at + 1:stop]
    if isinstance(value, dict) and len(value) < len(children):
        for drm, child in children.items():
            remaining[child.index - at - 1] = (
                child.render(_yaml_string(value[drm] or "", child)) if drm in value else child.comment()
            )
        first = header.render()
    elif isinstance(value, dict):
        indent = next(iter(children.values())).indent if children else header.indent * 2
        slots = []
        for drm, name in value.items():
            prior = children.get(drm)
            if name in (None, "") and prior:
                row = lines[prior.index]
            else:
                style = prior or (header if drm == current.preferred else None)
                fresh = _RouteLine(at, f"{indent}{drm}:", "", "", newline, indent)
                row = (prior or fresh).render(_yaml_string(name or "", style))
            slots.append(row if row.endswith("\n") else row + newline)
        order = list(children)
        if len(order) == 1 and len(slots) == 2 and order[0] != next(iter(value)):
            remaining = [slots[0], *lines[at + 1:children[order[0]].index], slots[1]]
        elif (len(order) == len(slots) == 2 and order != list(value)
                and (any(line.strip() for line in lines[at + 1:children[order[0]].index])
                     or any(line.strip() for line in lines[children[order[0]].index + 1:children[order[1]].index]))):
            first_slot, second_slot = order
            first_index, second_index = children[first_slot].index, children[second_slot].index
            before_first = lines[at + 1:first_index]
            i0 = next((i for i, line in enumerate(before_first) if line.strip()), len(before_first))
            lead_blank, first_comments = before_first[:i0], before_first[i0:]
            between = lines[first_index + 1:second_index]
            i1 = next((i for i, line in enumerate(between) if line.strip()), len(between))
            gap, second_comments = between[:i1], between[i1:]
            remaining = [*lead_blank, *second_comments, slots[0], *gap, *first_comments, slots[1]]
        else:
            for child, row in zip(children.values(), slots):
                remaining[child.index - at - 1] = row
            remaining.extend(slots[len(children):])
        first = header.render()
    else:
        for child in children.values():
            remaining[child.index - at - 1] = child.comment()
        style = children.get(sole_slot) if sole_slot else None
        first = header.render(_yaml_string(value, style or header)) if value is not None else header.comment()
    if first and remaining and not first.endswith("\n"):
        first += newline
    before = lines[:at]
    if first and before and not before[-1].endswith("\n"):
        before[-1] += newline
    return "".join([*before, first, *remaining, *lines[stop:]])


def _can_create_section(text: str, config: dict) -> bool:
    if "cdm" in config:
        return False
    try:
        edited = _edit_route(text, None, CdmRoute("default"), "ok", "widevine")
        edited_config, edited_section = _route_document(edited)
    except (CdmError, yaml.YAMLError):
        return False
    return (edited_section is not None and edited_section.header is not None
            and _ordered_equal(edited_config, {**config, "cdm": {"default": "ok"}}))


def choose(yaml_file: Path, wvds: Path, prds: Path, service: str, device: str | None) -> str | None:
    """Set or remove a scalar CDM choice and return the overwritten text if it changed."""
    if not SERVICE.fullmatch(service or ""):
        raise CdmError(f"Not a service: {service!r}")
    with ROUTE_LOCK:
        if not regular(yaml_file).exists():
            raise CdmError(f"No unshackle.yaml in {yaml_file.parent}")
        text = yaml_file.read_bytes().decode("utf8")
        config, section = _route_document(text)
        if section is None and not _can_create_section(text, config):
            raise CdmError(UNSAFE_EDIT)
        mapping = _cdm_mapping(config)
        existing_name = next((str(k) for k in mapping if str(k).lower() == service.lower()), service)
        secrets = _config_secrets(config)
        if _has_secret(service, secrets) or _has_secret(existing_name, secrets):
            raise CdmError("Choose a valid service")
        _, _, _, kinds, _ = _route_inventory(config, wvds, prds, secrets=secrets)
        if device is not None and device != NO_CDM and device not in kinds:
            raise CdmError(f"No device called {device!r}")
        if device == NO_CDM and service.lower() == "default":
            raise CdmError("The default CDM cannot be none: set none on the services without DRM")
        if device is None and service.lower() == "default":
            raise CdmError("The default CDM cannot be removed, only changed")
        routes = _configured_routes(config, section, kinds, secrets=secrets)
        current = routes.get(existing_name, CdmRoute(existing_name))
        if current.advanced or not isinstance(mapping.get(existing_name), (str, type(None))):
            raise CdmError(f"{service} has a rule by profile, quality or DRM: change it in unshackle.yaml")
        edited = _edit_route(text, section, current, device, None)
        _, _, before = _write_route(yaml_file, text, edited, config, current.service, device, kinds)
        return before


def squash(key) -> str:
    """A remote_cdm key as Unshackle compares them: device_type, "Device Type" and DeviceType are one."""
    return re.sub(r"[\s_]", "", str(key)).lower()


def field(entry: dict, name: str):
    """A remote_cdm field, whatever its spelling."""
    return next((v for k, v in entry.items() if squash(k) == squash(name)), None)


def remote_kind(entry: dict) -> str:
    """widevine, playready, decrypt_labs, or another type the page leaves to unshackle.yaml (custom_api)."""
    kind = str(field(entry, "type") or "").lower()
    if kind:
        return kind
    return "playready" if "PLAYREADY" in str(field(entry, "device_type") or "").upper() else "widevine"


def remote_system(entry: dict) -> str:
    cdm_type = entry.get("type")
    if cdm_type == "decrypt_labs":
        device_type = entry.get("device_type")
        device_name = entry.get("device_name", "ChromeCDM")
    elif cdm_type == "custom_api":
        dev = entry.get("device")
        dev = dev if isinstance(dev, dict) else {}
        device_type, device_name = dev.get("type", "CHROME"), dev.get("name", "ChromeCDM")
    else:
        device_type = entry.get("Device Type", entry.get("device_type", ""))
        device_name = None
    if str(device_type).upper() == "PLAYREADY" or (isinstance(device_name, str) and device_name.upper().startswith("SL")):
        return "PlayReady"
    return "Widevine"


def remote_view(entry: dict, secrets: set[str] | tuple[str, ...] = ()) -> dict:
    """A remote CDM as the page shows and edits it: never its secret, only whether it has one."""
    set_secrets = secrets if isinstance(secrets, set) else set(secrets)
    raw_kind = field(entry, "type")
    kind = "" if raw_kind is not None and not isinstance(raw_kind, str) else remote_kind(entry)
    if _has_secret(kind, set_secrets) or (isinstance(raw_kind, str) and _has_secret(raw_kind, set_secrets)):
        kind = ""
    host = field(entry, "host")
    return {"type": kind, "label": REMOTE_KINDS.get(kind, kind), "editable": kind in REMOTE_KINDS,
            "has_secret": any(bool(value) for key, value in entry.items() if squash(key) == "secret"),
            **({"host": _mask_secrets(host, set_secrets)} if isinstance(host, str) and host and host not in set_secrets else {}),
            **{k: value for k in ("device_name", "device_type")
               if type(value := field(entry, k)) in (str, int, float) and value != ""
               and not _has_secret(str(value), set_secrets)},
            **{k: value for k in ("system_id", "security_level")
               if type(value := field(entry, k)) is int and not _contains_secret(str(value), set_secrets)}}


def remote_save(yaml_file: Path, form: dict, was: str | None) -> str | None:
    """Add a remote CDM, or change one (was: its name before); its secret kept when the form leaves it empty
    and the address stays the same."""
    with ROUTE_LOCK:
        regular(yaml_file)
        text = yaml_file.read_bytes().decode("utf8") if yaml_file.exists() else ""
        config, _ = _route_document(text)
        raw_remote = config.get("remote_cdm")
        if raw_remote is not None and not isinstance(raw_remote, list):
            raise CdmError(UNSAFE_EDIT)
        entries = [e for e in raw_remote or [] if isinstance(e, dict)]
        mapping = _cdm_mapping(config)
        name = str(form.get("name") or "").strip()
        kind = str(form.get("type") or "")
        if not NAME.fullmatch(name):
            raise CdmError("A remote CDM's name: letters, digits, _ . - @")
        if kind not in REMOTE_KINDS:
            raise CdmError("Here, a remote CDM can be Widevine (pywidevine serve), PlayReady or Decrypt Labs. Add other kinds in unshackle.yaml")
        old = next((e for e in entries if str(e.get("name")) == was), None) if was else None
        if was and old is None:
            raise CdmError(f"No remote CDM called {was!r}")
        secrets = _config_secrets(config)
        if old is not None and (not isinstance(field(old, "type"), (str, type(None)))
                                or remote_kind(old) not in REMOTE_KINDS):
            # The translation catalog records the expressions used in the error template.
            was = "***" if _has_secret(str(was), secrets) else was
            old = {"type": remote_view(old, secrets)["type"] or "custom"}
            raise CdmError(f"{was} is a {remote_kind(old)} remote CDM: change it in unshackle.yaml")
        taken = {str(e.get("name")) for e in entries if e is not old} | {d["name"] for d in devices(*folders(yaml_file))}
        if name in taken:
            raise CdmError(f"{name} is already a device's or a remote CDM's name")
        if old is not None and name != was and any(was in names_in(v) for v in mapping.values()):
            raise CdmError(f"{was} is in use: give its services another device before renaming it")
        host = str(form.get("host") or "").strip()
        old_host = str(field(old, "host") or "") if old is not None else ""
        if host in (no_credentials(old_host), _mask_secrets(old_host, secrets)):
            host = old_host
        if kind != "decrypt_labs" and not re.fullmatch(r"https?://\S+", host):
            raise CdmError("Its address: http(s)://…")
        if kind == "playready" and not host.rstrip("/").endswith("/playready"):
            raise CdmError("A PlayReady remote CDM's address ends in /playready")
        secret = str(form.get("secret") or "")
        if not secret and old is not None:  # kept only for the same server: a saved key never follows a new address
            if host.rstrip("/") != str(field(old, "host") or "").rstrip("/") or kind != remote_kind(old):
                raise CdmError("Type its secret again: a saved secret is never sent to a new address")
            secret = str(field(old, "secret") or "")
        if kind != "decrypt_labs" and not secret:
            raise CdmError("Its secret (API key)")
        number = lambda k, default=None: int(form[k]) if str(form.get(k) or "").strip().isdigit() else default
        entry = {"name": name}
        if kind == "decrypt_labs":
            entry |= {"type": "decrypt_labs", "device_name": str(form.get("device_name") or "L1").strip()}
            entry |= ({"host": host} if host else {}) | ({"secret": secret} if secret else {})
        else:
            entry |= {"device_type": "PLAYREADY" if kind == "playready" else str(form.get("device_type") or "ANDROID").upper(),
                      **({"system_id": number("system_id", 26830)} if kind == "widevine" else {}),
                      "security_level": number("security_level", 3000 if kind == "playready" else 3),
                      "host": host, "secret": secret, "device_name": str(form.get("device_name") or "").strip()}
        if old is not None:  # fields the form doesn't know (a proxy, a timeout) stay
            entry |= {k: v for k, v in old.items() if not any(squash(k) == squash(f) for f in REMOTE_FIELDS)}
            if remote_system(entry) != remote_system(old) and any(was in names_in(v) for v in mapping.values()):
                raise CdmError(f"{was} is in use: give its services another device before changing its DRM")
        entries = [entry if e is old else e for e in entries] if old is not None else entries + [entry]
        return write_remote(yaml_file, text, config, entries)


def _device_in_use(name: str, used: list[str], secrets: set[str]) -> CdmError:
    if _has_secret(name, secrets):
        name = "***"
    return CdmError(f"{name} is used by {', '.join(used)}: pick another device for them first")


def remote_delete(yaml_file: Path, name: str) -> str | None:
    with ROUTE_LOCK:
        regular(yaml_file)
        text = yaml_file.read_bytes().decode("utf8") if yaml_file.exists() else ""
        config, _ = _route_document(text)
        raw_remote = config.get("remote_cdm")
        if raw_remote is not None and not isinstance(raw_remote, list):
            raise CdmError(UNSAFE_EDIT)
        entries = [e for e in raw_remote or [] if isinstance(e, dict)]
        mapping = _cdm_mapping(config)
        secrets = _config_secrets(config)
        if not any(str(e.get("name")) == name for e in entries):
            if _has_secret(name, secrets):
                name = "***"
            raise CdmError(f"No remote CDM called {name!r}")
        used = sorted(str(s) for s, v in mapping.items() if name in names_in(v))
        if used:
            used = [_REDACTED_RULE if _has_secret(service, secrets) else service for service in used]
            raise _device_in_use(name, used, secrets)
        return write_remote(yaml_file, text, config, [e for e in entries if str(e.get("name")) != name])


def section_end(lines: list[str], top: int) -> int:
    """The line after a top-level section: trailing blank lines and unindented comments belong to the next key, so they stay."""
    end = top + 1
    indent = len(lines[top]) - len(lines[top].lstrip(" "))
    while end < len(lines) and (
        not lines[end].strip() or lines[end][indent:indent + 1] in (" ", "\t", "-")
        or lines[end].lstrip().startswith("#")
    ):
        end += 1
    while end > top + 1 and (not lines[end - 1].strip() or lines[end - 1][:indent + 1].strip().startswith("#")):
        end -= 1
    return end


def write_remote(yaml_file: Path, text: str, config: dict, entries: list[dict]) -> str | None:
    if entries == config.get("remote_cdm"):
        return None
    lines = text.splitlines(keepends=True)
    top = next((i for i, l in enumerate(lines) if re.match(r"remote_cdm:\s*(#.*)?$", l.rstrip("\r\n"))), None)
    newline = "\r\n" if "\r\n" in text else "\n"
    block = yaml.safe_dump({"remote_cdm": entries}, sort_keys=False, allow_unicode=True, line_break=newline)
    if top is None:
        new = text + ("" if text.endswith("\n") or not text else newline) + block
    else:
        end = section_end(lines, top)
        new = "".join(lines[:top]) + block + "".join(lines[end:])
    after = yaml.safe_load(new) or {}
    if after.get("remote_cdm") != entries or {k: v for k, v in after.items() if k != "remote_cdm"} != {k: v for k, v in config.items() if k != "remote_cdm"}:
        raise CdmError("Could not change unshackle.yaml safely: change it by hand")
    write_atomic(yaml_file, new)
    return text


def add(wvds: Path, prds: Path, filename: str, content: bytes) -> dict:
    """A new device file, checked to be one: never over an existing one."""
    path = Path(filename or "")
    suffix = path.suffix.lower()
    if suffix not in KINDS:
        raise CdmError("A device is a .wvd (Widevine) or .prd (PlayReady) file")
    kind, magic = KINDS[suffix]
    if not NAME.fullmatch(path.stem) or "/" in filename or "\\" in filename:  # a name, never a path
        raise CdmError(f"Not a usable device name: {path.stem!r}")
    if len(content) > MAX_SIZE or not content.startswith(magic):
        raise CdmError(f"Not a {kind} device: a {suffix} file starts with {magic.decode()}")
    with ROUTE_LOCK:
        folder = wvds if kind == "Widevine" else prds
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{path.stem}{suffix}"
        if target.exists() or (folder / path.stem).exists():
            raise CdmError(f"{path.stem} is already there: delete it first to replace it")
        write_atomic(target, content, shared_or_private(folder))  # a private key
        return describe(target, kind)


def delete(
    yaml_file: Path, wvds: Path, prds: Path, name: str, kind: str, *, folder: bool | None = None,
) -> None:
    if (not NAME.fullmatch(name or "") or kind not in ("Widevine", "PlayReady")
            or (folder is not None and not isinstance(folder, bool))):
        raise CdmError("No such device")
    with ROUTE_LOCK:
        text = regular(yaml_file).read_bytes().decode("utf8") if yaml_file.exists() else ""
        config, section = _route_document(text)
        inventory, _ = _state_from(config, section, wvds, prds, text=text, redact_inventory=False)
        matches = (d for d in inventory["devices"]
                   if d["name"] == name and d["kind"] == kind and (folder is None or d["folder"] is folder))
        device = min(matches, key=lambda d: d["folder"], default=None)
        if not device:
            raise CdmError("No such device")
        used = device["used_by"]
        if used:
            raise _device_in_use(name, used, _config_secrets(config))
        if device["folder"]:
            shutil.rmtree(prds / name)
            return
        directories = (wvds,) if kind == "Widevine" else (prds, wvds)
        suffix = ".wvd" if kind == "Widevine" else ".prd"
        paths = (p for folder in directories if folder.is_dir()
                 for p in sorted(folder.iterdir(), key=lambda item: (item.name.lower(), item.suffix != suffix))
                 if p.is_file() and p.stem == name and p.suffix.lower() == suffix)
        path = min(paths, key=lambda p: not p.with_suffix(suffix).is_file(), default=None)
        if path is None:
            raise CdmError("No such device")
        path.unlink()


def allow_proxies(text: str, key: str, wvds: list[str], prds: list[str]) -> str:
    """unshackle.yaml with DownStream's key allowed the server's proxies (Unshackle 6: serve.users.<key>.server_proxy),
    its serve: block written anew and every other line as it was; checked by reading it back. Unshackle 5 reads no
    server_proxy and serves as before."""
    config = yaml.safe_load(text) or {}
    serve = dict(config.get("serve") or {}) if isinstance(config.get("serve") or {}, dict) else None
    if serve is None:
        raise CdmError("unshackle.yaml's serve: is not a section: change it by hand")
    users = dict(serve.get("users") or {}) if isinstance(serve.get("users") or {}, dict) else None
    if users is None:
        raise CdmError("unshackle.yaml's serve: users: is not a section: change it by hand")
    # a key serve listed by itself (the admin one) had every right: listed now, it keeps them all (5.4 reads server_cdm
    # and the devices); a key the operator listed keeps what it was given, the proxies added
    entry = users.get(key) if isinstance(users.get(key), dict) else {
        "devices": wvds, "playready_devices": prds, "username": "api_user",
        "admin": True, "server_cdm": True, "server_vault": True, "server_accounts": True}
    users[key] = {**entry, "server_proxy": True}
    serve["users"] = users
    lines = text.splitlines(keepends=True)
    top = next((i for i, l in enumerate(lines) if re.match(r"serve:\s*(#.*)?$", l.rstrip("\r\n"))), None)
    block = yaml.safe_dump({"serve": serve}, sort_keys=False, allow_unicode=True, default_flow_style=False)
    if top is None:
        new = text + ("" if text.endswith("\n") or not text else "\n") + block
    else:
        end = section_end(lines, top)
        new = "".join(lines[:top]) + block + "".join(lines[end:])
    after = yaml.safe_load(new) or {}
    if after.get("serve") != serve or {k: v for k, v in after.items() if k != "serve"} != {k: v for k, v in config.items() if k != "serve"}:
        raise CdmError("Could not change unshackle.yaml safely: change it by hand")
    return new
