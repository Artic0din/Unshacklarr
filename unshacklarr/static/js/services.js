/* Services: each service's sign-in, cookie files and series on one page, and what the sign-in status adds up to. */
const AUTH_METHOD_LABELS = { pairing: "pairing", cookies: "cookies", credentials: "credentials" };
const AUTH_METHOD_NAMES = { pairing: "Pairing", cookies: "Cookies", credentials: "Credentials" };
const AUTH_FAILURE_LABELS = { authentication_rejected: "authentication rejected", entitlement: "entitlement", region: "region", concurrency: "concurrency", network: "network", manifest: "manifest", drm: "DRM", licence: "licence", application: "application" };
function authenticationLabel(observation) {
  if (!observation) return "Not checked yet";
  const method = AUTH_METHOD_LABELS[observation.method] || "sign-in";
  const next = AUTH_METHOD_LABELS[observation.next_method] || "sign-in";
  const named = method[0].toUpperCase() + method.slice(1);
  if (observation.state === "ready") return `Ready · ${(observation.available_methods || []).map((item) => AUTH_METHOD_LABELS[item]).filter(Boolean).join(", ")}`;
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

const SERVICE_COLUMNS = ["Service", "Sign-in", "Cookies", "Sign-in methods", "Used by", "Actions"];
let servicesCookies = null;  // /api/cookies: the files of Unshackle's own cookies folder, by service
let servicesDrawn = "";      // what the table was drawn from: a refresh that changes nothing leaves it (and the focus) alone
let servicesAsked = "";      // the cookie file whose deletion is being confirmed: "SERVICE/profile"
let servicesReveal = "";     // a service to scroll to once the table is there

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
    const observation = setup || live?.observation || status.authentication || (status.state === "unknown" && methods.length
      ? { state: "ready", available_methods: methods } : null);
    const label = status.state === "anonymous" ? "No login required"
      : observation ? authenticationLabel(observation)
      : status.state === "needs_user_action" ? "Sign-in needed"
      : status.state === "validated" ? `Confirmed ${ago(status.validated_at)}` : "Not checked yet";
    // Cookie files are Unshackle's own, on the main server: another backend's row has none to show
    const cookieFiles = backend ? null : (files[service] || []).map((f) => ({ ...f, st: cookieStatus(f) }));
    // the backend that downloads it: the one set for it, else the main one, else (only on another server) that one
    const onMain = identities.has(service);
    const selected = S.config.service_defaults?.[service]?.backend || (onMain ? "" : [...identities.values()].find((i) => i.service === service)?.backend || "");
    const used = backend === selected ? seriesOf(service) : null;
    const cookieless = status.state === "anonymous" || (listed && methods.length > 0 && !methods.includes("cookies"));  // an empty list: not known
    // no cookie file is fine when none is needed, or a confirmed sign-in has another way in (credentials,
    // pairing): a cookie-only service confirmed before its last file went still needs one
    const signsInWithout = status.state === "anonymous" || (status.state === "validated" && listed && methods.some((m) => m !== "cookies"));
    const missing = Boolean(cookieFiles && !cookieFiles.length && !cookieless && used && servicesCookies?.folder && !signsInWithout);
    const attention = status.state === "needs_user_action" || Boolean(used && (missing || cookieFiles?.some((f) => f.st[0] === "bad")));
    return { key, service, backend, name: svcName(service) + (backend ? ` · ${backend}` : ""), label, state: status.state, setup, listed,
      methods: listed ? methods : null, anonymous: status.state === "anonymous", cookieFiles, cookieless, missing, used, attention };
  }).sort((a, b) => b.attention - a.attention || (b.used || 0) - (a.used || 0) || a.name.localeCompare(b.name));
}

