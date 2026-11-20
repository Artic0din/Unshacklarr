/* Schedule: Sonarr's calendar as a week board or a month grid, one chosen day for both.
   Episodes come from /api/calendar a week or a month at a time; the filter and views only re-render them. */
const EARLY_DAYS_MAX = 14;  // as in sync.py: a service puts an episode out up to two weeks before it airs
// date: the chosen day, the one Week and Month share; month: the first of the month the grid shows; pick: the day Month lists
const cal = { byDay: new Map(), date: null, month: null, pick: null, fetched: new Set(), placed: new Map() };

async function loadSchedule() {
  loadLate();
  renderHiddenButton();
  closeDetails(false);
  cal.byDay.clear(); cal.fetched.clear(); cal.placed.clear();
  $(".sched-tools").inert = false;
  await (schedView() === "month" ? loadMonth() : loadWeek());
}

async function loadLate() {
  let data;
  try { data = await api("/api/schedule"); }
  catch (e) { $("#next-sync").replaceChildren(failed(`Could not load the schedule: ${e.message}`, () => loadSchedule())); return; }
  const next = new Date(data.nextSync);
  $("#next-sync").textContent = trWith("Next sync at {0}", time(next));
  const newestFirst = [...data.missing].sort((a, b) => (b.airDateUtc || "").localeCompare(a.airDateUtc || ""));
  const names = newestFirst.map((d) => `${d.series} ${d.sxxeyy}`);
  $("#late-n").textContent = `${names.length} late`;
  const who = `${names.slice(0, 2).join(", ")}${names.length > 2 ? ` and ${names.length - 2} more` : ""}`;
  $("#late-sum").textContent = names.length > 1 ? `${who} aired but are not on the service yet. They are tried again at every sync for 14 days.`
    : `${who} aired but is not on the service yet. It is tried again at every sync for 14 days.`;
  $("#sched-missing").replaceChildren(...newestFirst.map((d) => schedCard({ ...d, fromLate: true }, d.airDateUtc ? day(new Date(d.airDateUtc)) : "")));
  $("#sched-late").hidden = !newestFirst.length;
  syncDetails();
}

const startOfDay = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; };
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const weekStartOf = (d) => addDays(startOfDay(d), -((d.getDay() + 6) % 7));  // Monday, whatever the clock did in between
const monthStartOf = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
const inMonth = (month, dom) => new Date(month.getFullYear(), month.getMonth(), Math.min(dom, new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()));
const dayOfKey = (key) => new Date(`${key}T00:00`);
const schedView = () => document.querySelector("[data-view][aria-pressed=true]").dataset.view;
const schedScope = () => document.querySelector(".sched-filter [aria-pressed=true]").dataset.scope;
const isHidden = (d) => S.config.hidden_series.includes(d.tvdbId);
const inScope = (d) => !isHidden(d) && ({ all: true, mine: d.managed, other: !d.managed })[schedScope()];

/* Hidden series: out of the calendar (not out of the downloads), saved at once. */
async function hideSeries(d, hidden, quiet = false) {
  try { S.config.hidden_series = await api("/api/hidden", { method: "POST", body: JSON.stringify({ tvdbId: d.tvdbId, hidden }) }); }
  catch (e) { return toast(`Could not ${hidden ? "hide" : "show"} ${d.series}: ${e.message}`, true); }
  if (!quiet) toast(hidden ? `${d.series} hidden from the schedule` : `${d.series} is back in the schedule`, false,
    ["Undo", () => hideSeries(d, !hidden)]);
  renderHideToggle();
  renderWall();  // its Hidden filter and badges
  if (!$("#tab-schedule").hidden) rerenderSchedule(); else renderHiddenButton();
}
/* The series page's own switch, saved at once like the Schedule's. */
const EYE_OPEN = '<path d="M2 12s3-8 10-8 10 8 10 8-3 8-10 8-10-8-10-8Z"/><circle cx="12" cy="12" r="3"/>', EYE_SHUT = '<path d="M9.9 4.2A10.9 10.9 0 0 1 12 4c7 0 10 8 10 8a17.6 17.6 0 0 1-2.2 3.3M6.6 6.6C3.6 8.6 2 12 2 12s3 8 10 8a10 10 0 0 0 5.4-1.6M14.1 14.1a3 3 0 0 1-4.2-4.2M2 2l20 20"/>';
function renderHideToggle() {
  if (!current) return;
  const hidden = isHidden(current), b = $("#d-hide");
  b.setAttribute("aria-pressed", !hidden);  // its name stays "In schedule": the state is what is pressed
  b.title = hidden ? "Hidden from the schedule: show it again" : "Hide this series from the schedule";
  b.querySelector("svg").innerHTML = hidden ? EYE_SHUT : EYE_OPEN;
}
$("#d-hide").onclick = () => hideSeries({ tvdbId: current.tvdbId, series: current.title }, !isHidden(current));

