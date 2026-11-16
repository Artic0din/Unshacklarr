const $ = (s) => document.querySelector(s);
/* Scrolling that glides, unless this person asked their system for less motion. */
let SCROLL = "smooth";
if (matchMedia("(prefers-reduced-motion: reduce)").matches) SCROLL = "auto";
/* A help text, one sentence a line: easier to read than a block. */
const breakSentences = (text) => text.replace(/([.!?]) (?=\p{Lu})/gu, "$1\n").replace(/([。！？])(?=\S)/gu, "$1\n");
/* A series' poster, or one made of its initials when Sonarr has none or it doesn't load: never the browser's broken
   image ("The Search for Leah Croucher: A Parent's Nightmare", banner only on TheTVDB, is SL). An image all the same,
   so every place sizes it as before. By mj23au */
function initialsOf(name) {
  const words = String(name || "").replace(/\([^)]*\)/g, " ").split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const small = /^(the|a|an|and|of|for|in|on|at|to|with|from|by|le|la|les|de|du|des|et|der|die|das|el|los)$/i;
  const kept = words.filter((w) => !small.test(w));
  return (kept.length ? kept : words).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
}
function posterSrc(src, name) {
  if (src) return src;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300"><rect width="200" height="300" fill="#2c2925"/>`
    + `<text x="100" y="150" dy=".35em" text-anchor="middle" font-family="system-ui,-apple-system,Segoe UI,sans-serif" `
    + `font-size="84" font-weight="700" fill="#a8a196">${initialsOf(name)}</text></svg>`;
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}
const posterFail = (name) => (e) => { const s = posterSrc("", name); if (e.target.getAttribute("src") !== s) e.target.src = s; };

function lineBySentence(node) {
  const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) walk.currentNode.nodeValue = breakSentences(walk.currentNode.nodeValue);
  return node;
}
/* Languages. The page is written in English; another language's texts are swapped in as they show up, whoever
   put them there (the markup, el(), a textContent), each text matched whole: "Test all", or "Test {0} ({1})" with
   what fills {0} and {1} translated in turn. i18n/en.json lists them (tools/i18n/extract.py), i18n/<lang>.json
   translates them. The choice is this browser's: the login and the setup need it before any account. */
const LANGS = { en: "English", fr: "Français", es: "Español", de: "Deutsch", "pt-BR": "Português (Brasil)", it: "Italiano",
  ru: "Русский", "zh-CN": "简体中文", ja: "日本語" };