function renderServices() {
  const box = $("#sv-list");
  if (!box) return;
  const models = serviceModels(), cookies = servicesCookies;
  const signature = JSON.stringify([models, cookies?.folder, cookies?.error, servicesAsked]);
  if (signature === servicesDrawn) return revealService();
  servicesDrawn = signature;
  const activePrompt = document.activeElement?.dataset?.authenticationService ? document.activeElement : null;
  let activePromptReused = false;

  const signInCell = (m) => {
    const controls = [];
    if (m.setup) {
      if (["timed_out", "cancelled", "error"].includes(m.setup.state)) {
        if (m.listed) controls.push(el("button", { className: "btn small", textContent: "Retry", onclick: () => startServiceAuthentication(m.service, m.backend) }));
      } else if (m.setup.prompt) {
        const reusePrompt = activePrompt?.dataset.authenticationService === m.service
          && activePrompt.dataset.authenticationBackend === m.backend && activePrompt.placeholder === m.setup.prompt;
        const input = reusePrompt ? activePrompt : el("input", { type: "text", ariaLabel: m.setup.prompt, placeholder: m.setup.prompt,
          autocomplete: "one-time-code", dataset: { authenticationService: m.service, authenticationBackend: m.backend } });
        activePromptReused ||= reusePrompt;
        controls.push(input, el("button", { className: "btn small", textContent: "Submit", onclick: () => answerServiceAuthentication(m.service, m.backend, input) }));
      }
      if (!["authenticated", "timed_out", "cancelled"].includes(m.setup.state)) {
        controls.push(el("button", { className: "btn small danger", textContent: "Cancel", onclick: () => cancelServiceAuthentication(m.service, m.backend) }));
      }
    } else if (m.listed && m.state !== "anonymous") {
      controls.push(el("button", { className: "btn small", textContent: m.state === "needs_user_action" ? "Reauthenticate" : "Sign in",
        onclick: () => startServiceAuthentication(m.service, m.backend) }));
    }
    return [el("small", { className: "sv-label", textContent: m.label }), ...(controls.length ? [el("div", { className: "sv-ctl" }, ...controls)] : [])];
  };

  const cookieCell = (m) => {
    if (m.backend) return [el("span", { className: "muted", textContent: "—" }), el("small", { textContent: "Managed on that server" })];
    if (!cookies?.folder) return [el("span", { className: "muted", textContent: "—" })];
    if (!m.cookieFiles.length) {
      if (m.cookieless) return [el("span", { className: "muted", textContent: "Not needed" })];
      const both = m.methods === null || m.methods.includes("credentials");
      return [el("span", { className: `ck-pill${m.missing ? " bad" : ""}`, textContent: m.missing ? "Missing" : "No cookie file" }),
        ...(m.missing ? [el("small", { textContent: both ? "Downloads will fail unless you add a cookie file, or set its username and password in unshackle.yaml."
          : "Downloads will fail unless you add a cookie file." })] : []),
        el("div", { className: "sv-ctl" }, el("button", { className: `btn small${m.missing ? " primary" : ""}`, textContent: "Add cookies", ariaLabel: `Add cookies for ${svcName(m.service)}`,
          onclick: () => openCookieDialog(m.service, "default", true) }))];
    }
    return m.cookieFiles.map((f) => {
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
        el("small", { textContent: [f.count === 1 ? "1 cookie" : `${f.count} cookies`, `updated ${ago_days(f.updated)}`].join(" · ") }),
        ...(servicesAsked === ask ? [sure] : [el("div", { className: "sv-ctl" },
          el("button", { className: `btn small${cls === "bad" || cls === "warn" ? " primary" : ""}`, textContent: "Replace", ariaLabel: `Replace ${file}`, onclick: () => openCookieDialog(m.service, f.profile) }), del)]));
    }).concat(el("div", { className: "sv-ctl" }, el("button", { className: "btn small", textContent: "Add cookies", ariaLabel: `Add cookies for ${svcName(m.service)}`,
      onclick: () => openCookieDialog(m.service, "", true) })));  // another profile (an account of its own)
  };

  const methodsCell = (m) => m.methods === null ? [el("span", { className: "muted", textContent: "—" })]
    : m.methods.length ? [el("small", { textContent: "Supports" }), el("div", { className: "sv-chips" }, ...m.methods.map((x) => el("span", { className: "sv-chip", textContent: AUTH_METHOD_NAMES[x] || x })))]
    : m.anonymous ? [el("span", { textContent: "No login required" })]
    : [el("span", { className: "muted", textContent: "—" })];  // listed without methods (its server unreachable): not known
  const usedCell = (m) => [el("span", { className: m.used === null ? "muted" : "", textContent: m.used === null ? "—" : m.used === 0 ? "No series" : m.used === 1 ? "1 series" : `${m.used} series` })];
  const actionCell = (m) => m.used ? [el("button", { className: "btn small", textContent: "Show series", onclick: () => showSeriesOf(m.service) })] : [];

  const cells = [signInCell, cookieCell, methodsCell, usedCell, actionCell];
  const table = el("table", { className: "sv-table" },
    el("thead", {}, el("tr", {}, ...SERVICE_COLUMNS.map((name) => el("th", { scope: "col", textContent: name })))),
    el("tbody", {}, ...models.map((m) => el("tr", { className: "sv-row", tabIndex: -1, dataset: m.attention ? { attention: "true" } : {}, id: `sv-${m.service}${m.backend ? `@${m.backend}` : ""}` },
      el("th", { scope: "row" }, el("span", { className: "sv-k", textContent: SERVICE_COLUMNS[0] }), el("b", { className: "sv-name", textContent: m.name })),
      ...cells.map((build, i) => el("td", {}, el("span", { className: "sv-k", textContent: SERVICE_COLUMNS[i + 1] }), ...build(m)))))));
  box.replaceChildren(...(models.length ? [table] : [el("p", { className: "muted", textContent: "No service is known yet. Unshackle lists them once it answers." })]));
  if (activePromptReused) activePrompt.focus();

  // The top of the page: the cookies folder, and what the statuses add up to
  const needing = models.filter((m) => m.attention).length, counts = signInCounts(S.authentication), summary = signInSummary(counts);
  const state = $("#sv-state");
  state.className = `sx-state ${needing ? "down" : counts.confirmed ? "ok" : ""}`;
  state.querySelector("b").textContent = needing ? (needing === 1 ? "1 service needs attention" : `${needing} services need attention`) : summary || "No service known yet";
  state.querySelector("small").textContent = needing ? summary : "";
  $("#sv-folder").textContent = cookies?.folder || "";
  $("#sv-note").textContent = !cookies ? "" : cookies.folder ? ""
    : S.config.settings.unshackle_mode === "remote" ? "To manage them here too, mount its Cookies folder and set its path in Settings, Unshackle, Folders."
    : cookies.error || "";
  revealService();
}
/* Scrolled to and focused, when another page sent you to one service's row. */
function revealService() {
  const backend = servicesReveal && S.config.service_defaults?.[servicesReveal]?.backend;
  const row = servicesReveal && ((backend && document.getElementById(`sv-${servicesReveal}@${backend}`)) || document.getElementById(`sv-${servicesReveal}`)
    || document.querySelector(`[id^="sv-${CSS.escape(servicesReveal)}@"]`));  // only on another server
  if (!row) return;
  servicesReveal = "";
  row.scrollIntoView({ block: "center", behavior: SCROLL });
  row.focus({ preventScroll: true });
}
async function loadServices() {
  if (!servicesDrawn) $("#sv-list").replaceChildren(loading("Checking the services…"));
  const [status, cookies] = await Promise.allSettled([api("/api/status?auth=1"), api("/api/cookies")]);
  if (status.status === "fulfilled") renderHealth(status.value);
  servicesCookies = cookies.status === "fulfilled" ? cookies.value : { folder: null, files: {}, error: cookies.reason.message };
  if (status.status === "rejected" && !Object.keys(S.authentication || {}).length) {
    servicesDrawn = "";
    return $("#sv-list").replaceChildren(failed(status.reason.message, loadServices));
  }
  renderServices();
}
/* From another page (a failing series): Settings, Services, at the service's row. */
async function openServiceRow(service) {
  if (current && !await closeDrawer(true)) return;
  servicesReveal = service;
  showTab("settings");
  showSettingsSec("services");
  renderServices();
}
function showSeriesOf(service) {  // every series of that service: the other filters cleared, as they could hide some
  showTab("series");
  $("#search").value = ""; $("#f-library").value = ""; $("#f-missing").checked = false; $("#f-monitored").checked = false;
  document.querySelectorAll("#tab-series .seg button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.managed === ""));
  $("#f-service").value = service;
  renderWall();
}
