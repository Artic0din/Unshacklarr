/* Services: each service's sign-in, cookie files and series on one page, and what the sign-in status adds up to. */
const AUTH_METHOD_LABELS = { pairing: "pairing", cookies: "cookies", credentials: "credentials" };
const AUTH_METHOD_NAMES = { pairing: "Pairing", cookies: "Cookies", credentials: "Credentials" };
const AUTH_FAILURE_LABELS = { authentication_rejected: "authentication rejected", entitlement: "entitlement", region: "region", concurrency: "concurrency", network: "network", manifest: "manifest", drm: "DRM", licence: "licence", application: "application" };
function authenticationLabel(observation) {
  if (!observation) return "Not checked yet";
  const method = AUTH_METHOD_LABELS[observation.method] || "sign-in";
  const next = AUTH_METHOD_LABELS[observation.next_method] || "sign-in";
  const named = method[0].toUpperCase() + method.slice(1);
  if (observation.state === "ready") return "Not signed in";  // no session now (not "yet": it may have been before)
  if (observation.state === "session_present") return `${named} session available`;
  if (observation.state === "session_expired") return `${named} session expired`;
  if (observation.state === "session_rejected") return `${named} session rejected`;
  if (observation.state === "renewing") return `Renewing ${method} session`;
  if (observation.state === "repairing") return `Repairing ${method} session`;
  if (observation.state === "fallback") return observation.failure === "authentication_rejected"
    ? `${named} rejected · trying ${next}`
    : `${named} failed · ${AUTH_FAILURE_LABELS[observation.failure] || "application"} · trying ${next}`;
  if (observation.state === "waiting") return `Waiting for ${method} approval`;
  if (observation.state === "authenticated") return `Signed in with ${method}`;
  if (observation.state === "timed_out") return `${named} timed out`;
  if (observation.state === "cancelled") return "Sign-in cancelled";
  if (observation.state === "error") return `Sign-in failed · ${AUTH_FAILURE_LABELS[observation.failure] || "application"}`;
  if (observation.state === "authenticating") return "Signing in";
  return "Not checked yet";
}

async function startServiceAuthentication(service, backend = "") {
  try {
    const setup = await api(`/api/unshackle/authentication/${encodeURIComponent(service)}`, {
      method: "POST", body: JSON.stringify({ backend }),
    });
    S.authenticationSetups = [...(S.authenticationSetups || []).filter((item) => item.service !== service || item.backend !== backend), setup];
    renderServices();
  } catch (error) { toast(error.message, true); }
}

async function cancelServiceAuthentication(service, backend = "") {
  try {
    const setup = await api(`/api/unshackle/authentication/${encodeURIComponent(service)}`, {
      method: "DELETE", body: JSON.stringify({ backend }),
    });
    S.authenticationSetups = [...(S.authenticationSetups || []).filter((item) => item.service !== service || item.backend !== backend), setup];
    renderServices();
  } catch (error) { toast(error.message, true); }
}

async function answerServiceAuthentication(service, backend, field) {
  if (!field.value) return;
  const response = field.value;
  field.value = "";
  try {
    await api(`/api/unshackle/authentication/${encodeURIComponent(service)}/input`, {
      method: "POST", body: JSON.stringify({ backend, response }),
    });
  } catch (error) { toast(error.message, true); }
}

/* What the sign-in status says, in counts: ready is confirmed or needing no login; the rest has not been checked. */
function signInCounts(authentication) {
  const states = Object.values(authentication || {}).map((status) => status.state);
  const confirmed = states.filter((state) => state === "validated" || state === "anonymous").length;
  const needs = states.filter((state) => state === "needs_user_action").length;
  return { confirmed, needs, unchecked: states.length - confirmed - needs, total: states.length };
}
function signInSummary(counts) {
  return [
    counts.confirmed === 1 ? "1 service confirmed" : counts.confirmed ? `${counts.confirmed} services confirmed` : "",
    counts.needs === 1 ? "1 needs sign-in" : counts.needs ? `${counts.needs} need sign-in` : "",
    counts.unchecked ? `${counts.unchecked} not checked yet` : "",
  ].filter(Boolean).join(" · ");
}
/* The setup's last screen: what the sign-in status says once its session exists. It never holds up finishing. */
function signInCheck() {
  const box = el("div", { className: "wz-signin", ariaLive: "polite" }, loading("Checking the sign-ins…"));
  const review = el("button", { type: "button", className: "btn small", textContent: "Review services",
    onclick: () => { location.hash = "#/settings/services"; location.reload(); } });
  api("/api/status?auth=1").then((status) => {
    const counts = signInCounts(status.authentication);
    if (status.unshackle?.ok === false) return box.replaceChildren(el("p", { textContent: "The sign-in check could not reach Unshackle." }), review);
    if (!counts.total) return box.replaceChildren();
    box.replaceChildren(el("p", { textContent: signInSummary(counts) }), review);
  }, () => box.replaceChildren(el("p", { textContent: "The sign-ins could not be checked." }), review));
  return box;
}

