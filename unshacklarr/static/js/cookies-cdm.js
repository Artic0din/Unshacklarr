/* Cookies: where a cookie file stands and the window that replaces it (its rows are Settings, Services); then the CDM page. */
const ago_days = (ts) => { const d = Math.floor((Date.now() / 1000 - ts) / 86400); return d < 1 ? "today" : d === 1 ? "yesterday" : `${d} days ago`; };
/* Where a cookie file stands: a colour, a word, a sentence for the tooltip. */
function cookieStatus(f) {
  const left = f.expires ? Math.floor((f.expires * 1000 - Date.now()) / 86400000) : null;
  if (f.unreadable) return ["bad", "Unreadable", "Unshacklarr cannot read this file: check its permissions, or replace it"];
  if (f.expired) return ["bad", "Expired", "The service will refuse them: replace them with fresh ones"];
  // Session cookies carry no date: how long they sign in is the service's secret
  if (left === null || left < 0) return ["mut", "Session only", "Session cookies have no expiry date: only a failed sign-in shows they are over"];
  const days = left === 1 ? "1 day" : `${left} days`;
  return left < 7 ? ["warn", `Expires in ${days}`, "Replace them soon"] : ["ok", `Valid · ${days} left`, "Nothing to do"];
}
function openCookieDialog(service = "", profile = "default", newProfile = false) {
  $("#ck-service").replaceChildren(...S.services.map((t) => el("option", { value: t, textContent: svcName(t) })));
  $("#ck-service").value = service || S.services[0] || "";
  $("#ck-service").disabled = Boolean(service);
  $("#ck-profile").value = profile;
  $("#ck-profile").disabled = Boolean(service) && !newProfile;  // adding: any profile name; replacing: that one
  $("#ck-title").textContent = service ? `Cookies for ${svcName(service)}` : "Add cookies";
  $("#ck-text").value = "";
  $("#ck-file").value = "";
  $("#ck-error").replaceChildren();
  $("#cookie-dialog").showModal();
}
$("#ck-file").onchange = async (e) => { const f = e.target.files[0]; if (f) $("#ck-text").value = await f.text(); };
$("#ck-form").onsubmit = async (e) => {
  if (e.submitter?.value !== "save") return;
  e.preventDefault();
  const body = { service: $("#ck-service").value, profile: $("#ck-profile").value.trim(), text: $("#ck-text").value };
  if (!body.text.trim()) return $("#ck-error").replaceChildren(failed("Pick a file or paste the cookies."));
  try {
    const saved = await api("/api/cookies", { method: "POST", body: JSON.stringify(body) });
    $("#cookie-dialog").close();
    toast(`${svcName(body.service)} cookies saved: ${saved.count} cookies`);
    loadServices();
  } catch (err) { $("#ck-error").replaceChildren(failed(err.message)); }
};

