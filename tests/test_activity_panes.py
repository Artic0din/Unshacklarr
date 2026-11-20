"""Activity's Stats and Waiting in downloads panes draw only their own answer; the output terminal says when it cannot connect."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from css_assets import load_css

JS = Path(__file__).parents[1] / "unshacklarr" / "static" / "js"

# Runs the page's real showStats / showLeftovers with api answers released in a chosen order, and prints what the pane ended up showing.
PANES = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const [first, second] = JSON.parse(process.argv[2]);  // the pane opened first, then the one opened second
const main = { children: [], replaceChildren(...children) { this.children = children; },
  get heading() { return JSON.stringify(this.children).match(/"textContent":"(Stats|Waiting in downloads)"/)?.[1] ?? "other"; } };
const title = { textContent: "" };
const stub = { textContent: "", hidden: false, classList: { add() {} }, replaceChildren() {} };
const pending = {};
const ctx = {
  $: (sel) => (sel === "#cd-main" ? main : sel === "#cd-top-title" ? title : stub),
  document: { querySelectorAll: () => [] },
  el: (tag, props = {}, ...kids) => ({ tag, ...props, kids }),
  failed: (t) => ({ failed: t }),
  clearTimeout() {},
  api: (path) => new Promise((resolve, reject) => { pending[path] = { resolve, reject }; }),
  day: () => "", ago: () => "", duration: () => "", LOCALE: "en", S: { series: [] }, svcName: (tag) => tag, icon: () => ({}), COUNT: {}, posterSrc: () => "", posterFail: () => null, OUTCOME: {}, renderDock: () => {},
};
vm.createContext(ctx);
vm.runInContext(`let picked_run = null, langTimer, langLast;\n` +
  ["markPicked", "showLeftovers", "showStats", "showLanguages"].map(grab).join("\n"), ctx);
const path = { stats: "/api/stats", left: "/api/leftovers" };
const answer = { stats: { month: {}, weeks: [], services: [], since: null }, left: { items: [], days: 0 } };
const open = { stats: ctx.showStats, left: ctx.showLeftovers };
(async () => {
  if (first === "languages") {
    const languages = ctx.showLanguages(), replacement = open[second]();
    pending[path[second]].resolve(answer[second]);
    await replacement;
    const content = main.children;
    pending["/api/languages"].reject(Error("network offline"));
    await languages;
    console.log(JSON.stringify({ title: title.textContent, heading: main.heading, unchanged: main.children === content }));
    return;
  }
  const a = open[first](), b = open[second]();
  for (const which of [second, first]) { pending[path[which]].resolve(answer[which]); await (which === second ? b : a); }
  console.log(JSON.stringify({ title: title.textContent, heading: main.heading }));
})();
"""

# Runs the page's real streamTerm against a fake socket and prints what was written into the terminal box.
TERMINAL = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const scenario = process.argv[2];
const written = [];
const sockets = [];
class FakeSocket { constructor() { sockets.push(this); } close() {} }
const ctx = { term: { write: (t) => written.push(typeof t === "string" ? t : "output") }, termSocket: null, termFor: null, termQuery: "",
  openTerm: () => true, termFilter: () => (b) => b, WebSocket: FakeSocket, location: { protocol: "http:", host: "x" } };
vm.createContext(ctx);
vm.runInContext(grab("streamTerm"), ctx);
ctx.streamTerm("run", "run=1");
const sock = sockets[0];
if (scenario === "output first") sock.onmessage({ data: new ArrayBuffer(1) });
if (scenario === "replaced") { ctx.termSocket = {}; }
sock.onclose?.(scenario === "clean" ? { code: 1000 } : { code: 1006 });
console.log(JSON.stringify(written));
"""


def node(script, *args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", script, "--", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


ACTIVITY_ACTIONS = r"""
const fs = require("fs"), vm = require("vm");
const [dir, scenario, ...args] = process.argv.slice(1);
const src = fs.readFileSync(`${dir}/activity.js`, "utf8");
const series = fs.readFileSync(`${dir}/series.js`, "utf8");
const core = fs.readFileSync(`${dir}/core.js`, "utf8");
const grab = (name, text = src) => text.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const line = (name, text = src) => text.match(new RegExp(`^const ${name} = .*?;(?:  //.*)?$`, "m"))[0];
const elements = {};
const el = (tag, props = {}, ...children) => ({ tag, children, classList: { add() {} },
  replaceChildren(...kids) { this.children = kids; }, querySelector: () => null,
  insertBefore(child) { this.children.push(child); }, cloneNode() { return { ...this }; }, ...props });