const CHECK_STAGES = { search: "Search", list: "Listing", tracks: "Tracks" };
const SERVICE_COLUMNS = ["Service", "Sign-in status", "Cookies", "Used by"];
let servicesCookies = null;  // /api/cookies: the files of Unshackle's own cookies folder, by service
let servicesDrawn = "";      // what the table was drawn from: a refresh that changes nothing leaves it (and the focus) alone
let servicesAsked = "";      // the cookie file whose deletion is being confirmed: "SERVICE/profile"

// a sign-in that ended badly (cancelled is your own doing; waiting and renewing are under way)
const SIGN_IN_FAILED = ["session_expired", "session_rejected", "fallback", "timed_out", "error"];
/* One row a service, or a service and its backend: the sign-in status, setups and live logins, and the cookie files, joined. */
function serviceModels() {
  const files = servicesCookies?.files || {};
  const identities = new Map();
  const add = (service, backend, status) => { const key = backend ? `${service}@${backend}` : service; if (!identities.has(key)) identities.set(key, { key, service, backend, status }); };
  Object.entries(S.authentication || {}).forEach(([tag, status]) => add(status.service || tag.split("@")[0], status.backend || "", status));
  (S.authenticationSetups || []).forEach((setup) => add(setup.service, setup.backend || "", { state: "unknown" }));
  Object.keys(files).forEach((tag) => add(tag, "", { state: "unknown" }));
  const seriesOf = (service) => Object.values(S.config.series || {})
    .filter((c) => usesService(c, service)).length;
  return [...identities.values()].map(({ key, service, backend, status }) => {
    const setup = (S.authenticationSetups || []).find((item) => item.service === service && (item.backend || "") === backend) || null;
    const live = (S.authenticationLive || []).find((item) => item.service === service && (item.backend || "") === backend);
    const listed = Object.hasOwn(S.authenticationMethods || {}, key);
    const methods = listed ? S.authenticationMethods[key] : [];
    // nothing seen yet: "Not checked yet", not a "ready" of our own, which would say no session exists (cookies may work)
    const observation = setup || live?.observation || status.authentication || null;
    const label = status.state === "anonymous" ? "No sign-in required"
      : observation ? authenticationLabel(observation)
      : status.state === "needs_user_action" ? "Sign-in needed"
      : status.state === "validated" ? `Confirmed ${ago(status.validated_at)}` : "Not checked yet";
    // signed in now, or confirmed and nothing newer says otherwise: its button signs in again, not for the first time
    const signedIn = observation ? ["authenticated", "session_present"].includes(observation.state) : status.state === "validated";
    const tone = status.state === "needs_user_action" || SIGN_IN_FAILED.includes(observation?.state) ? "bad" : signedIn ? "ok" : "";
    // a cookie-only sign-in only tests the cookie file (Unshackle saves nothing back): its button is the Cookies column's Check
    const cookiesOnly = listed && methods.length === 1 && methods[0] === "cookies";
    // Cookie files are Unshackle's own, on the main server: another backend's row has none to show
    const cookieFiles = backend ? null : (files[service] || []).map((f) => ({ ...f, st: cookieStatus(f) }));
    // the backend that downloads it: the one set for it, else the main one, else (only on another server) that one
    // from the live service list (as the download's backend is picked), not old sign-in records or cookie files
    const inventory = Object.keys(S.authenticationMethods || {}), set = S.config.service_defaults?.[service]?.backend || "";
    const selected = set && inventory.includes(`${service}@${set}`) ? set
      : inventory.includes(service) ? "" : (inventory.find((k) => k.startsWith(`${service}@`)) || "").split("@")[1] || "";
    const used = backend === selected ? seriesOf(service) : null;
    // the daily check runs on the backend that downloads it; a service only a fallback uses counts no series, yet is
    // checked; one no series uses any more keeps no result to show (the next run drops it)
    const checked = backend === selected && Object.values(S.config.series || {}).some((c) => usesService(c, service) || c?.fallback?.service === service);
    const kept = checked ? S.serviceChecks?.services?.[service] || null : null;
    const check = kept && (kept.backend || "") === backend ? kept : null;  // not one kept from the backend it was on before
    const cookieless = status.state === "anonymous" || (listed && methods.length > 0 && !methods.includes("cookies"));  // an empty list: not known
    // no cookie file is fine when none is needed, or a confirmed sign-in has another way in (credentials,
    // pairing): a cookie-only service confirmed before its last file went still needs one
    const used_method = status.authentication?.method;  // the method that signed in, when recorded
    const signsInWithout = status.state === "anonymous" || (status.state === "validated"
      && (used_method ? used_method !== "cookies" : listed && methods.some((m) => m !== "cookies")));
    const missing = Boolean(cookieFiles && !cookieFiles.length && !cookieless && used && servicesCookies?.folder && !signsInWithout);
    // the one test of "needs attention": the rows, the count above them, the Settings badge and a failing series' banner
    const attention = status.state === "needs_user_action" || SIGN_IN_FAILED.includes(observation?.state)
      || Boolean(used && (missing || cookieFiles?.some((f) => f.st[0] === "bad")));
    return { key, service, backend, name: svcName(service) + (backend ? ` · ${backend}` : ""), label, tone, state: status.state, signedIn, cookiesOnly, setup, listed,
      methods: listed ? methods : null, cookieFiles, cookieless, missing, used, attention, check };
  }).sort((a, b) => b.attention - a.attention || (b.used || 0) - (a.used || 0) || a.name.localeCompare(b.name));
}

