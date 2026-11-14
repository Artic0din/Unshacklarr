/* The server's next_sync (web.py): on the hour, every so many hours of the day in the app's time zone, not the browser's. */
function nextSyncAt(now, every, zone) {
  const parts = (d) => Object.fromEntries(new Intl.DateTimeFormat("en", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric",
    day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" }).formatToParts(d).map((p) => [p.type, Number(p.value)]));
  const offset = (d) => { const p = parts(d); return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(d.getTime() / 1000) * 1000; };
  const at = parts(now), hour = Math.min((Math.floor(at.hour / every) + 1) * every, 24);  // the grid starts again at midnight
  // that wall-clock hour in the zone, as the server counts it, across a clock change too
  const wall = Date.UTC(at.year, at.month - 1, at.day, hour), guess = new Date(wall - offset(now)), exact = new Date(wall - offset(guess));
  return parts(exact).hour === hour % 24 ? exact : guess;  // an hour the clocks skip: the offset before them, as Python takes it
}
/* Settings, Automation: when the next sync comes (on the hour, every so many hours of the day), the interval as chips */
function renderAutomation() {
  const select = $("[data-set=sync_every_hours]");
  if (!select) return;
  const every = Number(select.value || S.config.settings?.sync_every_hours || 2);
  document.querySelectorAll(".ax-seg button[data-hours]").forEach((b) => b.setAttribute("aria-checked", String(Number(b.dataset.hours) === every)));
  const zone = S.config.settings?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
  const next = nextSyncAt(new Date(), every, zone), nextAt = time(next, zone);
  $("#ax-state b").textContent = `Next sync at ${nextAt}`;
  $("#ax-state small").textContent = `in ${until(next)} · ${every === 24 ? "once a day" : every === 1 ? "every hour" : `every ${every} hours`}`;
  // How many a day, said in words
  const hours = Array.from({ length: Math.ceil(24 / every) }, (_, k) => k * every);
  $("#rs-sum").replaceChildren(el("b", { textContent: every === 24 ? "Once a day" : `${hours.length} syncs a day` }),
    el("span", { textContent: `on the hour. An episode is tried at the first sync after it airs. Next sync at ${nextAt}` }));

  renderReleaseTries();
}
document.querySelectorAll(".ax-seg button[data-hours]").forEach((b) => b.onclick = () => {
  const select = $("[data-set=sync_every_hours]");
  select.value = b.dataset.hours;
  select.dispatchEvent(new Event("change"));
  renderAutomation();
});
$("#ax-sync").onclick = () => $("#sync").click();
/* At a release time: what the two numbers amount to, the tries on a line, and the series it concerns */
function renderReleaseTries() {
  const every = Math.max(10, Number($("#ax-every").value) || 30), minutes = Math.max(1, Number($("#ax-for").value) || 10);
  const tries = Math.floor(minutes * 60 / every) + 1, start = new Date(); start.setHours(21, 0, 0, 0);
  const end = new Date(start.getTime() + minutes * 60000);
  const span = every < 60 ? `${every} s` : `${+(every / 60).toFixed(1)} min`;
  $("#rt-sum").replaceChildren(el("b", { textContent: `${tries} tries in ${minutes} min` }),
    el("span", { textContent: `one every ${span}: for a 21:00 release, from ${time(start)} to ${time(end)}` }));
  const ticks = Math.min(tries, 60);
  const secs = (d) => d.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const dot = (i) => {  // each try: which one, when; the first and the last, what they mean
    const n = ticks > 1 ? Math.round(i * (tries - 1) / (ticks - 1)) : 0, at = new Date(start.getTime() + n * every * 1000);
    const why = n === 0 ? "The release time: the first try" : n === tries - 1 ? "The last try: after it, the regular syncs take over" : "";
    return hoverTip(el("i", { style: `left:${ticks > 1 ? i / (ticks - 1) * 100 : 0}%` }),
      () => [el("b", { textContent: `Try ${n + 1} of ${tries} · ${secs(at)}` }), ...(why ? [el("br"), why] : [])]);
  };
  $("#rt-line").replaceChildren(el("span", { className: "rt-at", textContent: time(start) }),
    el("div", { className: "rt-track" }, ...Array.from({ length: ticks }, (_, i) => dot(i))),
    el("span", { className: "rt-at", textContent: time(end) }));
  document.querySelectorAll(".rt-seg").forEach((seg) => {
    const value = Number($(`#${seg.dataset.for}`).value);
    let hit = false;
    seg.querySelectorAll("button").forEach((b) => { const on = Number(b.dataset.v) === value; hit ||= on; b.setAttribute("aria-checked", String(on)); });
    seg.querySelector(".rt-custom").classList.toggle("on", !hit);  // a value of its own: the free field is the choice
  });
  const timed = S.series.filter((x) => S.config.series?.[x.tvdbId]?.release_time).map((x) => `${x.title} (${S.config.series[x.tvdbId].release_time})`);
  $("#rt-who").textContent = timed.length > 1 ? `${timed.length} series have a release time: ${timed.join(", ")}` : timed.length ? `1 series has a release time: ${timed[0]}`
    : "No series has a release time yet. Set one on a series' page, in its Settings tab.";
}
document.querySelectorAll(".rt-seg button").forEach((b) => b.onclick = () => {
  const input = $(`#${b.closest(".rt-seg").dataset.for}`);
  input.value = b.dataset.v;
  input.dispatchEvent(new Event("input", { bubbles: true }));
});
["#ax-every", "#ax-for", "#ax-days", "#nt-late", "#hs-keep", "#hs-days"].forEach((id) => {
  $(id).addEventListener("input", renderReleaseTries);
  $(id).addEventListener("focus", (e) => e.target.select());  // "Other": what is typed replaces it
});

/* Settings, Sonarr: where it is, whether it answers (the health check, or the last test), a way to open it */
function renderSonarrState(st = S.health?.sonarr || {}, tested = false) {
  const set = S.config.settings || {}, box = $("#sx-state");
  if (!box) return;
  $("#sx-where").textContent = set.sonarr_url || "Not set up";
  const web = sonarrWeb();
  $("#sx-open").hidden = !web;
  if (web) $("#sx-open").href = web;
  box.className = `sx-state ${st.ok ? "ok" : st.ok === false ? "down" : ""}`;
  box.querySelector("b").textContent = st.ok ? `Connected${st.version ? ` · Sonarr ${st.version}` : ""}` : st.ok === false ? "Unreachable" : "Checking…";
  box.querySelector("small").textContent = st.ok ? (tested ? "Tested just now" : "Checked a moment ago") : st.ok === false ? String(st.error || "").replace(/^Sonarr is unreachable: /, "") : "";
}
document.querySelectorAll("[data-health]").forEach((b) => b.onclick = () => {
  showTab("settings", true);  // not the phone's list: the section itself
  showSettingsSec(b.dataset.health);
});

const AUTH_METHOD_LABELS = { pairing: "pairing", cookies: "cookies", credentials: "credentials" };
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
    renderUnshackleStatus(unshackleDetails || {});
  } catch (error) { toast(error.message, true); }
}