/* The counter by the filters, and its list: each row keeps its place while the list is open,
   so a switch flipped by mistake flips back. */
function renderHiddenButton() {
  const n = S.config.hidden_series.length, b = $("#hidden-open");
  b.hidden = !n;
  b.querySelector("span").textContent = n;
  b.title = b.ariaLabel = `${n} series hidden from the schedule`;
}
$("#hidden-open").onclick = () => {
  const rows = S.config.hidden_series.map((tvdbId) => {
    const series = S.series.find((x) => x.tvdbId === tvdbId), name = series?.title || `TVDB ${tvdbId}`;
    const input = el("input", { type: "checkbox", checked: false, ariaLabel: trWith("In schedule: {0}", name) });
    const li = el("li", { className: "off" }, el("img", { alt: "", loading: "lazy", src: posterSrc(series?.poster, name), onerror: posterFail(name) }), el("span", { className: "n", textContent: name }),
      el("label", { className: "switch" }, "In schedule", input, el("i")));
    input.onchange = async () => {
      li.classList.toggle("off", !input.checked);
      await hideSeries({ tvdbId, series: name }, !input.checked, true);
      input.checked = !S.config.hidden_series.includes(tvdbId);  // as saved, should the save fail
      li.classList.toggle("off", !input.checked);
    };
    return li;
  }).sort((a, b) => a.textContent.localeCompare(b.textContent));
  $("#hidden-rows").replaceChildren(...rows);
  $("#hidden-dialog").showModal();
};
function rerenderSchedule() {
  renderHiddenButton();
  renderCalendar();
}
function renderCalendar() {
  const month = schedView() === "month";
  const start = weekStartOf(month ? cal.month : cal.date);
  if (cal.fetched.has(`${isoDay(start)}+${month ? 42 : 7}`)) month ? renderMonth() : renderWeek();
}
function hideButton(d) {  // hidden series are not listed here: Series, Hidden brings them back
  const b = el("button", { className: "icon-hide", title: "Hide this series from the schedule (Series, Hidden brings it back)", ariaLabel: `Hide ${d.series} from the schedule`,
    onclick: (e) => { e.preventDefault(); e.stopPropagation(); hideSeries(d, true); } });
  b.innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${EYE_SHUT}</svg>`;
  return b;
}

/* Networks (FX, Apple TV+…) by TMDB id, fetched for the series a calendar chunk brings. */
const networksById = {};
async function fetchNetworks(episodes) {
  const ids = [...new Set(episodes.map((d) => S.series.find((x) => x.tvdbId === d.tvdbId)?.tmdbId).filter((i) => i && !(i in networksById)))];
  if (!ids.length) return;
  ids.forEach((i) => networksById[i] = null);  // asked: don't ask twice
  try { Object.assign(networksById, await api(`/api/networks?tmdb=${ids.join(",")}`)); }
  catch { return; }  // just no logos this time
  renderCalendar();
}
function schedLogo(name, src, title = name) {
  const badge = el("span", { className: "sched-logo", title }, el("span", { textContent: name }));
  if (src) {
    const img = el("img", { alt: name, ariaHidden: "true", loading: "lazy",
      onload: () => { img.ariaHidden = null; badge.classList.add("loaded"); badge.replaceChildren(img); },
      onerror: () => img.remove(), src });
    badge.append(img);
  }
  return badge;
}
function networkBadge(d) {
  const tmdbId = S.series.find((x) => x.tvdbId === d.tvdbId)?.tmdbId;
  const net = networksById[tmdbId];
  if (!net) return "";
  // A channel of your country (M6 in FR) is watched there anyway, on air or its replay: no warning then
  const home = net.network_country && net.network_country === net.country;
  const networkTip = home ? `On ${net.name}, a channel in ${net.country}. TMDB lists no streaming service for it` : `Network: ${net.name}`;
  const network = net.name ? schedLogo(net.name, net.logo, networkTip) : "";
  // Where it streams in the first "Where to watch" country; else a warning, but not for a channel of that
  // country nor for a series Unshackle already downloads (its service is what counts then)
  const local = net.providers.length
    ? el("span", { className: "prov", title: `In ${net.country}: ${net.providers.map((p) => p.name).join(", ")}` },
        ...net.providers.slice(0, 3).map((p) => schedLogo(p.name, p.logo)))
    : home || d.managed ? ""
    : el("span", { className: "chip nofr", textContent: `No streaming in ${net.country}`,
        title: `TMDB (from JustWatch) lists no streaming service in ${net.country} for this series` });
  // The French services say where to watch it; the original network only helps when there are none
  // (which also folds a network that is its own service, like Canal+, into one logo).
  return el("span", { className: "badges" }, ...(net.providers.length ? [local] : [network, local]));
}

/* Fetch [from, from + days) once; episodes land in cal.byDay by local day. The route filters by air date, so it is
   asked EARLY_DAYS_MAX more days: an episode out inside the range may air after it. Each is filed once. */
async function fetchDays(from, days) {
  const key = `${isoDay(from)}+${days}`;
  if (cal.fetched.has(key)) return;
  const eps = await api(`/api/calendar?start=${isoDay(from)}&days=${days + EARLY_DAYS_MAX}`,
    { wait: 130 });  // as long as the server waits for a busy Sonarr (120 s)
  cal.fetched.add(key);
  const range = new Set();
  for (let i = 0; i < days; i++) { const day = isoDay(addDays(from, i)); range.add(day); cal.byDay.set(day, []); }
  const same = (a, b) => a.tvdbId === b.tvdbId && a.sxxeyy === b.sxxeyy;
  for (const d of eps) {  // on the day it airs; one out days before (a platform ahead of the channel) on the day it's tried
    const aired = isoDay(new Date(d.airDateUtc)), out = d.release && new Date(d.release) < new Date(d.airDateUtc) ? isoDay(new Date(d.release)) : aired;
    const id = `${d.tvdbId}|${d.sxxeyy}`, was = cal.placed.get(id), held = (day) => cal.byDay.get(day)?.some((x) => same(x, d));
    const day = range.has(out) ? out : range.has(aired) && !(was && held(was)) ? aired : null;  // else an earlier or later chunk files it
    if (!day) continue;
    if (was && was !== day) { const list = cal.byDay.get(was); const i = list?.findIndex((x) => same(x, d)); if (i >= 0) list.splice(i, 1); }
    cal.byDay.get(day).push(d);
    cal.placed.set(id, day);
  }
  fetchNetworks(eps);
}

/* Week view: seven day columns from Monday, the days' episodes as cards. */
async function loadWeek() {
  const start = weekStartOf(cal.date), current = () => schedView() === "week" && isoDay(weekStartOf(cal.date)) === isoDay(start);
  renderRange();
  $("#week-board").replaceChildren(loading("Loading the week…"));
  try { await fetchDays(start, 7); }
  catch (e) { if (current()) $("#week-board").replaceChildren(failed(`Could not load the calendar: ${e.message}`, loadWeek)); return; }
  if (current()) renderWeek();  // not a week left since, whether it loaded or failed
}
const countText = (list) => {  // "2 episodes · 1 downloading"
  const mine = list.filter((e) => e.managed).length, episodes = COUNT.episode(list.length);
  return !mine ? episodes : `${episodes} · ${mine === list.length ? (mine > 1 ? "all downloading" : "downloading") : `${mine} downloading`}`;
};
function renderWeek() {
  const start = weekStartOf(cal.date), now = new Date(), today = isoDay(now), tomorrow = isoDay(addDays(startOfDay(now), 1));
  renderRange();
  const board = $("#week-board"), tracks = [];
  const days = Array.from({ length: 7 }, (_, i) => {
    const date = addDays(start, i), key = isoDay(date);
    const list = (cal.byDay.get(key) || []).filter(inScope).sort(byWhen);
    const month = i === 0 || date.getDate() === 1;  // the month once the week turns
    tracks.push(list.length ? "minmax(0, 1fr)" : "minmax(0, .65fr)");
    return el("div", { className: "day" + (key === today ? " today" : ""), role: "group", ariaLabel: date.toLocaleDateString(LOCALE, { weekday: "long", day: "numeric", month: "long" }) },
      el("h4", { className: "day-h" }, el("b", { textContent: date.toLocaleDateString(LOCALE, { weekday: "short" }) }),
        el("span", { className: "num", textContent: date.toLocaleDateString(LOCALE, { day: "numeric", month: month ? "short" : undefined }) }),
        ...(key === today ? [el("span", { className: "rel", textContent: "Today" })] : key === tomorrow ? [el("span", { className: "rel", textContent: "Tomorrow" })] : [])),
      list.length ? el("small", { className: "n", textContent: countText(list) }) : "",
      ...(list.length ? list.map((e) => schedCard(e, whenText(e))) : [el("p", { className: "day-empty", textContent: "Nothing that day." })]));
  });
  board.style.setProperty("--week-columns", tracks.join(" "));
  keepFocus(board, () => board.replaceChildren(...days));
  syncDetails();
}
function moveWeek(step) {
  cal.date = step ? addDays(cal.date, 7 * step) : startOfDay(new Date());
  loadWeek();
}
/* When something happens to an episode: when it is tried (its release time, else the first sync after airing: the
   server's firstTry, while it is still to come), else airing. */
const triesAt = (d) => d.release || (d.managed && !d.hasFile && d.firstTry) || "";
const whenOf = (d) => triesAt(d) || d.airDateUtc || "";
const byWhen = (a, b) => new Date(whenOf(a)) - new Date(whenOf(b));  // instants: release times carry an offset, airings a Z
const whenText = (d) => {
  const aired = new Date(d.airDateUtc), tries = triesAt(d);
  if (tries) {
    const at = new Date(tries), other = isoDay(at) !== isoDay(aired), early = other && at < aired;
    // out days before it airs: listed on the day it's tried, so the airing says its day; the day after: the try does
    return el("span", { className: "tm", title: at > Date.now() ? `Tries in ${until(at)}` : "" },
      `${other && !early ? `${day(at)} ` : ""}${time(at)}`, el("small", { textContent: `airs ${early ? `${day(aired)} ` : ""}${time(aired)}` }));
  }
  // on disk, not yours, or aired and not tried yet (its pill says "Tries at the next sync"): when it airs
  return el("span", { className: "tm" }, time(aired), el("small", { className: "m", textContent: "airs" }));
};
/* A month cell's time: filed under the day it airs, a try on another day (a sync after midnight) says its weekday. */
const monthTime = (d, key) => { const at = new Date(whenOf(d)); return `${isoDay(at) !== key ? `${at.toLocaleDateString(LOCALE, { weekday: "short" })} ` : ""}${time(at)}`; };
/* Where one of your episodes stands, in a word and a colour. */
function schedStatus(d) {
  if (d.hasFile) return ["ok", d.managed ? "Downloaded" : "On disk"];
  if (!d.managed) return null;
  if (d.waitingImport) return ["wait", "Waiting for Sonarr"];
  if (d.fromLate) return ["late", `Late · not on ${svcName(d.service)} yet`];
  if (d.firstTry && new Date(d.firstTry) > Date.now()) return null;  // the time says it: "try 09:00"
  return new Date(d.airDateUtc) < Date.now() ? ["try", "Tries at the next sync"] : null;
}
const statusPill = (d, extra = "") => { const st = schedStatus(d); return st ? el("span", { className: `sched-st ${st[0]} ${extra}` }, el("i"), st[1]) : ""; };

/* Month view: a grid from Monday, six weeks; phones show counts and a day's list below. */
async function loadMonth() {
  const gridStart = weekStartOf(cal.month), current = () => schedView() === "month" && isoDay(weekStartOf(cal.month)) === isoDay(gridStart);
  renderRange();
  $("#cal-grid").replaceChildren(loading("Loading the month…"));
  $("#cal-day").replaceChildren();  // the day picked in the month before is not in this one
  try { await fetchDays(gridStart, 42); }
  catch (e) { if (current()) $("#cal-grid").replaceChildren(failed(`Could not load the calendar: ${e.message}`, loadMonth)); return; }
  if (current()) renderMonth();
}
function renderMonth() {
  const first = cal.month, gridStart = weekStartOf(first);
  const today = isoDay(new Date());
  renderRange();
  const heads = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => el("div", { className: "cal-head", textContent: d }));
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const date = addDays(gridStart, i), key = isoDay(date);
    const list = (cal.byDay.get(key) || []).filter(inScope);
    const mine = list.filter((d) => d.managed).length;
    // the three shown: yours first, never in "+N more"; then in the order they air
    const shown = [...list].sort((a, b) => b.managed - a.managed).slice(0, 3).sort(byWhen);
    const cell = el("button", {
      className: "cal-cell" + (date.getMonth() !== first.getMonth() ? " out" : "") + (key === today ? " today" : "") + (key === cal.pick ? " picked" : ""),
      ariaLabel: `${date.toLocaleDateString(LOCALE, { weekday: "long", day: "numeric", month: "long" })}: ${COUNT.episode(list.length)}`,
      ariaPressed: String(key === cal.pick),
      onclick: () => { pickDay(key); renderMonth(); $("#cal-day").scrollIntoView({ behavior: SCROLL, block: "nearest" }); },
    },
      el("span", { className: "cal-date", textContent: date.getDate() }),
      el("span", { className: "cal-count" }, ...(mine ? [el("i", { className: "mine", textContent: mine })] : []),
        ...(list.length - mine ? [el("i", { textContent: list.length - mine })] : [])),
      el("span", { className: "cal-eps" }, ...shown.map((d) => el("span", { className: "cal-ep" + (d.managed ? " mine" : "") },
        el("b", { textContent: monthTime(d, key) }), ` ${d.series}`)),
        ...(list.length > 3 ? [el("span", { className: "cal-ep more", textContent: `+${list.length - 3} more` })] : [])));
    cells.push(cell);
  }
  keepFocus($("#cal-grid"), () => $("#cal-grid").replaceChildren(...heads, ...cells));
  const picked = cal.pick && (cal.byDay.get(cal.pick) || []).filter(inScope);
  const listBox = $("#cal-day");
  keepFocus(listBox, () => listBox.replaceChildren(...(picked ? [
    el("h3", { className: "sched-day", textContent: day(dayOfKey(cal.pick)) }),
    picked.length ? el("div", { className: "sched-cards" }, ...picked.sort(byWhen).map((d) => schedCard(d, whenText(d))))
      : el("p", { className: "muted", textContent: "Nothing that day." })] : [])));
  syncDetails();
}
function moveMonth(step) {
  const today = startOfDay(new Date());
  cal.month = step ? new Date(cal.month.getFullYear(), cal.month.getMonth() + step, 1) : monthStartOf(today);
  cal.date = step ? inMonth(cal.month, cal.date.getDate()) : today;
  cal.pick = step ? null : isoDay(today);
  loadMonth();
}
/* One chosen day for both views: Month marks and lists it, Week shows its week. */
function pickDay(key) { cal.pick = key; cal.date = dayOfKey(key); }
function switchView(view) {
  if (view === "month") { cal.month = monthStartOf(cal.date); cal.pick = isoDay(cal.date); }
  else cal.pick = null;
}
function renderRange() {
  const month = schedView() === "month", start = weekStartOf(cal.date);
  $("#cal-range").textContent = month ? cal.month.toLocaleDateString(LOCALE, { month: "long", year: "numeric" })
    : new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric" }).formatRange(start, addDays(start, 6));
  $("#cal-prev").ariaLabel = month ? "Previous month" : "Previous week";
  $("#cal-next").ariaLabel = month ? "Next month" : "Next week";
}
$("#cal-prev").onclick = () => schedView() === "month" ? moveMonth(-1) : moveWeek(-1);
$("#cal-next").onclick = () => schedView() === "month" ? moveMonth(1) : moveWeek(1);
$("#cal-today").onclick = () => schedView() === "month" ? moveMonth(0) : moveWeek(0);

const FINALE = { season: "Season finale", series: "Series finale", midseason: "Mid-season finale" };
const shellQuote = (a) => /^[\w@%+=:,./-]+$/.test(a) ? a : `'${a.replaceAll("'", "'\\''")}'`;
/* What an episode's details offer: the command for one of yours (as the list row showed it), Download now only while
   it is not on disk; nothing for another series, and why for one the episode offset skips. */
function detailsPlan(d) {
  const command = d.managed && d.command ? d.command.map(shellQuote).join(" ") : "";
  return { command, skipped: !!d.managed && !d.command, download: !!(command && d.episodeId && !d.hasFile) };
}
/* An episode as a card: when, its name (opening its details), its status and where it comes from. */
function schedCard(d, when) {
  const series = S.series.find((x) => x.tvdbId === d.tvdbId), name = series?.title || d.series;
  const thumb = el("img", { className: "thumb", alt: "", loading: "lazy", src: posterSrc(series?.poster, name), onerror: posterFail(name) });
  const key = `${Boolean(d.fromLate)}|${d.tvdbId}|${d.sxxeyy}`;  // the same episode can be in the late list and on the board
  const open = el("button", { type: "button", className: "sc-open", ariaExpanded: "false", ariaHasPopup: "dialog",
    textContent: `${d.series} ${d.sxxeyy}`, onclick: () => open.getAttribute("aria-expanded") === "true" ? closeDetails() : openDetails(open, d, key) });
  const title = d.title && d.title !== "TBA" ? d.title : "";
  return el("article", { className: `sched-card ${d.managed ? "mine" : "other"}`, dataset: { key } },
    el("div", { className: "sc-main" }, thumb, el("span", { className: "what" }, open,
      el("span", { className: "sc-when" }, typeof when === "string" ? el("span", { className: "tm", textContent: when }) : when),
      ...(FINALE[d.finale] ? [el("span", { className: "finale-tag", textContent: FINALE[d.finale] })] : []),
      title ? el("small", {}, episodeTitle(d.tvdbId, d.sxxeyy, title)) : "")),
    el("div", { className: "sc-foot" }, el("div", { className: "sc-badges" }, statusPill(d),
      d.managed ? el("span", { className: "svc", textContent: svcName(d.service) }) : "",
      networkBadge(d),
      !d.managed && !d.hasFile ? el("button", { type: "button", className: "btn small add", textContent: "+ Add", ariaLabel: `Add ${d.series} to Unshackle`,
        onclick: () => series && openDrawer(series, "settings") }) : ""),
      d.fromLate ? "" : hideButton(d)));
}

/* Details: a popover by its card, a dialog on a phone. One at a time; Escape or Close returns to the card's name. */
const det = { trigger: null, d: null, key: "", phone: false };
function detailsNode(d) {
  const series = S.series.find((x) => x.tvdbId === d.tvdbId), plan = detailsPlan(d);
  const onService = d.serviceEpisode && d.serviceEpisode !== d.sxxeyy ? d.serviceEpisode : "";
  const tries = d.release ? new Date(d.release) : null;
  const facts = [
    ...(tries && tries > Date.now() ? [el("span", { textContent: `Tries in ${until(tries)}` })] : []),
    ...(d.firstTry ? [el("span", {}, new Date(d.firstTry) > Date.now() ? "Tries " : "Tried ", el("b", { textContent: `${day(new Date(d.firstTry))} ${time(new Date(d.firstTry))}` }),
      series && S.config.series[d.tvdbId]?.release_time ? `, then every ${S.config.settings?.burst_every_seconds ?? 30} s for ${S.config.settings?.burst_minutes ?? 10} min` : ", at the sync")] : []),
    ...(onService ? [el("span", {}, "Asked for as ", el("b", { textContent: onService }))] : []),
    ...(d.waitingImport ? [el("span", { textContent: "Already downloaded: waiting for Sonarr's import" })] : [])];
  const command = plan.command ? el("details", { className: "cmd" },
    el("summary", { textContent: "Show command" }), el("code", { textContent: plan.command })) : null;
  const copy = el("button", { type: "button", className: "btn small", textContent: "Copy command", onclick: async () => {
    try { await navigator.clipboard.writeText(plan.command); toast("Command copied"); }
    catch { command.open = true; toast("Could not copy: select the command instead", true); }
  } });
  const now = el("button", { type: "button", className: "btn small primary", textContent: "Download now", onclick: async () => {
    now.disabled = true;
    try { await api("/api/download", { method: "POST", body: JSON.stringify({ episodeIds: [d.episodeId] }) }); toast(`${d.series} ${d.sxxeyy}: downloading`); }
    catch (e) { now.disabled = false; toast(e.message, true); }
  } });
  const buttons = [...(plan.download ? [now] : []),
    ...(d.run ? [el("button", { type: "button", className: "btn small", textContent: "See in Activity", title: "Open its last download: its steps and output",
      onclick: () => { closeDetails(false); showTab("log"); pickRun(d.run); } })] : []),
    ...(series ? [el("button", { type: "button", className: "btn small", textContent: "Open the series", onclick: () => { closeDetails(); openDrawer(series); } })] : []),
    ...(command ? [copy] : [])];
  const close = el("button", { type: "button", className: "inbox-x", ariaLabel: "Close", onclick: () => closeDetails() });
  close.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  return el("div", { className: "sd" },
    el("div", { className: "sd-head" }, el("h2", { id: "sched-det-h", textContent: `${d.series} ${d.sxxeyy}` }), close),
    ...(buttons.length ? [el("div", { className: "btns" }, ...buttons)] : []),
    ...(facts.length ? [el("div", { className: "facts" }, ...facts)] : []),
    command || (plan.skipped ? el("p", { className: "muted", textContent: "Skipped: the episode offset puts it before the service's first episode." }) : ""));
}
function openDetails(trigger, d, key) {
  if (det.trigger) closeDetails(false);
  Object.assign(det, { trigger, d, key, phone: phoneLayout() });
  trigger.setAttribute("aria-expanded", "true");
  const box = $(det.phone ? "#sched-dlg" : "#sched-pop");
  box.replaceChildren(detailsNode(d));
  if (det.phone) { box.showModal(); return; }
  box.hidden = false;
  placeDetails();
  box.focus({ preventScroll: true });
}
function closeDetails(restoreFocus = true) {
  const { trigger } = det;
  if (!trigger) return;
  Object.assign(det, { trigger: null, d: null, key: "" });
  trigger.setAttribute("aria-expanded", "false");
  const pop = $("#sched-pop"), dlg = $("#sched-dlg");
  pop.hidden = true; pop.replaceChildren();
  if (dlg.open) dlg.close();
  dlg.replaceChildren();
  if (restoreFocus && trigger.isConnected) trigger.focus();
}
/* Beside its card (right, else left), kept inside the window; taller than the window: it scrolls inside. */
function popoverPlace(anchor, width, height, viewW, viewH, gap = 8) {
  const right = anchor.right + gap, left = Math.min(Math.max(right + width <= viewW - gap ? right : anchor.left - gap - width, gap), Math.max(gap, viewW - width - gap));
  const maxHeight = viewH - 2 * gap, top = Math.min(Math.max(anchor.top, gap), viewH - Math.min(height, maxHeight) - gap);
  return { left, top, maxHeight };
}
function placeDetails() {
  if (!det.trigger || det.phone) return;
  const pop = $("#sched-pop"), at = popoverPlace(det.trigger.closest(".sched-card").getBoundingClientRect(), pop.offsetWidth, pop.scrollHeight, innerWidth, innerHeight);
  Object.assign(pop.style, { left: `${at.left}px`, top: `${at.top}px`, maxHeight: `${at.maxHeight}px` });
}
/* After a redraw (a logo arrived, a filter changed): the card it belongs to, if it is still there, else closed. */
function syncDetails() {
  if (!det.trigger || det.trigger.isConnected) return placeDetails();
  const card = [...document.querySelectorAll(".sched-card")].find((c) => c.dataset.key === det.key);
  if (!card) return closeDetails(false);
  det.trigger = card.querySelector(".sc-open");
  det.trigger.setAttribute("aria-expanded", "true");
  placeDetails();
}
function detailsKey(e) {
  if (e.key !== "Escape" || !det.trigger || det.phone) return;  // a dialog closes itself; its "close" event comes back here
  e.preventDefault();
  closeDetails();
}
document.addEventListener("keydown", detailsKey);
document.addEventListener("click", (e) => {
  if (det.trigger && !det.phone && !e.target.closest("#sched-pop, .sc-open")) closeDetails(false);
});
addEventListener("scroll", placeDetails, { capture: true, passive: true });
addEventListener("resize", () => { if (det.trigger && det.phone !== phoneLayout()) closeDetails(false); else placeDetails(); });
$("#sched-dlg").addEventListener("close", () => closeDetails());

const LOCALE = LANG === "en" ? "en-GB" : LANG;  // English: a 24-hour clock, the day before the month
cal.date = startOfDay(new Date());
cal.month = monthStartOf(cal.date);
renderRange();
const time = (d, timeZone) => isNaN(d) ? "" : d.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit", timeZone });
function day(d) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((new Date(d).setHours(0, 0, 0, 0) - today) / 86400000);
  if (diff >= -1 && diff <= 1) return tr(["Yesterday", "Today", "Tomorrow"][diff + 1]);  // translated here: often glued to a time
  return d.toLocaleDateString(LOCALE, { weekday: "short", day: "numeric", month: "short",
        year: d.getFullYear() === today.getFullYear() ? undefined : "numeric" });
}
function until(d) {
  const min = Math.max(0, Math.round((d - Date.now()) / 60000));
  return min < 60 ? `${min} min` : `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")} min`;
}
$("#sched-refresh").onclick = () => loadSchedule();
document.querySelectorAll(".sched-filter .pill").forEach((b) => b.onclick = () => {
  document.querySelectorAll(".sched-filter .pill").forEach((x) => x.setAttribute("aria-pressed", x === b));
  renderCalendar();
});
document.querySelectorAll("[data-view]").forEach((b) => b.onclick = () => {
  if (b.getAttribute("aria-pressed") === "true") return;
  document.querySelectorAll("[data-view]").forEach((x) => x.setAttribute("aria-pressed", x === b));
  const month = b.dataset.view === "month";
  closeDetails(false);
  switchView(b.dataset.view);
  $("#sched-week").hidden = month;
  $("#sched-cal").hidden = !month;
  if (month) loadMonth(); else loadWeek();
});