const $ = (sel) => elements[sel] ??= el(sel);
const walk = (n) => n?.tag ? [n, ...n.children.flatMap(walk)] : [];
const posts = [], toasts = [], opened = [];
let finishPost;
const target = args[0] || "";
const sonarrs = [{ name: "4K", quality_ladder: ["2160"] }, { name: "Unset" }];
const ctx = { $, el, URL, URLSearchParams, LOCALE: "en", KIND: {}, DOCK: {},
  S: { config: { settings: { sonarrs }, series: { 72: { service: "NF", season_pages: { 2: { service: "DSNP" } } } } },
    serviceNames: { NF: "Netflix", DSNP: "Disney+" }, series: [] },
  savedSonarr: (n) => n === "4K" ? "4K Saved" : n, mainSonarr: () => "Main",
  markPicked() {}, renderDock() {}, loading() {}, posterSrc() {}, posterFail() {}, ago: () => "yesterday",
  toast: (...data) => toasts.push(data), episodeTitle: (_, __, title) => title,
  trWith: (key, ...fill) => key.replace(/\{(\d+)\}/g, (_, i) => fill[i]),
  AbortSignal, tr: (text) => text,
  fetch: async (path, options) => {
    const ok = (body) => ({ ok: true, json: async () => body });
    if (options.method === "POST") {
      posts.push({ path, body: JSON.parse(options.body) });
      if (args[1] === "refused") return { ok: false, status: 500, text: async () => "read-only proxy" };
      if (args[1] === "gateway") return { ok: false, status: 504, text: async () => "gateway timeout" };
      if (args[1] === "pending" && posts.length === 1) await new Promise((resolve) => { finishPost = resolve; });
      if (args[1] === "lost") throw new TypeError("network offline");
      if (args[1] === "timeout") throw new DOMException("timed out", "TimeoutError");
      return ok({});
    }
    if (path === "/api/runs?live=1") throw new Error("Catch up should not check runs");
    if (path.startsWith("/api/upgrades")) return ok({ items: [], scan: {} });
    return ok({ items: [
      { episodeId: 123, tvdbId: 72, series: "Example", sxxeyy: "S01E05" },
      { episodeId: 456, tvdbId: 72, series: "Example", sxxeyy: "S02E01" },
    ] });
  },
  FINISHING: new Set(), jobHidden: new Set(), jobCards: new Map(), openCards: new Set(),
  following: null, isLive: (c) => c.outcome === "running", isQueued: (c) => c.step === "queued",
  thumb() {}, posterOf() {}, day() {}, time() {}, clearTimeout() {}, runCards: [],
  outcomeOf: (c) => c.outcome, hovering: () => "", stepStates: () => [], icon() {}, glideBars() {}, jobDone: () => el("div"),
  duration: () => "1 min", stepList: () => el("div"), checksNote() {}, cardActs: () => [],
  renderConsole: () => ctx.renderJob(job),
  openServiceRow: (...data) => opened.push(data),
};
let job;
vm.createContext(ctx);
vm.runInContext(`let picked_run;\n` +
  [src.slice(src.indexOf("let missingDays"), src.indexOf('$("#con-missing").onclick')),
    src.slice(src.indexOf("let upgrade"), src.indexOf('$("#con-upgrades").onclick')),
    grab("api", core), grab("responseError", core), line("svcName", series), grab("seasonTag", series), line("fixSignIn"),
    line("JOB_TRANSIENT"),
    ...["signInFailed", "signInAction", "cardKind", "jobState", "jobFailure", "renderJob", "runBody"].map((n) => grab(n))
  ].join("\n"), ctx);
