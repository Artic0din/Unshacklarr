"""Errors shown clearly: in the error colour, announced, tied to their field, and the cause first (#280).
Each script runs the page's own code in Node, on a small stand-in for the DOM."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from css_assets import load_css

STATIC = Path(__file__).parents[1] / "unshacklarr" / "static"
JS = STATIC / "js"
HTML = (STATIC / "index.html").read_text()
CSS = load_css()

# A DOM just big enough to be asked what a field says about itself: attributes, classes, a tree to query.
FAKE_DOM = r"""
const fs = require("fs"), vm = require("vm");
const read = (file) => fs.readFileSync(file, "utf8");
const any = new Proxy(function () {}, { get: (_, k) => (k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : any), apply: () => any, construct: () => any, set: () => true });
const grab = (src, re) => { const m = src.match(re); if (!m) throw Error(`not in the source: ${re}`); return m[0]; };
class Fake {
  constructor(tag, props = {}, kids = []) {
    Object.assign(this, { tag, attrs: {}, kids: [], classes: new Set(), parent: null, style: { setProperty() {} }, dataset: {}, value: "", offsetTop: 0, offsetHeight: 0, offsetLeft: 0, offsetWidth: 0 }, props);
    String(props.className || "").split(" ").filter(Boolean).forEach((c) => this.classes.add(c));
    this.append(...kids);
  }
  get classList() {
    return { add: (c) => this.classes.add(c), remove: (c) => this.classes.delete(c), contains: (c) => this.classes.has(c),
      toggle: (c, on = !this.classes.has(c)) => { on ? this.classes.add(c) : this.classes.delete(c); return on; } };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...kids) { for (const k of kids.flat()) { if (k instanceof Fake) k.parent = this; this.kids.push(k); } }
  replaceChildren(...kids) { this.kids = []; this.append(...kids); }
  after(node) { const at = this.parent.kids.indexOf(this); node.parent = this.parent; this.parent.kids.splice(at + 1, 0, node); }
  remove() { this.parent?.kids.splice(this.parent.kids.indexOf(this), 1); this.parent = null; }
  matches(sel) {
    return sel.split(",").some((one) => {
      one = one.trim();
      const word = one.match(/^\[aria-describedby~="(.+)"\]$/);
      return word ? (this.attrs["aria-describedby"] || "").split(" ").includes(word[1]) : one.startsWith(".") ? this.classes.has(one.slice(1)) : one === this.tag;
    });
  }
  querySelectorAll(sel) { return this.kids.filter((k) => k instanceof Fake).flatMap((k) => [...(k.matches(sel) ? [k] : []), ...k.querySelectorAll(sel)]); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] ?? null; }
  addEventListener(type, fn) { (this.listeners ??= []).push([type, fn]); }
  fire(type, event) { (this.listeners || []).filter(([t]) => t === type).forEach(([, fn]) => fn(event)); }
  focus() { this.focused = true; }
  getClientRects() { return this.hidden || this.type === "hidden" ? [] : [{}]; }  // drawn, unless hidden
  get firstChild() { return this.kids[0]; }
  get lastChild() { return this.kids.at(-1); }
  get textContent() { return this.text ?? this.kids.map((k) => k?.textContent ?? k).join(""); }
  set textContent(v) { this.text = v; this.kids = []; }
}
const made = [];
const el = (tag, props = {}, ...kids) => { const n = new Fake(tag, props, kids); made.push(n); return n; };
const nodes = {};
const $ = (sel) => (nodes[sel] ??= new Fake("div", /^#[\w-]+$/.test(sel) ? { id: sel.slice(1) } : {}));
function sandbox(named = {}) {
  const own = { el, $, lineBySentence: (n) => n, structuredClone, Intl, sessionStorage: { getItem: () => null, setItem() {} }, ...named };
  const ctx = vm.createContext(new Proxy(own, { has: () => true, get: (t, k) => (k in t ? t[k] : k in globalThis ? globalThis[k] : any), set: (t, k, v) => ((t[k] = v), true) }));
  vm.runInContext(grab(read(process.argv[1]), /^let messageIds[\s\S]*?^function markInvalid[\s\S]*?^}\n/m), ctx);  // core.js
  return ctx;
}
"""


def node(body, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", FAKE_DOM + body, "--", str(JS / "core.js"), *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_initial_state_failure_shows_one_alert_and_retry_across_routes():
    shown = node(r"""
const src = read(process.argv[2]), shared = $("#initial-state-error");
shared.hidden = true;
let reloads = 0;
const ctx = sandbox({
  api: async (path) => path === "/api/session" ? { configured: true, logged_in: true } : {},
  fetch: async () => ({ ok: false, status: 503 }),
  responseError: async () => new Error("Service unavailable"),
  i18nReady: Promise.resolve(), location: { reload: () => reloads++ }, paintLights() {},
});
const core = read(process.argv[1]);
vm.runInContext(grab(core, /^function failed\(.*?^\}/ms), ctx);
vm.runInContext(src.slice(src.lastIndexOf("\n(async () => {")), ctx).then(() => {
  const alert = shared.firstChild, retry = alert?.kids[1];
  retry?.onclick?.();
  console.log(JSON.stringify([shared.hidden, alert?.role, alert?.kids[0].textContent, retry?.textContent, reloads]));
});
""", str(JS / "setup.js"))
    assert shown == [False, "alert", "Could not load app data: Service unavailable", "Try again", 1]
    assert re.search(r'<main[^>]*>\s*<div id="initial-state-error" hidden></div>', HTML)
    assert re.search(r"#initial-state-error:not\(\[hidden\]\) ~ section \{\s*display: none;", CSS)


def rule_colour(selector):
    """The colour of the last rule in the stylesheet that is exactly this selector (comments aside)."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    found = re.findall(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    colours = [m.group(1) for body in found if (m := re.search(r"(?<![-\w])color:\s*([^;]+)", body))]
    return colours[-1].strip() if colours else None


def test_an_error_in_a_dialog_is_in_the_error_colour_not_the_muted_one():
    assert rule_colour(".modal p.status-err") == "var(--err)"
    assert rule_colour(".modal p.status-warn") == "var(--warn)"


@pytest.mark.parametrize("id,role", [("remote-error", "alert"), ("jobopts-err", "alert"), ("folder-err", "alert"), ("sel-noservice", "status")])
def test_a_dialog_message_is_announced_when_it_is_written(id, role):
    tag = re.search(rf'<p [^>]*id="{id}"[^>]*>', HTML).group(0)
    assert f'role="{role}"' in tag


def test_a_field_says_it_is_invalid_and_by_what_while_keeping_its_help():
    seen = node(r"""
const ctx = sandbox();
const input = new Fake("input"), help = new Fake("small", { id: "help" }), say = new Fake("small", { id: "say" });
input.setAttribute("aria-describedby", "help");
const state = () => [input.classList.contains("bad"), input.getAttribute("aria-invalid"), input.getAttribute("aria-describedby")];
const out = {};
ctx.markInvalid(input, say); out.on = state();
ctx.markInvalid(input, say); out.twice = state();
ctx.markInvalid(input, say, false); out.off = state();
const bare = new Fake("input");
ctx.markInvalid(bare, say); ctx.markInvalid(bare, say, false);
out.bare = [bare.getAttribute("aria-invalid"), bare.getAttribute("aria-describedby")];
const noMessage = new Fake("input"); ctx.markInvalid(noMessage); out.noMessage = [noMessage.getAttribute("aria-invalid"), noMessage.getAttribute("aria-describedby")];
console.log(JSON.stringify(out));
""")
    assert seen == {
        "on": [True, "true", "help say"], "twice": [True, "true", "help say"], "off": [False, None, "help"],
        "bare": [None, None], "noMessage": ["true", None],
    }


WIZARD = r"""
const setup = read(process.argv[2]);
const gateForm = $("#gate-form");
const ctx = sandbox({ gate: () => {}, icon: () => new Fake("svg"), loading: (t) => new Fake("div", { text: t }), failed: (t) => new Fake("div", { role: "alert", text: t }),
  countryPicker: () => ({ input: new Fake("input"), list: new Fake("ul") }), listPicker: any, urlProblem: () => "", pwStrength: () => 1, LANG: "en", LOCALE: "en",
  api: async () => { throw new Error("The setup code is wrong"); }, document: { createElement: (t) => new Fake(t) } });
$("#gate .logo").cloneNode = () => new Fake("div");
vm.runInContext(grab(setup, /^let fieldIds[\s\S]*?^}\n/m).replace("const optional", "var optional"), ctx);
vm.runInContext(grab(setup, /^function showSetup[\s\S]*?\n}\n/m), ctx);
ctx.showSetup({});
const inputs = made.filter((n) => n.tag === "input" || n.tag === "select");
const labelOf = (input) => made.find((n) => n.tag === "label" && n.htmlFor === input.id);
const fieldOf = (text) => inputs.find((i) => labelOf(i)?.textContent.replace(/ Optional$/, "") === text);
"""


def test_the_setup_says_which_fields_are_needed_and_which_are_optional():
    seen = node(WIZARD + r"""
const text = (name) => labelOf(fieldOf(name)).textContent;
console.log(JSON.stringify({
  required: ["Setup code", "Password", "Confirm password", "Sonarr URL", "Downloads folder, as Sonarr sees it"].map((n) => fieldOf(n).required === true),
  optional: ["TMDB API key", "Unshackle command", "Downloads folder"].map(text),
  needed: ["Setup code", "Password"].map(text),
}));
""", str(JS / "setup.js"))
    assert seen == {
        "required": [True] * 5,
        "optional": ["TMDB API key Optional", "Unshackle command Optional", "Downloads folder Optional"],
        "needed": ["Setup code", "Password"],
    }


def test_the_setup_ties_a_fields_help_to_it():
    seen = node(WIZARD + r"""
const password = fieldOf("Password"), help = made.find((n) => n.id === `${password.id}-help`);
console.log(JSON.stringify({ described: password.getAttribute("aria-describedby") === `${password.id}-help`, help: help.textContent }));
""", str(JS / "setup.js"))
    assert seen == {"described": True, "help": "At least 8 characters."}


def test_a_wrong_setup_field_is_invalid_and_described_by_its_message_until_it_is_edited():
    seen = node(WIZARD + r"""
const code = fieldOf("Setup code"), password = fieldOf("Password");
const panelInput = made.find((n) => n.className === "wiz-panel");
const state = () => ({ invalid: code.getAttribute("aria-invalid"), described: code.getAttribute("aria-describedby"),
  bubbles: panelInput.querySelectorAll(".field-error").map((b) => [b.role, b.textContent, b.id]) });
const out = {};
gateForm.onsubmit({ preventDefault() {} }).then(() => {
  out.after = state();
  out.pointsAtBubble = out.after.described.split(" ").includes(out.after.bubbles[0][2]);
  out.focused = code.focused === true;
  console.log(JSON.stringify(out));
});
""", str(JS / "setup.js"))
    assert seen["after"]["invalid"] == "true"
    assert seen["after"]["bubbles"][0][:2] == ["alert", "Enter the setup code"]
    assert seen["pointsAtBubble"] and seen["focused"]


def test_the_passwords_strength_and_match_are_read_out_and_the_mismatch_is_tied_to_its_field():
    seen = node(WIZARD + r"""
const [password, confirm] = [fieldOf("Password"), fieldOf("Confirm password")];
const match = made.find((n) => n.classes.has("pw-match")), meter = made.find((n) => n.classes.has("pw-meter"));
const out = { matchRole: match.role, meterRegion: meter.parent.role };  // both exist before they are filled
password.value = "abcdefghij"; confirm.value = "abcdefgxyz";
confirm.oninput();
out.mismatch = [match.textContent, confirm.getAttribute("aria-invalid"), confirm.getAttribute("aria-describedby") === match.id];
confirm.value = "abcdefghij";
confirm.oninput();
out.same = [match.textContent, confirm.getAttribute("aria-invalid"), confirm.getAttribute("aria-describedby")];
console.log(JSON.stringify(out));
""", str(JS / "setup.js"))
    assert seen == {
        "matchRole": "status", "meterRegion": "status",
        "mismatch": ["Passwords do not match", "true", True],
        "same": ["Passwords match", None, None],
    }


def test_editing_a_wrong_setup_field_takes_its_flag_and_its_message_away():
    seen = node(WIZARD + r"""
const code = fieldOf("Setup code"), panel = made.find((n) => n.className === "wiz-panel");
gateForm.onsubmit({ preventDefault() {} }).then(() => {
  panel.fire("input", { target: code });
  console.log(JSON.stringify({ invalid: code.getAttribute("aria-invalid"), described: code.getAttribute("aria-describedby") === `${code.id}-help`, bubbles: panel.querySelectorAll(".field-error").length }));
});
""", str(JS / "setup.js"))
    assert seen == {"invalid": None, "described": True, "bubbles": 0}  # only its help is left


PASSWORD_BUTTON = r"""
const src = read(process.argv[2]);
let called = null;
const ctx = sandbox({ api: async (path, opts) => { called = JSON.parse(opts.body); if (answer) throw answer; return {}; }, errorDetail: (e) => e.message, toast() {}, loadAccount() {}, pwCheck() {}, icon: any,
  setTimeout() {} });
var answer = null;
vm.runInContext(grab(src, /^const PW_SAYS[\s\S]*?^function pwMistake[\s\S]*?^}\n/m), ctx);
vm.runInContext(grab(src, /^\$\("#pw-change"\)\.onclick = [\s\S]*?^};\n/m), ctx);
const set = (current, fresh, again) => { $("#pw-current").value = current; $("#pw-new").value = fresh; $("#pw-again").value = again; };
const say = (id) => [$(`#${id}`).getAttribute("aria-invalid"), $(`#${id}`).focused === true];
"""


def test_the_password_button_stays_on_and_says_what_is_missing_on_the_field():
    assert not re.search(r'id="pw-change"[^>]*\bdisabled\b', HTML)
    seen = node(PASSWORD_BUTTON + r"""
(async () => {
  const out = {};
  set("", "newpassword", "newpassword");
  await $("#pw-change").onclick();
  out.noCurrent = [...say("pw-current"), $("#pw-current-say").textContent, $("#pw-current").getAttribute("aria-describedby") === "pw-current-say"];
  set("old", "short", "short");
  await $("#pw-change").onclick();
  out.short = [...say("pw-new"), $("#pw-new-say").textContent, say("pw-current")[0]];
  set("old", "newpassword", "newpassworX");
  await $("#pw-change").onclick();
  out.mismatch = [...say("pw-again"), $("#pw-match").textContent, say("pw-new")[0]];
  out.sent = called;
  set("old", "newpassword", "newpassword");
  await $("#pw-change").onclick();
  out.fine = [called, say("pw-again")[0], $("#pw-change").disabled];
  console.log(JSON.stringify(out));
})();
""", str(JS / "settings-options.js"))
    assert seen == {
        "noCurrent": ["true", True, "Enter your current password", True],
        "short": ["true", True, "Password must be at least 8 characters", None],
        "mismatch": ["true", True, "Passwords do not match", None],
        "sent": None,
        "fine": [{"current": "old", "new": "newpassword"}, None, False],
    }


def test_a_password_the_server_refuses_is_said_on_its_field():
    seen = node(PASSWORD_BUTTON + r"""
answer = new Error("The current password is wrong");
set("old", "newpassword", "newpassword");
$("#pw-change").onclick().then(() => console.log(JSON.stringify([...say("pw-current"), $("#pw-current-say").textContent, $("#pw-change").disabled])));
""", str(JS / "settings-options.js"))
    assert seen == ["true", True, "The current password is wrong", False]


def test_the_download_window_says_a_half_set_window_beside_the_to_field():
    seen = node(r"""
const ctx = sandbox({ S: { config: { settings: {} } } });
vm.runInContext(grab(read(process.argv[2]), /^function renderLearnWindow\(\)[\s\S]*?^}\n/m), ctx);
const [from, to, say, err] = ["#ax-from", "#ax-to", "#ax-window-say", "#ax-window-err"].map($);
const state = () => [from, to].map((x) => [x.classes.has("bad"), x.getAttribute("aria-invalid"), x.getAttribute("aria-describedby")]).concat([[err.textContent, say.textContent]]);
const out = {};
from.value = "23:00"; ctx.renderLearnWindow(); out.half = state();
to.value = "06:00"; ctx.renderLearnWindow(); out.both = state();
console.log(JSON.stringify(out));
""", str(JS / "quality.js"))
    assert seen["half"] == [[False, None, None], [True, "true", "ax-window-err"], ["Set both a start and an end time, or neither.", ""]]
    assert seen["both"][:2] == [[False, None, None]] * 2
    assert seen["both"][2][0] == ""
    assert "#ax-window-err" not in HTML and 'id="ax-window-err"' in HTML.split('id="ax-to"')[1].split("</section>")[0]


def test_a_failed_lookup_is_an_error_with_a_way_to_try_again():
    seen = node(r"""
const failedBox = (text, retry) => ({ failed: text, retry });
const src = read(process.argv[2]);
let tries = 0;
const ctx = sandbox({ api: async () => { throw new Error("DownStream can't be reached"); }, failed: failedBox, S: { config: { settings: {} }, series: [] }, ugGroups: null });
vm.runInContext(grab(src, /^async function renderUpgradeGroups[\s\S]*?^}\n/m), ctx);
const box = $("#ug-groups");
ctx.renderUpgradeGroups().then(() => {
  const [shown] = box.kids;
  const out = { text: shown.failed, retry: typeof shown.retry };
  // library check: the same, in the line that already announces itself
  const say = $("#dx-lib-check");
  const lib = sandbox({ api: async () => { throw new Error("DownStream can't be reached"); }, libSeq: 0, libTimer: 0, libOf: () => ({}), mainSonarr: () => "Sonarr", savedSonarr: () => "",
    S: { config: { settings: {} } }, setTimeout: (fn) => fn() });
  vm.runInContext(grab(src, /^function checkLibrary\(\)[\s\S]*?^}\n/m), lib);
  lib.checkLibrary();
  setTimeout(() => {
    out.lib = [say.className, say.kids[0], say.kids.at(-1).textContent, say.kids.at(-1).onclick === lib.checkLibrary];
    console.log(JSON.stringify(out));
  }, 20);
});
""", str(JS / "quality.js"))
    assert seen["text"] == "Could not look it up: DownStream can't be reached" and seen["retry"] == "function"
    assert seen["lib"] == ["lib-check err", "DownStream can't be reached", "Try again", True]


def test_a_cookie_dialog_with_nothing_to_save_flags_the_text_it_is_about():
    seen = node(r"""
const failed = (t) => new Fake("div", { role: "alert", text: t });
const ctx = sandbox({ failed });
$("#ck-service").value = "ITV"; $("#ck-profile").value = "default"; $("#ck-text").value = "  ";
vm.runInContext(grab(read(process.argv[2]), /^const ckClear[^\n]*\n/m) + grab(read(process.argv[2]), /^\$\("#ck-text"\)\.oninput = ckClear;\n/m) + grab(read(process.argv[2]), /^\$\("#ck-form"\)\.onsubmit = [\s\S]*?^};\n/m), ctx);
$("#ck-form").onsubmit({ submitter: { value: "save" }, preventDefault() {} });
const text = $("#ck-text"), out = { invalid: text.getAttribute("aria-invalid"), described: text.getAttribute("aria-describedby"), focused: text.focused === true, said: $("#ck-error").kids[0].text };
$("#ck-text").oninput();
out.edited = [text.getAttribute("aria-invalid"), text.getAttribute("aria-describedby"), $("#ck-error").kids.length];
console.log(JSON.stringify(out));
""", str(JS / "cookies-cdm.js"))
    assert seen == {"invalid": "true", "described": "ck-error", "focused": True, "said": "Pick a file or paste the cookies.",
                    "edited": [None, None, 0]}


def test_a_notification_address_field_that_is_wrong_is_flagged_and_described():
    seen = node(r"""
const input = new Fake("input", { name: "url" });
nodes["#nt-fields [name=url]"] = input;
$("#nt-fields").querySelectorAll = () => [input];
const ctx = sandbox({ ntApp: "Discord", BUILDERS: { Discord: { check: () => ["url", "Paste the webhook address"], url: () => "x" } } });
vm.runInContext(grab(read(process.argv[2]), /^function ntBuilt\(\)[\s\S]*?^}\n/m), ctx);
ctx.ntBuilt();
const out = { invalid: input.getAttribute("aria-invalid"), described: input.getAttribute("aria-describedby"), focused: input.focused === true, said: $("#nt-d-result").kids[0].textContent };
console.log(JSON.stringify(out));
""", str(JS / "settings-options.js"))
    assert seen == {"invalid": "true", "described": "nt-d-result", "focused": True, "said": "Paste the webhook address"}


def test_the_settings_password_checks_are_in_regions_that_exist_before_they_are_filled():
    assert re.search(r'<div role="status"><div class="pw-meter" id="pw-meter"', HTML)
    assert re.search(r'id="pw-match" role="status"', HTML)


def test_editing_a_password_after_a_rejection_keeps_what_is_still_wrong_said_to_a_screen_reader():
    seen = node(PASSWORD_BUTTON.replace("pwCheck() {}, ", "") + r"""
vm.runInContext(grab(src, /^function pwStrength[\s\S]*?^}\n/m) + grab(src, /^function pwCheck[\s\S]*?^}\n/m) + grab(src, /^\$\("#pw-new"\)\.oninput = .*\n/m), ctx);
const edit = (id, value) => { $(`#${id}`).value = value; $(`#${id}`).oninput({ target: { id } }); };
(async () => {
  set("old", "short", "short");
  await $("#pw-change").onclick();
  edit("pw-new", "sixchr");  // still too short
  const out = { stillShort: say("pw-new")[0] };
  edit("pw-new", "newpassword"); edit("pw-again", "newpassworX");  // long enough now, but the two differ
  out.newOk = say("pw-new")[0];
  out.mismatch = [say("pw-again")[0], ($("#pw-again").getAttribute("aria-describedby") || "").split(" ").includes("pw-match")];
  edit("pw-again", "newpassword");
  out.matched = say("pw-again")[0];
  console.log(JSON.stringify(out));
})();
""", str(JS / "settings-options.js"))
    assert seen == {"stillShort": "true", "newOk": None, "mismatch": ["true", True], "matched": None}


def test_editing_another_notification_field_clears_the_flag_with_its_message():
    src = (JS / "settings-options.js").read_text()
    assert 'querySelectorAll("input").forEach((i) => markInvalid(i, $("#nt-d-result"), false)); $("#nt-d-result").replaceChildren();' in src


def test_picking_a_country_clears_the_flag_on_the_box_that_was_flagged():
    src = (JS / "setup.js").read_text()
    pick = src[src.index("const pick = (c) => {"):src.index("};", src.index("const pick = (c) => {"))]
    assert "markInvalid(input, null, false)" in pick  # the visible box, not the hidden input the input event comes from