/* CDM: Unshackle's devices (what they are, whether they still get a license) and which one each service uses. */
let cdmData = null, cdmFilter = "all", cdmQuery = "", cdmTesting = false, cdmShowUnused = false;
const cdmOpen = new Set();  // devices whose details are unfolded
const cdmRunning = new Set(), cdmJust = new Set();  // devices being tested; just tested (their result pops in)
async function loadCdm(data) {
  if (!data) {
    try { data = await api("/api/cdm"); } catch (e) { return $("#cdm-list").replaceChildren(failed(e.message, () => loadCdm())); }
  }
  cdmData = data;
  renderCdm();
}
function cdmTitle(d) {
  const i = d.info;
  if (!i || i.unreadable) return d.name;
  const words = [i.company, i.model].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
  return words || d.name;
}
/* Where a device stands, in a word, a colour and a sentence. */
function cdmStatus(d) {
  if (d.info?.unreadable) return ["bad", "Unreadable", d.info.unreadable];
  const t = d.test;
  if (!t) return ["mut", "Not tested", "Test asks the DRM's own test server for a license"];
  const when = tr(`tested ${ago(t.at)}`);  // translated here: glued to the server's own words below
  if (t.ok) return ["ok", "Works", `Got a license (${COUNT.key(t.keys)}), ${when}. A service may still refuse this device.`];
  if (t.revoked) return ["bad", "Revoked", `${t.error}, ${when}`];
  return ["warn", "Failed", `${t.error}, ${when}`];
}
const dateOf = (secs) => secs ? new Date(secs * 1000).toLocaleDateString(LOCALE, { day: "numeric", month: "short", year: "numeric" }) : "";
function cdmDetails(d) {
  const i = d.info || {};
  const rows = d.kind === "Widevine"
    ? [["File", `${d.name}.wvd`], ["System ID", i.system_id], ["Security level", i.level], ["Type", i.type], ["Maker", i.company], ["Model", i.model],
       ["Product", i.product], ["Architecture", i.architecture], ["CDM version", i.cdm_version], ["Security patch", i.patch_level],
       ["VMP", i.vmp === undefined ? "" : i.vmp ? "yes" : "no"], ["Certificate serial", i.serial], ["Certificate made", dateOf(i.created)],
       ["Certificate expires", i.expires ? dateOf(i.expires) : i.serial ? "never" : ""], ["Build", i.build]]
    : [["File", d.folder ? `${d.name}/ (a folder)` : `${d.name}.prd`], ["Security level", i.level], ["Maker and model", i.company], [".prd version", i.version],
       ["Reprovisionable", i.reprovisionable === undefined ? "" : i.reprovisionable ? "yes (it has its group key)" : "no (no group key: an older .prd)"],
       ["Certificates in the chain", i.certificates], ["Chain", i.chain], ["Device certificate", i.leaf_id], ["Expires", i.expires ? dateOf(i.expires) : i.chain ? "never" : ""]];
  const test = d.test ? [["Last test", `${d.test.ok ? "license granted" : d.test.revoked ? "revoked" : "failed"}, ${new Date(d.test.at).toLocaleString(LOCALE)}`],
    ...(d.test.error ? [["Test server said", d.test.error]] : [])] : [];
  return el("dl", { className: "cdm-facts" }, ...[...rows, ...test].filter(([, v]) => v !== undefined && v !== null && v !== "")
    .flatMap(([k, v]) => [el("dt", { textContent: k }), el("dd", { textContent: String(v) })]));
}
async function testCdm(d) {
  cdmRunning.add(d.name);
  renderCdm();
  try {
    d.test = await api("/api/cdm/test", { method: "POST", wait: 90, body: JSON.stringify({ kind: d.kind, name: d.name }) });
  } catch (e) { toast(`${d.name}: ${e.message}`, true); }
  cdmRunning.delete(d.name);
  cdmJust.add(d.name);
  setTimeout(() => cdmJust.delete(d.name), 1000);
  renderCdm();
}
async function testCdms(list) {
  for (const [n, d] of list.entries()) { cdmTesting = `${n + 1} of ${list.length}`; await testCdm(d); }
  cdmTesting = false;
  renderCdm();
  const bad = list.filter((d) => !d.test?.ok).length;
  toast(`${COUNT.device(list.length)} tested${bad ? `, ${bad} not working` : ", all working"}`, bad > 0);
}
/* A device's short name: its maker and model once (Apple TV+'s "EXPRESS LUCK … EXPRESS LUCK … LE-*" twice over),
   then its DRM and level. */
