/* Settings sections: one shown at a time, remembered in the URL. On a phone,
   #/settings is the list of sections, and a section is a page of its own that goes back to it. */
const LEGACY_SETTINGS_MAP = {
  sonarr:        { sec: "connections", anchor: "sonarr-sec", load: () => renderSonarrState() },
  unshackle:     { sec: "connections", anchor: "unshackle-sec", load: () => loadUnshackleStatus() },
  downloads:     { sec: "downloading", anchor: "downloads-sec" },
  automation:    { sec: "downloading", anchor: "automation-sec", load: () => { renderAutomation(); renderImportMode(); renderLearnWindow(); } },
  quality:       { sec: "quality-upgrades", anchor: "quality-sec", load: () => renderQuality() },
  upgrades:      { sec: "quality-upgrades", anchor: "upgrades-sec", load: () => { renderUpgradeSeries(); return renderUpgradeGroups(); } },
  services:      { sec: "services-devices", anchor: "services-sec", load: () => loadServices() },
  cookies:       { sec: "services-devices", anchor: "services-sec" },
  cdm:           { sec: "services-devices", anchor: "cdm-sec", load: () => loadCdm() },
  notifications: { sec: "notifications", anchor: "notifications-sec", load: () => { renderPush().catch(() => {}); loadSent(); } },
  interface:     { sec: "general", anchor: "interface-sec", load: () => renderInterface() },
  region:        { sec: "general", anchor: "region-sec", load: () => renderRegion() },
  history:       { sec: "general", anchor: "history-sec", load: () => loadHistory() },
  account:       { sec: "general", anchor: "account-sec", load: () => loadAccount() },
};
const settingsPages = Object.values(LEGACY_SETTINGS_MAP);
const legacySettings = (name) => Object.hasOwn(LEGACY_SETTINGS_MAP, name) ? LEGACY_SETTINGS_MAP[name] : null;
let settingsSec = "connections", settingsRoute = settingsSec, settingsList = false, secFromList = false;
let loadedSettings = null, settingsAnchor = null, settingsAnchorObserver = null;
const inSettingsSec = () => currentTab === "settings" && !settingsList;  // a section on screen, not the phone's list
const showingSettings = (name) => inSettingsSec() && legacySettings(name)?.sec === settingsSec;
const settingsHref = (name) => `#/settings/${name}`;
function clearSettingsAnchor() {
  settingsAnchorObserver?.disconnect();
  settingsAnchorObserver = settingsAnchor = null;
}
function loadSettingsSec() {
  if (!inSettingsSec() || !S.config.settings || loadedSettings?.sec === settingsSec) return;
  const entry = loadedSettings = { sec: settingsSec };
  const pending = [];
  for (const page of settingsPages) {
    if (page.sec !== entry.sec) continue;
    const task = page.load?.();
    if (task?.then) pending.push(task.catch(console.error));
  }
  Promise.all(pending).then(() => {
    entry.settled = true;
    if (loadedSettings !== entry) return;
    settingsAnchor?.scrollIntoView({ block: "start" });
    clearSettingsAnchor();
  });
}
function leaveSettingsSec() {
  loadedSettings = null;
  clearSettingsAnchor();
  leaveSettingsNews(settingsSec);
}
function showSettingsList(on) {
  const fromSec = on && phoneLayout() && inSettingsSec();
  if (fromSec) leaveSettingsSec();
  else if (on) clearSettingsAnchor();
  settingsList = on && phoneLayout();
  $(".set-layout").classList.toggle("at-list", settingsList);
  if (fromSec) document.querySelector(`.set-nav [data-sec="${settingsSec}"]`).focus({ preventScroll: true });  // the item it came from
}
function showSettingsSec(name, fromRoute = false, push = false, target = null) {
  const page = legacySettings(name), sec = page?.sec || (settingsPages.some((item) => item.sec === name) ? name : "connections");
  const changedSection = sec !== settingsSec;
  if (changedSection && inSettingsSec()) leaveSettingsSec();
  clearSettingsAnchor();
  const fromList = settingsList;
  if (changedSection || fromList) secFromList = fromList && !fromRoute;
  showSettingsList(false);
  settingsSec = sec;
  settingsRoute = page ? name : sec;
  document.querySelectorAll(".set-sec").forEach((x) => x.hidden = x.dataset.sec !== sec);
  document.querySelectorAll(".set-nav [data-sec]").forEach((x) => x.setAttribute("aria-current", x.dataset.sec === sec));
  loadSettingsSec();
  if (!fromRoute && inSettingsSec()) { navigate(push || fromList); updateTitle(); }
  const anchor = (target && document.querySelector(target)) || (page && document.getElementById(page.anchor));
  if (anchor) {
    const fold = anchor.closest("details");
    if (fold) fold.open = true;
    anchor.scrollIntoView({ block: "start" });
    const heading = [...anchor.querySelectorAll("h2, h3, h4, label")].find((node) =>
      node.getClientRects().length && !node.closest("[hidden], details:not([open])"));
    focusHeading(heading || anchor);
    if (!loadedSettings?.settled) {
      settingsAnchor = anchor;
      // Startup health renders can resize the section before its own loaders finish.
      settingsAnchorObserver = new ResizeObserver(() => settingsAnchor?.scrollIntoView({ block: "start" }));
      settingsAnchorObserver.observe(anchor.closest(".set-sec"));
    }
  } else if (changedSection || fromList || !fromRoute) {
    scrollTo({ top: 0 });
    focusHeading($(`.set-sec[data-sec="${sec}"] h2`));
  }
}
function openSettings(name, target) {
  const fromTab = currentTab !== "settings";
  if (fromTab) showTab("settings", true);
  if (currentTab === "settings") showSettingsSec(name, false, fromTab, target);
}
document.querySelectorAll(".set-nav [data-sec]").forEach((x) => x.onclick = () => showSettingsSec(x.dataset.sec));
$("#tab-settings").addEventListener("click", (e) => {
  const link = e.target.closest(".set-jumps a");
  if (!link || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  showSettingsSec(link.hash.split("/").pop());
});
$("#set-back").onclick = () => {
  if (secFromList) return history.back();  // the list is the page before: the phone's back does the same
  showSettingsList(true);
  navigate(false);
  updateTitle();
  scrollTo({ top: 0 });
};
/* The URL holds where you are (#/schedule, #/series/s/111421/settings…): a refresh
   lands on the same page, and back (or the phone's back gesture) closes a series. */
let currentTab = "schedule", drawerTab = null, drawerPushed = false;
const HASH_OF = { log: "activity", yaml: "unshackle.yaml" }, TAB_OF = { activity: "log", terminal: "log", defaults: "settings", "unshackle.yaml": "yaml" };  // #/terminal: its name before
function routeHash() {
  const hash = inSettingsSec() ? settingsHref(settingsRoute) : `#/${HASH_OF[currentTab] || currentTab}`;
  return hash + (current ? `/s/${current.tvdbId}/${drawerTab}` : "");
}
function navigate(push) {
  const hash = routeHash();
  if (location.hash !== hash) history[push ? "pushState" : "replaceState"](null, "", hash);
}
function parseRoute() {
  let [tab, ...rest] = location.hash.replace(/^#\/?/, "").split("/");
  const name = TAB_OF[tab] || tab;
  const sec = name === "settings" && rest[0] !== "s" ? rest.shift() : null;
  const [s, id, view] = rest;
  return { tab: ["series", "schedule", "settings", "log", "yaml"].includes(name) ? name : "schedule", id: s === "s" ? id : null, view, sec };
}
/* The tab's title says where you are: the page, a series (open over any page), a Settings section. */
const PAGE_NAME = { schedule: "Schedule", series: "Series", log: "Activity", settings: "Settings", yaml: "unshackle.yaml" };
function updateTitle() {
  if (document.body.classList.contains("gated")) return;  // the sign-in and the setup name themselves
  const section = currentTab === "settings" && !settingsList && $(`.set-nav [data-sec="${settingsSec}"] span`)?.textContent;
  document.title = current?.title?.trim() ? tr(`${current.title} · Unshacklarr`)
    : section ? tr(`Settings: ${section} · Unshacklarr`) : tr(`${PAGE_NAME[currentTab]} · Unshacklarr`);
}
let routed = false;
function applyRoute() {
  if (location.hash.startsWith("#/inbox")) {  // a push notification touched: the bell's list over the current page
    history.replaceState(null, "", `#/${HASH_OF[currentTab] || currentTab}`);
    openInbox();
  }
  const route = parseRoute();
  const alreadyOpen = inSettingsSec() && route.sec === settingsRoute;
  if (!routed || route.tab !== currentTab) showTab(route.tab, true);  // closing a series keeps its tab as it was
  if (route.sec) {
    if (alreadyOpen) loadSettingsSec();  // the initial state arrived after the URL was shown
    else showSettingsSec(route.sec, true);
  } else if (route.tab === "settings") { showSettingsList(true); loadSettingsSec(); }
  routed = true;
  const series = route.id && S.series.find((x) => String(x.tvdbId) === route.id);
  if (series && current?.tvdbId !== series.tvdbId) openDrawer(series, route.view, true);
  else if (series && route.view) showDrawerTab(route.view, true);
  else if (!series && current) closeDrawer(true);
  updateTitle();
}
window.addEventListener("popstate", applyRoute);
// Startup can scroll without user input; only input should interrupt a jump that is still loading.
for (const event of ["wheel", "touchmove", "pointerdown"]) {
  window.addEventListener(event, (e) => { if (e.isTrusted) clearSettingsAnchor(); }, { passive: true });
}
window.addEventListener("keydown", (e) => {
  if (e.isTrusted && ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " ", "Tab"].includes(e.key)) clearSettingsAnchor();
});

// The page's scroll padding, so focus stops clear of what is pinned: the header as tall as it is (a status row under it
// makes it taller), and how far up the bars pinned to the bottom reach, stacked, wrapped or expanded as they are now.
// By each bar's own offset and height, not where it is now: a sticky bar is measured where it sticks.
const BOTTOM_BARS = ['nav[aria-label="Main"]', "#savebar", "#sel-bar", "#dock", "#ep-bar"].map((sel) => $(sel));
function measureBars() {
  // first: the bars standing on the save bar take their place from it, and their reach is read below
  document.documentElement.style.setProperty("--save-h", `${$("#savebar").offsetHeight}px`);
  const reach = BOTTOM_BARS.map((bar) => bar.offsetHeight && bar.offsetHeight + (parseFloat(getComputedStyle(bar).bottom) || 0));
  document.documentElement.style.setProperty("--head-h", `${$("header").offsetHeight}px`);
  document.documentElement.style.setProperty("--bars-h", `${Math.max(...reach) + 8}px`);
  // a wide Activity pane scrolls itself, and its dock sticks above the pane's own bottom padding
  const pane = parseFloat(getComputedStyle($("#con-detail")).paddingBottom) || 0;
  document.documentElement.style.setProperty("--dock-h", `${reach[BOTTOM_BARS.indexOf($("#dock"))] + pane + 8}px`);
}
const barsSeen = new ResizeObserver(measureBars);
[$("header"), ...BOTTOM_BARS].forEach((n) => barsSeen.observe(n));
function showTab(name, fromRoute = false, quiet = false) {
  if (currentTab === "yaml" && name !== "yaml") {  // leaving the editor: it forgets the password and the file
    if (uyDirty() && !confirm("Leave unshackle.yaml without saving your changes?")) { if (fromRoute) navigate(true); return; }
    uyReset();
  }
  if (name !== currentTab && inSettingsSec()) leaveSettingsSec();
  if (name === "settings" && !fromRoute) showSettingsList(true);  // a phone: the Settings tab opens on its list
  currentTab = name;
  closeDetails(false);  // the Schedule's popover belongs to its card
  updateTitle();  // after the list is chosen: a phone's Settings tab names the list, not the section it left
  document.querySelectorAll("nav [data-tab]").forEach((b) => {
    if (b.dataset.tab === (name === "yaml" ? "settings" : name)) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  document.querySelectorAll("main > section").forEach((s) => s.hidden = s.id !== "tab-" + name);
  if (!fromRoute) navigate(true);
  if (quiet) return;
  if (name === "log") { refreshLog(); openActivity(); }
  else if (termSocket) { termSocket.close(); termSocket = null; termFor = null; termQuery = ""; }  // Activity left: its output stops streaming
  if (name === "settings" && !fromRoute) loadSettingsSec();
  if (name === "schedule") loadSchedule();
}
document.querySelectorAll("nav [data-tab]").forEach((b) => b.onclick = (e) => {
  if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;  // a new tab or window: the browser opens the link
  e.preventDefault();
  if (b.dataset.tab === "log") landOnLive = true;
  showTab(b.dataset.tab);
});
// the hash is the route: the skip link moves the focus itself and leaves the URL as it is
$(".skip").onclick = (e) => { e.preventDefault(); $("main").focus(); };
let wallTimer = null;  // typed: the wall drawn once the typing pauses, not at each key
$("#search").oninput = () => { clearTimeout(wallTimer); wallTimer = setTimeout(renderWall, 150); };
document.querySelectorAll("#tab-series .seg button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("#tab-series .seg button").forEach((x) => x.setAttribute("aria-pressed", x === b));
  renderWall();
});
["#f-service", "#f-library", "#f-sort", "#f-missing", "#f-monitored"].forEach((id) => $(id).onchange = renderWall);

function bindSeriesOptions() {
  const toggle = $("#series-options-toggle");
  const options = $("#series-options");
  const toolbar = $("#tab-series .toolbar");
  const narrow = matchMedia("(max-width: 700px)");
  const syncControls = () => toggle.setAttribute("aria-controls", narrow.matches ? "series-options" : "series-actions");
  syncControls();
  narrow.addEventListener("change", syncControls);
  const inDisclosure = (target) => target === toggle || options.contains(target);
  const expanded = () => toggle.getAttribute("aria-expanded") === "true";
  const close = (restoreFocus = true) => {
    if (!expanded()) return false;
    toggle.setAttribute("aria-expanded", "false");
    if (restoreFocus) toggle.focus();
    return true;
  };
  toggle.onclick = () => toggle.setAttribute("aria-expanded", String(!expanded()));
  toolbar.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && inDisclosure(e.target) && close()) e.preventDefault();
  });
  toolbar.addEventListener("focusout", (e) => {
    if (e.relatedTarget && inDisclosure(e.target) && !inDisclosure(e.relatedTarget)) close(false);
  });
  options.addEventListener("click", (e) => {
    if (e.target.closest("#bulk-open, #sel-toggle")) close();
  }, true);  // Suggest's dialog must open after focus moves back to the visible trigger.
}
bindSeriesOptions();