(async () => {
  if (scenario === "job") {
    const card = { tvdbId: 72, series: "Example", outcome: "failed", started: "2026-01-01", service: "NF" };
    const auth = target !== "unclassified" ? { auth_failures: { DSNP: "expired" }, auth_failure_backends: { DSNP: "secondary" } }
      : { cause: "Login failed" };
    const waiting = target === "live" ? { outcome: "running", step: "queued", waiting: true, paused: true } : {};
    const first = target === "mixed" ? { cause: "Connection timed out" } : { ...auth, ...waiting };
    ctx.renderJob({ job: "job1", cards: [{ ...card, ...first, id: "a", episodeId: 123 }, { ...card, ...auth, id: "b", episodeId: 456 }] });
    const buttons = $("#cd-foot").children;
    const fix = buttons.find((b) => b.textContent === "Fix sign-in");
    fix?.onclick();
    console.log(JSON.stringify({ primary: buttons.filter((b) => b.className.includes("primary")).map((b) => b.textContent),
      opened, fk: fix?.dataset?.fk ?? null }));
    return;
  }
  if (scenario === "failure-reasons") {
    const failures = JSON.parse(target);
    job = { job: "job1", cards: failures.map((failure, i) => ({
      id: `run${i}`, episodeId: i + 1, sxxeyy: `S01E${String(i + 1).padStart(2, "0")}`, tvdbId: 72, series: "Example", service: "AMZN",
      outcome: "failed", started: "2026-01-01T00:00:00Z", ended: "2026-01-01T00:01:00Z",
      ...(typeof failure === "string" ? { cause: failure } : failure),
    })) };
    ctx.renderJob(job);
    const text = () => walk($("#cd-main")).flatMap((n) => typeof n.textContent === "string" ? [n.textContent] : []);
    const groups = $("#cd-main").children.flatMap(walk).find((n) => n.className === "cd-note err")?.children.map((n) => n.textContent);
    const folded = text();
    const retry = $("#cd-foot").children.find((b) => b.dataset?.fk === "retry");
    walk($("#cd-main")).find((n) => n.dataset?.fk === "card:run0").onclick();
    console.log(JSON.stringify({ folded, groups: groups ?? null, expanded: text(), retry: retry.textContent, primary: retry.className.includes("primary") }));
    return;
  }
  if (scenario === "upgrades") {
    await ctx.showUpgrades();
    console.log(JSON.stringify(walk($("#cd-main")).filter((n) => n.tag === "small").map((n) => n.textContent)));
    return;
  }
  await ctx.showMissing();
  if (target) {
    walk($("#cd-main")).find((n) => n.tag === "button" && n.textContent === target).onclick();
    await new Promise(setImmediate);
  }
  const click = (b) => b?.onclick({ currentTarget: b, target: b });
  const lastRow = () => walk($("#cd-main")).filter((n) => n.textContent === "Download").at(-1);
  const unavailable = (b) => !!b.disabled || b.ariaDisabled === "true";
  // a pending or accepted row stays focusable: aria-disabled, never the native attribute
  const held = (b) => { if (b.disabled) throw new Error("natively disabled: focus would drop"); return b.ariaDisabled === "true"; };
  if (scenario === "redraw") {
    const posted = click(lastRow());
    const remainsFocusable = lastRow().ariaDisabled === "true" && !lastRow().disabled;
    await click(walk($("#cd-main")).find((n) => n.textContent === "90 days"));
    await new Promise(setImmediate);
    await click(lastRow());
    finishPost();
    await posted;
    const locked = held(lastRow());
    await click(walk($("#cd-main")).find((n) => n.textContent === "4K"));
    await new Promise(setImmediate);
    const otherInstance = held(lastRow());
    console.log(JSON.stringify({ posts, remainsFocusable, locked, otherInstance }));
    return;
  }
  if (scenario === "reload") {
    const button = lastRow();
    await click(button);
    await click(button);
    const beforeReload = held(button), initialPosts = posts.length;
    await ctx.showMissing();
    const afterReload = held(lastRow());
    await click(lastRow());
    console.log(JSON.stringify({ beforeReload, initialPosts, afterReload, posts, toasts }));
    return;
  }
  const all = walk($("#cd-main"));
  const rows = all.filter((n) => n.className?.split(" ").includes("left-row"));
  const buttons = rows.map((r) => walk(r).find((n) => n.tag === "button" && n.textContent === "Download"));
  const bulk = all.find((n) => n.tag === "button" && n.textContent === "Download the 2");
  let nativelyDisabledDuring;
  for (const action of scenario.split("-")) {
    const b = action === "row" ? buttons[1] : bulk;
    const request = click(b);
    nativelyDisabledDuring = !!b.disabled;
    await request;
  }
  console.log(JSON.stringify({ posts, toasts, bulkHidden: bulk.hidden, chips: rows.map((r) =>
    walk(r).find((n) => n.className === "sv-chip")?.textContent),
    nativelyDisabledDuring, buttons: buttons.map((b) => b && { primary: b.className.includes("primary"), disabled: unavailable(b), native: !!b.disabled }) }));
})();
"""


@pytest.mark.parametrize(("target", "sonarr"), [("", {}), ("4K", {"sonarr": "4K Saved"})])
def test_catch_up_row_download_uses_same_sonarr_as_bulk(target, sonarr):
    row = node(ACTIVITY_ACTIONS, str(JS), "row", target)
    bulk = node(ACTIVITY_ACTIONS, str(JS), "bulk", target)
    assert row["posts"] == [{"path": "/api/download", "body": {"episodeIds": [456], **sonarr}}]
    assert bulk["posts"] == [{"path": "/api/download", "body": {"episodeIds": [123, 456], **sonarr}}]
    assert row["chips"] == ["Netflix", "Disney+"]
    assert row["buttons"] == [{"primary": False, "disabled": False, "native": False}, {"primary": False, "disabled": True, "native": False}]


@pytest.mark.parametrize("action", ["row", "bulk"])
def test_catch_up_never_queues_when_sonarr_quality_is_unset(action):
    result = node(ACTIVITY_ACTIONS, str(JS), action, "Unset")
    assert result["posts"] == []
    assert result["bulkHidden"] is True
    assert all(b and b["disabled"] for b in result["buttons"])


def test_catch_up_download_error_allows_retry():
    result = node(ACTIVITY_ACTIONS, str(JS), "row-row", "", "refused")
    assert result["toasts"] == [["read-only proxy", True]] * 2
    assert len(result["posts"]) == 2
    assert result["buttons"][1]["disabled"] is False
    assert result["nativelyDisabledDuring"] is False


def test_catch_up_blocks_duplicate_after_redraw_but_not_in_another_sonarr():
    result = node(ACTIVITY_ACTIONS, str(JS), "redraw", "", "pending")
    assert [request["body"] for request in result["posts"]] == [{"episodeIds": [456]}]
    assert result["remainsFocusable"] is True
    assert result["locked"] is True
    assert result["otherInstance"] is False


@pytest.mark.parametrize("sonarr", ["", "4K"])
def test_catch_up_can_retry_accepted_download_still_missing_after_reload(sonarr):
    result = node(ACTIVITY_ACTIONS, str(JS), "reload", sonarr)
    assert result["beforeReload"] is True
    assert result["initialPosts"] == 1
    assert result["afterReload"] is False
    body = {"episodeIds": [456], **({"sonarr": "4K Saved"} if sonarr else {})}
    assert [request["body"] for request in result["posts"]] == [body, body]


@pytest.mark.parametrize("failure", ["lost", "timeout", "gateway"])
def test_catch_up_can_retry_when_download_response_fails(failure):
    result = node(ACTIVITY_ACTIONS, str(JS), "row-row", "", failure)
    assert len(result["posts"]) == 2
    assert len(result["toasts"]) == 2 and all(error for _, error in result["toasts"])
    assert result["buttons"][1]["disabled"] is False


@pytest.mark.parametrize(("order", "sent"), [("row-bulk", [[456], [123]]), ("bulk-row", [[123, 456]])])
def test_catch_up_row_and_bulk_do_not_queue_the_same_episode(order, sent):
    result = node(ACTIVITY_ACTIONS, str(JS), order)
    assert [request["body"]["episodeIds"] for request in result["posts"]] == sent
    assert all(b["disabled"] and not b["native"] for b in result["buttons"])  # held rows keep keyboard focus


@pytest.mark.parametrize(("classification", "primary", "opened", "fk"), [
    ("classified", ["Fix sign-in"], [["DSNP", "secondary"]], "sign-in"),
    ("live", ["Fix sign-in"], [["DSNP", "secondary"]], "sign-in"),
    ("mixed", ["Retry 2 failed"], [["DSNP", "secondary"]], "sign-in"),
    ("unclassified", ["Retry 2 failed"], [], None),
])
def test_failed_job_footer_offers_sign_in_only_for_classified_failure(classification, primary, opened, fk):
    result = node(ACTIVITY_ACTIONS, str(JS), "job", classification)
    assert result == {"primary": primary, "opened": opened, "fk": fk}


@pytest.mark.parametrize(("other", "summary", "primary"), [
    ([], [], False),
    (["404 Client Error: Not Found for url: https://example.test/three"], ["404 Not Found"], True),
    (["HTTP 403: Forbidden"], ["403 Forbidden"], True),
    (["503 Server Error: Service Unavailable for url: https://example.test/three", "Connection timed out"],
     ["503 Service Unavailable", "Connection timed out"], True),
])
def test_job_summarizes_failure_reasons_and_keeps_episode_details(other, summary, primary):
    raw = "451 Client Error: Unavailable for Legal Reason for url: https://example.test/"
    causes = [f"AMZN through Unshackle: HTTP 422: An unexpected error occurred: {raw}manifest?ep=1 (ref a0e2e9)",
              raw + "manifest?ep=2", *other]
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps(causes))
    assert len(result["groups"]) == 1 + len(summary)
    assert result["groups"][0].startswith("2 episodes: 451 Unavailable for Legal Reason")
    if not other:
        assert result["groups"] == ["2 episodes: 451 Unavailable for Legal Reason"]
        assert sum("451 Unavailable for Legal Reason" in text for text in result["folded"]) == 1
    assert all("https://" not in text for text in result["folded"])
    assert result["folded"].count("failed") == len(causes)
    assert causes[0] in result["expanded"]
    assert all(group.startswith(f"1 episode: {reason}") for group, reason in zip(result["groups"][1:], summary))
    assert result["retry"] == f"Retry {len(causes)} failed"
    assert result["primary"] is primary


def test_job_groups_same_status_by_provider_not_endpoint():
    raw = "403 Client Error: Forbidden for url: https://example.test/"
    failures = [raw + "licence?request=first (ref abc123)",
                raw + "licence?request=second (ref def456)",
                raw + "episodes/first-episode/manifest.mpd?request=third",
                raw + "episodes/second-episode/manifest.mpd?request=fourth",
                {"service": "DSNP", "cause": raw + "episodes/third-episode/manifest.mpd"}]
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps(failures))
    assert result["groups"] == [
        "4 episodes: 403 Forbidden · AMZN (S01E01, S01E02, S01E03, S01E04)",
        "1 episode: 403 Forbidden · Disney+ (S01E05)",
    ]


def test_job_groups_same_reason_across_operations_without_a_url():
    causes = ["Amazon widevine licence HTTP 403: Denied (ref a0e2e9)",
              "Manifest HTTP 403: Denied (ref b1e3f0)"]
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps(causes))
    assert result["groups"] == ["2 episodes: 403 Denied"]


def test_job_groups_eleven_prime_451s_across_endpoints_but_keeps_403_separate():
    denied = "Amazon widevine licence HTTP 403: Denied"
    raw = "451 Client Error: Unavailable for Legal Reason for url: https://"
    causes = [denied, *[raw + f"first.example/v1/playback?episode={i}" for i in range(10)],
              raw + "second.example/v2/manifest.mpd"]
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps(causes))
    assert result["groups"] == [
        "1 episode: 403 Denied (S01E01)",
        "11 episodes: 451 Unavailable for Legal Reason "
        "(S01E02, S01E03, S01E04, S01E05, S01E06, S01E07, S01E08, S01E09, S01E10, S01E11, S01E12)",
    ]
    assert result["primary"] is True


def test_job_groups_netflix_failures_with_different_or_truncated_references():
    prefix = (
        "NF through Unshackle: HTTP 400: Invalid input: Netflix MSL request failed: "
        "{'code': 'FAIL', 'detail': 'manifest/playapi-105: Viewable not available - validation error. "
    )
    complete = prefix + "(E3-first-reference)'} (ref abc123)"
    truncated = prefix + "(E3-second-truncated-reference (ref def456)"
    cards = [{"service": "NF", "cause": cause} for cause in [complete, truncated]]
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps(cards))
    assert result["groups"] == ["2 episodes: 400 Viewable not available - validation error."]
    assert complete in result["expanded"]


@pytest.mark.parametrize("first_line", ["HTTP 451: Unavailable for Legal Reason",
                                       "451 Client Error: Unavailable for Legal Reason"])
def test_job_parses_multiline_451_and_demotes_retry(first_line):
    cause = f"\n  {first_line}\r\nTraceback from https://example.test/path?token=internal"
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps([cause, first_line]))
    assert result["groups"] == ["2 episodes: 451 Unavailable for Legal Reason"]
    assert result["primary"] is False
    assert cause in result["expanded"]


def test_job_groups_multiline_causes_by_first_http_error():
    causes = ["Provider request failed\nHTTP 451: Denied\nHTTP 403: Forbidden",
              "Provider request failed\n503 Server Error: Service Unavailable"]
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps(causes))
    assert result["groups"] == [
        "1 episode: 451 Denied (S01E01)",
        "1 episode: 503 Service Unavailable (S01E02)",
    ]


def test_job_keeps_retry_primary_for_connection_reset_after_451():
    cause = "HTTP 451: Denied\nTemporary failure: connection reset"
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps([cause, cause]))
    assert result["groups"] == ["2 episodes: 451 Denied"]
    assert result["primary"] is True


def test_job_transient_pattern_matches_backend():
    from unshacklarr.sync import TRANSIENT

    source = (JS / "activity.js").read_text(encoding="utf-8")
    classifier = re.search(r"^const JOB_TRANSIENT = /(.+)/([a-z]*);$", source, re.MULTILINE)
    assert classifier is not None
    assert classifier.groups() == (TRANSIENT.pattern, "i" if TRANSIENT.flags & re.IGNORECASE else "")


def test_job_groups_long_reasons_by_full_sanitized_text():
    prefix = "The sign-in request did not complete. " * 3
    cancelled = f"HTTP 401: {prefix}Sign-in was cancelled"
    rejected = f"HTTP 401: {prefix}Sign-in was rejected"
    causes = [cancelled + " (ref abc123)", cancelled + " (ref def456)", rejected]
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps(causes))
    label = "401 The sign-in request did not complete. The sign-in request did not complete. The sign-in request did…"
    assert result["groups"] == [
        f"2 episodes: {label} (S01E01, S01E02)",
        f"1 episode: {label} (S01E03)",
    ]


def test_single_episode_job_shows_clean_reason_on_card_without_summary():
    cause = "HTTP 403: Denied ?request=first"
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps([cause]))
    assert result["groups"] is None
    assert "403 Denied · took 1 min" in result["folded"]
    assert cause in result["expanded"]


@pytest.mark.parametrize("cause", [
    "HTTP 403: Temporarily denied",
    "HTTP 404: Not found",
    "HTTP 451: Temporarily denied",
    "HTTP 451: Denied\nService is temporarily unavailable",
])
def test_job_keeps_retry_primary_unless_failures_are_clearly_permanent(cause):
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps([cause, cause]))
    assert result["retry"] == "Retry 2 failed"
    assert result["primary"] is True


def test_job_lists_affected_episodes_only_when_failure_reasons_differ():
    denied = "download worker failed: RuntimeError: Amazon widevine licence HTTP 403: Denied"
    blocked = "451 Client Error: Unavailable for Legal Reason for url: https://example.test/playback"
    result = node(ACTIVITY_ACTIONS, str(JS), "failure-reasons", json.dumps([denied, blocked, blocked]))
    assert result["groups"] == [
        "1 episode: 403 Denied (S01E01)",
        "2 episodes: 451 Unavailable for Legal Reason (S01E02, S01E03)",
    ]
    assert denied in result["expanded"]


def test_upgrades_explains_which_files_the_quality_ladder_selects():
    assert node(ACTIVITY_ACTIONS, str(JS), "upgrades")[0].split(".")[0] == "Your quality ladder decides which files can be upgraded"


SWITCHER = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8"), html = fs.readFileSync(process.argv[2], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const line = (name) => src.match(new RegExp(`^const ${name} = .*;$`, "m"))[0];
const handler = (id) => src.match(new RegExp(`^\\$\\("#${id}"\\)\\.onclick = .*?^\\};`, "ms"))[0];
const doc = { activeElement: null };
const node = (props = {}) => ({
  children: [], attrs: {}, dataset: {}, classList: { toggle() {}, add() {}, remove() {} },
  setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
  replaceChildren(...children) { this.children = children; }, get childElementCount() { return this.children.length; },
  focus() { doc.activeElement = this; },
  getBoundingClientRect: () => ({ left: 0, right: 100, width: 100 }),
  ...props,
});
const elements = { "#con-search": node({ value: "" }) };
const filters = ["all", "downloaded", "failed", "kept", "stopped"].map((f) => {
  const count = node();
  return node({ dataset: { f }, count, querySelector: () => count });
});
const buttons = [...html.matchAll(/id="(con-[^"]+)" data-con-view="([^"]+)" aria-pressed="([^"]+)"/g)].map(([, id, conView, pressed]) =>
  elements[`#${id}`] = node({ dataset: { conView }, attrs: { "aria-pressed": pressed } }));
const $ = (s) => {
  if (s.startsWith("#cd-main > ")) return $("#cd-main").children.find((n) => [`.${n.className}`, `#${n.id}`].includes(s.slice(11)));
  const chip = s.match(/^#con-running \[data-fk="([^"]+)"\]$/);
  if (chip) return $("#con-running").children.find((n) => n.dataset.fk === chip[1]);
  const row = s.match(/^\[data-fk="row:([^"]+)"\]$/);
  if (row) return [...$("#runs-live").children, ...$("#runs-history").children].find((n) => n.dataset.hk === `row:${row[1]}`);
  return elements[s] ??= node();
};
let detail = null;
const pending = {};
const location = { hash: "#/activity" };
const entries = [{ state: null, hash: location.hash }];
let entry = 0;
const historyStack = {
  get state() { return entries[entry].state; },
  pushState(state, _, hash = location.hash) { entries.splice(++entry, Infinity, { state, hash }); location.hash = hash; },
  replaceState(state, _, hash = location.hash) { entries[entry] = { state, hash }; location.hash = hash; },
  back() { traverse(-1); },
  forward() { traverse(1); },
};
function traverse(delta) {
  if (!entries[entry + delta]) return;
  location.hash = entries[entry += delta].hash;
  ctx.applyRoute({});
}
const panes = ["log", "schedule", "series"].map((id) =>
  elements[`#tab-${id}`] = node({ id: `tab-${id}`, hidden: id !== "log" }));
const strip = $("#con-running"), classes = new Set();
let scroll = () => {}, resize = () => {};
Object.assign(strip, { scrollLeft: 0, scrollWidth: 800, clientWidth: 300,
  addEventListener: (event, listener) => { if (event === "scroll") scroll = listener; },
  classList: { toggle: (name, on) => on ? classes.add(name) : classes.delete(name) },
});
const ctx = { $, innerWidth: 1000, history: historyStack, location, el: (tag, props) => node(props),
  CSS: { supports: () => process.argv[3] !== "chip-overflow" },
  ResizeObserver: class { constructor(callback) { resize = callback; } observe() {} },
  document: Object.assign(doc, { getElementById: (id) => elements[`#${id}`], querySelectorAll: (s) => ({
    ".con-views [data-con-view]": buttons, "#con-running .chip": $("#con-running").children,
    "#con .crow": [...$("#runs-live").children, ...$("#runs-history").children],
    "#tab-log .con-filters button": filters, "main > section": panes,
  })[s] || [] }), glideBars() {}, emptyHistory: () => node(),
  scrollTo() {}, focusHeading: (heading) => heading.focus(), getComputedStyle: () => ({ scrollPaddingInlineEnd: "0px" }),
  itemRow: (item) => node({ item, dataset: { hk: `row:${ctx.keyOf(item)}` }, onclick: () => ctx.pickRun(ctx.keyOf(item)) }),
  renderDetail: (card) => { detail = card.id; }, renderJob: (job) => { detail = `job:${job.job}`; },
  nothingPicked: () => { detail = null; $("#cd-main").replaceChildren(); }, keepFocus: (_, draw) => draw(),
  loading: () => node({ className: "loading" }), renderDock() {}, failed: (textContent) => node({ textContent }),
  clearTimeout() {}, setTimeout() {}, activityLater() {}, forgetGoneRuns() {}, followLive() {},
  api: (path) => new Promise((resolve, reject) => { pending[path] = { resolve, reject }; }),
};
vm.createContext(ctx);
if (src.includes("function watchRunningChipEdge")) {
  vm.runInContext(grab("watchRunningChipEdge") + "\n" + line("syncRunningChipEdge"), ctx);
}
vm.runInContext(`let picked_run = null, runBackKey, landOnLive = false, conFilter = "all", runCards = [], runsShown = 50, runsSeq = 0, runsTimer, liveFeed;\n` +
  ["itemKey", "isLive", "isQueued"].map(line).join("\n") + "\n" +
  ["openActivity", "renderConsole", "drawRunningChips", "drawConsole", "jobsOf", "markPicked", "pickRun", "openActivityTool", "showStats"].map(grab).join("\n") +
  '\nthis.keyOf = itemKey;\n' + src.match(/^\$\("#con-stats"\)\.onclick = .*;$/m)[0] + "\n" +
  handler("con-downloads") + "\n" + src.match(/^\$\("#cd-back"\)\.onclick = .*?(?:\};|;)$/ms)[0], ctx);
const pressed = () => buttons.filter((b) => b.attrs["aria-pressed"] === "true").map((b) => b.dataset.conView);
const snapshot = () => [pressed(), $("#con-running").hidden, detail];
const addRuns = (cards, liveOnly = false) => {
  ctx.cards = cards;
  vm.runInContext(`runCards = cards; renderConsole(${liveOnly})`, ctx);
};
for (const name of ["recordActivityDetail", "syncActivityRoute", "closeActivityDetail"]) {
  if (src.includes(`function ${name}(`)) vm.runInContext(grab(name), ctx);
}
vm.runInContext("let activityDetail = null", ctx);
const navigation = require("fs").readFileSync(require("path").join(require("path").dirname(process.argv[1]), "navigation.js"), "utf8");
vm.runInContext("let routed = true, currentTab = 'log', current = null, termSocket = null;\n" +
  ["routeHash", "navigate", "parseRoute", "applyRoute", "showTab"].map((name) =>
    navigation.match(new RegExp(`^function ${name}\\b[\\s\\S]*?^}`, "m"))[0]).join("\n"), Object.assign(ctx, {
  HASH_OF: { log: "activity" }, TAB_OF: { activity: "log" }, inSettingsSec: () => false,
  updateTitle() {}, closeDetails() {}, cancelSettingsJump() {}, loadSchedule() {}, refreshLog() {}, syncInboxRoute: () => false,
}));
const active = { id: "live", series: "Show", sxxeyy: "S01E01", outcome: "running", step: "downloading", batch: "batch" };
const queued = { ...active, id: "queued", sxxeyy: "S01E02", waiting: true, step: "queued" };
const history = { id: "old", series: "Older", outcome: "downloaded" };
async function lateRuns(selection) {
  // On phones opening Activity from the menu would automatically open the first live download.
  ctx.innerWidth = 500;
  if (selection !== "stats") addRuns([active, history]); // Cached rows remain available during a refresh.
  vm.runInContext("landOnLive = true", ctx);
  const request = ctx.openActivity();
  if (selection === "stats") $("#con-stats").onclick();
  if (selection === "downloads") $("#con-downloads").onclick({ currentTarget: $("#con-downloads") });
  if (selection === "run") $("#runs-history").children[0].onclick();
  pending["/api/runs"].resolve([active, history]);
  await request;
  console.log(JSON.stringify([pressed(), detail]));
}
async function failedRuns(selection) {
  const request = ctx.openActivity();
  if (selection === "stats") $("#con-stats").onclick();
  else {
    const id = html.match(/id="cd-main"><div ([^>]+)/)[1].match(/\bid="([^"]+)"/)?.[1];
    $("#cd-main").replaceChildren(node({ className: "loading", id }));
  }
  const loader = $("#cd-main").children[0];
  pending["/api/runs"].reject(Error("network offline"));
  await request;
  console.log(JSON.stringify([pressed(), $("#cd-main").children[0] === loader, $("#runs-live").children[0].textContent]));
}
function switchViews() {
const states = [pressed()];
addRuns([queued, history]);
states.push(snapshot());
addRuns([active, queued, history]);
const chip = $("#con-running").children[0];
const chipCount = $("#con-running").childElementCount;
addRuns([{ ...active, live: { progress: 10 } }, queued, history], true);
const steady = chip === $("#con-running").children[0];
$("#con-stats").onclick();
states.push(snapshot());
$("#runs-history").children[0].onclick();
states.push(snapshot());
$("#con-stats").onclick();
$("#runs-live").children[0].onclick();
states.push(snapshot());
$("#runs-history").children[0].onclick();
chip.onclick();
states.push(snapshot(), chip.attrs["aria-current"]);
vm.runInContext('picked_run = "serve"; markPicked(picked_run); landOnLive = true; renderConsole()', ctx);
states.push(snapshot());
$("#con-downloads").onclick({ currentTarget: $("#con-downloads") });
states.push(snapshot());
addRuns([history]);
states.push($("#con-running").hidden);
console.log(JSON.stringify({ states, chipCount, steady }));
}
const scenario = process.argv[3];
if (scenario === "chip-overflow") {
  const cue = () => classes.has("more-chips");
  addRuns([active]);
  const atStart = cue();
  strip.scrollLeft = 500; scroll();
  const atEnd = cue();
  strip.scrollLeft = 0; scroll();
  const backAtStart = cue();
  strip.clientWidth = 800; resize();
  console.log(JSON.stringify([atStart, atEnd, backAtStart, cue()]));
}
else if (scenario === "mixed-history") {
  const cards = ["downloaded", "downloaded", "failed"].map((outcome, i) => ({
    ...history, batch: "mixed", id: `r${i}`, sxxeyy: `S01E0${i + 1}`, outcome,
  }));
  addRuns([...cards, active, { ...queued, outcome: "downloaded" }]);
  const counts = filters.map((b) => b.count.textContent);
  const rows = ["downloaded", "failed"].map((filter) => {
    ctx.filter = filter;
    vm.runInContext("conFilter = filter; renderConsole()", ctx);
    return $("#runs-history").children.map(({ item }) => item?.cards?.map((c) => c.outcome) || [item?.outcome]);
  });
  console.log(JSON.stringify([counts, rows]));
}
else if (scenario === "fail-stats" || scenario === "fail-downloads") failedRuns(scenario.slice(5));
else if (scenario === "back-to-chip") {
  ctx.innerWidth = 500;
  addRuns([active, history]);
  const chip = strip.children[0], back = $("#cd-back");
  chip.onclick();
  const opened = detail;
  back.focus();
  back.onclick();
  console.log(JSON.stringify([opened, detail, doc.activeElement === chip]));
}
else if (scenario === "phone-history") {
  ctx.innerWidth = 390;
  addRuns([active, history]);
  const row = () => $("#runs-history").children[0];
  row().onclick();
  const opened = detail;
  historyStack.back();
  const browserBack = [detail, doc.activeElement === row()];
  historyStack.forward();
  const browserForward = detail;
  $("#cd-back").onclick();
  const buttonBack = [detail, doc.activeElement === row()];
  $("#con-stats").onclick();
  const stats = pressed();
  historyStack.back();
  console.log(JSON.stringify([opened, browserBack, browserForward, buttonBack, stats, pressed(), doc.activeElement === $("#con-stats")]));
}
else if (scenario === "reload-stats") {
  ctx.innerWidth = 390;
  $("#con-stats").onclick();
  vm.runInContext("routed = false; picked_run = activityDetail = null", ctx);
  addRuns([]);
  ctx.applyRoute();
  const reloaded = pressed();
  historyStack.back();
  console.log(JSON.stringify([reloaded, pressed(), doc.activeElement === $("#con-stats")]));
}
else if (scenario === "reenter-activity") {
  ctx.innerWidth = Number(process.argv[4]);
  addRuns([history]);
  $("#runs-history").children[0].onclick();
  const opened = detail;
  ctx.showTab("schedule");
  ctx.showTab("log");
  const reentered = [detail, historyStack.state];
  historyStack.back();
  const back = location.hash;
  historyStack.back();
  console.log(JSON.stringify([opened, reentered, back, location.hash, detail]));
}
else if (scenario === "downloads-width") {
  addRuns([active, history]);
  $("#runs-history").children[0].onclick();
  const downloads = $("#con-downloads"), list = $("#runs-history"), row = list.children[0];
  const state = () => [detail, downloads.getAttribute("aria-pressed"), list.children[0] === row];
  const before = state();
  const click = () => downloads.onclick({ currentTarget: downloads });
  click();
  const wide = state();
  ctx.innerWidth = 500;
  click();
  console.log(JSON.stringify([before, wide, state()]));
}
else if (scenario) lateRuns(scenario);
else switchViews();
"""


