import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

I18N = Path(__file__).resolve().parents[1] / "unshacklarr" / "static" / "i18n"
HOLE = re.compile(r"\{\d+\}")
CORE = Path(__file__).resolve().parents[1] / "unshacklarr" / "static" / "js" / "core.js"
NEEDED_CATEGORIES = {"ru": {"one", "few", "many", "other"}, "fr": {"one", "other"}, "pt-BR": {"one", "other"}}  # beyond "1 x" and "{0} xs"
ABBREVIATED = {"ru": {"{0} days", "{0} hours"}}  # "{0} дн.", "{0} ч": right for every number, whatever the sentence
CHANGED_ERROR_TEXTS = {
    "Add cookies for {0}",
    "Replace {0}",
    "(ref {0})",
    "1 cookie",
    "1 day",
    "1 needs sign-in",
    "1 series",
    "1 service confirmed",
    "1 service needs attention",
    "Add an option",
    "CDM devices",
    "Check {0} in Settings › Services",
    "Checking the services…",
    "Checking the sign-ins…",
    "Clear cache and sign-ins",
    "Credentials",
    "Delete partial downloads",
    "Delete {0}",
    "Delete {0} from Unshackle's cookies folder?",
    "Dismiss",
    "Downloads will fail unless you add a cookie file, or set its username and password in unshackle.yaml.",
    "Downloads will fail unless you add a cookie file.",
    "Failing: {0}",
    "HTTP {0}:",
    "Its downloads will fail: replace them in Settings › Services.",
    "Loading the week…",
    "Main",
    "Month",
    "Next week",
    "Managed on that server",
    "Needed to manage them in Settings › Services. Empty: Unshacklarr asks Unshackle, which works when both run on this computer.",
    "No series",
    "No service is known yet. Unshackle lists them once it answers.",
    "No service known yet",
    "Not needed",
    "Pairing",
    "Replace them before they expire, in Settings › Services.",
    "Previous week",
    "Request failed",
    "Review services",
    "Services",
    "Show series",
    "Sign-in",
    "Sign-in and cookies",
    "Sign-in methods",
    "Subtitles: {0}",
    "Test this series below: a URL the service no longer knows, or a sign-in to renew in Settings › Services.",
    "The push service refused the message",
    "The sign-in check could not reach Unshackle.",
    "The sign-ins could not be checked.",
    "Unshacklarr answered HTTP {0}{1}. Try again.",
    "Unshacklarr can't be reached. Check that it is running, then try again.",
    "Unshacklarr could not send this notification. Check its log.",
    "Unshacklarr did not answer after {0} s. Try again.",
    "Unshacklarr is set up",
    "Unshackle's cache is deleted, sign-ins included: every service signs in again the next time it downloads.",
    "Used by",
    "Week",
    "updated {0}",
    "{0} cookies",
    "{0} could not be reached. Check the Unshacklarr log.",
    "{0} days",
    "{0} need sign-in",
    "{0} not checked yet",
    "{0} refused Unshackle: its cookies may have expired. Update them in Settings › Services.",
    "{0} services confirmed",
    "{0} services need attention",
    "{0} through Unshackle",
    "{0}. Check this service's sign-in/session in Unshackle.",
    "{0}: HTTP {1}: {2}",
    "1 device",
    "1 download",
    "1 earlier check",
    "1 hour",
    "1 key",
    "1 message",
    "1 missing episode",
    "1 more device",
    "1 option",
    "1 problem",
    "1 service",
    "1 upgrade",
    "3 hours before an episode comes out, its series is checked on its service: a refused sign-in, a missing CDM, or a URL with no episodes",
    "A service that signs in with a username and password (set in unshackle.yaml) needs no cookies.",
    "all downloading",
    "Changed",
    "Connected to Unshackle ({0})",
    "Delete the key? Programs using it will stop working",
    "Delete your own ladders?",
    "Delete {0}?",
    "Delete {0}? It is in use",
    "Deletes Unshackle's cache, sign-ins included: services sign in again next time",
    "Delivered",
    "Delivered: look for it, then Add.",
    "Devices (CDM)",
    "downloading",
    "Downloading {0}{1}: follow it in Activity",
    "Each download's output shows much more: Unshackle's debug log, every call to Sonarr, and the job as Unshackle reports it.",
    "Enter the Unshackle address",
    "Every other device is signed out and stops getting push notifications. This one stays signed in.",
    "Export the cookies from your browser while signed in to the service, as cookies.txt (Netscape) or JSON.",
    "from unshackle.yaml.",
    "from unshackle.yaml. Empty keeps the saved one.",
    "from unshackle.yaml. Leave empty to keep the saved key.",
    "Got a license ({0}), {1}. A service may still refuse this device.",
    "If the service refuses the sign-in, the download is tried again with these profiles, in order. Useful for a second account while the first one's cookies are renewed.",
    "Imported",
    "Its path on the machine where Unshackle runs. Empty: the same path as above.",
    "Keeps the last {0} downloads, none older than {1}.",
    "Leave empty if the folder needs no sign-in.",
    "Managed where Unshackle runs",
    "No series is downloading yet.",
    "No sign-in required",
    "Not downloading",
    "Not out yet at the {0} {1}. Each check is in the output below.",
    "Now: a message when an episode is still missing {0} after airing.",
    "On another machine",
    "Others signed out",
    "Passwords match",
    "Reached: Sonarr {0}",
    "Reached: {0}",
    "Remove {0} from unshackle.yaml?",
    "Remove {0}?",
    "Reprovision {0}?",
    "Same title",
    "Season {0} is on {1} ({2}).",
    "Select {0}",
    "Session cookies have no expiry date: only a failed sign-in shows they are over",
    "Set for this service",
    "Show {0}, not in use",
    "Sign in first",
    "Sign in to continue.",
    "Sign in to the service in your browser.",
    "Sign out",
    "Sign out other devices",
    "Sign out other devices? They sign in again",
    "Sign-in failed on {0}: {1}",
    "Signed in on this device",
    "This file holds every secret Unshackle has (sign-ins, API keys). Enter your Unshacklarr password to open it.",
    "Unshacklarr reads {0}'s library: {1}",
    "Unshackle address",
    "Your settings and series stay as they are. Every device must sign in again.",
    "Your user key is shown on pushover.net once you sign in. Create an application there to get the API token.",
    "{0} came out on the service {1}{2}. Suggested release time: {3}",
    "{0} cleared from the history",
    "{0} devices",
    "{0} downloading again",
    "{0} downloads",
    "{0} earlier checks",
    "{0} has none of your {1}",
    "{0} has {1} of your {2}",
    "{0} in use not tested yet",
    "{0} kept",
    "{0} keys",
    "{0} may be better on {1}",
    "{0} messages",
    "{0} missing episodes",
    "{0} more devices",
    "{0} options",
    "{0} problems",
    "{0} tested{1}",
    "{0} that day{1}: click to change",
    "{0} to fix",
    "{0} upgrades",
    "{0} waiting for the end of the quiet hours",
    "{0}: signed in with the profile {1}",
    "{0}: {1} refused the sign-in, trying the profile {2}",
}

