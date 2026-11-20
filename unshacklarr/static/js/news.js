/* What's new: each new option wears a "New" badge until it has been on screen for a
   moment or clicked. What was seen is kept by the server, for the account: seen on the computer, gone on the phone
   too. A new install starts with nothing new. The window shows the release notes, read from the CHANGELOG, one
   release per row; a change whose title is an option's below gets a way to it. */
const NEWS = [
  { id: "release-gap", version: "1.6.0", title: "Next episode", series: true, target: 'label[for="d-release-gap"]' },
  { id: "download-window", version: "1.5.0", title: "Download window", sec: "automation", target: "#ax-window-card" },
  { id: "learn-release", version: "1.5.0", title: "Auto release times", sec: "automation", target: "#ax-learn-card" },
  { id: "add-audio", version: "1.5.0", title: "Add audio track", sec: "downloads", target: ".up-mode" },
  { id: "fallback-service", version: "1.5.0", title: "Fallback service", series: true, target: "#d-fb" },
  { id: "offsite-backups", version: "1.5.0", title: "Remote backup", sec: "account", target: "#bo-card" },
  { id: "series-notify", version: "1.5.0", title: "Notifications per series", series: true, target: "#d-notify-l" },
  { id: "no-spoilers", version: "1.5.0", title: "No spoilers", sec: "interface", target: "#rg-spoiler-card" },
  { id: "more-sonarr", version: "1.5.0", title: "Other Sonarr instances", sec: "sonarr", target: "#sn-card" },
  { id: "season-pages", version: "1.5.0", title: "Seasons listed as separate shows", series: true, target: "#d-pages-field" },
  { id: "separate-programmes", version: "1.5.0", title: "Separate programmes", series: true, target: "#d-programmes-field" },
  { id: "sonarr-name", version: "1.5.0", title: "Sonarr name", sec: "sonarr", target: "#sx-name-field" },
  { id: "upgrade-series", version: "1.5.0", title: "Upgrades you choose", sec: "upgrades", target: "#ug-series-card" },
  { id: "other-groups", version: "1.5.0", title: "Other release groups", sec: "upgrades", target: "#ug-other-card" },
  { id: "upgrade-auto", version: "1.5.0", title: "Check automatically", sec: "upgrades", target: "#ug-every-field" },
  { id: "upgrade-spread", version: "1.5.0", title: "Spread the questions", sec: "upgrades", target: "#ug-spread-field" },
  { id: "upgrade-new", version: "1.5.0", title: "Check new series", sec: "upgrades", target: "#ug-new-field" },
  { id: "downloads-at-once", version: "1.5.0", title: "Downloads at once", sec: "unshackle", target: "#ux-at-once-field" },
  { id: "orig-audio", version: "1.6.0", title: "orig in the accepted audio languages", sec: "downloads", target: "#dx-audio-field" },
  { id: "service-cache", version: "1.6.0", title: "Clear one service's cache", sec: "downloads", target: "#svc-defaults" },
  { id: "any-service-option", version: "1.6.0", title: "Any service option", sec: "downloads", target: "#svc-defaults" },
  { id: "sonarr-service-options", version: "1.6.0", title: "Service options per Sonarr", series: true, target: "#d-libs-adv" },
  { id: "after-download", version: "1.6.0", title: "After download", sec: "notifications", target: "#nt-after-card" },
  { id: "ladder-blind", version: "1.6.0", title: "Try unlisted codecs", sec: "quality", target: ".ql-blind" },
  { id: "ladder-chips", version: "1.6.0", title: "Ladders as chips, a bitrate per step", sec: "downloads", target: "#svc-defaults" },
  { id: "dl-generate-dv-sample", version: "1.6.0", title: "--generate-dv", sec: "downloads", target: "#dx-defaults-card" },
];
const NEWS_KINDS = { new: "New", improved: "Improved", fix: "Fix", security: "Security", note: "Note" };
const versionKey = (v) => String(v || "0").split(".").map((n) => parseInt(n, 10) || 0).reduce((a, n) => a * 1000 + n, 0);
function newsUnseen() {
  if (!S.news) return [];  // the state not in yet (a route applied first): nothing is new, nothing seen by mistake
  const news = S.news, seen = new Set(news.seen || []);
  return NEWS.filter((n) => !seen.has(n.id) && !(news.installed && versionKey(n.version) <= versionKey(news.installed)));
}
async function markNews(ids) {
  if (!ids.length) return;
  S.news = { ...(S.news || {}), seen: [...new Set([...(S.news?.seen || []), ...ids])] };
  renderNews();
  try { await api("/api/news/seen", { method: "POST", body: JSON.stringify({ ids }) }); } catch { /* the badge comes back on the next load */ }
}

/* The badges: on each new option's title, its card outlined. */
const newsTitle = (box) => box.querySelector(".sx-head h3, summary b, .sub") || (box.matches("label, span[id]") ? box : null);  // a field's own label
let newsBoxes = new Map();
function renderNews() {
  const boxes = new Map(), titles = new Set();
  for (const n of newsUnseen()) {
    const box = document.querySelector(n.target);
    if (!box) continue;
    if (!boxes.has(box)) boxes.set(box, []);
    boxes.get(box).push(n.id);
    const title = newsTitle(box);
    if (title) titles.add(title);
  }
  for (const badge of document.querySelectorAll(".new-badge")) {
    if (!titles.delete(badge.parentElement)) badge.remove();
  }
  for (const title of titles) title.append(el("span", { className: "new-badge", textContent: "New" }));
  for (const box of newsBoxes.keys()) {
    if (boxes.has(box)) continue;
    newsSeen.unobserve(box);
    clearTimeout(newsTimers.get(box));
    newsTimers.delete(box);
    box.classList.remove("is-new", "new-blink");
    box.removeEventListener("click", clickNews);
  }
  for (const box of boxes.keys()) {
    if (newsBoxes.has(box)) continue;
    if (!box.matches("label, span[id]")) box.classList.add("is-new");  // a field's label: its badge is enough
    box.addEventListener("click", clickNews);
    newsSeen.observe(box);
  }
  newsBoxes = boxes;
}