def switcher(*args):
    return node(SWITCHER, str(JS / "activity.js"), str(JS.parent / "index.html"), *args)


def test_running_strip_keeps_overflow_cue_without_scroll_timeline():
    assert switcher("chip-overflow") == [True, False, True, False]
    css = load_css()
    assert re.search(r"@supports not \(animation-timeline: scroll\(\)\)\s*\{\s*"
                     r"\.con-running\.more-chips\s*\{[^}]*mask-image:", css)


def test_switcher_follows_run_selection_and_only_shows_chips_for_running_downloads():
    shown = switcher()
    assert shown == {
        "chipCount": 1,
        "steady": True,
        "states": [
            ["downloads"], [["downloads"], True, "queued"], [["stats"], True, "queued"],
            [["downloads"], False, "old"], [["downloads"], False, "job:batch"],
            [["downloads"], False, "job:batch"], "true", [[], True, "job:batch"],
            [["downloads"], False, "job:batch"], True,
        ],
    }


@pytest.mark.parametrize(("selection", "expected"), [
    ("stats", [["stats"], None]),
    ("downloads", [["downloads"], None]),
    ("run", [["downloads"], "old"]),
])
def test_pending_runs_do_not_override_an_explicit_selection(selection, expected):
    assert switcher(selection) == expected