# The sign-in lifecycle texts added since 1.5.0 ("DRM" and the Python "Traceback" line are not translated).
SIGN_IN_TEXTS = {
    "Approval",
    "Approvals · {0}",
    "Approve this device",
    "Authentication backend identity is unavailable",
    "Authentication backend is no longer configured",
    "Authentication cleanup is no longer available",
    "Authentication session is no longer available",
    "Authentication session is not on the configured backend",
    "Code: {0}",
    "Configure a {0} series before signing in",
    "Confirmed {0}",
    "Copy details",
    "Details copied",
    "Enter the requested response",
    "Invalid service or backend",
    "No authentication session is waiting",
    "Not checked yet",
    "Open: {0}",
    "Ready · {0}",
    "Reauthenticate",
    "Renewing {0} session",
    "Repairing {0} session",
    "Service approval",
    "Sign-in cancelled",
    "Sign-in failed · {0}",
    "Sign-in needed",
    "Signed in with {0}",
    "Signing in",
    "Submit",
    "The configured Unshackle does not support secure device approvals; update it before using this local core",
    "Unknown backend",
    "Unshackle could not cancel sign-in",
    "Unshackle could not start sign-in",
    "Unshackle did not accept the response",
    "Unshackle did not create an authentication session",
    "Waiting for {0} approval",
    "authentication rejected",
    "{0} failed · {1} · trying {2}",
    "{0} needs approval",
    "{0} rejected · trying {1}",
    "{0} services need approval",
    "{0} session available",
    "{0} session expired",
    "{0} session rejected",
    "{0} timed out",
}


def test_translations_fit_the_page():
    """Each language translates texts the page has, with no {n} the English lacks (it would show as is)."""
    english = json.loads((I18N / "en.json").read_text())
    for path in I18N.glob("*.json"):
        if path.name == "en.json":
            continue
        translated = json.loads(path.read_text())
        for key, value in translated.items():
            assert key in english, f"{path.name}: {key!r} is not on the page (run tools/i18n/extract.py?)"
            for text in value.values() if isinstance(value, dict) else [value]:
                assert isinstance(text, str) and text.strip(), f"{path.name}: {key!r} is empty"
                assert set(HOLE.findall(text)) <= set(HOLE.findall(key)), f"{path.name}: {key!r} has a {{n}} of its own"
        assert CHANGED_ERROR_TEXTS <= translated.keys(), f"{path.name}: changed error text is untranslated"