/* The service filter lists only the services some series actually uses. */
function renderServiceFilter() {
  const used = [...new Set(Object.values(S.config.series).flatMap((c) => [c.service, ...Object.values(c.season_pages || {}).map((p) => p.service)]).filter(Boolean))].sort();
  const f = $("#f-service"), keep = f.value;
  f.querySelectorAll("option.svc-opt").forEach((o) => o.remove());
  const n = (t) => S.series.filter((s) => usesService(S.config.series[s.tvdbId], t)).length;
  f.options[0].textContent = `All services (${S.series.length})`;
  f.append(...used.map((t) => el("option", { className: "svc-opt", value: t, textContent: `${svcName(t)} (${n(t)})` })));
  f.value = [...f.options].some((o) => o.value === keep) ? keep : "";
  renderLibraryFilter();
}
/* The Sonarr library filter: shown once another Sonarr is set up; each with the number of series it shares. */
function renderLibraryFilter() {
  const f = $("#f-library"), keep = f.value, names = (S.config.settings?.sonarrs || []).map((i) => i.name);
  f.hidden = !names.length;
  const n = (name) => S.series.filter((s) => (S.sonarrsOf?.[s.tvdbId] || []).some((o) => o.name === name)).length;
  const main = S.series.filter((s) => s.id).length;
  f.querySelectorAll("option.lib-opt").forEach((o) => o.remove());
  f.options[0].textContent = `All libraries (${S.series.length})`;
  f.append(el("option", { className: "lib-opt", value: "-", textContent: `${mainSonarr()} (${main})` }),  // "-": the main one
    ...names.map((name) => el("option", { className: "lib-opt", value: name, textContent: `${name} (${n(name)})` })));
  f.value = [...f.options].some((o) => o.value === keep) ? keep : "";
}
window.addEventListener("beforeunload", (e) => { if (!$("#savebar").hidden) e.preventDefault(); });