function renderServices() {
  const box = $("#sv-list");
  if (!box) return;
  const models = serviceModels(), cookies = servicesCookies;
  const signature = JSON.stringify([models, cookies?.folder, cookies?.error, cookies?.unwritable, servicesAsked]);
  if (signature === servicesDrawn) return revealService();
  servicesDrawn = signature;
  const activePrompt = document.activeElement?.dataset?.authenticationService ? document.activeElement : null;
  let activePromptReused = false;

  // Leave maintenance actions secondary if there is a more direct way to sign in.
  const priority = { signIn: 0, repair: 1, renew: 2, check: 3, maintenance: 4 };
  const signInCell = (m, prefer) => {
    const controls = [];
    if (m.setup) {
      if (["timed_out", "cancelled", "error"].includes(m.setup.state)) {
        if (m.listed && !m.cookiesOnly) controls.push(prefer(priority.signIn, el("button", { className: "btn small", textContent: "Retry", onclick: () => startServiceAuthentication(m.service, m.backend) })));
      } else if (m.setup.prompt) {
        const reusePrompt = activePrompt?.dataset.authenticationService === m.service
          && activePrompt.dataset.authenticationBackend === m.backend && activePrompt.placeholder === m.setup.prompt;
        const input = reusePrompt ? activePrompt : el("input", { type: "text", ariaLabel: m.setup.prompt, placeholder: m.setup.prompt,
          autocomplete: "one-time-code", dataset: { authenticationService: m.service, authenticationBackend: m.backend } });
        activePromptReused ||= reusePrompt;
        controls.push(input, prefer(priority.signIn, el("button", { className: "btn small", textContent: "Submit", onclick: () => answerServiceAuthentication(m.service, m.backend, input) })));
      }
      if (!["authenticated", "timed_out", "cancelled"].includes(m.setup.state)) {
        controls.push(el("button", { className: "btn small", textContent: "Cancel", onclick: () => cancelServiceAuthentication(m.service, m.backend) }));
      }
    } else if (m.listed && m.state !== "anonymous" && !m.cookiesOnly) {
      controls.push(prefer(priority.signIn, el("button", { className: "btn small", textContent: m.signedIn || m.state === "needs_user_action" ? "Sign in again" : "Sign in",
        onclick: () => startServiceAuthentication(m.service, m.backend) })));
    }
    return [el("div", { className: "sv-signin" }, el("small", { className: "sv-label", textContent: m.label, dataset: m.tone ? { tone: m.tone } : {} }),
      ...(controls.length ? [el("div", { className: "sv-ctl" }, ...controls)] : [])), ...checkLines(m)];
  };
  // the daily check (servicecheck.py): its result, the stages that failed, and what the search found (shown, never alerted)
  const checkLines = (m) => {
    const done = m.check;
    if (!done) return m.used ? [el("small", { className: "sv-check", textContent: "Daily check: not run yet" })] : [];
    if (done.skipped) return [el("small", { className: "sv-check", textContent: done.skipped === "programmes"
      ? "Daily check skipped: its programmes are found one episode at a time" : "Daily check skipped: relayed through another server" })];
    const signIn = Object.values(done.stages).some((stage) => stage.code === "AUTH_FAILED"), when = ago(done.checked), search = done.stages.search;
    return [el("small", { className: "sv-check", dataset: done.ok ? {} : { tone: "bad" },
        textContent: done.ok ? `Daily check passed ${when}` : signIn ? `Daily check: sign-in failed ${when}` : `Daily check failed ${when}` }),
      ...done.failed.map((stage) => el("small", { className: "sv-check", textContent: `${CHECK_STAGES[stage]}: ${done.stages[stage].message}` })),
      ...(search.ok ? [el("small", { className: "sv-check", textContent: search.found ? `Search results: ${search.count}` : `Search results: ${search.count}, series not among them` })] : [])];
  };
  // a cookie-only service's sign-in check, in the Cookies column; none while a check runs
  const checking = (m) => m.setup && !["authenticated", "timed_out", "cancelled", "error"].includes(m.setup.state);

  const cookieCell = (m, prefer) => {
    const checkButtons = () => m.cookiesOnly && m.state !== "anonymous" && !checking(m) ? [prefer(priority.check, el("button", { className: "btn small", textContent: "Check",
      ariaLabel: `Check the cookies for ${svcName(m.service)}`, onclick: () => startServiceAuthentication(m.service, m.backend) }))] : [];
    const checkCtl = () => {
      const buttons = checkButtons();
      return buttons.length ? [el("div", { className: "sv-ctl" }, ...buttons)] : [];
    };
    if (m.backend) return [el("span", { className: "muted", textContent: "—" }), el("small", { textContent: "Managed on that server" }), ...checkCtl()];
    if (!cookies?.folder) return [el("span", { className: "muted", textContent: "—" }), ...checkCtl()];
    if (!m.cookieFiles.length) {
      if (m.cookieless) return [el("span", { className: "muted", textContent: "Not needed" })];
      const both = m.methods === null || m.methods.includes("credentials");
      const pill = el("span", { className: `ck-pill ${m.missing ? "bad" : "absent"}`, textContent: m.missing ? "Missing" : "No cookie file" });
      return [el("div", { className: "sv-file" },
        el("div", { className: "sv-file-top" }, m.missing ? hoverTip(pill, () => [both ? "Downloads will fail unless you add a cookie file, or set its username and password in unshackle.yaml."
          : "Downloads will fail unless you add a cookie file."]) : pill),
        el("div", { className: "sv-ctl" }, prefer(m.missing ? priority.repair : priority.maintenance, el("button", { className: "btn small", textContent: "Add", ariaLabel: `Add cookies for ${svcName(m.service)}`,
          onclick: () => openCookieDialog(m.service, "default", true) }))))];
    }
    // the check signs in with the profile its series use, not a file picked here: beside the only file, else under them all
    const single = m.cookieFiles.length === 1, working = m.cookieFiles.some((f) => f.st[0] !== "bad");  // a broken file: Replace, not a check bound to fail
    const checkOn = single && working ? 0 : -1;
    return [...m.cookieFiles.map((f, i) => {
      const [cls, word, why] = f.st, file = f.profile ? `${f.profile}.txt` : `${m.service}.txt`, ask = `${m.service}/${f.profile}`;
      const del = el("button", { className: "btn small danger", textContent: "Delete", ariaLabel: `Delete ${file}`, dataset: { ask }, onclick: () => {
        servicesAsked = ask;
        renderServices();
        document.querySelector(".sv-confirm .btn:not(.danger)")?.focus();
      } });
      const sure = el("div", { className: "sv-confirm", role: "group", ariaLabel: `Delete ${file}` },
        el("span", { textContent: `Delete ${file} from Unshackle's cookies folder?` }),
        el("div", { className: "sv-ctl" },
          el("button", { className: "btn small", textContent: "Cancel", onclick: () => { servicesAsked = ""; renderServices(); document.querySelector(`[data-ask="${ask}"]`)?.focus(); } }),
          el("button", { className: "btn small danger", textContent: `Delete ${file}`, onclick: async () => {
            try { await api("/api/cookies/delete", { method: "POST", body: JSON.stringify({ service: m.service, profile: f.profile }) }); servicesAsked = ""; loadServices(); }
            catch (e) { toast(e.message, true); }
          } })));
      return el("div", { className: "sv-file" },
        el("div", { className: "sv-file-top" }, el("b", { textContent: file }), hoverTip(el("span", { className: `ck-pill ${cls}`, textContent: word }), () => [why])),
        ...(f.unreadable ? [] : [el("small", { textContent: [f.count === 1 ? "1 cookie" : `${f.count} cookies`, `updated ${ago_days(f.updated)}`].join(" · ") })]),
        ...(servicesAsked === ask ? [sure] : [el("div", { className: "sv-ctl" }, ...(i === checkOn ? checkButtons() : []),
          prefer(cls === "bad" ? priority.repair : cls === "warn" ? priority.renew : priority.maintenance,
            el("button", { className: "btn small", textContent: "Replace", ariaLabel: `Replace ${file}`, onclick: () => openCookieDialog(m.service, f.profile) })), del)]));
    }), ...(!single && working ? checkCtl() : [])];
  };

  // the count, and the series behind it: "Show series" sits with what it shows, not under a column of its own
  const usedCell = (m) => [el("span", { className: m.used === null ? "muted" : "", textContent: m.used === null ? "—" : m.used === 0 ? "No series" : m.used === 1 ? "1 series" : `${m.used} series` }),
    ...(m.used ? [el("div", { className: "sv-ctl" }, el("button", { className: "btn small", textContent: "Show series", onclick: () => showSeriesOf(m.service) }))] : [])];

  const row = (m) => {
    const actions = [];
    const prefer = (rank, button) => { actions[rank] ||= button; return button; };
    const cells = [signInCell(m, prefer), cookieCell(m, prefer), usedCell(m)];
    // lime only where something is wrong (the row needs attention, or a cookie file is bad or expiring): healthy rows stay quiet
    const first = actions.findIndex(Boolean);
    if (first >= 0 && (m.attention || first === priority.repair || first === priority.renew)) actions[first].className += " primary";
    return el("tr", { role: "row", className: "sv-row", tabIndex: -1,
      dataset: { fk: `sv-${m.key}`, ...(m.attention ? { attention: "true" } : {}) }, id: `sv-${m.key}` },
      el("th", { role: "rowheader", scope: "row" },
        el("b", { className: "sv-name", textContent: svcName(m.service) }),
        ...(m.backend ? [el("small", { className: "sv-backend", textContent: m.backend })] : []),
        ...(m.methods?.length ? [el("div", { className: "sv-chips", role: "group", ariaLabel: "Signs in with" },
          ...m.methods.map((x) => el("span", { className: "sv-chip", textContent: AUTH_METHOD_NAMES[x] || x })))] : [])),
      ...cells.map((children, i) => el("td", { role: "cell" }, el("span", { className: "sv-k", textContent: SERVICE_COLUMNS[i + 1] }), ...children)));
  };
  // Keep the table semantics when narrow layouts change the cells' display.
  const table = el("table", { role: "table", className: "sv-table" },
    el("thead", {}, el("tr", {}, ...SERVICE_COLUMNS.map((name) => el("th", { scope: "col", textContent: name })))),
    el("tbody", { role: "rowgroup" }, ...models.map(row)));
  // Files Unshackle can't write (owned by root after a docker exec): a service then fails on a cache or token it can't save
  const locked = cookies?.unwritable?.length ? [el("div", { className: "sv-locked" },
    el("p", { className: "status-err", textContent: "Unshackle can't write these files. Give them back to the container's user, for example with chown." }),
    el("ul", { className: "ck-locked" }, ...cookies.unwritable.map((path) => el("li", {}, el("code", { textContent: path })))))] : [];
  const active = document.activeElement;
  const focusedRow = active?.matches?.(".sv-row") && box.contains(active) ? active : null;
  const rowPosition = focusedRow?.getBoundingClientRect();
  const draw = () => box.replaceChildren(...locked, ...(models.length ? [table] : [el("p", { className: "muted", textContent: "No service is known yet. Unshackle lists them once it answers." })]));
  if (focusedRow) keepFocus(box, draw); else draw();
  if (activePromptReused) activePrompt.focus();

  // The top of the page: the cookies folder, and what the statuses add up to
  const needing = models.filter((m) => m.attention), counts = signInCounts(S.authentication), summary = signInSummary(counts);
  const state = $("#sv-state");
  state.className = `sx-state ${needing.length ? "down" : counts.confirmed ? "ok" : ""}`;
  state.querySelector("b").textContent = needing.length ? needingText(needing.length) : summary || "No service known yet";
  state.querySelector("small").textContent = needing.map((m) => m.name).join(", ");  // which ones: the count's own rows, by name
  paintServicesBadge(needing.length);
  $("#sv-folder").textContent = cookies?.folder || "";
  $("#sv-note").textContent = !cookies ? "" : cookies.folder ? ""
    : S.config.settings.unshackle_mode === "remote" ? "To manage them here too, mount its Cookies folder and set its path in Settings › Connections › Unshackle, Folders."
    : cookies.error || "";
  // A refresh can reorder the focused row without changing the user's place in it.
  if (rowPosition && rowPosition.bottom > 0 && rowPosition.top < innerHeight && document.activeElement.id === focusedRow.id) {
    scrollBy({ top: document.activeElement.getBoundingClientRect().top - rowPosition.top });
  }
  revealService();
}
let servicesCookiesAsked = null;  // the cookie files read once for the badge, before Services is opened
/* An expired or missing cookie file needs attention too: the Settings badge reads them from any page, once. */
function loadServiceCookies() {
  return servicesCookiesAsked ||= api("/api/cookies").then((cookies) => { servicesCookies ??= cookies; }, () => {}).then(() => paintServicesBadge());
}
function needingText(n) { return n === 1 ? "1 service needs attention" : `${n} services need attention`; }
/* The count of the rows that need attention, beside Services in the Settings list, from any page. */
function paintServicesBadge(n = serviceModels().filter((m) => m.attention).length) {
  const nav = document.querySelector('.set-nav [data-sec="services-devices"]');
  if (!nav) return;
  nav.querySelector(":scope > .sv-attn")?.remove();
  if (n) nav.querySelector(":scope > span").after(el("b", { className: "ck-pill bad sv-attn", textContent: String(n), title: needingText(n) }));
}
function serviceRow({ service, backend = S.config.service_defaults?.[service]?.backend }) {
  return (backend && document.getElementById(`sv-${service}@${backend}`)) || document.getElementById(`sv-${service}`)
    || document.querySelector(`[id^="sv-${CSS.escape(service)}@"]`);
}
function revealService() {
  if (settingsJump?.ready && settingsJump.target?.service) applySettingsJump(settingsJump);
}
async function loadServices() {
  if (!servicesDrawn) $("#sv-list").replaceChildren(loading("Checking the services…"));
  const [status, cookies, checks] = await Promise.allSettled([api("/api/status?auth=1"), api("/api/cookies"), api("/api/service-checks")]);
  if (checks.status === "fulfilled") S.serviceChecks = checks.value;
  if (status.status === "fulfilled") renderHealth(status.value);
  servicesCookies = cookies.status === "fulfilled" ? cookies.value : { folder: null, files: {}, error: cookies.reason.message };
  if (status.status === "rejected" && !Object.keys(S.authentication || {}).length) {
    servicesDrawn = "";
    return $("#sv-list").replaceChildren(failed(status.reason.message, loadServices));
  }
  renderServices();
}
/* From another page (a failing series, a refused download): Settings › Services & Devices › Services, at the service's row; with a
   backend, that server's row. */
async function openServiceRow(service, backend) {
  if (current && !await closeDrawer(true)) return;
  openSettings("services", { service, backend });
  renderServices();
}
function showSeriesOf(service) {  // every series of that service: the other filters cleared, as they could hide some
  showTab("series");
  clearWallFilters(false);
  $("#f-service").value = service;
  renderWall();
}

async function pollServiceCheck() {
  try { S.serviceChecks = await api("/api/service-checks"); } catch (error) { toast(error.message, true); $("#sv-check").disabled = false; return; }
  renderServices();
  if (S.serviceChecks.running) setTimeout(pollServiceCheck, 3000); else $("#sv-check").disabled = false;
}
$("#sv-check").onclick = async () => {
  $("#sv-check").disabled = true;
  try { await api("/api/service-checks", { method: "POST" }); } catch (error) { toast(error.message, true); $("#sv-check").disabled = false; return; }
  setTimeout(pollServiceCheck, 1000);
};