/* Seen when its section is left: every new option there, looked at or not. */
function leaveNews(test) {
  const ids = newsUnseen().filter(test).map((n) => n.id);
  if (ids.length) markNews(ids);
}
function leaveSettingsNews(sec) {
  leaveNews((n) => legacySettings(n.sec)?.sec === sec);
}
/* Seen: in sight for 2.5 seconds, or clicked. In sight: half of it on screen, or, for one taller than the screen,
   a good part of the screen filled with it. */
const newsTimers = new Map();
const newsSeen = new IntersectionObserver((entries) => {
  for (const e of entries) {
    const box = e.target;
    if (!newsBoxes.has(box)) continue;
    if (e.isIntersecting && (e.intersectionRatio >= 0.5 || e.intersectionRect.height >= innerHeight * 0.4)) {
      box.classList.add("new-blink");  // it blinks as it comes into sight, not off screen
      if (!newsTimers.has(box)) newsTimers.set(box, setTimeout(() => markNews(newsBoxes.get(box) || []), 2500));
    } else { clearTimeout(newsTimers.get(box)); newsTimers.delete(box); }
  }
}, { threshold: [0, 0.1, 0.2, 0.3, 0.4, 0.5] });  // tall ones cross the lower steps
function clickNews({ currentTarget }) {
  markNews(newsBoxes.get(currentTarget) || []);
}

/* The What's new window: one row per release, the installed one open; a newer one links to GitHub. */
let releaseNotes = null;
const inlineMd = (text) => text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).filter(Boolean).map((t) =>
  t.startsWith("**") ? el("b", { textContent: t.slice(2, -2) }) : t.startsWith("`") ? el("code", { textContent: t.slice(1, -1) }) : t);
function showOption(n) {
  $("#news-dlg").close();
  if (n.series) {
    const s = S.series.find((x) => S.config.series[x.tvdbId]?.service) || S.series[0];
    if (s) openDrawer(s, "settings");
    setTimeout(() => { const box = document.querySelector(n.target), fold = box?.closest("details"); if (fold) fold.open = true; box?.scrollIntoView({ behavior: SCROLL, block: "center" }); }, 400);  // in a folded section: opened
  } else {
    openSettings(n.sec, n.target);
  }
}
function releaseRow(r, installed, latest) {
  const numbered = r.version !== "Unreleased", name = numbered ? `v${r.version}` : "Unreleased";
  const date = r.date ? new Date(`${r.date}T12:00`).toLocaleDateString(LOCALE, { day: "numeric", month: "short", year: "numeric" }) : "";
  const changes = r.changes.length === 1 ? "1 change" : `${r.changes.length} changes`;
  return el("details", { className: "news-rel", open: r.version === installed },
    el("summary", {}, el("b", { textContent: name }),
      ...(r.version === installed ? [el("span", { className: "news-tag", textContent: "Installed" })] : []),
      ...(r.version === latest ? [el("span", { className: "news-tag latest", textContent: "Latest" })] : []),
      el("small", { textContent: changes }), el("time", { textContent: date })),
    el("ul", { className: "news-list" }, ...r.changes.map((c) => {
      const n = NEWS.find((x) => c.text.startsWith(`**${x.title}.**`));
      return el("li", { className: c.kind }, el("span", { className: "news-kind", textContent: NEWS_KINDS[c.kind] }),
        el("p", {}, ...inlineMd(c.text),
          ...(n ? [" ", el("button", { type: "button", className: "news-go", textContent: "Show me", onclick: () => showOption(n) })] : [])));
    })));
}
async function openNews() {
  const list = $("#news-list"), dlg = $("#news-dlg");
  if (!dlg.open) dlg.showModal();
  try { releaseNotes ||= await api("/api/changelog"); } catch (e) { return list.replaceChildren(failed(e.message, openNews)); }
  const { installed, releases } = releaseNotes, newer = S.update?.version;
  const latest = newer || installed;
  $("#news-version").textContent = `Release notes for Unshacklarr ${installed}.`;
  const rows = [];
  if (newer) rows.push(el("a", { className: "news-rel news-out", href: S.update.url, target: "_blank", rel: "noopener" },
    el("b", { textContent: `v${newer}` }), el("span", { className: "news-tag latest", textContent: "Latest" }), el("small", { textContent: "See on GitHub ↗" })));
  let earlier = false;
  for (const r of releases) {
    if (!earlier && r.version !== "Unreleased" && versionKey(r.version) < versionKey(installed)) {
      earlier = true;
      rows.push(el("p", { className: "news-earlier", textContent: "Earlier releases" }));
    }
    rows.push(releaseRow(r, installed, latest));
  }
  list.replaceChildren(...rows);
}
$("#set-version").onclick = openNews;
$("#news-close").onclick = $("#news-x").onclick = () => $("#news-dlg").close();
$("#news-dlg").addEventListener("click", (e) => {  // a click outside the window (on the dimmed page) closes it
  const r = e.currentTarget.getBoundingClientRect();
  const outside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
  if (e.target === e.currentTarget && outside) e.currentTarget.close();  // not a button pressed with the keyboard
});