def test_failed_runs_leave_a_pending_tool_loader_in_place():
    assert switcher("fail-stats") == [["stats"], True, "Could not load the downloads: network offline"]
    assert switcher("fail-downloads") == [["downloads"], False, "Could not load the downloads: network offline"]


def test_history_outcomes_count_and_keep_whole_jobs_without_running_jobs():
    mixed = ["downloaded", "downloaded", "failed"]
    assert switcher("mixed-history") == [["(1)", "(1)", "(1)", "(0)", "(0)"], [[mixed], [mixed]]]


def test_back_from_a_running_download_returns_focus_to_its_chip():
    assert switcher("back-to-chip") == ["live", None, True]


def test_phone_activity_browser_and_in_app_back_restore_the_list_and_opener():
    assert switcher("phone-history") == ["old", [None, True], "old", [None, True], ["stats"], ["downloads"], True]


def test_phone_activity_reload_restores_stats_before_browser_back():
    assert switcher("reload-stats") == [["stats"], ["downloads"], True]


def test_reentering_activity_from_schedule_uses_the_destination_detail():
    assert switcher("reenter-activity", "390") == ["old", [None, None], "#/schedule", "#/activity", "old"]


def test_reentering_wide_activity_keeps_the_side_by_side_run_selection():
    assert switcher("reenter-activity", "1440") == ["old", ["old", None], "#/schedule", "#/activity", "old"]


