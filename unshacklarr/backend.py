"""unshackle, through its REST API (`unshackle serve`).

Remote: a serve that already runs (another container, another machine), reached with
its URL and API key. Local: Unshacklarr starts one itself from the Unshackle installed
on this computer, bound to 127.0.0.1 on a free port, with a key made up for the run
and set in memory, so the user's unshackle.yaml is never touched.
"""

import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from unshacklarr.files import no_credentials

# Runs with Unshackle's own Python: its config, cookies and CDMs, plus a key for this run.
# Port and key come through the environment, never the command line (which every user of the machine
# can read). Where it can, Unshacklarr binds the socket itself and hands it over: no moment when the port
# is free for another program to take and pass for serve.
LAUNCHER = """
import os
from unshackle.core.config import config
config.serve["api_secret"] = key = os.environ.pop("UNSHACKLARR_SERVE_KEY")
# Unshackle 6 lets a key use the server's proxies (a country code, nordvpn:fr) only with server_proxy. A key listed in
# serve.users is no longer the admin one (unlisted: every right), so this run's key gets every right the admin key has,
# and the devices serve would give it; 5.4 reads server_cdm and the devices among them, and serves as before
from pathlib import Path
def device_names(folder, pattern):
    try:
        return [p.stem for p in Path(getattr(config.directories, folder)).glob(pattern)]
    except (AttributeError, TypeError, OSError):
        return []
users = config.serve.get("users") if isinstance(config.serve.get("users"), dict) else {}
users[key] = {"devices": device_names("wvds", "*.wvd"), "playready_devices": device_names("prds", "*.prd"),
              "username": "api_user", "admin": True, "server_cdm": True, "server_vault": True, "server_accounts": True,
              "server_proxy": True}
config.serve["users"] = users
port, fd = os.environ.pop("UNSHACKLARR_SERVE_PORT"), os.environ.pop("UNSHACKLARR_SERVE_FD", "")
if fd:
    import socket
    from aiohttp import web
    sock, run_app = socket.socket(fileno=int(fd)), web.run_app
    web.run_app = lambda app, *args, host=None, port=None, **kw: run_app(app, *args, sock=sock, **kw)
from unshackle.core.__main__ import main
main(["serve", "--api-only", "-h", "127.0.0.1", "-p", port])
"""

TERMINAL = {"completed", "failed", "cancelled"}

AUTHENTICATION_STATES = {
    "ready",
    "session_present",
    "session_expired",
    "session_rejected",
    "renewing",
    "repairing",
    "fallback",
    "waiting",
    "authenticated",
    "timed_out",
    "cancelled",
    "error",
}
AUTHENTICATION_METHODS = {"cookies", "credentials", "pairing"}
AUTHENTICATION_FAILURES = {
    "authentication_rejected",
    "entitlement",
    "region",
    "concurrency",
    "network",
    "manifest",
    "drm",
    "licence",
    "application",
}
TERMINAL_AUTHENTICATION_STATES = {"authenticated", "timed_out", "cancelled", "error"}


def authentication_observation(value) -> dict | None:
    """Return one strictly allowlisted core lifecycle snapshot."""
    allowed = {"state", "method", "available_methods", "next_method", "failure"}
    if not isinstance(value, dict) or set(value) - allowed:
        return None
    state = value.get("state")
    method = value.get("method")
    next_method = value.get("next_method")
    failure = value.get("failure")
    methods = value.get("available_methods", [])
    if not isinstance(state, str) or state not in AUTHENTICATION_STATES:
        return None
    if method is not None and (not isinstance(method, str) or method not in AUTHENTICATION_METHODS):
        return None
    if next_method is not None and (
        not isinstance(next_method, str) or next_method not in AUTHENTICATION_METHODS
    ):
        return None
    if failure is not None and (not isinstance(failure, str) or failure not in AUTHENTICATION_FAILURES):
        return None
    if not isinstance(methods, (list, tuple)) or any(
        not isinstance(item, str) or item not in AUTHENTICATION_METHODS for item in methods
    ):
        return None
    if len(set(methods)) != len(methods):
        return None
    if state == "ready":
        if not methods or method or next_method or failure:
            return None
    elif methods:
        return None
    if state == "fallback":
        if not method or not next_method or method == next_method or failure is None:
            return None
    elif next_method is not None:
        return None
    if state == "error":
        if failure is None:
            return None
    elif state != "fallback" and failure is not None:
        return None
    result = {"state": state}
    if method is not None:
        result["method"] = method
    if methods:
        result["available_methods"] = list(methods)
    if next_method is not None:
        result["next_method"] = next_method
    if failure is not None:
        result["failure"] = failure
    return result