async function cancelServiceAuthentication(service, backend = "") {
  try {
    const setup = await api(`/api/unshackle/authentication/${encodeURIComponent(service)}`, {
      method: "DELETE", body: JSON.stringify({ backend }),
    });
    S.authenticationSetups = [...(S.authenticationSetups || []).filter((item) => item.service !== service || item.backend !== backend), setup];
    renderUnshackleStatus(unshackleDetails || {});
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

function renderUnshackleStatus(st) {
  const activePrompt = document.activeElement?.dataset?.authenticationService ? document.activeElement : null;
  let activePromptReused = false;
  const local = st.mode === "local";
  $("#ux-run").replaceChildren(...(local ? [
    el("button", { className: "btn small", textContent: st.ok ? "Restart" : "Start", onclick: restartUnshackle }),
    el("button", { className: "btn small", textContent: "View log", onclick: showServeLog }),
  ] : []));
  const missing = (st.tools || []).filter((t) => !t.installed && t.required);
  const maint = (action, label, why) => el("button", { className: "btn small", textContent: label, title: why, onclick: async (e) => {
    e.target.disabled = true;
    try {
      const r = await api(`/api/unshackle/maintenance/${action}`, { method: "POST" });
      toast(action === "refresh-services" ? "Services reloaded" : `${label}: ${r.freed_bytes ? `${(r.freed_bytes / 2 ** 20).toFixed(0)} MB freed` : "done"}`);
      loadUnshackleStatus();
    } catch (err) { e.target.disabled = false; toast(err.message, true); }
  } });
  const copyCmd = (cmd) => el("div", { className: "st-cmd" }, el("code", { textContent: cmd }), el("button", { className: "btn small", textContent: "Copy",
    onclick: async () => { try { await navigator.clipboard.writeText(cmd); toast("Command copied"); } catch { toast("Could not copy: select it instead", true); } } }));
  const authenticationStatuses = Object.entries(S.authentication || {});
  const authentication = [
    ...authenticationStatuses,
    ...(S.authenticationSetups || []).filter((setup) => !authenticationStatuses.some(([tag, status]) =>
      (status.service || tag.split("@")[0]) === setup.service && (status.backend || "") === (setup.backend || "")))
      .map((setup) => [`${setup.service}${setup.backend ? `@${setup.backend}` : ""}`,
        { service: setup.service, backend: setup.backend || "", state: "unknown" }]),
  ].map(([tag, status]) => {
    const service = status.service || tag.split("@")[0], backend = status.backend || "";
    const setup = (S.authenticationSetups || []).find((item) => item.service === service && item.backend === backend);
    const live = (S.authenticationLive || []).find((item) => item.service === service && (item.backend || "") === backend);
    const configured = Object.hasOwn(S.authenticationMethods || {}, tag);
    const methods = configured ? S.authenticationMethods[tag] : [];
    const observation = setup || live?.observation || status.authentication || (status.state === "unknown" && methods.length
      ? { state: "ready", available_methods: methods } : null);
    const label = status.state === "anonymous" ? "No login required"
      : observation ? authenticationLabel(observation)
      : status.state === "needs_user_action" ? "Sign-in needed"
      : status.state === "validated" ? `Confirmed ${ago(status.validated_at)}` : "Not checked yet";
    const name = svcName(service) + (backend ? ` · ${backend}` : "");
    const controls = [];
    if (setup) {
      if (["timed_out", "cancelled", "error"].includes(setup.state)) {
        if (configured) controls.push(el("button", { className: "btn small", textContent: "Retry", onclick: () => startServiceAuthentication(service, backend) }));
      } else if (setup.prompt) {
        const reusePrompt = activePrompt?.dataset.authenticationService === service
          && activePrompt.dataset.authenticationBackend === backend && activePrompt.placeholder === setup.prompt;
        const input = reusePrompt ? activePrompt : el("input", { type: "text", ariaLabel: setup.prompt, placeholder: setup.prompt,
          autocomplete: "one-time-code", dataset: { authenticationService: service, authenticationBackend: backend } });
        activePromptReused ||= reusePrompt;
        controls.push(input, el("button", { className: "btn small", textContent: "Submit", onclick: () => answerServiceAuthentication(service, backend, input) }));
      }
      if (!["authenticated", "timed_out", "cancelled"].includes(setup.state)) {
        controls.push(el("button", { className: "btn small danger", textContent: "Cancel", onclick: () => cancelServiceAuthentication(service, backend) }));
      }
    } else if (configured && status.state !== "anonymous") {
      controls.push(el("button", { className: "btn small", textContent: status.state === "needs_user_action" ? "Reauthenticate" : "Sign in",
        onclick: () => startServiceAuthentication(service, backend) }));
    }
    return el("div", { className: "st-job" }, el("span", { textContent: name }), el("small", { textContent: label }), ...controls);
  });
  const extra = [
    ...(authentication.length ? [el("div", { className: "st-sect" }, el("b", { textContent: "Service access" }),
      el("div", { className: "st-jobs" }, ...authentication))] : []),
    ...(st.ok ? [
    el("div", { className: "st-sect" }, el("b", { textContent: st.queue && (st.queue.downloading || st.queue.queued)
      ? `Queue · ${st.queue.downloading} downloading${st.queue.queued ? `, ${st.queue.queued} waiting` : ""}` : "Queue" }),
      ...(st.jobs?.length ? [el("div", { className: "st-jobs" }, ...st.jobs.map((j) => el("div", { className: "st-job" },
        el("span", { textContent: `${j.title}`, title: j.title }),
        el("small", { textContent: j.status === "queued" ? `${j.service} · waiting` : `${j.service} · ${j.progress}%` }),
        el("button", { className: "btn small danger", textContent: "Cancel", onclick: async (e) => {
          e.target.disabled = true;
          try { await api(`/api/unshackle/jobs/${encodeURIComponent(j.id)}/cancel`, { method: "POST" }); toast("Cancelling"); setTimeout(loadUnshackleStatus, 1500); }
          catch (err) { e.target.disabled = false; toast(err.message, true); }
        } }))))] : [el("small", { className: "muted", textContent: "Nothing is downloading or waiting." })])),
    el("div", { className: "st-sect" }, el("b", { textContent: "Maintenance" }),
      el("div", { className: "st-maint" },
        maint("refresh-services", "Reload services", "After adding or updating a service in its services folder"),
        maint("clear-temp", "Clear temp", "Deletes the leftovers of interrupted downloads"),
        maint("clear-cache", "Clear cache", "Deletes Unshackle's cache, logins included: services log in again next time"))),
    // the commands name the bundled compose's container: shown only for its address (http://unshackle:8786)
    ...(local || !/^https?:\/\/unshackle(:\d+)?\/?$/.test(S.config.settings.unshackle_url || "") ? [] : [el("div", { className: "st-sect" }, el("b", { textContent: "Restart it or read its log where it runs" }),
      el("div", { className: "st-cmds" }, copyCmd("docker compose restart unshackle"), copyCmd("docker logs -f --tail 200 unshackle")))]),
    ] : []),
  ];
  // Unshackle 6 serves its proxies (a country code, a provider) only to a key allowed to: said, and allowed in one click
  const restartCmd = /^https?:\/\/unshackle(:\d+)?\/?$/.test(S.config.settings.unshackle_url || "") ? "docker compose restart unshackle" : "";
  const proxies = st.proxy_refused ? [el("div", { className: "st-sect warn" },
    el("b", { textContent: "Unshackle doesn't let Unshacklarr use its proxies" }),
    el("small", { textContent: "Since Unshackle 6, an API key may use the proxies set in unshackle.yaml (a country code such as au, or a provider) only once it is allowed. Downloads that ask for one fail until then." }),
    el("div", { className: "st-maint" }, el("button", { className: "btn small primary", textContent: "Allow Unshacklarr's key", onclick: async (e) => {
      e.target.disabled = true;
      try {
        await api("/api/unshackle/allow-proxies", { method: "POST" });
        toast("Allowed in unshackle.yaml. Restart Unshackle when nothing is downloading, so that it reads it.");
        e.target.closest(".st-sect").replaceChildren(el("b", { textContent: "Allowed in unshackle.yaml" }),
          el("small", { textContent: "Restart Unshackle when nothing is downloading, so that it reads it." }), ...(restartCmd ? [copyCmd(restartCmd)] : []));
      } catch (err) { e.target.disabled = false; toast(err.message, true); }
    } })),
    el("small", { textContent: "To do it by hand, the README shows the lines to add to unshackle.yaml." }))] : [];
  $("#u-status").replaceChildren(
    ...(st.error ? [el("p", { className: "status-err", textContent: st.error })] : []),
    ...proxies,
    ...(missing.length ? [el("p", { className: "status-err", textContent: `Missing: ${missing.map((t) => t.name).join(", ")}. Install them, then check again.` })] : []),
    ...extra,
    ...(st.tools ? [el("details", { className: "tools-box" },
      el("summary", { className: missing.length ? "bad" : "ok", textContent: missing.length ? `Tools: ${missing.length} missing` : `Tools: all ${st.tools.filter((t) => t.required).length} required ones found` }),
      el("div", { className: "tools" }, ...st.tools.map((t) => el("span", { className: t.installed ? "" : t.required ? "missing" : "optional-missing",
        title: t.installed ? `${t.name} ${t.version || ""}`.trim() : `${t.name} is missing${t.required ? "" : " (optional)"}`,
        textContent: `${t.installed ? "✓" : "✗"} ${t.name}` }))))] : []));
  if (activePromptReused) activePrompt.focus();
}
async function loadUnshackleStatus() {
  $("#u-status").replaceChildren(loading("Checking Unshackle…"));
  await refreshHealth(true);
}
async function restartUnshackle() {
  $("#u-status").replaceChildren(loading("Restarting Unshackle…"));
  try { renderUnshackleStatus(await api("/api/unshackle/restart", { method: "POST", wait: 120 })); toast("unshackle restarted"); }
  catch (e) { toast(e.message, true); loadUnshackleStatus(); }
}
async function showServeLog() {
  let log;
  try { ({ log } = await api("/api/unshackle/log")); } catch (e) { return toast(e.message, true); }
  showTab("log");
  picked_run = "serve";
  $("#con").classList.add("open");
  $("#cd-main").replaceChildren(el("div", { className: "cd-head" }, el("div", {}, el("h3", { textContent: "unshackle serve" }),
    el("small", { textContent: "Its log, last lines" }))));
  $("#cd-raw").hidden = false;
  $("#cd-raw").open = true;
  if (openTerm()) { termFor = "serve"; term.write(log.replaceAll("\n", "\r\n")); }
  document.querySelectorAll(".crow").forEach((r) => r.classList.remove("sel"));
}

/* Suggest services: every series without a service, airing ones first, with what TMDB finds for it, added at once. */
async function openBulk() {
  const todo = S.series.filter((s) => !S.config.series[s.tvdbId]?.service && s.monitored
    && !S.config.hidden_series.includes(s.tvdbId) && s.tmdbId)
    .sort((a, b) => (a.status === "ended") - (b.status === "ended"));  // ended ones too, after the airing ones
  const rows = todo.map((s) => {
    const li = el("li", {}, el("img", { alt: "", loading: "lazy", src: posterSrc(s.poster, s.title), onerror: posterFail(s.title) }),
      el("div", {}, el("b", { textContent: s.title }), el("div", { className: "opts" }, loading("Looking on TMDB…"))));
    li.dataset.tvdb = s.tvdbId;
    return li;
  });
  $("#bulk-rows").replaceChildren(...(rows.length ? rows : [el("li", { className: "none", textContent: "Every series you follow already has a service." })]));
  $("#bulk-add").disabled = true;
  $("#bulk-dialog").showModal();
  let done = 0;
  const pickCount = () => {
    const n = [...document.querySelectorAll("#bulk-rows input:checked")].filter((i) => i.value).length;
    $("#bulk-add").disabled = !n;
    $("#bulk-add").textContent = n ? `Add ${n} series` : "Add";
  };
  const one = async (s, li) => {
    let links;
    try { links = (await api(`/api/suggest/${s.tmdbId}?network=${encodeURIComponent(s.network || "")}`, { wait: 120 })).links; }
    catch {  // TMDB refuses bursts now and then: say so, and let it be asked again
      li.querySelector(".opts").replaceChildren(el("span", { className: "none", textContent: "TMDB did not answer" }),
        el("button", { type: "button", className: "btn small", textContent: "Retry", onclick: () => one(s, li) }));
      $("#bulk-progress").textContent = `Checked ${++done} of ${todo.length}`;
      return;
    }
    // other_title: another title of the series' service (its specials): never the series itself
    const usable = links.filter((l) => !l.needs_series_url && !l.episode && !l.other_title && S.services.includes(l.service));
    const name = `pick-${s.tvdbId}`;
    // Skip is picked by default: adding a series is a choice
    const opt = (l, i) => el("label", {
      title: l ? l.url : "Leave it without a service",
    }, el("input", { type: "radio", name, value: l ? JSON.stringify([l.service, l.url]) : "",
      checked: !l, onchange: pickCount }), l ? (l.name ? `${l.service} · ${l.name}` : l.service) : "Skip",
      l ? el("small", { textContent: l.country }) : "");
    li.querySelector(".opts").replaceChildren(...(usable.length ? [...usable.map(opt), opt(null, -1)] : [el("span", { className: "none", textContent: "Nothing found on TMDB" })]));
    $("#bulk-progress").textContent = `Checked ${++done} of ${todo.length}`;
    pickCount();
  };
  const queue = todo.map((s, i) => [s, rows[i]]);  // two at a time (each asks TMDB per country); cached a week after
  await Promise.all(Array.from({ length: 2 }, async () => { while (queue.length) { const [s, li] = queue.shift(); if ($("#bulk-dialog").open) await one(s, li); } }));
}
$("#bulk-open").onclick = openBulk;
$("#bulk-form").onsubmit = async (e) => {
  if (e.submitter?.value !== "add") return;
  e.preventDefault();
  const picks = [...document.querySelectorAll("#bulk-rows input:checked")].filter((i) => i.value);
  for (const input of picks) {
    const [service, title] = JSON.parse(input.value), tvdbId = Number(input.closest("li").dataset.tvdb);
    // its other settings stay; what belonged to a former service (its options, season pages, the date automatic
    // downloads started) starts again, and the server sets that date to now
    const { since, season_pages, ...kept } = S.config.series[tvdbId] || {};
    S.config.series[tvdbId] = { options: {}, ...kept, service, title, service_options: {} };
  }
  try { await save(); $("#bulk-dialog").close(); toast(`${picks.length} series added: their new episodes download from now on`); }
  catch (err) { toast(err.message, true); }
};

/* Release time, learnt: when its episodes were seen coming out, and the time to try then. */
async function showReleaseSeen(s) {
  const box = $("#d-release-seen");
  box.hidden = true;
  let r;
  try { r = await api(`/api/series/${s.tvdbId}/release`); } catch { return; }
  const sg = r.suggestion, conf = S.config.series[s.tvdbId];
  if (!sg || current?.tvdbId !== s.tvdbId) return;
  const same = conf?.release_time === sg.time && Number(conf?.release_day || 0) === sg.day;
  const when = sg.between[0] ? `between ${sg.between[0]} and ${sg.between[1]}` : `by ${sg.between[1]}`;
  box.replaceChildren(el("span", { textContent: `${sg.episodes} episode${sg.episodes > 1 ? "s" : ""} came out on the service ${when}${sg.day ? `, ${releaseDayLabel(sg.day)} airing` : ""}. Suggested release time: ${sg.time}` }),
    same ? el("span", { className: "muted", textContent: "· in use" }) : el("button", { type: "button", className: "btn small primary", textContent: "Use it", onclick: () => {
      $("#d-release").value = sg.time;
      $("#d-release-day").value = String(sg.day);
      $("#d-release").dispatchEvent(new Event("input", { bubbles: true }));
      $("#d-release-day").dispatchEvent(new Event("change", { bubbles: true }));
      box.hidden = true;
      toast(`Release time set to ${sg.time}: save to keep it`);
    } }));
  box.hidden = false;
}

/* Test this series: the service's episodes, the next ones against Sonarr, a season map if needed. */
$("#d-probe").onclick = async () => {
  const conf = S.config.series[current.tvdbId];
  const out = $("#d-probe-out"), state = $("#d-probe-state");
  if (!conf?.service || !conf.title) { state.textContent = "Pick a service and its URL first."; return; }
  $("#d-probe").disabled = true;
  state.replaceChildren(loading("Asking the service… (up to a minute)"));
  out.replaceChildren();
  const slow = slowHint(svcName(conf.service));
  try {
    const r = await api("/api/probe", { method: "POST", wait: 120,
      body: JSON.stringify({ show: conf, seriesId: current.id, title: current.title }) });
    state.textContent = "";
    const seasons = r.seasons.map((x) => `S${x.season} (${x.episodes})`).join(", ");
    const rows = r.checks.map((c) => el("div", { className: "probe-row" },
      el("span", { className: c.found ? "y" : "n", textContent: c.found ? "✓" : c.aired ? "✗" : "…",
        title: c.found ? "On the service" : c.aired ? "Not on the service" : "Not aired yet" }),
      el("b", { textContent: c.sxxeyy }),
      el("span", { className: "mut", textContent: c.service && c.service !== c.sxxeyy ? `= ${c.service}` : "" }),
      el("span", {}, c.found ? `${c.name || ""} ` : c.aired ? "not on the service" + (c.hasFile ? " (on disk already)" : "") : "not aired yet",
        c.found && c.file ? el("code", { textContent: ` → ${c.file}` }) : "")));
    const maps = Object.entries(r.season_map);
    const apply = maps.length ? [el("div", { className: "probe-map" },
      el("span", { textContent: `The service numbers ${maps.map(([a, b]) => `Sonarr season ${a} as ${b}`).join(", ")}.` }),
      el("button", { type: "button", className: "btn small primary", textContent: "Apply", onclick: () => {
        conf.season_map = { ...(conf.season_map || {}), ...Object.fromEntries(maps.map(([a, b]) => [a, b])) };
        $("#d-seasons").value = Object.entries(conf.season_map).map(([a, b]) => `${a}=${b}`).join(", ");
        $("#d-adv").open = true;
        dirty();
        toast("Season map set: save, then test again");
      } }))] : [];
    // An episode link, not the series: the service lists fewer than Sonarr has aired. A series simply new (one aired,
    // one listed) is no warning.
    const single = r.count > 0 && r.count < 3 && r.checks.filter((c) => c.aired).length > r.count ? [el("div", { className: "probe-warn" },
      el("b", { textContent: "This link may be an episode, not the series." }),
      el("span", { textContent: " On the service, open the series' own page (all its episodes) and paste that link instead." }))] : [];
    out.replaceChildren(el("div", { className: "probe-out" },
      el("div", { className: "head" }, "Found ", el("b", { textContent: r.series || "the series" }), `: ${r.count} episodes${seasons ? ` · ${seasons}` : ""}`),
      ...single, ...apply, ...rows));
  } catch (e) { state.replaceChildren(failed(e.message)); }
  finally { $("#d-probe").disabled = false; clearTimeout(slow); }
};

/* This device's notifications (Web Push): allowed here, sent by the server through the browser's push service. */
const pushable = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const standalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const iOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
function b64key(s) {
  const raw = atob((s + "=".repeat((4 - s.length % 4) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}
async function renderPush() {
  const line = $("#push-line"), said = $("#push-state");
  const state = (text, cls = "") => { said.textContent = text; said.className = cls; line.replaceChildren(); };
  if (iOS() && !standalone()) return state("On an iPhone: add Unshacklarr to the home screen first (Share, Add to Home Screen), then open it from there.");
  if (!pushable()) return state("This browser cannot receive them.");
  if (Notification.permission === "denied") return state("Blocked in this browser's settings for this site.", "bad");
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  const btn = (text, cls, fn) => el("button", { className: `btn small ${cls}`, textContent: text, onclick: async (e) => {
    e.target.disabled = true;
    try { await fn(); } catch (err) { toast(err.message || String(err), true); }
    renderPush();
  } });
  said.textContent = sub ? "On · gets every message turned on below" : "Off. Notifications come from the app itself, no other service needed";
  said.className = sub ? "ok" : "";
  line.replaceChildren(...(sub ? [
    btn("Test", "", async () => { await api("/api/push/test", { method: "POST", body: JSON.stringify({ endpoint: sub.endpoint }) }); toast("Test sent to this device"); }),
    btn("Turn off", "danger", async () => {
      await api("/api/push/unsubscribe", { method: "POST", body: JSON.stringify({ endpoint: sub.endpoint }) });
      await sub.unsubscribe();
    }),
  ] : [btn("Turn on", "primary", async () => {
    if (await Notification.requestPermission() !== "granted") throw new Error("Notifications were not allowed");
    const { key } = await api("/api/push/key");
    const made = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64key(key) });
    const label = /iPhone|iPad/.test(navigator.userAgent) ? "iPhone" : /Android/.test(navigator.userAgent) ? "Android" : "Computer";
    await api("/api/push/subscribe", { method: "POST", body: JSON.stringify({ subscription: made.toJSON(), label }) });
    toast("Notifications on for this device");
  })]));
}