def test_every_language_translates_the_sign_in_texts_with_their_placeholders():
    english = json.loads((I18N / "en.json").read_text())
    assert SIGN_IN_TEXTS <= english.keys()
    for path in I18N.glob("*.json"):
        if path.name == "en.json":
            continue
        translated = json.loads(path.read_text())
        assert SIGN_IN_TEXTS <= translated.keys(), f"{path.name}: {sorted(SIGN_IN_TEXTS - translated.keys())}"
        for key in SIGN_IN_TEXTS:
            assert set(HOLE.findall(translated[key])) == set(HOLE.findall(key)), f"{path.name}: {key!r} loses or adds a {{n}}"


def test_authentication_guidance_translates_without_changing_the_provider_reason():
    from unshacklarr import i18n
    message = "unshackle serve: HAYU (ref ef1b9f): Hayu playback failed: Invalid Token. Check this service's sign-in/session in Unshackle."
    translated = i18n.tr(message, "fr")
    assert "Vérifiez la connexion ou la session" in translated
    assert "HAYU (ref ef1b9f)" in translated and "Invalid Token" in translated
    internal = "Unshackle rejected the internal API key. Check the server API key in Settings, Unshackle."
    assert "clé API interne" in i18n.tr(internal, "fr")


def test_the_server_translates_a_notification(tmp_path, monkeypatch):
    from unshacklarr import i18n
    (tmp_path / "fr.json").write_text(json.dumps({"Downloaded: {0}": "Téléchargé: {0}", "Imported by Sonarr.": "Importé par Sonarr.",
                                                  "{0} failed": "{0} en échec", "3 parts": "3 parties"}))
    monkeypatch.setattr(i18n, "FOLDER", tmp_path)
    i18n.catalog.cache_clear()
    assert i18n.tr_lines("Downloaded: Silo S02E03\nImported by Sonarr.", "fr") == "Téléchargé: Silo S02E03\nImporté par Sonarr."
    assert i18n.tr("3 parts failed", "fr") == "3 parties en échec"  # what fills {0} is translated too
    assert i18n.tr("Something else", "fr") == "Something else" and i18n.tr("Downloaded: x", "en") == "Downloaded: x"
    i18n.catalog.cache_clear()


def test_a_short_template_does_not_swallow_a_sentence(tmp_path, monkeypatch):
    from unshacklarr import i18n
    (tmp_path / "fr.json").write_text(json.dumps({"{0} ago": "il y a {0}", "{0} of {1}": "{0} sur {1}"}))
    monkeypatch.setattr(i18n, "FOLDER", tmp_path)
    i18n.catalog.cache_clear()
    assert i18n.tr("5 min ago", "fr") == "il y a 5 min" and i18n.tr("3 of 6", "fr") == "3 sur 6"
    long = "A download of this episode already waits in the downloads folder"
    assert i18n.tr(long, "fr") == long and i18n.tr("Device certificate revoked (0x8004C065), tested 59 min ago", "fr").endswith("ago")
    i18n.catalog.cache_clear()


def test_a_hostile_line_cannot_make_translation_slow(tmp_path, monkeypatch):
    import time
    from unshacklarr import i18n
    (tmp_path / "fr.json").write_text(json.dumps({"Seen {0} on {1} at {2} for {3} in {4} by {5}.": "Vu {0} sur {1} à {2} pour {3} dans {4} par {5}."}))
    monkeypatch.setattr(i18n, "FOLDER", tmp_path)
    i18n.catalog.cache_clear()
    line = "Seen " + " on at for in by" * 10_000 + " x" * 50_000  # every piece there, many times, but not the final "."
    start = time.monotonic()
    assert i18n.tr(line, "fr") == line
    assert time.monotonic() - start < 1  # a regular expression took minutes on this
    assert i18n.tr("Seen it on M6 at 9 for me in Paris by bus.", "fr") == "Vu it sur M6 à 9 pour me dans Paris par bus."
    i18n.catalog.cache_clear()


def test_the_extractor_does_not_backtrack_on_a_long_code_literal():
    import time
    from tools.i18n.extract import wanted
    line = "access-token " * 10_000 + "!"
    start = time.monotonic()
    assert wanted(line)
    assert time.monotonic() - start < 1


def test_translations_load_where_the_system_encoding_is_not_utf8(tmp_path, monkeypatch):
    # Windows before Python 3.15 reads a file as cp1252 unless told otherwise; the catalogues are UTF-8
    import pathlib
    from unshacklarr import i18n
    (tmp_path / "ja.json").write_text(json.dumps({"Downloaded: {0}": "東京でダウンロード: {0}"}, ensure_ascii=False), encoding="utf8")
    read_text = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text", lambda self, encoding=None, errors=None, newline=None:
                        read_text(self, encoding=encoding or "cp1252", errors=errors, newline=newline))
    monkeypatch.setattr(i18n, "FOLDER", tmp_path)
    i18n.catalog.cache_clear()
    assert i18n.tr("Downloaded: Silo", "ja") == "東京でダウンロード: Silo"
    i18n.catalog.cache_clear()