class UnshackleError(Exception):
    """unshackle cannot be reached or refused a request; the message says why."""
    retry_after = 0  # serve's own limit on requests reached (Unshackle 6): seconds before it answers again
    status = 0  # the HTTP status serve answered with, when it answered one
    error_code = ""  # fixed API classification, when serve supplied one


# Unshackle 6 serves its proxies (a country code, a provider) only to a key allowed to (server_proxy)
PROXY_REFUSED = re.compile(r"does not resolve country codes into proxies|in a different region from yours", re.IGNORECASE)
PROXY_HINT = ("Unshackle 6 doesn't let Unshacklarr use its proxies (a country code such as au, or a provider): "
              "allow it in Settings, Unshackle")


def response_error(response: requests.Response) -> tuple[dict, str, str | None]:
    """The useful, safe parts of an Unshackle error response."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    message = next((value.strip() for key in ("message", "error", "detail")
                    if isinstance((value := payload.get(key)), str) and value.strip()), response.text.strip())
    if not message or re.search(r"<\s*(?:!doctype|html|head|body|h\d)\b", message, re.IGNORECASE):
        message = response.reason or "Request failed"
    message = no_credentials(message)[:500]
    reference = no_credentials(str(payload.get("ref") or "").strip())[:490]
    if reference and reference not in message:
        suffix = f" (ref {reference})"
        message = f"{message[:500 - len(suffix)].rstrip()}{suffix}"
    details = payload.get("details") or {}
    service = str(details.get("service") or "").strip() if isinstance(details, dict) else ""
    return payload, message, service or None


def unshackle_python(command: str) -> tuple[str, Path]:
    """The Python that runs the `unshackle` command (its script's shebang, or the venv's own),
    and the folder to run it from: a git clone's, when the command is in its .venv, since a
    config there may name its folders relative to it (services: [unshackle/services])."""
    found = shutil.which(command or "unshackle")
    if not found:
        raise UnshackleError(
            f"The {command or 'unshackle'!r} command was not found. Install Unshackle, "
            "or give the full path to its command in Settings, Unshackle."
        )
    script = Path(found).resolve()
    venv = script.parent.parent
    folder = venv.parent if venv.name == ".venv" else Path.home()
    with script.open("rb") as f:
        first = f.readline(512)
    if first.startswith(b"#!") and b"python" in first:
        return first[2:].decode(errors="replace").strip().split()[0], folder
    for name in ("python.exe", "python3", "python"):  # a Windows .exe launcher, or an odd shebang
        if (script.parent / name).exists():
            return str(script.parent / name), folder
    raise UnshackleError(f"Could not tell which Python runs {script}")


EXAMPLE_KEYS = {"change-me-to-a-long-random-string", "the-UNSHACKLE_API_KEY-of-.env"}


class Local:
    """A serve of our own, started on demand and restarted if it dies."""

    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.process: subprocess.Popen | None = None
        self.started: datetime | None = None
        self.url = self.key = ""
        self.command = None
        self.lock = threading.Lock()

    def endpoint(self, command: str) -> tuple[str, str]:
        with self.lock:
            if self.process and self.process.poll() is None and command == self.command:
                return self.url, self.key
            self.stop()
            self.start(command)
            return self.url, self.key

    def start(self, command: str) -> None:
        python, folder = unshackle_python(command)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        handed = os.name != "nt"  # Windows cannot pass a socket this way: there, serve binds the port itself
        if handed:
            sock.listen(128)
            sock.set_inheritable(True)
        else:
            sock.close()
        self.key, self.url, self.command = secrets.token_urlsafe(24), f"http://127.0.0.1:{port}", command
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if self.log_file.exists() and self.log_file.stat().st_size > 20_000_000:  # one older log kept, no more
            self.log_file.replace(self.log_file.with_suffix(".log.1"))
        log = self.log_file.open("ab")
        env = {**os.environ, "UNSHACKLARR_SERVE_KEY": self.key, "UNSHACKLARR_SERVE_PORT": str(port)}
        if handed:
            env["UNSHACKLARR_SERVE_FD"] = str(sock.fileno())
        try:
            self.process = subprocess.Popen(
                [python, "-c", LAUNCHER],
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=folder, env=env,
                pass_fds=(sock.fileno(),) if handed else (),
            )
        except OSError as e:  # its Python is gone or not runnable: health and callers handle UnshackleError only
            raise UnshackleError(f"Could not start unshackle serve with {python}: {e}") from e
        finally:
            if handed:
                sock.close()  # serve has its own copy
        deadline = time.monotonic() + 90  # Unshackle loads every service at start
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise UnshackleError(f"unshackle serve stopped at start: {self.tail()}")
            try:
                requests.get(f"{self.url}/api/health", timeout=2).raise_for_status()
            except requests.RequestException:
                time.sleep(0.5)
                continue
            try:
                response = requests.get(
                    f"{self.url}/api/remote/logins",
                    headers={"X-Secret-Key": self.key},
                    timeout=2,
                )
                if response.status_code in (404, 405):
                    self.stop()
                    raise UnshackleError(
                        "The configured Unshackle does not support secure device approvals; update it before using this local core"
                    )
                response.raise_for_status()
            except UnshackleError:
                raise
            except requests.RequestException:
                time.sleep(0.5)
                continue
            self.started = datetime.now(timezone.utc)
            return
        self.stop()
        raise UnshackleError(f"unshackle serve did not answer within 90 s: {self.tail()}")

    def tail(self, lines: int = 3, sep: str = " / ") -> str:
        try:
            with self.log_file.open("rb") as f:  # its end only: the log grows for as long as serve runs
                f.seek(max(0, f.seek(0, os.SEEK_END) - 400_000))
                text = f.read().decode(errors="replace")
        except OSError:
            return "no output"
        return sep.join(text.strip().splitlines()[-lines:]) or "no output"

    def paths(self, command: str) -> dict[str, Path]:
        """Where this unshackle keeps its config file, cookies and CDMs, as it says itself (asked once)."""
        if getattr(self, "_paths", (None, None))[0] != command:
            python, folder = unshackle_python(command)
            ask = ("from unshackle.core.config import config, config_path; d = config.directories\n"
                   "print(config_path or ''); print(d.cookies.resolve()); print(d.wvds.resolve()); print(d.prds.resolve());"
                   " print(d.temp.resolve())")
            try:
                out = subprocess.run([python, "-c", ask], cwd=folder, capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired as e:
                raise UnshackleError(f"unshackle did not answer within 60 s when asked where its files are ({python})") from e
            except OSError as e:
                raise UnshackleError(f"Could not ask unshackle where its files are with {python}: {e}") from e
            lines = out.stdout.strip().splitlines()[-5:]
            if out.returncode or len(lines) != 5:
                raise UnshackleError(f"Could not ask unshackle where its files are: {out.stderr.strip()[-300:]}")
            self._paths = (command, dict(zip(("config", "cookies", "wvds", "prds", "temp"), map(Path, lines))))
        return self._paths[1]

    def cookies_dir(self, command: str) -> Path:
        return self.paths(command)["cookies"]

    def restart(self, command: str) -> None:
        with self.lock:
            self.stop()
            self.start(command)

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()  # reaped: no zombie left behind
        self.process, self.started = None, None


class Unshackle:
    name = ""  # another serve's name in Settings; the main one has none

    def __init__(self, data_dir: Path):
        self.local = Local(data_dir / "unshackle-serve.log")
        self.settings: dict = {}
        self._services: tuple[float, list] = (0.0, [])
        self._remote: tuple[float, list] = (0.0, [])
        self._config: tuple[float, dict] = (0.0, {})
        self._down: tuple[float, UnshackleError | None] = (0.0, None)
        self.proxy_refused = ""  # when serve last refused its proxies to this key (Unshackle 6, no server_proxy)

    def configure(self, settings: dict) -> None:
        self.settings = settings
        self._services = (0.0, [])
        self._remote = (0.0, [])
        self._config = (0.0, {})
        self._down = (0.0, None)

    def cached_get(self, path: str) -> dict:
        """A GET whose answer is kept: an unreachable serve is said at once for a minute, instead of each call (the
        page's state asks for the services three times) waiting for the connection to time out (5 s) again."""
        at, error = self._down
        if error and time.monotonic() - at < 60:
            raise error
        try:
            return self.call("GET", path)
        except UnshackleError as e:
            if "unreachable" in str(e):
                self._down = (time.monotonic(), e)
            raise

    def logins(self) -> list[dict]:
        """Transient caller-owned remote login state, strictly bounded at the core response."""
        if self.mode == "local" and not (self.local.process and self.local.process.poll() is None):
            return []
        try:
            payload = self.call("GET", "/api/remote/logins", timeout=(2, 4))
        except UnshackleError:
            return []  # an older or temporarily unavailable core: download-job approvals still work
        logins = payload.get("logins") or [] if isinstance(payload, dict) else []
        result = []
        for login in logins if isinstance(logins, list) else []:
            if not isinstance(login, dict):
                continue
            approval = login.get("approval") if isinstance(login, dict) else None
            message = approval.get("message") if isinstance(approval, dict) else None
            observation = authentication_observation(login.get("authentication"))
            item = {
                "id": str(login.get("id") or "")[:128],
                "service": str(login.get("service") or "")[:64],
            }
            if isinstance(message, str) and message:
                item["approval"] = {"message": message[:2000]}
            if observation is not None:
                item["authentication"] = observation
            if (item.get("approval") or observation is not None) and item["service"]:
                result.append(item)
        return result

    def approvals(self) -> list[dict[str, str]]:
        """Transient approvals for caller-owned remote logins; never read them from durable logs."""
        return [
            {"service": login["service"], "message": login["approval"]["message"]}
            for login in self.logins()
            if login.get("approval")
        ]

    @property
    def mode(self) -> str:
        return self.settings.get("unshackle_mode") or ("remote" if self.settings.get("unshackle_url") else "local")

    def endpoint(self) -> tuple[str, str]:
        if self.mode == "remote":
            url = str(self.settings.get("unshackle_url") or "").rstrip("/")
            if not url:
                raise UnshackleError("Set the address of unshackle serve in Settings, Unshackle")
            key = str(self.settings.get("unshackle_api_key") or "")
            if key in EXAMPLE_KEYS:  # the value of .env.example: anyone who read it knows it
                raise UnshackleError("The API key of unshackle serve is still the example one: put a long random one in "
                                     "UNSHACKLE_API_KEY and in serve: api_secret (openssl rand -hex 32)")
            return url, key
        return self.local.endpoint(str(self.settings.get("unshackle_command") or ""))

    def call(self, method: str, path: str, **kwargs):
        url, key = self.endpoint()
        timeout = kwargs.pop("timeout", (5, 60))
        try:
            r = requests.request(method, f"{url}{path}", headers={"X-Secret-Key": key}, timeout=timeout,  # a server down: 5 s, not 60
                                 allow_redirects=False, **kwargs)  # the key is sent only where it was configured
        except requests.RequestException as e:
            raise UnshackleError(no_credentials(f"unshackle serve is unreachable at {url}: {e}")) from e
        if r.is_redirect:
            to = urlparse(urljoin(r.url, r.headers.get("Location", "")))  # http to https, or a base path, shows as such
            host = f"{to.scheme}://{to.netloc.rpartition('@')[2]}" if to.netloc else ""
            if host and path and to.path.endswith(path):  # the same route under another address: that address to type
                raise UnshackleError(no_credentials(f"{url} redirects to {host}{to.path[:-len(path)]}: use that address "
                                                    "for unshackle serve in Settings, Unshackle"))
            # another route: no address can be told from it, so none is offered as the one to type
            raise UnshackleError(no_credentials(f"{url} redirects to {host + to.path if host else 'another address'}, "
                                                "which is not unshackle serve's: check its address in Settings, Unshackle"))
        if r.status_code == 429:  # a limit set on the key (Unshackle 6): waited for, not a lost job
            err = UnshackleError("unshackle serve is busy: its limit of requests for this key is reached")
            err.retry_after = int(r.headers.get("Retry-After") or 60) if str(r.headers.get("Retry-After") or "60").isdigit() else 60
            raise err
        if not r.ok:
            payload, message, service = response_error(r)
            provider_auth_failed = payload.get("error_code") == "AUTH_FAILED"
            if r.status_code == 401:
                if provider_auth_failed:
                    message = f"{message}. Check this service's login/session in Unshackle."
                else:
                    message = "Unshackle rejected the internal API key. Check the server API key in Settings, Unshackle."
            if not provider_auth_failed and "requested CDM is not permitted" in message:  # --cdm, Unshackle 6: the operator's opt-in
                message = ("Unshackle refuses to pick the CDM device named in --cdm: allow it in unshackle.yaml "
                           "with serve: cdm_overrides: true (or a list of devices), then restart Unshackle")
            if not provider_auth_failed and PROXY_REFUSED.search(message):
                self.proxy_refused = datetime.now(timezone.utc).isoformat()
                message = PROXY_HINT
            owner = f"{service} through Unshackle" if service else "Unshackle"
            err = UnshackleError(no_credentials(f"{owner}: HTTP {r.status_code}: {message}"))
            err.status = r.status_code
            err.error_code = "AUTH_FAILED" if provider_auth_failed else ""
            raise err
        try:
            return r.json()
        except ValueError:  # a proxy's login page, or another program at this address
            raise UnshackleError(no_credentials(f"{url} did not answer like unshackle serve (no JSON): is the address right?")) from None

    def services(self) -> list[dict]:
        """Tag, URL and help of each service, kept 10 minutes."""
        fetched, services = self._services
        if not services or time.monotonic() - fetched > 600:
            services = self.cached_get("/api/services")["services"]
            self._services = (time.monotonic(), services)
        return services

    def remote_services(self) -> list[dict]:
        """The servers of Unshackle's remote_services and the services each offers (for --remote), kept
        10 minutes; none when this Unshackle cannot tell (no such route, or unreachable)."""
        fetched, servers = self._remote
        if time.monotonic() - fetched > 600:
            try:
                servers = self.call("GET", "/api/remote/services").get("servers") or []
            except UnshackleError:
                servers = []
            self._remote = (time.monotonic(), servers)
        return servers

    def health(self) -> dict:
        """Its version, and whether a newer one is out."""
        return self.call("GET", "/api/health")

    def tools(self) -> list[dict]:
        """The programs Unshackle needs (ffmpeg, mkvmerge, shaka-packager…): found or not, and their version."""
        return self.call("GET", "/api/env/check")["checks"]

    def jobs(self) -> list[dict]:
        return self.call("GET", "/api/download/jobs")["jobs"]

    def restart(self) -> None:
        if self.mode == "remote":
            raise UnshackleError("A remote unshackle serve is restarted where it runs")
        self.local.restart(str(self.settings.get("unshackle_command") or ""))
        self.configure(self.settings)  # a restarted serve reads unshackle.yaml afresh: so does the copy kept 10 minutes

    def dl_config(self) -> dict:
        """The `dl:` section of its unshackle.yaml (secrets redacted), kept 10 minutes."""
        return self.config().get("dl") or {}

    def cdm_config(self) -> dict:
        """The `cdm:` section of its unshackle.yaml: the device each service decrypts with, and the default."""
        return self.config().get("cdm") or {}

    def config(self) -> dict:
        """Its unshackle.yaml (secrets redacted), kept 10 minutes."""
        fetched, config = self._config
        if not fetched or time.monotonic() - fetched > 600:
            config = self.cached_get("/api/config")["config"] or {}
            self._config = (time.monotonic(), config)
        return config

    def download(self, payload: dict) -> str:
        if not payload.get("remote"):
            # A service that failed to import is in serve's load_errors (Unshackle after 5.4.0; none before): told
            # now, not once the job fails. Asked afresh each time, not the cached list: serve may have restarted.
            catalogue = self.call("GET", "/api/services")
            tag = str(payload.get("service") or "")
            for error in catalogue.get("load_errors") or []:
                if isinstance(error, str) and error.partition(":")[0].casefold() == tag.casefold():
                    # its own words stay out: the error may quote a secret; a missing module is safe to name
                    if module := re.search(r"No module named '([A-Za-z0-9_.]+)'", error):
                        raise UnshackleError(f"{tag} did not load in unshackle serve: the Python module {module[1]} is missing "
                                             "on the machine where it runs. Its startup log has more details")
                    raise UnshackleError(f"{tag} did not load in unshackle serve: its startup log says why")
        return self.call("POST", "/api/download", json=payload)["job_id"]

    def job(self, job_id: str) -> dict:
        return self.call("GET", f"/api/download/jobs/{job_id}")

    def cancel(self, job_id: str) -> None:
        self.call("DELETE", f"/api/download/jobs/{job_id}")

    def stop(self) -> None:
        self.local.stop()


if __name__ == "__main__":  # python -m unshacklarr.backend [command]: start a local serve and list its services
    u = Unshackle(Path(os.environ.get("TMPDIR", "/tmp")))
    u.configure({"unshackle_command": sys.argv[1] if len(sys.argv) > 1 else ""})
    try:
        print(sorted(s["tag"] for s in u.services()))
    finally:
        u.stop()