function cdmShort(d) {
  if (!d) return "";
  const title = cdmTitle(d).replace(/^(.{6,}?)\s+\1\b/i, "$1");
  const lvl = d.info?.level || d.level;
  return `${title} · ${d.remote ? "Remote " : ""}${d.kind === "PlayReady" ? "PR" : "WV"}${lvl ? ` ${lvl}` : ""}`;
}
/* A small window by a button: a device to pick, a device's actions; gone on a click elsewhere or Escape. */
let cdmPop = null;
const closeCdmPop = () => { cdmPop?.remove(); cdmPop = null; };
document.addEventListener("pointerdown", (e) => { if (cdmPop && !cdmPop.contains(e.target) && !e.target.closest?.(".cdm-pop-btn")) closeCdmPop(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeCdmPop(); });
function cdmPopAt(anchor, ...nodes) {
  const again = cdmPop?.dataset.for === anchor.dataset.key && anchor.dataset.key;
  closeCdmPop();
  if (again) return null;  // the same button again: it closes
  hideTip();
  cdmPop = el("div", { className: "cdm-pop", dataset: { for: anchor.dataset.key || "" } }, ...nodes);
  cdmPop.anchor = anchor;
  document.body.append(cdmPop);
  onTop(cdmPop);
  placeCdmPop();
  return cdmPop;
}
function placeCdmPop() {  // by its button, as the page scrolls; gone when the button is
  const anchor = cdmPop?.anchor;
  if (!anchor) return;
  const r = anchor.getBoundingClientRect(), menu = cdmPop.classList.contains("menu");  // a ⋯ menu ends at its button's right
  if (!anchor.isConnected || r.bottom < 0 || r.top > innerHeight) return closeCdmPop();
  const p = cdmPop.getBoundingClientRect();
  cdmPop.style.left = `${Math.min(Math.max(8, menu ? r.right - p.width : r.left), innerWidth - p.width - 8)}px`;
  cdmPop.style.top = `${r.bottom + 6 + p.height > innerHeight - 8 ? Math.max(8, r.top - p.height - 6) : r.bottom + 6}px`;
}
addEventListener("scroll", () => { if (cdmPop) placeCdmPop(); }, true);  // true: a scroll inside the page's panes too
addEventListener("resize", placeCdmPop);
async function cdmChoose(service, device, also = []) {  // also: other services moving to the same device
  try {
    for (const svc of [service, ...also]) cdmData = await api("/api/cdm/choose", { method: "POST", body: JSON.stringify({ service: svc, device }) });
    renderCdm();
    const d = [...cdmData.devices, ...cdmData.remote].find((x) => x.name === device);
    toast(service === "default" ? `Default device: ${cdmShort(d) || device}` : device ? `${svcName(service)}: ${cdmShort(d) || device}` : `${svcName(service)}: the default device`);
  } catch (e) { toast(e.message, true); loadCdm(); }
}
/* Pick a device for a service: searched, grouped by DRM, what uses each in sight. */
function cdmPicker(anchor, service, current, also = []) {
  const data = cdmData, q = el("input", { type: "search", className: "cdm-pop-search", placeholder: "Search a device", ariaLabel: "Search a device" });
  const list = el("div", { className: "cdm-pop-list" });
  const devices = [...data.devices.filter((d) => !d.info?.unreadable), ...data.remote.map((r) => ({ ...r, remote: true }))];
  const byDefault = [...data.devices, ...data.remote].find((d) => d.name === data.map.default);
  const opt = (value, main, sub) => el("button", { type: "button", className: `cdm-opt${value === (current || "") ? " on" : ""}`,
    onclick: () => { closeCdmPop(); if (value !== (current || "")) cdmChoose(service, value || null, also); } },
    el("b", { textContent: main, title: main }), ...(sub ? [el("small", { textContent: sub })] : []));
  const draw = () => {
    const text = q.value.trim().toLowerCase();
    const fits = (d) => !text || `${d.name} ${cdmTitle(d)} ${d.used_by.join(" ")}`.toLowerCase().includes(text);
    list.replaceChildren(
      ...(service !== "default" && !text ? [opt("", "The default device", byDefault ? cdmShort(byDefault) : ""),
        opt("none", "No CDM", "No DRM, nothing to decrypt")] : []),
      ...[["Widevine", (d) => !d.remote && d.kind === "Widevine"], ["PlayReady", (d) => !d.remote && d.kind === "PlayReady"], ["Remote", (d) => d.remote]]
        .flatMap(([name, kind]) => {
          const found = devices.filter(kind).filter(fits);
          return found.length ? [el("small", { className: "cdm-pop-h", textContent: name }),
            ...found.map((d) => opt(d.name, cdmShort(d), d.used_by.length ? `Used by ${d.used_by.join(", ")}` : ""))] : [];
        }));
    if (!list.children.length) list.append(el("p", { className: "muted", textContent: "No device matches." }));
  };
  q.oninput = draw;
  draw();
  const who = service === "default" ? "The default device" : `Device for ${[service, ...also].map(svcName).join(", ")}`;
  if (cdmPopAt(anchor, el("b", { className: "cdm-pop-t", textContent: who }), q, list)) q.focus();
}
const cdmCard = (svg, title, text, extra, ...body) => el("div", { className: "sx-card" },
  el("div", { className: "sx-head" }, el("span", { className: "sx-ico", ariaHidden: "true", innerHTML: svg }),
    el("div", {}, el("h3", { textContent: title }), el("p", { textContent: text })), ...(extra ? [extra] : [])), ...body);
/* No device to list: what was asked for named, with a way back to the whole list. */
function emptyDevices(known) {
  if (!known) return el("p", { className: "muted cdm-empty", textContent: "No device yet: add a .wvd or .prd file." });
  const label = { Widevine: "Widevine", PlayReady: "PlayReady", used: "In use", problems: "Problems" }[cdmFilter];
  const typed = cdmQuery.trim();
  const text = typed && label ? `No device under ${label} matches “${typed}”.` : typed ? `No device matches “${typed}”.`
    : label ? `No device under ${label}.` : "No device matches.";
  return el("div", { className: "cdm-empty", role: "status" }, el("p", { className: "muted", textContent: text }),
    ...(typed ? [el("button", { type: "button", className: "btn small", textContent: "Clear search", onclick: () => { cdmQuery = ""; renderCdm(); $("#cdm-list .con-search")?.focus(); } })] : []),
    ...(label ? [el("button", { type: "button", className: "btn small", textContent: "Show all", onclick: () => { cdmFilter = "all"; renderCdm(); $("#cdm-list .con-filters [aria-pressed=true]")?.focus(); } })] : []));
}
function renderCdm(typing = false) {  // typing: in the search box, whose own element must stay
  const data = cdmData;
  $("#cdm-folder").textContent = data.folder || "";
  $("#cdm-add").hidden = !data.folder;
  const state = $("#cdm-state");
  const show = (cls, b, small) => { state.className = `sx-state ${cls}`; state.querySelector("b").textContent = b; state.querySelector("small").textContent = small; };
  if (!data.folder && S.config.settings.unshackle_mode === "remote") { show("", "Managed where Unshackle runs", ""); $("#cdm-alerts").replaceChildren(); $("#cdm-hero-test").replaceChildren();
    return $("#cdm-list").replaceChildren(el("p", { className: "muted", textContent: "To manage its devices here too, mount the folder of its unshackle.yaml and set its path in Settings, Unshackle, Folders." })); }
  if (!data.folder) { show("down", "No CDM folder", ""); $("#cdm-alerts").replaceChildren(); $("#cdm-hero-test").replaceChildren(); return $("#cdm-list").replaceChildren(el("p", { className: "status-err", textContent: data.error })); }
  const all = [...data.devices, ...data.remote.map((r) => ({ ...r, remote: true }))];
  const deviceOf = (name) => all.find((d) => d.name === name);
  const problem = (d) => d.info?.unreadable || (d.test && !d.test.ok);
  // Services, grouped by the device they use: one line a device, a service's chip to change its own
  const inSeries = Object.values(S.config.series).map((c) => c.service).filter(Boolean);
  const shown = [...new Set([...Object.keys(data.map).filter((k) => k.toLowerCase() !== "default"), ...inSeries])]
    .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  const current = (svc) => data.map[Object.keys(data.map).find((k) => k.toLowerCase() === svc.toLowerCase())];
  const chip = (svc, now) => el("button", { type: "button", className: "cdm-chip cdm-pop-btn", dataset: { key: `svc:${svc}` }, textContent: svcName(svc),
    title: `Change the device ${svcName(svc)} uses`, onclick: (e) => cdmPicker(e.currentTarget, svc, now) });
  const deviceCell = (name) => {
    if (name === "none") return el("span", { className: "cdm-to" }, el("b", { textContent: "No CDM" }), el("small", { textContent: "no DRM: no device used" }));
    const d = deviceOf(name);
    return el("span", { className: `cdm-to${d ? "" : " bad"}` }, el("b", { textContent: d ? cdmShort(d) : name }),
      el("small", { textContent: d ? (problem(d) ? cdmStatus(d)[1] : d.name) : "not in the CDM folder: pick another" }));
  };
  const groups = new Map();
  const rules = [], onDefault = [];
  for (const svc of shown) {
    const v = current(svc);
    if (v && typeof v === "object") rules.push([svc, v]);
    else if (v) groups.set(v, [...(groups.get(v) || []), svc]);
    else onDefault.push(svc);
  }
  const def = typeof data.map.default === "string" ? data.map.default : "";
  const defButton = el("button", { type: "button", className: "btn small cdm-pop-btn", dataset: { key: "svc:default" }, textContent: "Change",
    onclick: (e) => cdmPicker(e.currentTarget, "default", def) });
  const others = data.services.filter((t) => !shown.some((x) => x.toLowerCase() === t.toLowerCase()) && t !== "EXAMPLE");
  const addSvc = el("button", { type: "button", className: "btn small cdm-pop-btn", dataset: { key: "add" }, textContent: "+ Another service", onclick: (e) => {
    const anchor = e.currentTarget, q = el("input", { type: "search", className: "cdm-pop-search", placeholder: "Search a service" }), list = el("div", { className: "cdm-pop-list" });
    const draw = () => list.replaceChildren(...others.filter((t) => `${t} ${svcName(t)}`.toLowerCase().includes(q.value.trim().toLowerCase()))
      .map((t) => el("button", { type: "button", className: "cdm-opt", onclick: () => { closeCdmPop(); anchor.dataset.key = `svc:${t}`; cdmPicker(anchor, t, ""); } }, el("b", { textContent: svcName(t) }))));
    q.oninput = draw; draw();
    if (cdmPopAt(anchor, el("b", { className: "cdm-pop-t", textContent: "A device of its own for…" }), q, list)) q.focus();
  } });
  const services = el("div", { className: "cdm-svcs-box" },
    el("div", { className: "cdm-grp cdm-default" }, el("span", { className: "cdm-lbl", textContent: "Default" }), deviceCell(def), defButton),
    ...[...groups.entries()].sort((a, b) => b[1].length - a[1].length).map(([name, svcs]) =>
      el("div", { className: `cdm-grp${deviceOf(name) || name === "none" ? "" : " bad"}` }, el("span", { className: "cdm-chips" }, ...svcs.map((svc) => chip(svc, name))), deviceCell(name))),
    ...(onDefault.length ? [el("div", { className: "cdm-grp cdm-fold" }, el("span", { className: "cdm-chips" }, ...onDefault.map((svc) => chip(svc, ""))),
      el("span", { className: "cdm-to" }, el("small", { textContent: onDefault.length === 1 ? "uses the default device" : "use the default device" })))] : []),
    ...rules.map(([svc, v]) => el("div", { className: "cdm-grp" }, el("span", { className: "cdm-chips" }, el("span", { className: "cdm-chip static", textContent: svcName(svc) })),
      el("span", { className: "cdm-to" }, el("small", { textContent: `Set by a rule by profile, quality or DRM (${v.rule.join(", ")}): edit it in unshackle.yaml` })))),
    ...(others.length ? [el("div", { className: "cdm-add-svc" }, addSvc)] : []));
  // What needs you: a service on a device that is not there, a device in use that failed its test
  const alerts = [
    ...[def, ...groups.keys()].filter((name) => name && name !== "none" && !deviceOf(name)).map((name) => {
      const svcs = name === def ? ["the default"] : groups.get(name);
      const fix = el("button", { type: "button", className: "btn small primary cdm-pop-btn", dataset: { key: `fix:${name}` }, textContent: "Pick a device",
        onclick: (e) => name === def ? cdmPicker(e.currentTarget, "default", name) : cdmPicker(e.currentTarget, svcs[0], name, svcs.slice(1)) });
      return el("div", { className: "cdm-alert" }, el("span", {}, el("b", { textContent: svcs.join(", ") }), svcs.length === 1 ? ` uses ${name}, which is not in the CDM folder` : ` use ${name}, which is not in the CDM folder`), fix);
    }),
    ...data.devices.filter((d) => d.used_by.length && problem(d)).map((d) => el("div", { className: "cdm-alert" },
      el("span", {}, el("b", { textContent: cdmShort(d) }), `, used by ${d.used_by.join(", ")}: ${cdmStatus(d)[2]}`))),
  ];
  // Devices: one line each, those in use or in trouble first, the others folded
  const matches = (d) => ({ all: true, Widevine: d.kind === "Widevine", PlayReady: d.kind === "PlayReady", used: d.used_by.length > 0, problems: problem(d) }[cdmFilter])
    && (!cdmQuery.trim() || `${d.name} ${cdmTitle(d)} ${d.used_by.join(" ")}`.toLowerCase().includes(cdmQuery.trim().toLowerCase()));  // the same trimmed query the empty line names
  const found = data.devices.filter(matches).sort((a, b) => (b.used_by.length > 0) - (a.used_by.length > 0) || (cdmTesting ? 0 : (problem(b) ? 1 : 0) - (problem(a) ? 1 : 0)));  // no jumping about while a batch is tested
  const folding = cdmFilter === "all" && !cdmQuery.trim() && !cdmShowUnused;
  const list = folding ? found.filter((d) => d.used_by.length || problem(d)) : found;
  const folded = found.length - list.length;
  const counts = { all: data.devices.length, Widevine: data.devices.filter((d) => d.kind === "Widevine").length,
    PlayReady: data.devices.filter((d) => d.kind === "PlayReady").length, used: data.devices.filter((d) => d.used_by.length).length, problems: data.devices.filter(problem).length };
  const filters = el("div", { className: "con-filters", role: "group", ariaLabel: "Show" }, ...[["all", "All"], ["Widevine", "Widevine"], ["PlayReady", "PlayReady"], ["used", "In use"], ["problems", "Problems"]]
    .map(([k, t]) => el("button", { ariaPressed: String(cdmFilter === k), textContent: `${t} (${counts[k]})`, onclick: () => { cdmFilter = k; renderCdm(); } })));
  const search = el("input", { type: "search", className: "con-search", placeholder: "Search a device, a maker, a service", value: cdmQuery, ariaLabel: "Search the devices" });
  search.oninput = () => { cdmQuery = search.value; renderCdm(true); };
  const testable = found.filter((d) => !d.info?.unreadable && !d.folder);
  const inUse = data.devices.filter((d) => d.used_by.length && !d.info?.unreadable && !d.folder);
  const off = Boolean(cdmTesting || cdmRunning.size || data.details_error);
  const testAll = el("button", { id: "cdm-test-all", className: "btn small", textContent: cdmTesting ? `Testing ${cdmTesting}…` : `Test ${testable.length === data.devices.length ? "all" : "these"} (${testable.length})`,
    disabled: off || !testable.length, onclick: () => testCdms(testable) });
  $("#cdm-hero-test").replaceChildren(...(inUse.length ? [el("button", { className: "btn small", textContent: cdmTesting ? `Testing ${cdmTesting}…` : `Test the ${inUse.length} in use`, disabled: off, onclick: () => testCdms(inUse) })] : []));
  const actions = (d, anchor) => {
    const item = (text, run, extra = {}) => el("button", { type: "button", className: `cdm-opt${extra.danger ? " danger" : ""}`, disabled: !!extra.disabled, title: extra.title || "", onclick: run }, el("b", { textContent: text }),
      ...(extra.sub ? [el("small", { textContent: extra.sub })] : []));
    const test = item("Test", () => { closeCdmPop(); testCdm(d); },
      { disabled: d.info?.unreadable || d.folder || data.details_error || cdmTesting || cdmRunning.has(d.name), sub: "A license from a test server" });
    const reprov = d.kind === "PlayReady" && d.info?.reprovisionable ? item("Reprovision", async (e) => {
      const b = e.currentTarget;
      if (!confirmClick(b, `Reprovision ${cdmShort(d)}?`, b.querySelector("b"))) return;
      closeCdmPop(); toast(`${cdmShort(d)}: reprovisioning…`);
      try {
        const r = await api("/api/cdm/reprovision", { method: "POST", wait: 90, body: JSON.stringify({ name: d.name }) });
        cdmData = r.state;
        const fresh = cdmData.devices.find((x) => x.kind === d.kind && x.name === d.name);
        if (fresh) await testCdm(fresh);
        renderCdm();
        toast(`${cdmShort(d)}: reprovisioned, the old file kept as ${r.backup}`);
      } catch (err) { toast(err.message, true); }
    }, { sub: "New keys, from its group key" }) : "";
    const del = item("Delete", async (e) => {
      const b = e.currentTarget;
      if (!confirmClick(b, `Delete ${cdmShort(d)}?`, b.querySelector("b"))) return;
      closeCdmPop();
      try { cdmData = await api("/api/cdm/delete", { method: "POST", body: JSON.stringify({ name: d.name, kind: d.kind }) }); renderCdm(); }
      catch (err) { toast(err.message, true); }
    }, { danger: true, disabled: d.used_by.length > 0, sub: d.used_by.length ? "In use: move its services first" : "" });
    cdmPopAt(anchor, el("b", { className: "cdm-pop-t", textContent: cdmShort(d), title: cdmShort(d) }), el("div", { className: "cdm-pop-list" }, test, reprov, del))?.classList.add("menu");
    placeCdmPop();
  };
  const row = (d) => {
    const [tone, word, why] = cdmRunning.has(d.name) ? ["run", "Testing…", "Asking the test server for a license"] : cdmStatus(d);
    const menu = el("button", { type: "button", className: "jact cdm-pop-btn", dataset: { key: `dev:${d.name}` }, title: "Actions", ariaLabel: `Actions for ${cdmTitle(d)}`, onclick: (e) => actions(d, e.currentTarget) });
    menu.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>';
    const lvl = d.info?.level || d.level;
    const fold = () => { cdmOpen.has(d.name) ? cdmOpen.delete(d.name) : cdmOpen.add(d.name); renderCdm(); };
    return el("div", { className: `cdm-dev t-${tone}${cdmOpen.has(d.name) ? " open" : ""}${cdmJust.has(d.name) ? " just" : ""}`, tabIndex: 0, role: "button",
      ariaExpanded: String(cdmOpen.has(d.name)),
      // the row unfolds its details; not its buttons, nor a click in the details (their text can be selected)
      onclick: (e) => { if (!e.target.closest("button, .cdm-more") && !getSelection().toString()) fold(); },
      onkeydown: (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) { e.preventDefault(); fold(); } } },
      el("span", { className: "dot", title: why, ariaHidden: "true" }),
      el("span", { className: "who" }, el("b", { textContent: cdmTitle(d).replace(/^(.{6,}?)\s+\1\b/i, "$1") }),
        el("small", { textContent: d.folder ? `${d.name}/` : `${d.name}.${d.kind === "Widevine" ? "wvd" : "prd"}` })),
      el("span", { className: "kind" }, el("i", { textContent: `${d.kind === "PlayReady" ? "PlayReady" : "Widevine"}${lvl ? ` ${lvl}` : ""}` }), ...(d.info?.vmp ? [el("i", { textContent: "VMP" })] : [])),
      el("span", { className: "used" }, ...(d.used_by.length ? d.used_by.map((u) => el("span", { className: "cdm-chip static", textContent: u.toLowerCase() === "default" ? "default" : u }))
        : [el("small", { textContent: "not in use" })])),
      el("span", { className: `st ${tone}`, title: why, textContent: word }),
      menu,
      ...(cdmOpen.has(d.name) ? [el("div", { className: "cdm-more" }, ...(d.test && !d.test.ok ? [el("p", { className: `why ${tone}`, textContent: why })] : []), cdmDetails(d))] : []));
  };
  // Where things stand, in the header: what needs you first, else how the devices in use last tested
  const used = data.devices.filter((d) => d.used_by.length), untested = used.filter((d) => !d.test && !d.info?.unreadable);
  const facts = [COUNT.device(data.devices.length), `${used.length} in use`, ...(data.remote.length ? [`${data.remote.length} remote`] : [])].join(" · ");
  if (alerts.length) show("down", `${COUNT.problem(alerts.length)} to fix`, facts);
  else if (!data.devices.length && !data.remote.length) show("", "No device yet", "Add a .wvd or .prd file");
  else if (untested.length) show("", `${COUNT.device(untested.length)} in use not tested yet`, facts);
  else show("ok", used.length ? "The devices in use work" : "Nothing in use", facts);
  $("#cdm-alerts").replaceChildren(...alerts);
  const plus = el("button", { type: "button", className: "btn small", textContent: "+ Add a remote CDM", onclick: () => editRemote(null) });
  const devices = el("div", { id: "cdm-devices", className: "cdm-devs" }, ...(list.length ? list.map(row) : [emptyDevices(data.devices.length)]),
    ...(folded ? [el("button", { type: "button", className: "cdm-more-btn", textContent: `Show ${COUNT.moreDevice(folded)}, not in use`, onclick: () => { cdmShowUnused = true; renderCdm(); } })] : []));
  // Typing keeps the search box itself (a new one would put the cursor at the end and break an input method's composition): only what it filters is drawn again
  if (typing && $("#cdm-devices")) { $("#cdm-devices").replaceWith(devices); $("#cdm-test-all").replaceWith(testAll); return; }
  $("#cdm-list").replaceChildren(
    cdmCard('<svg viewBox="0 0 24 24"><path d="M4 7h10M4 12h6M4 17h10"/><path d="m15 9 4 3-4 3"/></svg>', "Which device each service uses",
      "Click a service to move it to another device. A change applies to the next download.", null, services),
    cdmCard('<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>', "Devices",
      "The .wvd and .prd files in the CDM folder. Click one for its details; a test asks the DRM's test server for a license.", null,
      ...(data.details_error ? [el("p", { className: "cdm-note", textContent: `${data.details_error}. The list below comes from the files alone.` })] : []),
      el("div", { className: "cdm-tools" }, search, testAll),
      filters,
      devices),
    cdmCard('<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/></svg>', "Remote CDMs",
      "A device on a server: pywidevine serve, a PlayReady API, Decrypt Labs. Saved in unshackle.yaml.", plus,
      ...(data.remote.length ? [el("div", { className: "cdm-devs" }, ...data.remote.map(remoteRow))] : [])));
}
/* A remote CDM: a device on a server, named in unshackle.yaml's remote_cdm; changed from the page, its secret never shown. */
function remoteRow(r) {
  const menu = el("button", { type: "button", className: "jact cdm-pop-btn", dataset: { key: `remote:${r.name}` }, title: "Actions", ariaLabel: `Actions for ${r.name}`, onclick: (e) => {
    const item = (text, run, extra = {}) => el("button", { type: "button", className: `cdm-opt${extra.danger ? " danger" : ""}`, disabled: !!extra.disabled, onclick: run },
      el("b", { textContent: text }), ...(extra.sub ? [el("small", { textContent: extra.sub })] : []));
    const del = item("Delete", async (ev) => {
      const b = ev.currentTarget;
      if (!confirmClick(b, `Remove ${r.name} from unshackle.yaml?`, b.querySelector("b"))) return;
      closeCdmPop();
      try { cdmData = await api("/api/cdm/remote-delete", { method: "POST", body: JSON.stringify({ name: r.name }) }); renderCdm(); }
      catch (err) { toast(err.message, true); }
    }, { danger: true, disabled: r.used_by.length > 0, sub: r.used_by.length ? "In use: move its services first" : "" });
    cdmPopAt(e.currentTarget, el("b", { className: "cdm-pop-t", textContent: r.name }), el("div", { className: "cdm-pop-list" },
      item("Edit", () => { closeCdmPop(); editRemote(r); }, { disabled: !r.editable, sub: r.editable ? "" : `A ${r.type} remote CDM: change it in unshackle.yaml` }), del))?.classList.add("menu");
    placeCdmPop();
  } });
  menu.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>';
  const where = [r.host ? r.host.replace(/^https?:\/\//, "") : "", r.device_name].filter(Boolean).join(" · ");
  return el("div", { className: "cdm-dev t-mut" }, el("span", { className: "dot", ariaHidden: "true" }),
    el("span", { className: "who" }, el("b", { textContent: r.name }), el("small", { textContent: where || r.label })),
    el("span", { className: "kind" }, el("i", { textContent: r.label })),
    el("span", { className: "used" }, ...(r.used_by.length ? r.used_by.map((u) => el("span", { className: "cdm-chip static", textContent: u })) : [el("small", { textContent: "not in use" })])),
    el("span", { className: "st", textContent: r.has_secret ? "key saved" : "" }), menu);
}
function editRemote(r) {
  const dialog = $("#remote-dialog"), form = dialog.querySelector("form");
  $("#remote-title").textContent = r ? `Remote CDM ${r.name}` : "A new remote CDM";
  const f = form.elements;
  f.name.value = r?.name || "";
  f.type.value = r?.type && r.editable ? r.type : "widevine";
  f.host.value = r?.host || "";
  f.secret.value = "";
  f.secret.placeholder = r?.has_secret ? "Saved: leave empty to keep it" : "";
  f.device_name.value = r?.device_name || "";
  f.device_type.value = r?.device_type && r.device_type !== "PLAYREADY" ? r.device_type : "ANDROID";
  f.system_id.value = r?.system_id ?? "";
  f.security_level.value = r?.security_level ?? "";
  const shape = () => {  // the fields each kind takes
    const kind = f.type.value;
    form.querySelectorAll("[data-for]").forEach((x) => x.hidden = !x.dataset.for.split(" ").includes(kind));
    $("#remote-host-help").textContent = kind === "playready" ? "Ends in /playready (pyplayready adds its own paths to it)"
      : kind === "decrypt_labs" ? "Empty: keyxtractor.decryptlabs.com" : "The pywidevine serve address";
    f.device_name.placeholder = kind === "decrypt_labs" ? "L1, L2, ChromeCDM (Widevine) or SL2, SL3 (PlayReady)" : "The device's name on the server";
  };
  f.type.onchange = shape;
  shape();
  $("#remote-error").textContent = "";
  form.onsubmit = async (e) => {
    e.preventDefault();
    const values = Object.fromEntries(["name", "type", "host", "secret", "device_name", "device_type", "system_id", "security_level"].map((k) => [k, f[k].value.trim()]));
    try {
      cdmData = await api("/api/cdm/remote-save", { method: "POST", body: JSON.stringify({ form: values, was: r?.name || null }) });
      dialog.close();
      renderCdm();
      toast(`${values.name}: saved in unshackle.yaml`);
    } catch (err) { $("#remote-error").textContent = err.message; }
  };
  dialog.showModal();
  f.name.focus();
}
$("#remote-cancel").onclick = () => $("#remote-dialog").close();
$("#cdm-add").onclick = () => $("#cdm-file").click();
$("#cdm-file").onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin = "";
  bytes.forEach((b) => { bin += String.fromCharCode(b); });
  try { loadCdm(await api("/api/cdm/add", { method: "POST", body: JSON.stringify({ filename: file.name, data: btoa(bin) }) })); toast(`${file.name} added`); }
  catch (err) { toast(err.message, true); }
};