def test_pressed_downloads_keeps_wide_detail_but_returns_to_the_narrow_list():
    assert switcher("downloads-width") == [["old", "true", True], ["old", "true", True], [None, "true", False]]


def test_late_languages_error_does_not_replace_stats_content():
    assert node(PANES, str(JS / "activity.js"), '["languages", "stats"]') == {
        "title": "Stats", "heading": "Stats", "unchanged": True,
    }


@pytest.mark.parametrize("suggestions", [{"2": {"service": "SBS", "count": 8}}, {}])
@pytest.mark.parametrize("failure", [False, True])
def test_series_refresh_displays_new_search_before_a_slower_saved_result(suggestions, failure):
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8"), suggestions = JSON.parse(process.argv[2]);
const failure = JSON.parse(process.argv[3]), errors = [];
const s = { tvdbId: 1, id: 10, title: "Show" }, stub = { replaceChildren() {}, setAttribute() {}, removeAttribute() {} };
let rendered;
const pages = Object.fromEntries(Array.from({length: 10}, (_, i) => [i + 1, {url: `https://iview/season-${i + 1}`} ]));
const ctx = { S: { services: ["IV", "SBS", "NF"], config: { series: { 1: {season_pages: pages} } } }, current: s, epElsewhere: { 3: { service: "NF" } }, epElsewhereFresh: false,
  $: () => stub, el: () => ({}), seriesSvcs: () => "IV", slowHint: () => 0, clearTimeout() {},
  api: async (path, opts) => {
    if (opts.wait < 1100) throw Error("No answer before slow season pages and services finish");
    return { elsewhere: suggestions, elsewhere_error: failure ? "Search failed" : undefined, available: {}, checked: "2026-11-13T02:00:00Z" };
  },
  viewAvail: (x) => x, localTitles() {}, renderSeason: () => { rendered = ctx.epElsewhere; },
  renderPreview() {}, renderCatchUp() {}, checkLabel() {}, renderSeriesLanguage() {}, toast: (message) => { errors.push(message); } };