def counted_nouns() -> list[str]:
    """The many-form text of each counted noun of the page (COUNT in core.js): "{0} devices"."""
    block = re.search(r"const COUNT = \{(.*?)\n\};", CORE.read_text(), re.S).group(1)
    return ["{0} " + noun for noun in re.findall(r"`\$\{n\} ([^`]+)`", block)]


def test_a_language_with_more_plural_forms_has_a_text_for_each_of_them():
    nouns = counted_nouns()
    assert len(nouns) == 15
    for lang, needed in NEEDED_CATEGORIES.items():
        translated = json.loads((I18N / f"{lang}.json").read_text())
        for noun in set(nouns) - ABBREVIATED.get(lang, set()):
            forms = translated.get(noun)
            assert isinstance(forms, dict), f"{lang}: {noun!r} has no text per plural category"
            assert needed <= forms.keys(), f"{lang}: {noun!r} lacks {sorted(needed - forms.keys())}"


@pytest.mark.parametrize("lang, expected", [
    ("ru", {1: "1 устройство", 2: "2 устройства", 5: "5 устройств", 21: "21 устройство", 11: "11 устройств", 112: "112 устройств"}),
    ("fr", {0: "0 appareil", 1: "1 appareil", 2: "2 appareils"}),
    ("pt-BR", {0: "0 dispositivo", 1: "1 dispositivo", 2: "2 dispositivos"}),
    ("de", {1: "1 Gerät", 2: "2 Geräte"}),
])
def test_the_server_picks_the_plural_form_of_the_language(lang, expected):
    from unshacklarr import i18n
    english = lambda n: "1 device" if n == 1 else f"{n} devices"
    assert {n: i18n.tr(english(n), lang) for n in expected} == expected


def page_translate(lang: str, expressions: list[str]) -> list[str]:
    """What the page's own tr() makes of each JavaScript expression (a string, or COUNT.device(2)), in this language."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    source = CORE.read_text()
    code = "\n".join(re.search(pattern, source, re.M | re.S).group() for pattern in (
        r"^let T = null, TP = \[\];", r"^const PLURALS = .*?;$", r"^function plural\([^\n]*\}$", r"^function templates\(.*?^\}",
        r"^const translated = .*?;", r"^const trSeen = .*?;", r"^function tr\(.*?^\}", r"^function trFind\(.*?^\}",
        r"^function trTemplate\(.*?^\}", r"^const COUNT = \{.*?^\};"))
    harness = f"""
const vm = require("vm"), fs = require("fs");
const box = {{ LANG: {json.dumps(lang)}, Intl, fs, path: {json.dumps(str(I18N / f"{lang}.json"))} }};
vm.createContext(box);
vm.runInContext({json.dumps(code)} + `
if (LANG !== "en") {{ T = JSON.parse(fs.readFileSync(path, "utf8")); TP = templates(T); }}
out = [{", ".join(expressions)}].map((text) => tr(text));`, box);
console.log(JSON.stringify(box.out));
"""
    done = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("lang, expected", [
    ("ru", ["1 устройство", "2 устройства", "5 устройств", "21 устройство"]),
    ("en", ["1 device", "2 devices", "5 devices", "21 devices"]),
])
def test_the_page_picks_the_plural_form_of_the_language(lang, expected):
    assert page_translate(lang, [f"COUNT.device({n})" for n in (1, 2, 5, 21)]) == expected


SIGN_IN_LABELS = {
    "Sign-in failed · authentication rejected": "Échec de la connexion · authentification refusée",
    "Pairing failed · network · trying cookies": "Appairage en échec · network · essai de cookies",
    "Cookies rejected · trying pairing": "Cookies refusé · essai de pairing",
    "Waiting for pairing approval": "En attente de l'approbation (pairing)",
    "Signed in with cookies": "Connecté avec cookies",
}


def test_a_template_with_a_dot_separator_is_read_whole_before_its_pieces():
    from unshacklarr import i18n
    # "Sign-in failed" alone would match the older "{0} failed" and leave the rest of the line in English
    assert {text: i18n.tr(text, "fr") for text in SIGN_IN_LABELS} == SIGN_IN_LABELS
    assert page_translate("fr", [json.dumps(text) for text in SIGN_IN_LABELS]) == list(SIGN_IN_LABELS.values())


def test_a_superscript_number_picks_the_other_form_instead_of_failing():
    from unshacklarr import i18n
    assert i18n.pick({"one": "un", "other": "plusieurs"}, "fr", ["²"]) == "plusieurs"