const LANG = (() => {
  let chosen = null;
  try { chosen = localStorage.getItem("lang"); } catch {}
  if (LANGS[chosen]) return chosen;
  for (const wanted of navigator.languages || [navigator.language || "en"]) {
    const hit = LANGS[wanted] ? wanted : Object.keys(LANGS).find((k) => k.split("-")[0] === wanted.split("-")[0]);
    if (hit) return hit;
  }
  return "en";
})();
document.documentElement.lang = LANG;
/* Light or dark: the system's unless this browser picked one (the <head> applies it before the first paint). */
const THEMES = ["system", "light", "dark"];
let themePicked = null;  // this visit's pick, kept even when the browser can't store it
function themeChoice() {
  if (themePicked) return themePicked;
  try { const t = localStorage.getItem("theme"); return THEMES.includes(t) ? t : "system"; } catch { return "system"; }
}
function applyTheme(choice) {
  if (choice === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = choice;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", getComputedStyle(document.documentElement).getPropertyValue("--bg").trim());
}
function setTheme(choice) {
  themePicked = choice;
  try { if (choice === "system") localStorage.removeItem("theme"); else localStorage.setItem("theme", choice); } catch { /* this visit only */ }
  applyTheme(choice);
}
applyTheme(themeChoice());
matchMedia("(prefers-color-scheme: light)").addEventListener?.("change", () => applyTheme(themeChoice()));
async function setLang(lang) {
  try { localStorage.setItem("lang", lang); } catch {}
  try { if (setupDraft) sessionStorage.setItem("setup-draft", JSON.stringify(setupDraft())); } catch {}  // the first run goes on where it was
  await api("/api/language", { method: "POST", body: JSON.stringify({ language: lang }) }).catch(() => {});  // the notifications' too; before logging in, nothing to tell
  location.reload();
}
/* The language, in a corner of the login and the first run: its name, the others in a menu. */
function langCorner() {
  const menu = el("div", { className: "lang-menu", role: "menu", hidden: true },
    ...Object.entries(LANGS).map(([k, name]) => el("button", { type: "button", role: "menuitemradio", ariaChecked: String(k === LANG),
      className: k === LANG ? "on" : "", onclick: () => { if (k !== LANG) setLang(k); } }, name)));
  const open = (on) => { menu.hidden = !on; button.setAttribute("aria-expanded", String(on)); };
  const button = el("button", { type: "button", className: "lang-btn", ariaHasPopup: "menu", ariaExpanded: "false", ariaLabel: `Language: ${LANGS[LANG]}`,
    onclick: () => open(menu.hidden) }, el("span", { textContent: LANGS[LANG] }), el("span", { className: "caret", ariaHidden: "true" }));
  const corner = el("div", { className: "lang-corner", translate: "no" }, button, menu);
  document.addEventListener("click", (e) => { if (!corner.contains(e.target)) open(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") open(false); });
  return corner;
}
let T = null, TP = [];  // exact texts; patterns, the most specific first
const translated = new Set();  // texts already in the language: not taken for English again
const trSeen = new Map();  // key -> its translation, or null: a series' title is tried against the patterns once
function tr(text, depth = 0) {
  const key = text.replace(/\s+/g, " ").trim();
  if (!T || !key) return text;
  let out = T[key];
  if (out === undefined && depth === 0 && trSeen.has(key)) out = trSeen.get(key) ?? undefined;
  else if (out === undefined && depth === 0) {
    out = trFind(key, depth);
    if (trSeen.size > 5000) trSeen.clear();  // "3 min ago" changes all day: bounded
    trSeen.set(key, out ?? null);
  }
  else if (out === undefined) out = trFind(key, depth);
  return out === undefined ? text : text.match(/^\s*/)[0] + out + text.match(/\s*$/)[0];
}
function trFind(key, depth) {
  let out;
  if (key.includes(" · ")) {  // pieces joined by " · ": each its own text
    const parts = key.split(" · "), done = parts.map((x) => tr(x, depth + 1));
    if (done.some((x, i) => x !== parts[i])) out = done.join(" · ");
  }
  if (out === undefined && depth < 3 && key.length <= 300) {  // a long text (a log line) is no template: their lazy groups
    for (const p of TP) {                                       // backtrack for seconds on it
      if (!key.includes(p.anchor)) continue;
      const m = p.re.exec(key);
      // a template with little text of its own ("{0} ago", "{0} of {1}") takes short fillers only, not a whole sentence
      // ... and only numbers, or texts it has a translation for: "5 min ago", not "Set up Unshacklarr in a few steps"
      if (m && p.weak && m.slice(1).some((x) => x.length > 24 || !(/\d/.test(x) || T[x.trim()] !== undefined || !x.trim()))) continue;
      if (m) { out = p.to.replace(/\{(\d+)\}/g, (_, i) => tr(m[+i + 1] ?? "", depth + 1)); break; }
    }
  }
  return out;
}
const I18N_SKIP = ".term, .cm-editor, pre, code, textarea, script, style, [translate=no]", I18N_ATTRS = ["placeholder", "title", "aria-label", "data-tip"];
function trText(node) {
  const v = node.nodeValue;
  if (!/\p{L}/u.test(v) || translated.has(v) || node.parentElement?.closest(I18N_SKIP)) return;
  const t = tr(v);
  if (t === v) return;
  const out = node.parentElement?.closest(".field > small") ? breakSentences(t) : t;
  if (translated.size > 5000) translated.clear();  // live texts ("43%", "3 min ago") would fill it over days
  translated.add(out);
  node.nodeValue = out;
}
function trAttr(e, name) {
  const v = e.getAttribute(name);
  if (!v || translated.has(v)) return;
  const t = tr(v);
  if (t !== v) { translated.add(t); e.setAttribute(name, t); }
}
function trTree(root) {
  if (root.nodeType === 3) return trText(root);
  if (root.nodeType !== 1 || root.closest(I18N_SKIP)) return;
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT,
    { acceptNode: (n) => n.nodeType === 1 && n.matches(I18N_SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
  for (let n = root; n; n = walk.nextNode()) {
    if (n.nodeType === 3) trText(n);
    else for (const a of I18N_ATTRS) if (n.hasAttribute(a)) trAttr(n, a);
  }
}
const i18nReady = (async () => {  // awaited before the first screen; English if the file can't be had
  try {
    if (LANG === "en") return;
    T = await (await fetch(`/i18n/${LANG}.json`, { cache: "no-cache" })).json();
    TP = Object.entries(T).filter(([k]) => /\{\d+\}/.test(k)).map(([k, to]) => {
      const parts = k.split(/\{\d+\}/);
      const re = new RegExp("^" + parts.map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("(.*?)") + "$", "s");  // a hole may be empty: a plural's "s"
      const letters = parts.join("").replace(/[^\p{L}]/gu, "").length;
      return { re, to, anchor: parts.reduce((a, b) => (b.length > a.length ? b : a), ""), weight: parts.join("").length, weak: letters < 10 && parts.filter((x) => x.trim()).length < 2 };
    }).filter((p) => /\p{L}/u.test(p.anchor)).sort((a, b) => b.weight - a.weight);
    trTree(document.body);
    new MutationObserver((changes) => {
      for (const c of changes) {
        if (c.type === "childList") c.addedNodes.forEach(trTree);
        else if (c.type === "characterData") trText(c.target);
        else if (!c.target.closest(I18N_SKIP)) trAttr(c.target, c.attributeName);
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: I18N_ATTRS });
    for (const name of ["confirm", "alert", "prompt"]) { const own = window[name].bind(window); window[name] = (m, ...rest) => own(tr(String(m)), ...rest); }
  } catch (e) { T = null; console.warn("No translation:", e); }
  finally { document.documentElement.classList.remove("i18n-wait"); }
})();
const tmdbHint = () => ["Optional and free: ", el("a", { href: "https://www.themoviedb.org/settings/api", target: "_blank", rel: "noopener", textContent: "create one on TMDB" }),
  " (sign in, then Settings, API).\nWith it, the Schedule shows each series' channel and streaming services.\n"
  + "For a series not in English, it also finds episodes by their title: Sonarr only has English titles."];
let S = { series: [], config: { defaults: {}, series: {}, notifications: {} }, services: [], serviceNames: {}, authentication: {}, authenticationMethods: {}, authenticationSetups: [], authenticationLive: [], dlOptions: [], health: {} };
const serviceOptions = {};
let current = null;

async function responseError(response) {
  const detail = (await response.text()).trim();
  const reason = response.statusText ? `: ${response.statusText}` : "";
  const context = tr(`Unshacklarr answered HTTP ${response.status}${reason}. Try again.`);
  const safeDetail = detail && !/^\s*</.test(detail) ? detail
    .replace(/\/\/[^:/@\s]*:[^/@\s]+@/g, "//***@")
    .replace(/([?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)=)[^&#\s]+/gi, "$1***")
    .replace(/\b(Authorization:\s*(?:Bearer|Basic)\s+|(?:X-Api-Key|X-Secret-Key|Api-Key):\s*)\S+|\b((?:Set-)?Cookie:)\s*[^\r\n]+/gi,
      (_, authorization, cookie) => `${(authorization || cookie).trimEnd()} ***`) : "";
  const error = new Error(safeDetail ? `${context}\n${tr(safeDetail)}` : context);
  error.detail = safeDetail;
  return error;
}
const errorDetail = (error) => error.detail || error.message;
async function api(path, { wait = 30, ...opts } = {}) {
  let r;
  try {
    // wait seconds at most (30 unless said): a request lost in a server restart fails visibly instead of spinning forever
    r = await fetch(path, { headers: { "Content-Type": "application/json", "X-Unshackle": "1" }, signal: AbortSignal.timeout(wait * 1000), ...opts });
  } catch (e) {
    throw new Error(e.name === "TimeoutError"
      ? `Unshacklarr did not answer after ${wait} s. Try again.`
      : "Unshacklarr can't be reached. Check that it is running, then try again.");
  }
  if (r.status === 401 && !path.startsWith("/api/login")) { showLogin(); throw new Error("Sign in first"); }
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/* The inline SVG icons of the page (stroke in currentColor, as .ico): for a tick, a chevron or an arrow, never a text glyph.
   "inl" sizes one to the line of text it starts. */
const ICON_PATHS = {
  check: '<path d="M20 6 9 17l-5-5"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>', alert: '<path d="M12 6v8M12 18h.01"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>', chevronLeft: '<path d="m15 6-6 6 6 6"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>', arrowLeft: '<path d="M19 12H5m6-6-6 6 6 6"/>',
  arrowUp: '<path d="M12 19V5m-6 6 6-6 6 6"/>', arrowDown: '<path d="M12 5v14m-6-6 6 6 6-6"/>',
};
function icon(name, className = "", label = "") {
  const holder = document.createElement("template");
  holder.innerHTML = `<svg class="ico ${className}" viewBox="0 0 24 24" aria-hidden="true">${ICON_PATHS[name]}</svg>`;
  const svg = holder.content.firstChild;
  if (label) { svg.removeAttribute("aria-hidden"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", label); }  // the only sign of what it means
  return svg;
}
/* A counted noun, one whole text for one and one for many: a language writes its own plural from either, no suffix glued on. */
const COUNT = {
  episode: (n) => n === 1 ? "1 episode" : `${n} episodes`,
  missingEpisode: (n) => n === 1 ? "1 missing episode" : `${n} missing episodes`,
  upgrade: (n) => n === 1 ? "1 upgrade" : `${n} upgrades`,
  download: (n) => n === 1 ? "1 download" : `${n} downloads`,
  device: (n) => n === 1 ? "1 device" : `${n} devices`,
  moreDevice: (n) => n === 1 ? "1 more device" : `${n} more devices`,
  problem: (n) => n === 1 ? "1 problem" : `${n} problems`,
  key: (n) => n === 1 ? "1 key" : `${n} keys`,
  option: (n) => n === 1 ? "1 option" : `${n} options`,
  message: (n) => n === 1 ? "1 message" : `${n} messages`,
  service: (n) => n === 1 ? "1 service" : `${n} services`,
  earlierCheck: (n) => n === 1 ? "1 earlier check" : `${n} earlier checks`,
  day: (n) => n === 1 ? "1 day" : `${n} days`,
  hour: (n) => n === 1 ? "1 hour" : `${n} hours`,
};
/* Two clicks for what cannot be undone: the first turns the label into the question, naming the action and what it is done to;
   the second does it. No timer takes the question back while it is being read: leaving the button, a press anywhere else
   (Safari does not focus a clicked button, so it never blurs), or Escape does. */
function confirmClick(button, question, label = button) {
  if (button.dataset.sure === "1") { label.textContent = button.dataset.was; delete button.dataset.sure; return true; }
  button.dataset.sure = "1"; button.dataset.was = label.textContent;
  label.textContent = question;
  const cancel = (e) => {
    if (e.type === "keydown" && e.key !== "Escape") return;
    if (e.type === "pointerdown" && button.contains(e.target)) return;  // the second click on the button itself
    button.removeEventListener("blur", cancel); button.removeEventListener("keydown", cancel);
    document.removeEventListener("pointerdown", cancel, true);
    if (button.dataset.sure !== "1") return;
    delete button.dataset.sure; label.textContent = button.dataset.was;
  };
  button.addEventListener("blur", cancel); button.addEventListener("keydown", cancel);
  document.addEventListener("pointerdown", cancel, true);
  return false;
}
/* Asking a service that is slow to answer: after 20 s, it may be waiting for a sign-in only Unshackle's log shows. */
const slowHint = (svc) => setTimeout(() => toast(`${svc} is slow to answer. It may be waiting for you to sign in: look at Unshackle's log.`, false, ["OK", () => {}]), 20000);
function toast(msg, err = false, action = null) {  // action: [label, onclick], e.g. ["Undo", …]
  const t = document.createElement("div"), stays = err || action;  // an error or a choice waits to be read: no time limit
  t.className = "toast" + (err ? " err" : "") + (stays ? " act" : "");
  t.setAttribute("role", err ? "alert" : "status");
  t.textContent = msg;
  if (action) t.append(el("button", { textContent: action[0], onclick: () => { t.remove(); action[1](); } }));
  if (stays) t.append(el("button", { className: "toast-x", textContent: "Dismiss", onclick: () => t.remove() }));
  $("#toasts").append(t);
  onTop($("#toasts"));  // above a window open as a modal too
  // a plain note goes by itself, but not while the pointer is on it or its text is selected
  const later = () => setTimeout(() => t.matches(":hover") || getSelection().containsNode(t, true) ? later() : t.remove(), 2500);
  if (!stays) later();
}

let unsaved = false;
let savedConfig = "";  // the settings as last loaded or saved: a discard that brings them back clears the bar
// what a save sends: a series opened without a service is not part of it
// keys in order: a field cleared and typed again comes back last, and is still the same settings
const stableJSON = (v) => JSON.stringify(v, (k, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.keys(x).sort().map((y) => [y, x[y]])) : x));
// hidden_series is left out: hiding saves at once, never through Save; versions too: a save's answer, not an edit
const configKey = (c) => stableJSON({ ...c, hidden_series: undefined, versions: undefined, series: Object.fromEntries(Object.entries(c.series || {}).filter(([, x]) => x.service)) });
// Each part of the config (a section, a series) as last loaded or saved: a save sends which ones changed since, so
// the server keeps what another tab changed meanwhile (web.merge_page_changes)
let savedUnits = {};
const configUnits = (c) => Object.fromEntries([
  ...Object.entries(c).filter(([k]) => !["series", "versions", "hidden_series"].includes(k)).map(([k, v]) => [k, JSON.stringify(v)]),
  ...Object.entries(c.series || {}).filter(([, x]) => x.service).map(([k, v]) => [`series:${k}`, JSON.stringify(v)])]);
// Each other Sonarr's name as the server knows it: a rename reaches the server only at Save, so the requests that
// name a Sonarr send this one until then. By entry: the Sonarr editors change their entry in place.
const sonarrSavedName = new WeakMap();
const sonarrNames = () => (S.config.settings.sonarrs || []).map((i) => [i, i.name]);
const keepSonarrNames = (names) => names.forEach(([i, name]) => sonarrSavedName.set(i, name));
const savedSonarr = (name) => { const i = name && (S.config.settings.sonarrs || []).find((o) => o.name === name); return (i && sonarrSavedName.get(i)) || name; };
function dirty() {  // a change put back as it was hides the bar again
  renderCommands();
  unsaved = configKey(S.config) !== savedConfig;
  $("#savebar").hidden = !unsaved;
  $("#d-save").hidden = !unsaved;
  if (current) renderInherited(S.config.series[current.tvdbId]);  // a series option may now hide an inherited one
}

/* Spoiler-free: an episode's title blurred until clicked, for a series that asks (else the settings). What was shown
   is remembered in this browser. */
let revealed;
try { revealed = new Set(JSON.parse(localStorage.getItem("unshacklarr.revealed") || "[]")); } catch { revealed = new Set(); }
const spoilerFree = (tvdbId) => S.config?.series?.[tvdbId]?.spoiler_free ?? S.config?.settings?.spoiler_free === true;
const titleHidden = (tvdbId, sxxeyy, title) => !!title && !/^(TBA|Episode \d+)$/i.test(title) && spoilerFree(tvdbId) && !revealed.has(`${tvdbId}-${sxxeyy}`);
function episodeTitle(tvdbId, sxxeyy, title, className = "") {
  if (!titleHidden(tvdbId, sxxeyy, title)) return el("span", { className, textContent: title || "" });
  const show = (ev) => {
    ev.preventDefault(); ev.stopPropagation();
    revealed.add(`${tvdbId}-${sxxeyy}`);
    try { localStorage.setItem("unshacklarr.revealed", JSON.stringify([...revealed].slice(-2000))); } catch { /* shown for now */ }
    ev.currentTarget.replaceWith(el("span", { className, textContent: title }));
  };
  return el("span", { className: `${className} spoiler`.trim(), textContent: title, role: "button", tabIndex: 0,
    ariaLabel: "Hidden episode title. Press to show it.", title: "Show the title", onclick: show,
    onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") show(ev); } });
}

function el(tag, { dataset, ...props } = {}, ...children) {
  const e = Object.assign(document.createElement(tag), props);
  if (dataset) Object.assign(e.dataset, dataset);  // read-only as a whole: filled key by key
  e.append(...children);
  return e;
}

/* One row per option already set, plus a picker listing every other option the CLI knows. */
function optionsEditor(root, specs, values, anyFlag = false) {  // anyFlag: a service's own options, any flag as written too
  root.replaceChildren();
  for (const [flag, value] of Object.entries(values)) {
    const spec = specs.find((s) => s.flag === flag) || { flag, help: "", is_flag: typeof value === "boolean", choices: [] };
    let input;
    if (spec.is_flag) {
      input = el("label", { className: "check" }, el("input", { type: "checkbox", checked: !!value, onchange: (e) => { values[flag] = e.target.checked; dirty(); } }), "on");
    } else {
      input = el("input", { type: "text", value: value ?? "", placeholder: spec.choices.length ? spec.choices.join(", ") : spec.help,
        oninput: (e) => { values[flag] = e.target.value; dirty(); } });
      if (spec.choices.length) {
        const id = "dl" + Math.random().toString(36).slice(2);
        input.setAttribute("list", id);
        root.append(el("datalist", { id }, ...spec.choices.map((c) => el("option", { value: c }))));
      }
    }
    root.append(el("div", { className: "opt" },
      el("code", { title: spec.help }, flag),
      input,
      el("button", { className: "rm", title: "Remove", ariaLabel: `Remove ${flag}`,
        onclick: () => { delete values[flag]; dirty(); optionsEditor(root, specs, values, anyFlag); } }, icon("x"))));
  }
  const free = specs.filter((s) => !(s.flag in values)).sort((a, b) => a.flag.localeCompare(b.flag));
  if (!specs.length && !Object.keys(values).length) root.append(el("small", { className: "muted", textContent: "None." }));
  if (!free.length && !anyFlag) return;
  root.append(optionPicker(free, (spec) => {
    values[spec.flag] = spec.value ?? (spec.is_flag ? true : "");
    dirty();
    optionsEditor(root, specs, values, anyFlag);
    // Straight to the new option's value (the last row), or back to the search for a flag.
    const rows = root.querySelectorAll(".opt");
    (spec.is_flag ? root.querySelector(".picker input") : rows[rows.length - 1]?.querySelector("input"))?.focus();
  }, anyFlag));
}

/* Search box over the options not set yet: matches the flag, its short form and its help. */
function optionPicker(free, onPick, anyFlag = false) {
  const input = el("input", { type: "text", placeholder: "Add an option: type to search, e.g. lang, audio, atmos", ariaLabel: "Add an option",
    role: "combobox", ariaAutoComplete: "list", ariaExpanded: "false", autocomplete: "off", spellcheck: false });
  const list = el("ul", { className: "picker-list", role: "listbox", hidden: true });
  list.id = "pl" + Math.random().toString(36).slice(2);
  input.setAttribute("aria-controls", list.id);
  let shown = [], active = 0;

  // the flag as typed, case kept (AMZN's -B is not its -b): its exact short or long form first
  const exact = (s, raw) => raw.startsWith("-") && (s.short === raw || s.flag === raw);
  const rank = (s, q, raw) => exact(s, raw) ? -1 : !q ? 0 : s.flag.replace(/^-+/, "").startsWith(q) ? 0 : s.flag.includes(q) || s.short.includes(q) ? 1 : 2;
  // A flag none of them is (a remote server's version of the service has options this one lacks): added as written,
  // "-B" on, or "-X value" with its value
  const typedFlag = () => {
    const m = /^(-{1,2}[A-Za-z0-9][A-Za-z0-9-]*)(?:\s+(.+))?$/.exec(input.value.trim());
    return anyFlag && m && !free.some((s) => exact(s, m[1])) ? { flag: m[1], short: "", help: "", is_flag: !m[2], value: m[2] ? m[2].trim() : true, typed: true } : null;
  };
  function render() {
    const raw = input.value.trim().split(/\s+/)[0] || "";
    const q = raw.toLowerCase().replace(/^-+/, "");
    shown = free
      .filter((s) => !q || exact(s, raw) || s.flag.includes(q) || s.short.toLowerCase().includes(q) || s.help.toLowerCase().includes(q))
      .sort((a, b) => rank(a, q, raw) - rank(b, q, raw) || a.flag.localeCompare(b.flag));
    const typed = typedFlag();
    if (typed) shown.push(typed);
    active = Math.min(active, Math.max(shown.length - 1, 0));
    list.replaceChildren(...(shown.length ? shown.map((s, i) => {
      const li = el("li", { role: "option", className: i === active ? "on" : "",
        onmousedown: (e) => { e.preventDefault(); onPick(s); } },
        el("code", { textContent: s.typed ? `${s.flag}${s.value === true ? "" : ` ${s.value}`}` : exact(s, raw) && s.short === raw && s.flag !== raw ? `${s.short}, ${s.flag}` : s.flag }),
        el("span", { textContent: s.typed ? "Add it as written: the service on the remote server may know it" : s.help }));
      li.id = `${list.id}-${i}`;
      li.setAttribute("aria-selected", i === active);
      return li;
    }) : [el("li", { className: "none", textContent: "No option matches." })]));
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-activedescendant", shown.length ? `${list.id}-${active}` : "");
    list.querySelector("li.on")?.scrollIntoView({ block: "nearest" });
  }
  function close() { list.hidden = true; input.setAttribute("aria-expanded", "false"); }

  input.onfocus = render;
  input.oninput = () => { active = 0; render(); };
  input.onblur = close;
  input.onkeydown = (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (list.hidden) return render();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
      render();
    } else if (e.key === "Enter" && !list.hidden && shown[active]) {
      e.preventDefault();
      onPick(shown[active]);
    } else if (e.key === "Escape" && !list.hidden) {
      e.stopPropagation();  // close the list, not the drawer
      close();
    }
  };
  return el("div", { className: "picker" }, input, list);
}

const mainSonarr = () => S.config?.settings?.sonarr_name || "Sonarr";  // the main Sonarr where libraries are named
const SEL = { on: false, ids: new Set() };  // the series picked to change together (js/bulk.js)
/* A series uses a service when it downloads from it, or one of its seasons does (a season's own page) */
const usesService = (conf, tag) => conf?.service === tag || Object.values(conf?.season_pages || {}).some((page) => page.service === tag);
// The names a series is searched by: Sonarr's title, its other titles there, its name in file names
const seriesNames = (s) => [s.title, ...(s.altTitles || []), S.config.series[s.tvdbId]?.file_name || ""];
function renderWall() {
  const q = $("#search").value.trim().toLowerCase();
  const svc = $("#f-service").value, lib = $("#f-library").value;
  const libsOf = (s) => S.sonarrsOf?.[s.tvdbId] || [];
  const on = (s) => Boolean(S.config.series[s.tvdbId]?.service);
  const failing = (s) => Boolean(S.health[s.tvdbId]) && on(s);
  const counts = { "": S.series.length, "*": S.series.filter(on).length, h: S.config.hidden_series.length, f: S.series.filter(failing).length };
  counts["-"] = counts[""] - counts["*"];
  const hiddenTab = document.querySelector('#tab-series .seg [data-managed="h"]');
  hiddenTab.hidden = !counts.h;
  const failTab = document.querySelector('#tab-series .seg [data-managed="f"]');
  failTab.hidden = !counts.f;
  if ((!counts.h && hiddenTab.getAttribute("aria-pressed") === "true") || (!counts.f && failTab.getAttribute("aria-pressed") === "true")) {
    document.querySelectorAll("#tab-series .seg button").forEach((x) => x.setAttribute("aria-pressed", x.dataset.managed === ""));  // emptied: All again
  }
  document.querySelectorAll("#tab-series .seg button").forEach((b) => b.querySelector("span").textContent = `(${counts[b.dataset.managed]})`);
  $("#f-missing-n").textContent = `(${S.series.filter((s) => s.missing > 0).length})`;
  $("#f-monitored-n").textContent = `(${S.series.filter((s) => s.monitored).length})`;
  const managed = document.querySelector("#tab-series .seg [aria-pressed=true]").dataset.managed;
  const sorts = {
    title: (a, b) => a.title.localeCompare(b.title, "fr"),
    missing: (a, b) => b.missing - a.missing,
    year: (a, b) => (b.year ?? 0) - (a.year ?? 0),
  };
  const shown = S.series
    .filter((s) => {
      const on = S.config.series[s.tvdbId]?.service || "";
      return (!q || seriesNames(s).some((n) => n.toLowerCase().includes(q)))
        && (!managed || (managed === "f" ? failing(s) : managed === "h" ? S.config.hidden_series.includes(s.tvdbId) : managed === "*" ? on : !on))
        && (!svc || usesService(S.config.series[s.tvdbId], svc))
        && (!lib || (lib === "-" ? !!s.id : libsOf(s).some((o) => o.name === lib)))
        && (!$("#f-missing").checked || s.missing > 0)
        && (!$("#f-monitored").checked || s.monitored);
    })
    .sort(sorts[$("#f-sort").value]);
  const cards = shown.map((s) => {
      const conf = S.config.series[s.tvdbId];
      const art = el("span", { className: "art" });
      if (s.poster) art.append(el("img", { src: s.poster, alt: "", loading: "lazy", decoding: "async" }));
      if (conf?.service) art.append(el("span", { className: "svc", textContent: svcName(conf.service) }));
      if (libsOf(s).length) {  // the Sonarr libraries it is in, by their names; one switched off for it dimmed (by mj23au, #10)
        const off = (name, main) => Boolean(conf?.service) && Boolean(main ? conf.main_off : conf.sonarrs?.[name]?.off);
        art.append(el("span", { className: "lib" }, ...[...(s.id ? [[mainSonarr(), true]] : []), ...libsOf(s).map((o) => [o.name, false])]
          .flatMap(([n, main], i) => [...(i ? [" · "] : []),
            el("span", { textContent: n, ...(off(n, main) ? { className: "lib-off", title: "Switched off" } : {}) })])));
      }
      const sick = conf?.service && S.health[s.tvdbId];
      if (sick) art.append(el("span", { className: "sick", role: "img", ariaLabel: sick.cause ? `Failing: ${sick.cause}` : "Failing",
        title: `Its last ${sick.failing} downloads failed${sick.cause ? `: ${sick.cause}` : ""}` }, icon("alert")));
      if (S.config.hidden_series.includes(s.tvdbId)) {
        const off = el("span", { className: "off", role: "img", ariaLabel: "Hidden from the schedule", title: "Hidden from the schedule" });
        off.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">${EYE_SHUT}</svg>`;
        art.append(off);
      }
      const card = el("button", { className: "poster" + (conf?.service ? " on" : "") + (SEL.ids.has(s.tvdbId) ? " picked" : ""),
        ariaPressed: SEL.on ? String(SEL.ids.has(s.tvdbId)) : null, onclick: () => SEL.on ? pickSeries(s.tvdbId) : openDrawer(s) },
        art,
        el("span", { className: "name", textContent: s.title }),
        el("span", { className: "meta" }, `${s.year ?? ""}`,
          ...(s.missing ? [" · ", el("span", { className: "miss", textContent: `${s.missing} missing` })] : [])));
      card.dataset.tvdb = s.tvdbId;
      return card;
    });
  const managed0 = document.querySelector("#tab-series .seg [aria-pressed=true]").dataset.managed === "*" && !counts["*"];
  const empty = managed0
    ? el("div", { className: "empty" }, el("b", { textContent: "No series is downloading yet." }),
        "Open a series under All, pick a service or one of the links found on TMDB, then save.")
    : el("div", { className: "empty" }, el("b", { textContent: "No series match these filters." }), "Clear the search or pick another filter.");
  $("#wall").removeAttribute("aria-busy");
  $("#wall").replaceChildren(...(cards.length ? cards : [empty]));
}

async function loadServiceOptions(tag) {
  if (!tag) return [];
  serviceOptions[tag] ??= await api(`/api/services/${encodeURIComponent(tag)}`);
  return serviceOptions[tag];
}

async function openDrawer(s, tab, fromRoute = false) {
  current = s;
  $("#d-probe-out").replaceChildren();
  $("#d-url").placeholder = "URL or ID of the series";  // a Crave suggestion changes it for one series only
  showReleaseSeen(s);
  const sick = S.config.series[s.tvdbId]?.service && S.health[s.tvdbId];
  $("#d-sick").hidden = !sick;
  if (sick) $("#d-sick").replaceChildren(el("b", { textContent: `Its last ${sick.failing} downloads failed` }),
    el("span", { textContent: sick.cause || "See the history in Activity for why." }),
    el("span", { textContent: "Test this series below: a URL the service no longer knows, or a sign-in to renew in Settings › Services." }));
  $("#d-probe-state").textContent = "Asks the service which episodes it has. Nothing is downloaded.";
  drawerPushed = !fromRoute;
  if (!fromRoute) { drawerTab = tab || "episodes"; navigate(true); }  // back will close it
  const existed = s.tvdbId in S.config.series;
  const conf = (S.config.series[s.tvdbId] ??= { service: "", title: "", options: {}, service_options: {} });
  conf.options ??= {}; conf.service_options ??= {};  // before the snapshot: filling them in is no change
  drawerSnapshot = { id: s.tvdbId, existed, conf: JSON.stringify(conf) };  // what closing it compares with
  $("#d-poster").src = posterSrc(s.poster, s.title);
  $("#d-title").textContent = s.title;
  renderMeta(s);
  $("#d-service").replaceChildren(el("option", { value: "", textContent: "Not downloading" }),
    ...S.services.map((t) => el("option", { value: t, textContent: svcName(t) })));
  $("#d-service").value = conf.service || "";
  $("#d-url").value = conf.title || "";
  renderOrder();
  renderSeriesLanguage();
  fillProgrammes(conf);
  fillPages(conf);
  $("#d-fallback").value = conf.fallback_profiles || "";
  renderFind(conf.service);
  $("#d-subs").value = conf.subs_accept || "";
  $("#d-prefer").value = conf.audio_prefer || "";
  $("#d-prefer").placeholder = S.config.settings?.audio_prefer || "Example: fr";
  $("#d-subs").placeholder = S.config.settings?.subs_accept || "Example: fr";
  knownProfiles(conf.service);
  $("#d-release").value = conf.release_time || "";
  $("#d-release-day").value = String(conf.release_day || 0);
  $("#d-release-gap").value = conf.release_gap || "";
  $("#d-release-gap-help").textContent = "Two episodes the same evening, published one after the other. Empty: same time."
    + (s.runtime ? ` Sonarr: ${s.runtime} min.` : "");
  $("#d-audio").value = conf.audio_accept || "";
  $("#d-audio").placeholder = S.config.settings?.audio_accept || "Example: fr, en";
  bcMonth = null;  // its own schedule's month: from its first day's
  $("#d-bc-form").hidden = true;
  $("#d-bc").open = !!conf.broadcast;  // folded away unless the series has one
  $("#d-since").textContent = conf.since
    ? `New episodes airing from ${new Date(conf.since).toLocaleDateString(LOCALE, { day: "numeric", month: "long", year: "numeric" })} are downloaded automatically. For older ones, tick them in Episodes.`
    : "Once it has a service and you save, new episodes are downloaded automatically. For older ones, tick them in Episodes.";
  fillAdv(conf, s.title);
  fillQualityImport(conf);
  $("#d-adv").open = Boolean(conf.file_name || Object.keys(conf.season_map || {}).length || conf.episode_offset || conf.season_offset
    || Object.keys(conf.episode_map || {}).length || conf.join_parts === false || conf.parts || (conf.episode_name && conf.episode_name !== "joined")
    || conf.programmes);
  optionsEditor($("#d-opts"), S.dlOptions, conf.options);
  renderHideToggle();
  if (!$("#drawer").classList.contains("open")) drawerOpener = document.activeElement === document.body ? null : document.activeElement;
  $("#drawer").classList.add("open");
  $("#backdrop").classList.add("open");
  drawerModal(true);
  if (!document.body.classList.contains("drawer-open")) wallScroll = scrollY;  // a phone scrolls the page itself: back to it on close
  document.body.classList.add("drawer-open");
  showDrawerTab(tab || (conf.service ? "episodes" : "settings"), true);  // a new series needs its service first
  navigate(false);
  loadEpisodes(s);
  $("#drawer .d-body").scrollTop = 0;
  dsPicked = null;
  requestAnimationFrame(dsLight);  // its first card lit in the shortcuts
  scrollTo({ top: 0 });
  ($("#close").getClientRects().length ? $("#close") : $("#d-back")).focus();  // a phone shows Back, not Close
  loadSuggestions(s);
  await renderServiceOptions(conf);
}

/* Where the series stands, above its settings: downloaded from its service, missing its URL, failing, or not downloaded. */
function renderSeriesState() {
  const conf = current && S.config.series[current.tvdbId], box = $("#ds-state");
  if (!conf) return;
  renderSeriesLanguage();  // its service picked or changed since the page opened: said then too
  const sick = conf.service && S.health[current.tvdbId];
  const [cls, text] = !conf.service ? ["", "Not downloading"]
    : sick ? ["down", `Its downloads from ${svcName(conf.service)} fail`]
    : !conf.title && !conf.programmes ? ["warn", `On ${svcName(conf.service)}: its series URL is missing`]
    : conf.programmes ? ["ok", `Downloaded from ${svcName(conf.service)}, each episode its own programme`]
    : ["ok", `Downloaded from ${svcName(conf.service)}`];
  box.classList.remove("ok", "down", "warn");
  if (cls) box.classList.add(cls);
  $("#ds-state-text").textContent = text;
  // What failed, and where to mend it: the service's row in Settings, Services
  $("#ds-fix").hidden = !sick;
  $("#ds-fix").replaceChildren(...(sick ? [el("span", { textContent: sick.cause || "See the history in Activity for why." }),
    el("button", { type: "button", className: "btn small", textContent: `Check ${svcName(conf.service)} in Settings › Services`, onclick: () => openServiceRow(conf.service) })] : []));
}
/* Service options only show for a service that has some; "stop" only for a managed series. */
async function renderServiceOptions(conf) {
  renderSeriesState();
  const specs = await loadServiceOptions(conf.service).catch(() => []);  // Unshackle down: no options to offer
  if (current && S.config.series[current.tvdbId] !== conf && oneOff !== conf) return;  // another series opened meanwhile
  $("#d-service-field").hidden = !conf.service;  // its options, or any flag written as the service on a remote server takes it
  optionsEditor($("#d-service-opts"), specs, conf.service_options, true);
  $("#d-stop").hidden = !conf.service;
  renderInherited(conf);
  renderBroadcast();
}

/* The logo goes home: the schedule, from wherever you are. */
$("#home").onclick = async (e) => {
  e.preventDefault();
  if (current && !await closeDrawer(true)) return;
  showTab("schedule");
  scrollTo({ top: 0 });
};
let wallScroll = 0;
/* The drawer is a modal: with it open the page behind cannot be reached by keyboard or screen reader, and closed, it is out of the tab order. */
let drawerOpener = null;
function drawerModal(open) {
  // the toasts join the drawer while it is open: their Dismiss and Undo stay in reach and focus never leaves the dialog
  const toasts = $("#toasts"), shown = Boolean(toasts.showPopover) && toasts.matches(":popover-open");  // an older browser has no popover: its z-index
  if (open) $("#drawer").append(toasts); else document.body.append(toasts);
  if (shown) onTop(toasts);  // moving it closes the popover it shows in
  $("#drawer").inert = !open;
  for (const behind of document.querySelectorAll("body > header, main")) behind.inert = open;
}
/* Closed, focus goes back to what opened it if that is still there and in sight, else to the series' poster. */
function returnFocus(opener, tvdbId) {
  const seen = (e) => e?.isConnected && e.getClientRects().length;
  // the opener may be gone (Schedule redrew it) or hidden (the Series page): the series' own control in sight, else the current page's tab
  const back = [opener, ...document.querySelectorAll(`[data-tvdb="${tvdbId}"]`)].find(seen) || document.querySelector('nav [aria-current="page"]');
  back?.focus({ preventScroll: true });
}
/* Focus stays inside the open drawer: the toasts after it are outside the inert page but must not take focus from it
   (a modal dialog opened from the drawer, such as "unsaved changes", is its own layer and keeps focus) */
let drawerLastFocus = null;
function drawerFocusGuard(e) {
  const d = $("#drawer");
  if (!d.classList.contains("open") || d.inert) return;
  if (d.contains(e.target)) { drawerLastFocus = e.target; return; }
  if (e.target.closest("dialog[open]")) return;  // a window opened on top of it
  const usable = (x) => x?.isConnected && d.contains(x) && !x.disabled && x.getClientRects().length;
  // the last one may have been redrawn away (the episode list refreshes): then the first control in sight
  const to = usable(drawerLastFocus) ? drawerLastFocus : [...d.querySelectorAll("button, a[href], input, select, textarea")].find(usable);
  to?.focus();
}
document.addEventListener("focusin", drawerFocusGuard);/* A series' settings changed since its panel opened, and not saved: closing it asks first. */
let drawerSnapshot = null;
const drawerChanged = () => !!current && drawerSnapshot?.id === current.tvdbId && stableJSON(S.config.series[current.tvdbId]) !== stableJSON(JSON.parse(drawerSnapshot.conf));
function discardDrawer() {  // the series as it was when its panel opened; the bar goes if nothing else waits
  const { id, existed, conf } = drawerSnapshot;
  if (existed) S.config.series[id] = JSON.parse(conf); else delete S.config.series[id];
  if (configKey(S.config) === savedConfig) { unsaved = false; $("#savebar").hidden = true; $("#d-save").hidden = true; }
}
function askUnsaved(name) {
  const dialog = $("#unsaved-dialog");
  $("#unsaved-text").textContent = `${name}: its settings changed and are not saved yet.`;
  dialog.returnValue = "keep";
  dialog.showModal();
  return new Promise((done) => dialog.addEventListener("close", () => done(dialog.returnValue || "keep"), { once: true }));
}
async function closeDrawer(fromRoute = false) {
  if (!$("#drawer").classList.contains("open")) return true;
  if (drawerChanged()) {
    const choice = await askUnsaved(current.title);
    if (choice === "save") {
      try { await save(); } catch (e) { toast(`Could not save: ${e.message}`, true); return keepDrawer(fromRoute); }
    } else if (choice === "discard") discardDrawer();
    else return keepDrawer(fromRoute);
  }
  if (!fromRoute && drawerPushed) { history.back(); return true; }  // popstate closes it, and back stays in step
  if (drawerTab === "settings") leaveNews((n) => n.series);  // its settings were open: their news are seen
  $("#drawer").classList.remove("open");
  $("#backdrop").classList.remove("open");
  drawerModal(false);
  document.body.classList.remove("drawer-open");
  const id = current.tvdbId;
  current = null;
  if (!fromRoute) navigate(false);  // opened from a link: no history entry to go back to
  renderWall();  // rebuilds the cards: a poster that opened it is a new one now
  scrollTo({ top: wallScroll });
  returnFocus(drawerOpener, id);
  drawerOpener = null;
  return true;
}
function keepDrawer(fromRoute) {  // it stays open; the back button already left its address: back to it
  if (fromRoute) { drawerPushed = true; history.pushState(null, "", routeHash()); }
  return false;
}

$("#d-refresh").onclick = () => current && loadSuggestions(current, true);
/* A spinner with its text while something loads; a message and a retry when it fails. */
function loading(text) {
  return el("div", { className: "loading", role: "status" }, el("span", { className: "spinner", ariaHidden: "true" }), text);
}
function failed(text, retry) {
  return el("div", { className: "failed", role: "alert" }, el("span", { textContent: text }),
    retry ? el("button", { className: "btn small", textContent: "Try again", onclick: retry }) : "");
}

/* The series' channel may have a catch-up service here, picked and looked up on by its name. */
function networkButton(s, tag) {
  return el("button", { type: "button", ariaLabel: `Find it on ${svcName(tag)}`, onclick: () => {
    const sel = $("#d-service");
    if (sel.value !== tag) { sel.value = tag; sel.dispatchEvent(new Event("change")); }
    $("#d-find").hidden = true;
    $("#d-find-q").value = s.title;
    $("#d-find-open").click();
  } }, el("b", { textContent: svcName(tag) }), el("span", { textContent: `Find ${s.title} on ${svcName(tag)}` }));
}
/* No link from TMDB: the channel's service is all there is to offer. */
function networkPick(s, box, none, lead) {
  const tag = S.networkServices?.[s.tvdbId];
  if (!tag) return box.replaceChildren(el("small", { className: "muted", textContent: none }));
  box.replaceChildren(el("small", { className: "muted", textContent: `${lead} Its channel, ${s.network}, is on ${svcName(tag)}:` }),
    networkButton(s, tag));
}

async function loadSuggestions(s, refresh = false) {
  const box = $("#d-suggest");
  $("#d-checked").textContent = "";
  $("#d-refresh").hidden = !s.tmdbId;
  if (!s.tmdbId) return networkPick(s, box, "Sonarr has no TMDB ID for this series.", "Sonarr has no TMDB ID for this series.");
  box.replaceChildren(loading("Looking up where to watch it…"));
  let links, brands;
  try {
    // as long as /api/probe: a service linking several titles is asked for their names (named_titles)
    const found = await api(`/api/suggest/${s.tmdbId}?network=${encodeURIComponent(s.network || "")}${refresh ? "&refresh=1" : ""}`, { wait: 120 });
    links = found.links;
    brands = found.brands || [];
    if (current === s) $("#d-checked").textContent = `checked ${ago(found.checked)}`;
  }
  catch (e) { if (current === s) box.replaceChildren(failed(`TMDB lookup failed: ${e.message}`, () => loadSuggestions(s, refresh))); return; }
  if (current !== s) return;  // another series was opened meanwhile
  if (!links.length && !brands.length) return networkPick(s, box, `TMDB lists no supported service in ${S.config.tmdb_countries.join(", ")}. Enter it below by hand.`,
    "TMDB lists no supported service.");
  box.replaceChildren(...links.map((l) => el("button", {
    ariaLabel: `Use ${svcName(l.service)}: ${[l.name, l.url].filter(Boolean).join(", ")}`,
    onclick: () => applySuggestion(l),
  }, el("b", { textContent: svcName(l.service) }), el("span", { textContent: (l.name ? `${l.name} · ` : "")  // a service linking several titles names each
    + (l.needs_series_url || l.episode ? `episode link · ${l.url}` : l.found_by === "search" ? `found by its title · ${l.url}` : l.found_by === "homepage" ? `TMDB homepage · ${l.url}` : l.url) }),
    el("small", { textContent: l.country }))));
  box.querySelectorAll("button").forEach((b, i) => b.dataset.url = links[i].url);
  const network = S.networkServices?.[s.tvdbId];  // after TMDB's links: theirs keep their order
  if (network && !links.some((l) => l.service === network)) box.append(networkButton(s, network));
  // A brand TMDB lists only inside Amazon/Apple, not found on its own service by title: look it up there by hand.
  brands.filter((t) => t !== network).forEach((t) => box.append(networkButton(s, t)));
}

async function applySuggestion(link) {
  const conf = S.config.series[current.tvdbId];
  if (conf.service !== link.service) conf.service_options = {};
  conf.service = link.service;
  conf.title = link.needs_series_url ? "" : link.url;
  $("#d-service").value = link.service;
  $("#d-url").value = conf.title;
  if (link.needs_series_url) {  // Crave: only an episode is linked; its series page has the URL to use
    if (/^https?:\/\//i.test(link.url)) window.open(link.url, "_blank", "noopener");  // a web page only, never javascript:
    toast("This Crave link points to an episode. On crave.ca, open the series page and paste that URL here.");
    $("#d-url").placeholder = "https://www.crave.ca/en/series/name-12345";
    $("#d-url").focus();
  }
  renderSeriesState();
  renderMeta(current);
  renderCheck(current, true);  // Episodes offers to ask the service at once, as a typed link does
  optionsEditor($("#d-service-opts"), await loadServiceOptions(conf.service).catch(() => []), conf.service_options, true);
  dirty();
  renderWall();
}

$("#d-service").onchange = async (e) => {
  const conf = S.config.series[current.tvdbId];
  conf.service = e.target.value;
  conf.service_options = {};
  dirty();
  renderMeta(current);
  renderCheck(current, true);
  knownProfiles(conf.service);
  renderFind(conf.service);
  fillQualityImport(conf);  // its Default is its new service's
  await renderServiceOptions(conf);
  renderWall();
};
$("#d-stop").onclick = async () => {
  const conf = S.config.series[current.tvdbId];
  conf.service = "";
  conf.service_options = {};
  delete conf.since;
  $("#d-service").value = "";
  dirty();
  renderCheck(current, true);
  await renderServiceOptions(conf);
  renderWall();
  toast(`${current.title} will no longer be downloaded once you save`);
};
/* The service a link is on, from the services' sites (www.canalplus.com: CanalPlus); null for none known. */
function serviceOfLink(link) {
  let host;
  try { host = new URL(String(link).trim()).hostname.replace(/^www\./, ""); } catch { return null; }
  const hit = Object.entries(S.domains || {}).find(([domain]) => host === domain || host.endsWith(`.${domain}`));
  return hit ? hit[1] : null;
}
/* The series looked up by its name on its service (unshackle's search): a result picked fills in its URL. */
function renderFind(service) {
  $("#d-find").hidden = true;
  $("#d-find-out").replaceChildren();
  $("#d-find-open").hidden = !service;
  $("#d-find-open").textContent = service ? `Find it on ${svcName(service)}` : "";
}
$("#d-find-open").onclick = () => {
  $("#d-find").hidden = !$("#d-find").hidden;
  if ($("#d-find").hidden) return;
  if (!$("#d-find-q").value) $("#d-find-q").value = current.title;
  $("#d-find-go").click();
};
$("#d-find-q").onkeydown = (e) => { if (e.key === "Enter") $("#d-find-go").click(); };
$("#d-find-go").onclick = async () => {
  const conf = S.config.series[current.tvdbId], s = current, out = $("#d-find-out");
  if (!$("#d-find-q").value.trim()) return out.replaceChildren(el("p", { className: "status-err", textContent: "Type the series' name first" }));
  out.replaceChildren(loading(`Searching ${svcName(conf.service)}…`));
  let r;
  try { r = await api("/api/series/search", { method: "POST", body: JSON.stringify({ show: conf, query: $("#d-find-q").value }) }); }
  catch (e) { if (current === s) out.replaceChildren(el("p", { className: "status-err", textContent: e.message })); return; }
  if (current !== s) return;
  if (!r.results.length) return out.replaceChildren(el("p", { className: "muted", textContent: `Nothing found on ${svcName(conf.service)} under that name.` }));
  out.replaceChildren(...r.results.map((x) => el("button", { type: "button", className: "url-hit", onclick: () => {
    $("#d-url").value = x.url || x.id;
    $("#d-url").dispatchEvent(new Event("input"));
    $("#d-find").hidden = true;
    toast(`${x.title}: its URL is filled in`);
  } }, el("b", { textContent: x.title }), x.label ? el("span", { className: "url-hit-label", textContent: x.label }) : "",
    x.description ? el("small", { textContent: x.description }) : "")));
};
/* The profiles a service logs in with (credentials and cookie files): a click adds one to the series' fallbacks. */
async function knownProfiles(service) {
  const box = $("#d-fallback-known");
  box.hidden = true;
  if (!service) return;
  let r;
  try { r = await api(`/api/profiles/${encodeURIComponent(service)}`); } catch { return; }
  if (S.config.series[current?.tvdbId]?.service !== service || !r.profiles.length) return;
  box.replaceChildren(el("span", { textContent: `On ${svcName(service)}:` }), ...r.profiles.map((p) => el("button", { type: "button", className: "chip-btn", textContent: p,
    onclick: () => {
      const list = $("#d-fallback").value.split(/[\s,]+/).filter(Boolean);
      if (!list.includes(p)) { $("#d-fallback").value = [...list, p].join(", "); $("#d-fallback").dispatchEvent(new Event("input")); }
    } })));
  box.hidden = false;
}
$("#d-prefer").oninput = (e) => { S.config.series[current.tvdbId].audio_prefer = e.target.value.trim() || undefined; dirty(); };
$("#d-subs").oninput = (e) => { S.config.series[current.tvdbId].subs_accept = e.target.value.trim() || undefined; dirty(); };
$("#d-fallback").oninput = (e) => { S.config.series[current.tvdbId].fallback_profiles = e.target.value.trim() || undefined; dirty(); };
/* Each episode its own programme (BBC Documentaries and the like): found by its title, or by a URL pasted here. */
function fillProgrammes(conf) {
  $("#d-programmes").checked = !!conf.programmes;
  showProgrammes(!!conf.programmes);
  $("#d-progmap").value = Object.entries(conf.programme_map || {}).map(([a, b]) => `${a} ${b}`).join("\n");
}
function showProgrammes(on) {
  $("#d-progmap-field").hidden = !on;
  $("#d-probe").hidden = $("#d-probe-state").hidden = on;  // it lists a series URL's episodes
  // each episode's number comes from its programme: the series' numbering does nothing then
  for (const id of ["#d-seasons", "#d-pages", "#d-offset", "#d-soffset", "#d-epmap"]) $(id).closest(".field").hidden = on;
}
$("#d-programmes").onchange = (e) => {
  const conf = S.config.series[current.tvdbId];
  if (e.target.checked) conf.programmes = true; else delete conf.programmes;
  showProgrammes(e.target.checked);
  dirty();
  renderSeriesState();
};
/* A season the service lists as a show of its own (SBS: Has Fallen's S02 is "Apollo Has Fallen"): its page. */
function fillPages(conf) {
  $("#d-pages").value = Object.entries(conf.season_pages || {})
    .map(([s, p]) => `S${String(s).padStart(2, "0")} ${p.url}${Number(p.season || 1) !== 1 ? ` ${p.season}` : ""}`).join("\n");
}
$("#d-pages").oninput = (e) => {
  const rows = [...e.target.value.matchAll(/^\s*S?(\d+)\s+(\S+)(?:\s+(\d+))?\s*$/gim)];
  const conf = S.config.series[current.tvdbId];
  const other = (season, url) => {  // its site's service, kept if the series' changes; an ID keeps the one it had
    const tag = serviceOfLink(url), previous = conf.season_pages?.[season];
    if (tag) return { service: tag };
    return previous?.url === url && previous.service ? { service: previous.service } : {};
  };
  if (rows.length) conf.season_pages = Object.fromEntries(rows.map((m) => [Number(m[1]), { url: m[2], ...(m[3] && Number(m[3]) !== 1 ? { season: Number(m[3]) } : {}), ...other(Number(m[1]), m[2]) }]));
  else delete conf.season_pages;
  dirty();
};
$("#d-progmap").oninput = (e) => {
  const pairs = [...e.target.value.matchAll(/^\s*(S\d+E\d+)\s+(\S+)\s*$/gim)];
  const conf = S.config.series[current.tvdbId];
  if (pairs.length) conf.programme_map = Object.fromEntries(pairs.map((m) => [m[1].toUpperCase(), m[2]])); else delete conf.programme_map;
  dirty();
};
$("#d-url").oninput = async (e) => {
  const conf = S.config.series[current.tvdbId], before = serviceOfLink(conf.title);
  conf.title = e.target.value.trim();
  dirty();
  renderMeta(current);
  renderSeriesState();
  renderCheck(current, true);  // Episodes offers to ask the service at once
  // A link to another site: its service, picked for you (a service chosen by hand stays while its link is edited)
  const tag = serviceOfLink(conf.title);
  if (tag && tag !== before && tag !== conf.service && S.services.includes(tag)) {
    conf.service = tag;
    conf.service_options = {};
    $("#d-service").value = tag;
    toast(`${svcName(tag)}: recognised from the link`);
    dirty();  // a series without a service was not part of the save: with one now, Save shows
    renderMeta(current);
    renderCheck(current, true);
    await renderServiceOptions(conf);
    renderWall();
  }
};
/* Sonarr as a browser opens it: its public address, else the one Unshacklarr uses unless it's a Docker name (http://sonarr:8989). */
function sonarrWeb(url = S.config.settings?.sonarr_url, publicUrl = S.config.settings?.sonarr_public_url) {
  if (publicUrl) return publicUrl.replace(/\/+$/, "");
  try {
    const u = new URL(url);
    // A Docker name or a LAN address only works at home. Sonarr runs beside Unshacklarr (as in the compose file): the
    // name this page was opened with reaches the same machine (Tailscale, a VPN, another LAN name). A LAN address
    // stays as it is through a reverse proxy (no port in the page's address): Sonarr's port is rarely open there,
    // and the LAN link still works at home. A Docker name always takes the page's: it has no link otherwise.
    const docker = !u.hostname.includes(".") && u.hostname !== "localhost";
    const lan = u.hostname === "localhost" || /^(10|127|192\.168|172\.(1[6-9]|2\d|3[01]))\./.test(u.hostname);
    if (location.hostname !== u.hostname && (docker || (lan && location.port))) u.hostname = location.hostname;
    return u.origin + u.pathname.replace(/\/+$/, "");
  } catch { return ""; }
}
/* The other Sonarr instances that have the series, set up here or not: their names, each a link to it there. */
function inOtherSonarrs(s, ext) {
  const others = S.sonarrsOf?.[s.tvdbId] || [];
  if (!others.length) return [];
  return others.flatMap((o) => {
    const web = sonarrWeb(o.url, "");
    return [" · ", web && o.slug ? ext(o.name, `${web}/series/${o.slug}`) : o.name];
  });
}
/* Under the series' name: it on TVDB, TMDB, its service (the page Unshackle downloads from) and Sonarr. */
function renderMeta(s) {
  const ext = (label, href) => el("a", { href, target: "_blank", rel: "noopener", textContent: label, title: `This series on ${label}` });
  const conf = S.config.series[s.tvdbId];
  $("#d-meta").replaceChildren(ext("TVDB", `https://thetvdb.com/dereferrer/series/${s.tvdbId}`),
    ...(s.tmdbId ? [" · ", ext("TMDB", `https://www.themoviedb.org/tv/${s.tmdbId}`)] : []),
    ...(conf?.service && /^https?:\/\//.test(conf.title || "") ? [" · ", ext(svcName(conf.service), conf.title)] : []),
    ...(s.id && sonarrWeb() && s.titleSlug ? [" · ", ext("Sonarr", `${sonarrWeb()}/series/${s.titleSlug}`)] : []),
    ...inOtherSonarrs(s, ext),
    s.year ? ` · ${s.year}` : "");
}
/* Sonarr 5 numbers a series in an episode order (aired, DVD, Netflix…): a numbering set here is for one order; Sonarr
   numbering it in another since, its new episodes wait (sync.order_changed) until the numbering is checked. */
const NUMBERED = ["season_map", "season_offset", "season_offset_from", "episode_offset", "episode_map"];
function renderOrder() {
  const conf = S.config.series[current.tvdbId] || {}, box = $("#d-order"), now = current.order || "official";
  const name = (t) => current.orders?.[t] || (t === "official" ? "the aired order" : `the ${t} order`);
  const changed = conf.sonarr_order && conf.sonarr_order !== now && NUMBERED.some((k) => conf[k]);
  box.className = `order-note${changed ? " warn" : ""}`;
  box.hidden = !changed && now === "official";
  if (box.hidden) return box.replaceChildren();
  if (changed) $("#d-adv").open = true;
  box.replaceChildren(el("p", { textContent: changed
    ? `Sonarr now numbers this series in ${name(now)}, but the numbering below was set for ${name(conf.sonarr_order)}. New episodes of this series are not downloaded until you check the numbering and confirm it.`
    : `Sonarr numbers this series in ${name(now)}. Set the numbering below for this order.` }),
    ...(changed ? [el("button", { type: "button", className: "btn small", textContent: "Numbering is correct",
      onclick: () => { conf.sonarr_order = now; dirty(); renderOrder(); } })] : []));
}
$("#d-adv").addEventListener("input", (e) => {  // numbering set now: for the order Sonarr has now
  if (!$("#oneoff-dialog").open && ["d-seasons", "d-offset", "d-soffset", "d-sfrom", "d-epmap"].includes(e.target.id)) {
    S.config.series[current.tvdbId].sonarr_order = current.order || "official";
    renderOrder();
  }
});
/* Sonarr 5 gives a series' titles in its metadata language: English by default, against a service naming episodes in
   your language, they meet less; one click asks Sonarr for them in yours (it refreshes the series at once). */
function renderSeriesLanguage() {
  const conf = S.config.series[current.tvdbId] || {}, want = S.metadataLanguage;
  // once its service was asked and their titles don't agree with Sonarr's (Shifting Gears on a French Disney+), or for
  // a series made in your language (Surveillant !); in its Settings and atop its Episodes
  const off = !want || !current.language || current.language === want || !(epTitlesAgree === false || current.originalLanguage === want);
  document.querySelectorAll(".lang-note").forEach((box) => {
    box.hidden = off;
    if (off) return box.replaceChildren();
    box.replaceChildren(
      el("div", {}, el("b", { textContent: `Episode titles in ${current.language}` }),
        el("p", { textContent: conf.service
          ? `Sonarr shows this series' episode titles in ${current.language}, but ${svcName(conf.service)} shows them in ${want}. With ${want} titles in Sonarr, Unshacklarr can match each episode with ${svcName(conf.service)} by its title.`
          : `Sonarr shows this series' episode titles in ${current.language}, but streaming services in your country show them in ${want}. With ${want} titles in Sonarr, Unshacklarr can match each episode by its title.` })),
      el("button", { type: "button", className: "btn small primary", textContent: `Use ${want} titles`, onclick: async (e) => {
        e.target.disabled = true;
        try {
          await api(`/api/series/${current.tvdbId}/language`, { method: "POST", body: "{}" });
          current.language = want;
          toast(`Sonarr is updating ${current.title} with ${want} titles.`);
          renderSeriesLanguage();
          followTitles(current, want);  // the list follows, then the service is asked again
        } catch (err) { e.target.disabled = false; toast(err.message, true); }
      } }));
  });
}