vm.createContext(ctx);
vm.runInContext(src.match(/async function askService\b[\s\S]*?\n}\n/)[0], ctx);
(async () => {
  await ctx.askService(s);
  const cache = src.match(/api\(`\/api\/probe\/\$\{s.tvdbId\}`\)\.then\((\(hit\) => \{[\s\S]*?)\n    }\)\.catch/)[1] + "\n}";
  ctx.s = s;
  vm.runInContext(`(${cache})({elsewhere: {4: {service: "STAN"}}, checked: "2026-11-13T03:00:00Z", elsewhere_checked: "2026-11-12T02:00:00Z"})`, ctx);
  console.log(JSON.stringify({ rendered, kept: ctx.epElsewhere, errors }));
})();
""", str(JS / "series.js"), json.dumps(suggestions), json.dumps(failure))
    assert shown == {"rendered": suggestions, "kept": suggestions,
                     "errors": ["Availability refreshed, but the search on other services failed: Search failed"] if failure else []}


@pytest.mark.parametrize("on_service", ["none", "future", "aired"])
def test_other_service_suggestions_are_visible_when_every_aired_episode_is_on_disk(on_service):
    shown = node(r"""
const fs = require("fs"), vm = require("vm"), src = fs.readFileSync(process.argv[1], "utf8");
const box = { hidden: true, classList: {toggle() {}}, replaceChildren(...kids) { this.kids = kids; } };
const onService = process.argv[2];
const ctx = { $: () => box, svcName: (tag) => tag, COUNT: { episode: (n) => n === 1 ? "1 episode" : `${n} episodes`, upgrade: (n) => `${n}`, missingEpisode: (n) => `${n}` }, current: {tvdbId: 1}, S: {config: {series: {1: {service: "BINGE"}}}},
  epSeasons: {7: [{id: 1, seasonNumber: 7, hasFile: true, sonarrAir: "2000-01-01T00:00:00Z"}, {id: 2, seasonNumber: 7, hasFile: false, sonarrAir: "2999-01-01T00:00:00Z"}]},
  epAvail: onService === "none" ? {} : {[onService === "aired" ? 1 : 2]: {service: "S07E01"}}, epBusy: new Map(), epPages: {}, epElsewhere: {7: {service: "NINE", count: 5, url: "https://9now/paramedics"}},
  state: (e) => e.hasFile ? "disk" : "soon", belowAsked: () => false, seriesSvcs: () => "BINGE", seasonSvc: () => "BINGE",
  document: {querySelectorAll: () => []}, el: (tag, props = {}, ...kids) => ({tag, ...props, kids}) };
