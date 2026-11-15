import json
import re
from pathlib import Path

I18N = Path(__file__).resolve().parents[1] / "unshacklarr" / "static" / "i18n"
HOLE = re.compile(r"\{\d+\}")
CHANGED_ERROR_TEXTS = {
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
    "Main",
    "Managed on that server",
    "Needed to manage them in Settings › Services. Empty: Unshacklarr asks Unshackle, which works when both run on this computer.",
    "No series",
    "No service is known yet. Unshackle lists them once it answers.",
    "No service known yet",
    "Not needed",
    "Pairing",
    "Replace them before they expire, in Settings › Services.",
    "Request failed",
    "Review services",
    "Services",
    "Show series",
    "Sign-in",
    "Sign-in and cookies",
    "Sign-in methods",
    "Subtitles: {0}",
    "Supports",
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
    "{0}. Check this service's login/session in Unshackle.",
    "{0}: HTTP {1}: {2}",
}


def test_translations_fit_the_page():
    """Each language translates texts the page has, with no {n} the English lacks (it would show as is)."""
    english = json.loads((I18N / "en.json").read_text())
    for path in I18N.glob("*.json"):
        if path.name == "en.json":
            continue
        translated = json.loads(path.read_text())
        for key, text in translated.items():
            assert key in english, f"{path.name}: {key!r} is not on the page (run tools/i18n/extract.py?)"
            assert isinstance(text, str) and text.strip(), f"{path.name}: {key!r} is empty"
            assert set(HOLE.findall(text)) <= set(HOLE.findall(key)), f"{path.name}: {key!r} has a {{n}} of its own"
        assert CHANGED_ERROR_TEXTS <= translated.keys(), f"{path.name}: changed error text is untranslated"


def test_authentication_guidance_translates_without_changing_the_provider_reason():
    from unshacklarr import i18n
    message = "unshackle serve: HAYU (ref ef1b9f): Hayu playback failed: Invalid Token. Check this service's login/session in Unshackle."
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