showTab(parseRoute().tab, true, true);  // the right tab straight away, before the data comes
if (parseRoute().sec) showSettingsSec(parseRoute().sec, true);
else if (currentTab === "settings") showSettingsList(true);

/* Pull to reload, in the installed app (iPhone, Android): the browser gives it in a tab, not there. From the top of a
   page, pulled down far enough and let go: the page loads again. Not over an open window, nor from a list that
   scrolls on its own, nor with unsaved changes (said instead). A badge follows the finger, slowing down as a rubber
   band would, its ring filling up; past the mark it turns, and once let go it spins until the page is back. */
(() => {
  const PULL = 80, TRAVEL = 210;  // px pulled before letting go reloads; how far the badge could come down at most
  const RING = 2 * Math.PI * 15;  // the ring's length (r = 15)
  const tip = el("div", { className: "ptr", ariaHidden: "true" });
  tip.innerHTML = `<span class="ptr-badge"><svg viewBox="0 0 36 36"><circle class="ptr-track" cx="18" cy="18" r="15"/>
    <circle class="ptr-arc" cx="18" cy="18" r="15" stroke-dasharray="${RING}" stroke-dashoffset="${RING}"/></svg>
    <svg class="ptr-arrow" viewBox="0 0 24 24"><path d="M12 5v13M6 12l6 6 6-6"/></svg></span><span class="ptr-say"></span>`;
  document.body.append(tip);
  const arc = tip.querySelector(".ptr-arc"), say = tip.querySelector(".ptr-say");
  let startY = null, pulled = 0, ready = false;
  const scrolledInside = (node) => {
    for (let n = node; n && n !== document.body; n = n.parentElement)
      if (n.scrollTop > 0 && n.scrollHeight > n.clientHeight) return true;
    return false;
  };
  const show = () => {
    const y = TRAVEL * (1 - Math.exp(-pulled / 90));  // a rubber band: quick at first, slower and slower (126 px at the mark)
    tip.style.setProperty("--y", `${y}px`);
    arc.setAttribute("stroke-dashoffset", String(RING * (1 - Math.min(pulled / PULL, 1))));
    const now = pulled >= PULL;
    if (now !== ready) {
      ready = now;
      tip.classList.toggle("ready", ready);
      say.textContent = ready ? "Release to reload" : "Pull to reload";
      if (ready) navigator.vibrate?.(8);  // Android; an iPhone does not let a page do it
    }
  };
  addEventListener("touchstart", (e) => {
    startY = null;
    if (!standalone() || e.touches.length !== 1 || window.scrollY > 0 || document.querySelector("dialog[open]")
        || scrolledInside(e.target) || tip.classList.contains("loading")) return;
    startY = e.touches[0].clientY;
    pulled = 0; ready = false;
    tip.className = "ptr pulling";
    say.textContent = "Pull to reload";
  }, { passive: true });
  addEventListener("touchmove", (e) => {
    if (startY === null) return;
    if (window.scrollY > 0) { startY = null; tip.className = "ptr"; return; }
    pulled = Math.max(0, e.touches[0].clientY - startY);
    tip.classList.toggle("on", pulled > 6);
    show();
  }, { passive: true });
  addEventListener("touchend", () => {
    if (startY === null) return;
    startY = null;
    tip.classList.remove("pulling");  // from here it moves on its own, with a spring
    if (ready && unsaved) { tip.className = "ptr"; return toast("Save or discard your changes first", true); }
    if (!ready) { tip.className = "ptr"; return; }
    tip.className = "ptr on ready loading";
    say.textContent = "Reloading…";
    tip.style.setProperty("--y", "116px");
    setTimeout(() => location.reload(), 350);  // the spin seen a moment, then the page comes back
  }, { passive: true });
})();