vm.createContext(ctx);
vm.runInContext(src.match(/function renderCatchUp\b[\s\S]*?\n}\n/)[0], ctx);
ctx.renderCatchUp();
console.log(JSON.stringify({hidden: box.hidden, content: JSON.stringify(box.kids || [])}));
""", str(JS / "series.js"), on_service)
    assert shown["hidden"] is (on_service == "aired")
    assert ("Season 7 is on NINE (5 episodes)" in shown["content"]) is (on_service != "aired")


@pytest.mark.parametrize("first,second,heading", [("stats", "left", "Waiting in downloads"), ("left", "stats", "Stats")])
def test_a_late_answer_does_not_fill_the_pane_of_the_one_picked_since(first, second, heading):
    shown = node(PANES, str(JS / "activity.js"), json.dumps([first, second]))
    assert shown == {"title": heading, "heading": heading}


def test_terminal_says_so_when_it_closes_before_any_output():
    written = node(TERMINAL, str(JS / "attempts.js"), "silent")
    assert len(written) == 1 and "WebSocket" in written[0]


def test_terminal_stays_quiet_when_it_closes_after_output():
    assert node(TERMINAL, str(JS / "attempts.js"), "output first") == ["output"]


def test_terminal_stays_quiet_when_the_server_ends_it_cleanly_with_no_output():
    assert node(TERMINAL, str(JS / "attempts.js"), "clean") == []  # a cancelled episode has no log


def test_terminal_ignores_the_close_of_a_socket_it_already_replaced():
    assert node(TERMINAL, str(JS / "attempts.js"), "replaced") == []


def test_opening_languages_clears_the_dock_of_the_download_shown_before():
    # The dock's Stop, Retry and Pause act on the download it was drawn for: Languages is no download
    shown = node(r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const grab = (name) => src.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}\\n`))[0];
const docks = [];
const stub = { textContent: "", hidden: false, classList: { add() {} }, replaceChildren() {} };
const ctx = { $: () => stub, document: { querySelectorAll: () => [] }, api: () => new Promise(() => {}),
  renderDock: (d) => docks.push(d), clearTimeout() {} };
vm.createContext(ctx);
vm.runInContext(`var picked_run = null, langTimer = null, langLast = null;\n${grab("markPicked")}\n${grab("showLanguages")}`, ctx);
ctx.showLanguages();
console.log(JSON.stringify(docks));
""", str(JS / "activity.js"))
    assert shown == [None]