/* Health: the header's lights, from the server's background check; details in Settings. */
let healthTimer = null;
let unshackleDetails = null;
/* Downloads going on: counted on the menu's Activity, every 5 s while the page is in sight. */
let busyStarted = false;
/* Back in sight: the lights, the bell and the sync state at once, not at their next round. */
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && busyStarted) { refreshHealth(); refreshInbox(); refreshLog(); }
});
/* A service's device approval is visible only while its owning job or login waits. */
let approvalShown = "";
let currentApprovals = [];
function showApprovals(approvals, force = false) {
  const dlg = $("#signin-dlg");
  const reopen = $("#approval-reopen");
  currentApprovals = approvals;
  reopen.hidden = !approvals.length;
  reopen.textContent = approvals.length > 1 ? `Approvals · ${approvals.length}` : "Approval";
  if (!approvals.length) {
    if (dlg.open && approvalShown) dlg.close();
    $("#signin-title").textContent = "Service approval";
    $("#signin-message").textContent = "";
    $("#signin-copy").onclick = null;
    approvalShown = "";
    return;
  }
  const details = approvals.map((approval) => [approval.service && svcName(approval.service), approval.message].filter(Boolean).join("\n")).join("\n\n");
  const signature = details;
  if (!force && signature === approvalShown) return;
  approvalShown = signature;
  $("#signin-title").textContent = approvals.length > 1 ? `${approvals.length} services need approval`
    : approvals[0].service ? `${svcName(approvals[0].service)} needs approval` : "Service approval";
  $("#signin-message").textContent = details;
  $("#signin-copy").onclick = async () => {
    try { await navigator.clipboard.writeText(details); toast("Details copied"); } catch { /* the details stay on screen */ }
  };
  if (!dlg.open) dlg.showModal();
}
$("#approval-reopen").onclick = () => showApprovals(currentApprovals, true);
async function refreshBusy() {
  if (!document.hidden) {
    try {
      const b = await api("/api/busy"), badge = $("#nav-busy");
      badge.hidden = !(b.running || b.queued);
      badge.textContent = b.running || b.queued;
      badge.classList.toggle("queued", !b.running);
      badge.title = [b.running && `${b.running} downloading`, b.queued && `${b.queued} queued`].filter(Boolean).join(", ");
      showApprovals(b.approvals || []);
      S.authenticationLive = b.authentication || [];
      S.authenticationSetups = b.authentication_setups || [];
      if (currentTab === "settings" && settingsSec === "services") renderServices();  // a sign-in waiting for its answer moves on its own
      else if (servicesCookies) paintServicesBadge();
      else loadServiceCookies();
    } catch { /* offline a moment: the next round */ }
  }
  setTimeout(refreshBusy, 5000);
}
async function refreshHealth(full = false) {
  if (document.hidden && !full) { clearTimeout(healthTimer); healthTimer = setTimeout(refreshHealth, 60000); return; }  // out of sight
  const authentication = !full && currentTab === "settings" && (settingsSec === "services" || settingsSec === "unshackle");  // Unshackle's own page lists the queue it brings
  try { renderHealth(await api(`/api/status${full ? "?full=1" : authentication ? "?auth=1" : ""}`)); } catch { /* the lights keep their last state */ }
  clearTimeout(healthTimer);  // after the await: calls that overlapped leave one loop, not one each
  healthTimer = setTimeout(refreshHealth, 60000);
}
function renderHealth(h) {
  if (h.authentication) S.authentication = h.authentication;
  if (h.authentication_methods) S.authenticationMethods = h.authentication_methods;
  if (h.authentication_setups) S.authenticationSetups = h.authentication_setups;
  paintLights(h);
  const detailed = h.unshackle && ("tools" in h.unshackle || h.unshackle.ok === false);
  if (detailed) unshackleDetails = {
    ...h.unshackle,
    ...(!("tools" in h.unshackle) && unshackleDetails?.tools ? { tools: unshackleDetails.tools } : {}),
  };
  else if (h.unshackle && unshackleDetails) unshackleDetails = {
    ...h.unshackle, ...(unshackleDetails.tools ? { tools: unshackleDetails.tools } : {}),
  };
  if (detailed || h.authentication && unshackleDetails) renderUnshackleStatus(unshackleDetails);  // down: its actions and why
  if (h.authentication) renderServices();
  renderSonarrState(h.sonarr);
  renderUnshackleState(h.unshackle);
  paintServers(h.servers);
  paintSonarrs(h.sonarrs);
}
/* The header's two lights alone: needs nothing but a status answer, so the page paints them before its state loads. */
function paintLights(h) {
  for (const [name, label] of [["unshackle", "Unshackle"], ["sonarr", "Sonarr"]]) {
    const st = h[name] || {}, b = document.querySelector(`[data-health=${name}]`);
    b.querySelector(".dot").className = "dot " + (st.ok ? (st.latest ? "warn" : "ok") : st.ok === false ? "down" : "");
    const state = st.ok ? (st.latest ? "warn" : "ok") : st.ok === false ? "down" : "wait";
    b.dataset.state = state;
    b.querySelector("small").textContent = { warn: "Update available", down: "Unreachable", wait: "Checking…" }[state] || "";  // said in words, not by the colour alone
    // its name says the state too: on a narrow screen the dot is all there is to see
    b.ariaLabel = { ok: `${label}: running`, warn: `${label}: update available`, down: `${label}: unreachable`, wait: `${label}: checking` }[state];
    b.title = st.ok ? `${label} ${st.version || ""} is running${st.latest ? ` (${st.latest} is out)` : ""}`
      : st.ok === false ? st.error || `${label} is unreachable` : `Checking ${label}…`;
  }
}
function renderUnshackleState(st = S.health?.unshackle || {}, tested = false) {
  const set = S.config.settings || {}, box = $("#ux-state");
  if (!box) return;
  const local = (st.mode || set.unshackle_mode || UNSHACKLE_MODE) === "local";
  $("#ux-where").textContent = `${local ? "Local" : "Remote"} · ${st.address || (local ? set.unshackle_command || "unshackle" : set.unshackle_url || "")}`;
  box.className = `sx-state ${st.ok ? "ok" : st.ok === false ? "down" : ""}`;
  box.querySelector("b").textContent = st.ok ? `${local ? "Running" : "Connected"}${st.version ? ` · Unshackle ${st.version}` : ""}` : st.ok === false ? (local ? "Not running" : "Unreachable") : "Checking…";
  const since = st.since ? `since ${day(new Date(st.since))} ${time(new Date(st.since))}` : "";
  box.querySelector("small").textContent = st.ok ? [st.latest && `${st.latest} is out`, tested ? "Tested just now" : st.services && `${st.services} services`, since]
    .filter(Boolean).join(" · ") : st.ok === false ? String(st.error || "") : "";
}
const UNSHACKLE_MODE = "local";
