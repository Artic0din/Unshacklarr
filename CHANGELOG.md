# Changelog

Every change worth knowing, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/): until 1.0.0, a minor version may change how things work.

## [Unreleased]

### Security

- **Session revocation.** The app now refuses to verify sessions when the sign-out record is corrupt. (#367)
- **cryptography 50.0.2.** Its wheels carry OpenSSL 4.0.3, a security release whose most severe fix is High. Push
  notifications are signed and encrypted with it.
- **oauthlib 4.0.1.** Fixes CVE-2026-49272, a device-flow token endpoint that handed out a bearer token without a
  valid device code. Unshacklarr runs no OAuth server, so it was not exposed; oauthlib comes with Apprise.
- **No one can lock the owner out of signing in.** Wrong passwords are limited per client only, no longer 30 for
  everyone together, and `X-Real-IP` is believed only from the proxy's addresses listed in Settings, Account. Behind
  a reverse proxy, list its addresses there, even without signing in through it: until then, every client behind it
  shares one limit. (#212)
- **aiohttp 3.14.4.** Eight advisories fixed, three of them high: the server no longer waits without end for a
  request's headers, can no longer be made to use too much memory, CPU or file descriptors, and parses requests more
  strictly. (#24)
- **certifi 2026.10.23.** The emSign root certificates, whose intermediate keys were compromised, are no longer
  trusted for Unshacklarr's own HTTPS connections (a critical advisory).

### Added

- Added the shared DevKit pull request check, which rejects non-conventional titles and commit messages, agent attribution and forbidden paths such as `node_modules`.
- Added six Australian series to the matching corpus, one each on 9Now, 7plus, ABC iview, SBS On Demand, Stan and
  Binge, so their numbering is tested: RBT's S05E166 on 9Now, Bluey's Auslan S01E01 (Sonarr's S01E16), Stan's Will &
  Grace Christmas collection and Binge's reordered Crimes That Shook Australia. (#317)
**📦 Long jobs**
- **A bar at the bottom of a job.** The episode going on stays in sight however long the job; one tap on the bar opens
  its output, a click beside folds it. On a phone, the job's buttons are in it too.
- **Show or hide a job's episodes.** Click Done, Queued, Failed… in a job to hide those episodes or show them again.
- **Options of a job.** While it runs, its download and service options can be changed for the episodes still to
  come, starting from the ones they have now; the series stays as it is.
- **Retry the failed episodes while the job runs**, and a retry goes before the episodes still to come.
- **A job survives a restart.** Its queued episodes are kept on disk and queued again when Unshacklarr starts; a paused
  job stays paused.
- **Delete the job.** A job that is over leaves the history in one click.
- **The video's codec in Activity.** Video 1080p SDR H.265: the codec asked while it downloads, the file's once made.

**🌐 Proxies**
- **A proxy that fails is tried again**, at once, 3 times, each on another server of the provider (nordvpn:fr). If it
  still fails, the job pauses and you are told, instead of failing every episode left.

**🎧 Services and languages**
- **A daily check of every service.** Once a day, and while no download runs, each service a series uses is searched,
  its series listed, and the tracks of its latest episode asked for, through Unshackle only (no download, no licence).
  A stage that fails is told once in the bell, and again when it recovers; a stale sign-in shows as a sign-in failure.
  The last result of each service is in Settings › Services, which also has Check now. (#319)
- **orig in the accepted audio languages.** Each series' original language as Sonarr gives it, so "orig, fr" works for
  every series at once. In Settings › Download options.
- **Clear one service's cache.** In Settings › Per service, without logging every other service out. Unshacklarr
  needs to see Unshackle's Cache folder (`CACHE_DIR` with Docker).
- **Any service option.** A flag the service on a remote server knows, such as AMZN's `-B`, can be written as is in a
  service's or a series' options.
- **The API speaks the service's numbering.** `"numbering": "service"` takes Disney+'s S04E05 for the episode it is in
  Sonarr, and `"audio": "fr"` lets Unshacklarr decide: download, download again, or add the French track.

**🧩 Unshackle after 6.0.0**
- **A remote server's login questions.** An OTP or a PIN its login asks while it lists a series comes to the bell,
  with a field to answer.
- **What your Unshackle supports**, in Settings › Unshackle, each with what it needs; a series set to `--remote` on
  an Unshackle that cannot run it is told in the bell.
- **Its log, errors by service and remote sessions** in Settings › Unshackle, even in Docker, once `unshackle.yaml`
  has a `serve: dashboard: key:` and Unshacklarr sees that file.
- **Restart waits for the downloads**, with that key too: Restart in Settings › Unshackle says Unshackle is busy
  instead of cutting them.
- **`--generate-dv`.** With `-r HYBRID`, Dolby Vision made from the HDR10+ when a title has none. In Download options.
- **Proxies by network or IP.** `nordvpn:fr@187.14.108.15`, `nordvpn:ca@-datacamp`: the API's `proxy` takes them.
- **Clear finished**, in Settings › Unshackle › Maintenance: Unshackle forgets its finished downloads.
- **The editor knows the new keys** of `unshackle.yaml`: `codec_names`, `muxing.track_names`, `original_label`…

**⏰ Release times**
- **Next episode.** Two episodes the same evening, published one after the other: the second is tried that many
  minutes later. In a series' When.

**📶 Quality ladders, simpler**
- **Ladders as chips.** A service or a series picks its ladder in one tap; Edit ladders leads to Settings, Quality.
- **What the ladder takes over is said.** `--quality`, `--vcodec` and `--vbitrate-range` set at that level are flagged
  with one button to remove them; with a ladder they are no longer applied, and the command shows the ladder's video.
- **A highest bitrate per step.** 1080p up to 6000 kbps, 4K at its best: a cap on one step only.
- **Try unlisted codecs.** A ladder can try its AV1 or H.265 step even when the service lists only H.264, as Amazon
  does through serve.

**🗂️ Several Sonarr, scripts and checks**
- **Service options per Sonarr.** A series' 4K or AV1 copy can use another profile or flags, in its Libraries, Advanced.
- **After download.** Each episode downloaded is posted as JSON to your script: series, Sonarr, episode and file paths.
- **Read-only files.** The Cookies page lists Unshackle's files it can no longer write, often left to root by a
  `docker exec`.
- **Search by any title.** The series search also finds a series by its other titles in Sonarr and its name in files.

**💾 Saving**
- **Discard unsaved changes.** The bar at the bottom has a Discard changes button next to Save changes: it puts the
  settings back as last saved, a notification address you removed included, and says "Unsaved changes" to a screen
  reader when it shows. (#280)

### Changed

- Grouped repeated episode failures in Activity, kept the original errors in episode details, and made Retry secondary when none of the failures are likely to clear on retry. (#358)
- Kept Series wall filters on one desktop toolbar and made every filter and action reachable on phones without sideways scrolling. (#352)
- Balanced Series status buttons on phones, kept search and selects together on wider screens, and closed the filters panel when keyboard focus moved away.
- Corrected which Series controls the Filters and actions button announced as collapsed on desktop.
- Moved Activity tools into a compact switcher, added shortcuts to running downloads, and kept the download detail pane full size. (#353)
- Added service names and individual downloads to Catch up, tightened Waiting and Upgrades, and added Fix sign-in to failed jobs that need it. (#353)

- Made the Schedule toolbar fit smaller screens, showed more episodes with artwork in Week view, and moved episode actions ahead of the command. (#352)
- Made the Series drawer more compact, with expandable subtitle lists, fewer toolbar rows, and clearer episode status when file details are unavailable. (#352)

- Kept the header in view while scrolling, moved version details to Settings, and made Inbox filters and episode lists easier to read on small screens. (#351)
- Gave service names more room in Settings and showed service names instead of codes on CDM devices. (#357)
- Switched to a dark theme with lime highlights and removed the light theme and Appearance setting. (#375)

- Fewer things ask for attention. The Settings sections no longer carry a "New" badge, the version no longer counts new options, and Activity hides a history filter with nothing under it, keeping All and the one you picked.
- Less stands between you and the content. On a phone, the Series filters sit in one row that scrolls sideways under the search, and each choice above them takes one line. The Schedule puts Reload beside the sync line and Week/Month beside its filter. In Activity, the five shortcuts sit in two columns, so the history starts higher on every screen.
- **Success has its own green, apart from the teal accent.** Healthy status dots, "Downloaded" notifications, valid cookie pills, a working CDM and finished job steps no longer share the teal that marks what is selected or being downloaded. (#280)
- Buttons, dropdowns, search boxes and filters share two heights everywhere (36px in toolbars and forms, 30px in rows and cards), dropdowns look the same in Safari, plain buttons have a visible edge, cards and rows that need attention are framed in their colour instead of a bar on the left, Settings uses the whole width, Interface and Region cards sit side by side with a Language dropdown, the Services table reads Service, Sign-in methods, Sign-in, Cookies, Used by, Actions with each cookie file on one line and Add only when there is none, notifications are two-line rows, and the job bar at the bottom of Activity is readable in the light look.
- The page takes the Molt look: warm neutrals with one teal for the main action, shared shadows and spacing, one badge style whose colour says what it means, and a light theme; Settings › Interface › Appearance picks System, Light or Dark for this browser.
- Services are named, not coded (RMC BFM Play, not RMCBFM), a series is "Downloading" or "Not downloading" everywhere, every sign-in says "Sign in", two-click confirmations name what they delete and stay until you leave the button, and counts such as "1 episode" and "2 episodes" are whole texts a translation can phrase its own way.
- Press feedback on buttons, tabs and pills, hover colours only where a pointer can hover, a plain wizard (the normal Next button, a solid panel, no overshoot), tick, chevron and arrow icons drawn as icons instead of text glyphs, language names without flags, and reduced motion keeps short opacity cross-fades.
- The Schedule is one view with a Week board (seven day columns of episode cards, with Previous, Today and Next) and the Month grid, replacing the separate List and Calendar; an episode's details, command and actions open from its name in a popover, or a dialog on a phone, and rows no longer run across the whole screen.
- A series' episode list now starts higher on the screen: a single-season series drops its season strip and catch-up box (its counts are in the title and select rows) and the refresh button moves next to Select, Settings cards lose their icon tiles and most intro sentences, the "new options" strip and a few helper lines that repeated a label are gone, the series list no longer prints its own count, and a fourth or fifth filter button stays on the same row on a phone.
- Settings › Services now shows every service's sign-in, cookie files and series on one page (it replaces the Cookies page), the setup's last screen says how many services are confirmed, failure messages say where to fix them, and Clear cache asks first and names the sign-ins it also clears.
- The series page now works without a mouse: it is a proper dialog that keeps the page behind it out of reach and gives focus back when closed, a managed poster's focus no longer looks like its resting ring, a failing Sonarr or Unshackle says so in words, hover-only details (failure marks, badges, subtitles) open on focus too, errors stay until dismissed, long titles and subtitle lists wrap instead of being cut, and the Region pickers, header and button groups name their roles and state to screen readers.
- Text now follows the browser's text-size setting, the page uses your system font with no request to Google Fonts, headings step down in size (the season heading is smaller than the series title), and corners use three shared sizes.
- Error text, placeholders, the Settings group labels and field edges now meet contrast, availability on a service shows in the accent colour instead of the green that means done, "New" labels no longer look like success, and the system's Increase Contrast setting is followed.
- The translation files match the page again: 13 texts it no longer shows were removed from every language, and the sign-in texts added since are listed for translating.
- Settings now starts, observes, answers, cancels, retries, and restores service sign-in sessions, with transient approval details and fixed redacted lifecycle and fallback states.
- Device approval links and codes are now delivered only through a transient, job-owned API and cleared on every terminal path instead of being retained in download history, logs, notifications, or diagnostics.
- The bundled Unshackle image now builds from the reviewed authentication-contract commit and both container images publish their exact source revision.
- Settings now keeps and shows each backend's last confirmed authenticated download or classified sign-in failure without reading private session files or contacting the provider.
- Authentication errors distinguished a service's rejected login or playback token from Unshackle's internal API key and preserved the provider's reason and error reference.
- Availability searches found and displayed seasons on other services even when all aired episodes were already on disk.
- Refreshing a series' episode availability also searched other services for missing seasons and showed the suggestions immediately.
- A series' page now always shows which episodes are on its service, with when that was checked, instead of only for 12 hours after "What's on <service>?". Every series' listing is refreshed in the background once a week.
- The weekly check also asks the service for one episode of each season, and the season's title shows the best quality there, for example "ABC iview: up to 1080p AVC SDR, AAC 2.0".
- The weekly check now looks for a season missing from a series' service on every other installed service that can search, and the Episodes tab offers it: "Season 3 is on STAN (8 episodes)" with a button that sets that season's page and service. Nothing changes until you accept it.
- A season listed as a separate show can now be on another service: a URL on another installed service's site under "Seasons listed as separate shows" (for example `S02 https://www.sbs.com.au/ondemand/tv-series/…` for a series on ABC iview) makes that season download from that service. Its episodes, the Schedule, the CDM checks, cookies and Upgrades all use it.
- Suggest services now also lists ended series without a service, after the airing ones, so their back catalogue can be set up the same way.
- Synced the fork with upstream 1.5.0 while retaining its provider-readiness and terminal-disconnect regression coverage.
- Amazon and Apple Channels (a brand sold inside Prime Video or Apple TV) are never shown: the schedule shows the brand's own logo, or its name when TMDB has none, and the series' suggestions offer only the brand's own service, found by its title or with a "Find it on" button, even when Amazon or Apple itself is not installed. A brand's own row is preferred over its Channel in JustWatch order.
- Mapped JustWatch's `10play.com.au` links to TEN and normalised them to `10.com.au` show URLs so titles like Fire Country suggest 10 Play, matching JustWatch AU.
- Suggest scrape follows TMDB/JustWatch sections (Stream / Free / Ads only). Anchor titles mark Channel packaging and Amazon/Apple purchases, which are never offered. Stale suggest cache without `kind` is refreshed.
- Removed a duplicated test file, an unused constant and several repeated helpers (reading a file with `mkvmerge`, the retried download's numbering and Replace, the HH:MM check, the page's local-date helper), with no change in behaviour.
- The API document now says what `GET /api/v1/downloads` returns: the queued downloads first, then every other one, running ones included, newest first.
- **The wording is clearer and consistent across the app.** The Schedule's "Refresh" is "Reload calendar" and its
  helper line is gone, the logo is named "Unshacklarr, schedule" and goes to the Schedule, Settings › Downloads asks
  you to "Wait for the audio, in days", the series selection says "Change" throughout, "Kept" names that outcome
  everywhere in Activity, the "Diagnostic" button is "Save diagnostic", durations say "2 min 24 s" and "1 h 05 min",
  a paused job and the country pickers no longer use emoji, the series page says a failure once (with its fix) and
  hides the empty "Missing, available on …" choice, a phone's Back is named for the page it returns to, and the
  audio-upgrade explainer is easier to read. The translation catalogues are back in step with the page. (#280)

### Fixed

- Prevented repeat submissions in Catch up and let users retry if the request failed or a refreshed list still showed the episode as missing. (#353)

- Prevented repeat Catch up downloads after switching views, kept keyboard focus on failed requests, and showed Fix sign-in even while other episodes were still queued.
- Kept selected library names and sort labels from getting cut off in the Series filters.
- Kept Sort with the Series filters when a longer label needed more room.
- Revealed running download shortcuts again when returning from their details, and kept the scroll cue visible in older browsers when more shortcuts were off-screen.
- Fixed Activity's shifting layout and kept keyboard focus and the selected view in place as downloads updated.
- Translated the episode subtitle button's screen-reader label and showed a text status instead of empty file cells for episodes without files.
- Fixed expanded episode subtitles pushing status icons off-screen, clipping keyboard focus rings, and closing the whole drawer on Escape. (#352)
- **The background glow no longer repeats in bands down a short page, such as a list that is still loading.**
- **The unshackle serve log now shows after viewing a download, and empty Activity no longer shows the old download's bar.** (#365)
- **Switching Sonarr connections no longer lets an in-flight sync lookup put the old library back in the cache.** (#368)
- **The Remote CDMs heading has room on phones.** The add button wraps below the heading and description on narrow screens. (#369)
- **Clearing series file name, season map, join parts, or episode name now clears the unsaved save bar.** Normalizing
  empty and default series fields (including `sonarr_order` when no numbering overrides remain) during comparison means
  undoing an edit no longer leaves the save bar stuck open. (#335)
- **Keyboard focus stays in place across the Quality editor, series notification chips, and Inbox filters, and CDM
  device chips show the standard focus ring.** Editing a step, moving a step or ladder, removing a step, or picking a
  default ladder chip no longer drops focus to the page. (#332)
- **Touch targets stay at least 44 px on tablets and phones.** Desktop 36 px and 30 px control heights now apply only
  to fine pointers above 700 px, while coarse-pointer touch screens (including iPads above 700 px) keep 44 px minimum
  hit targets across navigation, filters, buttons, drawers, dock controls, and collapsible summaries. (#333)
- **Per-service Clear cache now asks for confirmation first.** Clicking Clear cache in Settings › Per service asks to
  confirm before clearing the service's logins, tokens, and sessions. (#334)
- **A tool in Activity no longer shows the last job's bar.** Opening Waiting, Catch up, Upgrades, Languages or Stats
  after a download left that download's bar at the bottom of the pane; it is hidden now. (#363)
- **On phones, the last items in an Activity job scroll clear of the dock even when the save bar is visible.** (#363)
- **Web requests no longer stall behind slow TMDB, cache, or Sonarr scans.** Shared worker-pool sizing, deduplicated
  TMDB network lookups with serialized off-loop cache writes, mtime-cached read-only config/auth/JSON readers, direct
  live-card reads for `GET /api/runs?live=1`, cached `unwritable_files()` checks, a short-TTL `sonarr_series()` cache,
  and fresh-statistics filtering in `missing_of_managed()` keep fast API endpoints responsive under load.
  After you switch Sonarr connections, an older lookup from the web interface no longer saves the previous library.
  One failed TMDB lookup no longer blocks the rest. (#356)
- **An episode under its own number is no longer hidden for a small difference in its title.** Kath & Kim on Netflix
  lists S01E08 "The Wedding" and S03E01 "Cactus"; Sonarr calls them "Wedding" and "Cactus Hour", so both showed as
  not on the service and were not downloaded. Under the same number, a title that is the other's first or last
  words, or the same with other spaces or punctuation ("Sea Dog", "Seadog"), no longer says another episode; another
  title or another part number still does. (#344)
- **A title TMDB dates to another episode no longer blocks the episode Sonarr itself gives it to.** Binge's "Killer
  Connection / Bloody Birthday" is Sonarr's S15E08, but TMDB gives the same name to the episode aired on 2014-05-01,
  S15E06: the title fitted two episodes, so it was matched to neither. When a title is exactly one episode's own
  title (Sonarr's, or TVDB's in your language) and the others fit only through a title TMDB dates to them, that
  episode is now the one; a name only TMDB gives is found as before, and what was matched before stays as it was.
  (#321)
- **An episode whose title joins stories with "/" is found whichever way round they are written.** The First 48 on
  Binge lists "Night Shift / Mobbed" for Sonarr's S12E13 "Mobbed/Night Shift", and "Runaround / The Night Cap" for
  S04E07 "The Run Around/Night Cap": neither was matched, so downloads asked Binge for Sonarr's own number. A title
  of two or more stories that the whole title and the first story leave unmatched is now compared with each Sonarr
  title story by story, in any order and as close as a single title must be, or spelt with other spaces. What was
  matched before stays matched as it was. (#322)
- **An episode whose title joins two stories is found by the first.** 9Now's RBT names its Ep 166 "Pretty Little
  Penny/Passed in Not Passed Out": both halves were Sonarr titles (S21E06, and S19E07 from 2024), so the episode was
  matched to neither and every download asked 9Now for Sonarr's own number, which it doesn't have. The first story
  now names the episode: S21E06 is downloaded as 9Now's S05E166, and S19E07 is no longer taken for it. A title whose
  first story names none of them is still matched to none.
- **Every page tells the same story about a service, a download and a cookie file.** Settings, Services counts every
  service whose sign-in failed, timed out or was rejected as needing attention, names them, and shows the count beside
  Services in the Settings list. A cookie file's days left are counted the same way in Services and in the bell. A
  failed download no longer shows its last steps as done. The setup's Unshackle test and Settings count the same
  services (Unshackle's EXAMPLE left out).
- **A failing series says why where it opens.** Its Episodes tab starts with the last error and, for a sign-in, a
  button to that service in Settings, Services.
- **The bell keeps one line per cookie file.** "Expires in 5 days", then "4 days" the next day, replaces its line
  instead of adding one, and a click on it opens the service in Settings, Services.
- **The setup picks the country of your time zone.** It started on United States whatever the time zone; it now starts
  on the time zone's country (Australia for Australia/Melbourne) until you pick one.
- **Every button on a phone is big enough to tap.** Episode titles, the eye that hides an episode, the week arrows, Week and Month, the filters, the series' links and shortcuts and the other small controls in Schedule, Series and Activity now answer a finger 44 px wide and tall, mostly without changing how they look. The series page's Back button sits in the page's margin instead of against the screen's edge, and the header shows the whole name "Unshacklarr" (or only the logo on the narrowest phones) instead of "Uns…"; on a phone, the version and what's new are in Settings.
- **The page works better with a keyboard and a screen reader.** A "Skip to content" link comes first; the main tabs
  are links, so they open in a new tab; a series poster says its title before its service; the header's status dots
  say "running" or "unreachable" in their name; Local and Remote are a radio group the arrow keys move through; and
  Activity's headings no longer skip a level. Menus and dialogs cast a tighter shadow, and section titles are a step
  larger.
- **Clearer words where they mattered.** A Schedule card without a release time shows when the sync tries it, with
  its airing beside it, instead of the airing labelled "next sync"; a download refused for an expired sign-in offers
  Fix sign-in first, which opens that service in Settings › Services, and Retry after it; Activity says it is loading
  instead of "Nothing picked" while the history loads; the setup's API key help names the variable the key came
  from and what leaving it empty does; and the Services table's columns say what they hold, with a neutral Cancel.
- **Services go by their names.** Apple TV+, Prime Video, Netflix, SBS On Demand, 7plus and the rest are named as
  people know them on every page, where most showed their web address (tv.apple.com) and only Paramount+ its name.
- **The Services page shows where each sign-in stands at a glance.** Its state is a pill: green when signed in, red
  when a sign-in is needed, whose button turns primary. A cookies-only service (Apple TV+) has no Sign in button,
  which only ever tested its cookie file: Check, in the Cookies column, does that. Every button in a row sits on one line.
- **Four more visual slips are gone.** The demo's tour card follows the light or dark theme, where its heading and
  subtitle were near-invisible in light mode; "Sign-in and cookies", "Open Sonarr" and "CDM devices" sit level with the
  buttons beside them; the Local and Remote tiles line up their titles; and on a phone, Activity's history filters and
  its Clear… are 36 px tall, easy to tap. (#280)
- **The Services page says where each sign-in stands once.** "Ready · pairing, cookies" repeated the sign-in methods
  and read like a pairing in progress: a service nothing has checked yet now reads "Not checked yet", and one
  Unshackle reports as not signed in reads "Not signed in". A service already signed in or confirmed offers
  "Sign in again" instead of "Sign in", and "Reauthenticate" is "Sign in again" too.
- **On a phone, the Activity bar and the selection bar no longer hide behind the save bar.** With unsaved Settings
  changes, the save bar sat in the same spot as a running download's bar, and the Series selection bar overlapped it
  once it wrapped to two rows. Both now stand on the save bar, as tall as it is. (#298)
- **The header's Sonarr and Unshackle lights show at once after a reload.** They used to stay grey until the series and, in Settings, a fresh check of Unshackle had loaded, a few seconds or more; they now show the last background check straight away and the details follow.
- **Tabbing to a control no longer leaves it hidden behind a bar.** The page, and a series' slide-out, now stop the focused control short of the header, the tab bar, the save bar, the select bar, the download bar at the bottom of a job and the series' settings shortcuts, instead of leaving it under them. The last row of Settings also clears the save bar at the end of the page. (#280)
- **Focus is easier to see, and the small visual slips are gone.** A text field, the "Other" number pill, the Activity icon buttons and the filter bars now show a clear 2px ring when you reach them; "Open Sonarr", "Sign-in and cookies" and "CDM devices" are drawn in the button colour instead of the browser's link blue; the new remote CDM fields no longer make iOS zoom the page; choice chips have a visible edge; pressed controls scale to 96%; dialogs and menus no longer scroll the page behind them at their ends; a series with no poster, or one that fails to load, shows its initials on the wall; a failed load spans the whole wall, and the loading boxes can be seen and are announced as "Loading series…"; and the country list in setup is as wide as its field. (#280)
- **Escape, focus and page titles now follow where you are.** Escape in a series with unsaved changes opens the "unsaved
  changes" question and leaves it open (it was cancelled by the same key press). Closing a series opened from a Schedule
  card returns to that card even after the Schedule redrew. The browser tab's title names the page, the series or the
  Settings section (and the setup step), in your language. The unshackle.yaml editor says "Esc, then Tab, leaves the
  editor", and "Find it on" a service says whether its results are open and how many it found. (#280)
- **Activity and the first-run setup no longer leave you stranded.** On a phone, a running job's bar has Open series
  next to Pause, Options and Stop, and a finished job keeps its Delete; a download waiting for your OTP code or answer
  says "Waiting for your answer" in a chip, with no running pulse or progress bar; a step of the setup scrolls its card
  to the top and puts the keyboard on its heading; the Sonarr and Unshackle API key say "Found in the environment" in
  their help, where the placeholder was cut off; and switching language in the setup asks first, since it clears the
  password and keys. (#280)
- **Nothing is cut off or piled on top of anything else on a narrow screen.** At 320 px (or 400% zoom), a run's buttons
  wrap to a second line instead of losing "Delete", a running card's speed and time left sit on a row under the episode
  (and a finished card's line carries its whole text as a tooltip), the series filter takes a second row instead of
  spilling "Downloading" over "Not downloading", the late-episodes banner puts its sentence under its count and Show,
  a long service name stays inside its poster, a wrong setup code's message wraps inside the card instead of widening the
  page, "Notifications" no longer runs under Clear, the logo no longer overlaps the version (with new options, only
  their count shows there on the narrowest phones, and the chip's name still says the version), and on a short screen a
  series' head and shortcut bar scroll away with the page instead of pinning, so the settings under them can be reached;
  choosing a shortcut no longer jumps the page back. (#280)
- **Errors are easier to see, and say what is wrong where it is wrong.** The messages in the folder browser, the remote CDM form, a job's options and the change-several-series dialog were grey like the text around them; they now take the error colour and are read out when they appear. A failed lookup (the release group, the library check) is shown as an error with a Try again button. A wrong field in the setup, the quality settings, the cookie and notification dialogs, the download window and the password form is now marked invalid for screen readers and linked to its message, and the setup marks which fields are needed and which are optional. The password strength and match are read out as you type. A refused setup or sign-in now shows the server's reason, not "Unshacklarr answered HTTP 403. Try again." ahead of it, and "Change the password" stays pressable and says on the field what is missing instead of staying dimmed without a reason. (#280)
- **Deleting now asks first.** Clearing the notifications, deleting a job or a run, deleting the partial downloads and restoring a backup used to act on one click. Each now asks, naming what goes and that it cannot be brought back: the notifications' Clear turns into the question (Escape or a click elsewhere takes it back), and the others ask in a window that keeps Cancel as the default, naming the backup's file when restoring. Their buttons are red like the other deletes, and a screen reader now hears the question when a button turns into one. (#280)
- **The keyboard no longer loses its place when a list redraws or a view changes.** Activity's live buttons, the Select mode of the series wall, the quality, broadcast and calendar buttons of a series, Notifications' Sends, the CDM devices and Schedule's month days keep their focus when they are redrawn, instead of Tab starting again at the top of the page. A phone's Settings section and Activity download open on their heading and Back returns to the item it came from, the Setup steps focus their first visible field (or heading), Escape on the language menu returns to its button, a series opened from Schedule's popover returns to its card on Escape, and the picked day of the month says it is pressed. (#280)
- **Controls are named by what they act on, and say their state.** An option's value (and its on box) is named by its flag, and the Upgrades search by what it finds. Each Test, Remove and Download of an address or a saved backup names its own, the app picker no longer reads its badge letters, and a series' suggested services are a group named by the series. The running dot, the picked Activity row and the output toggle (open or closed) are announced, the columns move up and down, not left and right, and a series hidden from the Schedule is named from its visible "In schedule". The selection count is read out, and the Select button keeps one name while it says it is pressed. The language list is a plain button and list, not a menu without its arrow keys, and its button is named in your language. (#280)
- **The device menus and the setup pop-up work from the keyboard.** In Settings, CDM, the ⋯ menus (Test, Reprovision,
  Delete), the Change picker and a service's device menu, and in Activity the ⓘ that shows how a download runs, now
  take focus when they open, keep Tab and the arrow keys inside, and give focus back to their button on Escape or
  once a choice is made. Their buttons say whether the menu is open. A device's row in the CDM list is now a real
  button that unfolds its details, with the ⋯ beside it instead of inside it. (#280)
- **States no longer rest on a colour alone.** The header says "Update available" and "Checking…" in words (on a phone an update gets the same row as "Unreachable", and a check shows a ring); each download step says Done, Running, Failed, Stopped, Kept or Waiting to a screen reader, the current one is marked, and a failed or stopped one carries a mark; the weekly Stats bars come with a table of their numbers; the chosen quality ladder is marked like the other chips, with "Edit ladders" outside the group; the active country in the setup has an accent bar; and the Missing and Monitored pills have a visible edge and a tick when on. (#280)
- **A list that goes on now shows it, and a cut-off name can be read in full.** The setup's country list shows part of the next row, the Activity stats table shades the edge that still hides columns, and the hidden-series list, the option picker's help text, the notification log and the device map wrap their text instead of cutting it off with an ellipsis. (#280)
- **Settings is readable between phone and desktop widths.** A cookie file's name was squeezed to one letter per line in a window narrower than 1440 pixels, which the previous UI review round's equal-width buttons caused, and now keeps its room. The services table becomes stacked rows below 1180 pixels, so "Used by" and "Show series" no longer hide past an edge. A ladder's steps stack below 1120 pixels, so Codec and Range show their choice and the page no longer scrolls sideways. On a phone, Unshackle's Cancel and Copy buttons and the Notifications cards and quiet-hours fields no longer run past the right edge. (#280)
- **Quieter text is no longer too faint to read.** Other series' cards in Schedule, days outside the month, the counts on filters (the bell, Series, Activity), Series in Select mode that are not picked, an Unshackle feature that is not supported, a one-off download's file name and a hidden count in a job were faded with opacity, which left their text under the 4.5:1 contrast it needs. They now take the muted text colour instead, and a job count you hide keeps its strike-through. (#280)
- **The header stays on one row on a tablet.** Between 701 and 1240 px wide the nav, the Unshackle and Sonarr status buttons and "Run sync now" did not fit and wrapped to a second row, leaving the bell and the sync button alone on the left. Here the sync button is an icon, the status buttons are dots and the update pill is an icon, as on a phone; under 1040 px the logo loses its name and under 940 px the nav its icons. A service that is down or has an update still says so in words, on a row of its own with the bell and the sync button kept on the first. The sync button keeps "Last sync …" and "Sync running…" for a screen reader, and shows a ring while it runs with "Reduce motion" on. (#280)
- With "Reduce motion" on, the shimmer on a download's current step in Activity now stays still, like every other animation, instead of looping for as long as the download runs. (#280)
- **An empty list now says what it was asked for and how to get back.** Series, Activity, Settings › Upgrades and
  Settings › CDM name the search or filter that matched nothing and offer "Clear filters", "Clear search" or "Show all";
  the empty Series list announces itself to a screen reader, Activity's empty history says downloads start from a
  series or with Run sync now, and a series Sonarr lists no episode for has a Refresh button. (#280)
- A restart while a retry ran beside its job (another Replace choice) no longer loses the job's queued episodes: each is kept with its own settings and picked up again. The queue saved by the version before still loads; once this version has saved it, an older version can no longer read it.
- An API download request with `"audio"` now asks the service for that language first, with the series' own audio languages after it, and accepts the file in it (an episode that has a file is replaced only by one in that language), instead of downloading the series' usual language again and counting it as an audio upgrade. (#187)
- With `--generate-dv` on, an episode with HDR10+ and no Dolby Vision now fits a quality ladder's Hybrid step, in downloads and in Upgrades, instead of failing with "None of the quality ladder's steps" or taking a lower step.
- Activity › Languages now judges a season listed on another service by that service's audio languages, as its downloads do, instead of listing its correct files as missing the main service's language.
- A sign-in refused on a series' fallback service no longer downloads the wrong episode: the other profiles are tried on that same service with its own episode number, instead of asking the series' own service for the fallback's number, and the failure names the service that refused.
- A saved file that could not be read for a moment (a network share dropping out) is no longer written over with only the newest item: the bell, the sent log, the messages held for the quiet hours, the warnings already given and the sign-in records now skip that write and keep what they had.
- A full or read-only disk during the quiet hours no longer stops the rest of a job: a message that cannot be kept for later is sent at once instead.
- An episode folder left without a video (an import that went through after Unshacklarr stopped waiting, or a crash) no longer turns "add the audio track" into a whole new download that replaces the library's file: the folder is cleared and the track is added.
- Adding an audio track can no longer leave a cut-off file that Import puts over the library's good one: the merge is written as `.mkv.part` and renamed only once it is whole, and what a restart midway leaves (the `.part` and the audio downloaded for it, which can be an `.mkv`) is removed when Unshacklarr starts.
- A stuck `mkvmerge` or `mkvpropedit` (on a stalled network share, for example) no longer holds every later sync at "A sync is already running" until a restart: reading a file now gives up after 2 minutes and a join or an audio merge after an hour, that episode fails with the reason, and no cut-off file is left behind for import.
- The episode list and a running download's track list now draw on iPhones before iOS 17.4, where "What's on…?" results and the live track list used to stop the page drawing.
- "What's on…?" for a series that is in no main Sonarr now asks the Sonarr you are viewing (for example 4K), not always the first, so its badges match that library's episodes.
- Reloading on Settings, Automation or Interface no longer throws, so the installed app keeps pull-to-reload on those pages.
- Download and Sync no longer say "Save your changes first" for 1.6 seconds after a Save: they only wait when something is really unsaved.
- The account password you type to download or restore a backup is now cleared from the form afterwards.
- Backup and diagnostic downloads no longer fail on Safari: the file is kept for 30 seconds after the click instead of being released at once.
- Tapping a push notification now opens the bell even when the app's window cannot be navigated: it opens a new window on it.
- Activity no longer grows in memory while its tab stays open: what the page keeps per download (time left, bar widths, posters, unfolded tracks) is dropped once the download leaves the list.
- Typing in the series search no longer redraws every poster on each key: the wall updates once you pause for 150 ms, so large libraries stay smooth.
- "Change and download…" no longer shows "Pick a service and its URL first" on a series that only has season pages.
- Typing in the device search (Settings, CDM) no longer jumps the cursor to the end or breaks Japanese and Chinese input: the box stays, and only the list under it is redrawn.
- A release day from 8 to 13 days before airing can now be picked (the list skipped them), instead of a suggested one saving as "the day it airs".
- Settings, Per service no longer stays blank when one service's options cannot be loaded (Unshackle down, or a service it no longer has): the list shows, and the stale entry can be removed.
- The README now creates `unshackle-data/temp` with the other folders, so a fresh Docker install does not get it owned by root, which Unshackle could not write to.
- The README's Docker and `uv`/`pipx` install steps now fetch this repository's files and package, not upstream's.
- The sign-in texts added since 1.5.0 (approvals, reauthenticate, session available or expired, signed in with…, not checked yet…) are now translated into German, Spanish, French, Italian, Japanese, Brazilian Portuguese, Russian and Chinese instead of showing in English. A line such as "Sign-in failed · authentication rejected" is now translated whole. (#166)
- After you clear Unshackle's cache, the Services page no longer shows those sign-ins as confirmed: the services read "Not checked yet" until a check or a download confirms them again. Clearing one service's cache does this for that service only. (#171)
- Counts now follow each language's plural forms: in Russian, 2 devices read "2 устройства" and 21 read "21 устройство"; French and Brazilian Portuguese count 0 as singular. (#175)
- Run sync now (`POST /api/sync` and `/api/v1/sync`) now starts while a single download, a retry or an upgrade is going, and only a sync of every missing episode counts as "a sync running" on Settings and in `/api/v1/status`.
- A retry through the API (`"retry": true` on `POST /api/v1/downloads`) now repeats its last attempt's numbering and Replace anyway, as the page's Retry does, instead of asking for the series' numbering and keeping the file.
- Changing the password, the API key or the page's language, logging out other devices, restoring a backup and saving where backups are sent now wait for a sync's settings write, so a revoked key or an old password can no longer come back when both happen at once.
- The README's reverse proxy section now says to pass on the original Host, without which Activity's live output is refused as cross-origin behind plain Nginx.
- A notification address over https, such as an ntfy topic at `https://ntfy.sh/familyalerts`, now reaches the page with everything after its host hidden; only Discord's and Slack's webhook paths still show.
- Activity's catch-up with a superscript digit as its number of days (`/api/missing?days=²`) now answers that days is a number instead of a server error.
- Someone signed in through the reverse proxy can now use the Test buttons for Sonarr and Unshackle, instead of being told to enter the setup code first.
- A setup code or session cookie with an accented character is now refused as wrong instead of failing with a server error that kept the page from loading.
- **Test Unshackle** with an edited local command no longer points the downloads and syncs running at the same moment at the test command, and no longer refuses to run while a download is going.
- Restarting Unshackle from the page now makes Unshacklarr look again at where it keeps its cookies, devices and config, so a changed `directories:` no longer leaves sign-ins looking expired until Unshacklarr restarts.
- A local Unshackle whose launcher starts with `#!/usr/bin/env python3` now starts, instead of failing with "illegal option".
- A busy or failing Unshackle no longer lets a retry start a second download into the folder the first may still be writing: a job counts as gone only when Unshackle says there is no such job.
- A busy Unshackle that answers "try again in 0 seconds" no longer makes Unshacklarr cancel the running download; it waits a second and asks again.
- An Unshackle that answers nothing but "busy" for 2 hours no longer holds its download slot forever: the download is given up with a message saying the server stayed busy, and the next one in line starts. Any other answer starts the 2 hours over, so an hourly limit is still waited through.
- A local Unshackle that will not start is now said once for a minute, instead of every page load and sync waiting 90 seconds to start it again.
- The example Docker Compose file now builds Unshackle from this repository's Dockerfile at the reviewed commit and pulls this repository's image, instead of upstream's, which ignored the commit pin; that commit now includes official Unshackle's latest development work.
- The `--remote` servers' options now show in the first 10 minutes after the machine starts, instead of being missing until then.
- Renaming or removing a Sonarr in Settings no longer makes every later Save fail with "no Sonarr named …": a rename keeps each series' own settings for it (such as switched off), and a removal drops them.
- Failed downloads now show the provider's final reason instead of a Python traceback in Activity and notifications.
- Error messages now identify the failing service or server, retain safe upstream details, redact credentials, and give a useful next action.
- Hayu suggestions now replace an episode-only link with the show's page found by title, so later seasons are included instead of only that episode's season.
- Change and download's preview no longer shows a season listed as a separate show as missing or as the wrong episode: it numbers the season as its own page does and matches it against that page's titles, as the download already did.
- A series' suggestions now name each title when one service links several (Netflix's Kath & Kim and its 20th Anniversary Specials): the one with the series' own title comes first, and Suggest services no longer offers the others for the series.
- The page no longer says Sonarr is unreachable while Sonarr is busy importing a batch of downloads: the series list and the schedule now wait up to 2 minutes, as Unshacklarr's other Sonarr reads already did, instead of 30 seconds. The release check, which runs every 30 seconds, still gives up after 30. A request that takes too long now says how long it waited, not always 30 seconds.
- A series' suggestions no longer fill in an audio-described or Auslan edition of the show (Binge's `audio-description-…`, SBS's and ABC iview's `…-auslan`): the show itself is found by its title where the service can search, else that service gets a "Find it on" button.
- ABC iview and 7plus suggestions now link the show's page (`iview.abc.net.au/show/<name>`, `7plus.com.au/<name>` without its `?episode-id=`) instead of one episode, so Unshackle sees every episode; before, a series like Dustfall showed only episode 1 as on iview. Series already set to an episode link need their Series URL replaced once.
- The schedule now shows a series' network catch-up service (for example 9Now for a Nine Network series) beside TMDB's services, as the series page already suggests it, with that service's own logo. Australia's free-to-air networks are recognised under all the names Sonarr and TMDB use: ABC TV, ABC iview and ABC Kids; Nine, 9 and 9Now; Network 10, 10 and 10 Play; Seven, Seven Network, 7plus and 7mate; SBS and SBS On Demand.
- A Channel's own Amazon or Apple title is no longer offered as Prime Video when JustWatch also lists it under that name (Stick's free first episode, an Apple TV Amazon Channel title, listed as "Amazon Prime Video"); in the schedule, Prime Video or Apple TV listed only in TMDB's free section beside a Channel they host is that Channel's free episode and is not shown, while an ad-supported tier such as Prime Video with Ads still shows.
- A brand listed only as an Amazon or Apple Channel (for example Binge Amazon Channel or Paramount+ Amazon Channel) is now routed to that brand's own installed service: its series page is searched there by title and suggested as home, and no Channel chip is shown. If the title search finds nothing, the series page offers to find it on that service. Sonarr country tags such as "(AU)" no longer stop a title search from matching.
- Series suggestions now include TMDB's own homepage link when it is an installed service, so titles like Paramedics (AU) suggest 9Now instead of only the BINGE Amazon Channel, which Amazon refuses without that add-on. Week-old suggestion caches refresh.
- Prime Video and Apple TV+ are now treated like any other service in the schedule and the series' suggestions, instead of being hidden as a "storefront" whenever another service carries the show, so Amazon and Apple Originals such as The Rings of Power show Prime Video again. Purchases from Amazon Video and the Apple TV Store are never shown.
- Mapped JustWatch AU's `9now.app.link` Branch redirects and `9now.com.au` links to NINE, and Nine Network catch-up, so titles like Travel Guides suggest 9Now instead of "no supported service"; week-old suggest caches refresh when those mappings change.
- A series' own network catch-up service (for example SEVEN or TEN) is now suggested beside the TMDB links, not only when TMDB lists none.
- Preserved the selected Unshackle backend, Sonarr instance, provider programme, and season page across retries and upgrades.
- Change and download no longer shows "Seasons listed as separate shows", which changed the series' saved settings instead of only the episodes picked, then made Download ask to save first.
- A series with a fallback service no longer fails with `UnboundLocalError` when its own service has the episode in none of the accepted audio languages and the fallback service downloads it: the episode is now imported, and no login-fallback profile is tried because of an earlier episode's error.
- A notification address with every level unticked no longer receives every message, and it still shows three unticked boxes after a reload.
- Choosing a CDM device for one service no longer drops the other services' devices when `cdm:` in unshackle.yaml is written on one line (`cdm: {default: l3, AMZN: l3}`): Unshacklarr now refuses and says to change it by hand, leaving the file as it was.
- A syntax error in `unshackle.yaml` no longer stops its editor from opening it or saving over it, and no longer silences the hourly alerts: the disk-full alerts still go, and cookies and CDM devices count as not checked.
- The automatic backup and update-check loops no longer stop for good when a pass fails with an unexpected error: the error is logged and the next pass runs after the usual wait.
- Off-site backups to S3-style storage whose address has a path (`https://nas.example/s3`) or a default port (`:443`) are no longer refused as a wrong access key: the signature now covers the path and host actually sent.
- An interrupted download (cut off by a restart) can now be deleted from Activity, and Clear all removes it, instead of answering "No such download in the history" and staying.
- Activity's weekly stats now start each week on Monday at midnight in the app's time zone, not in UTC, and the week labels no longer show the day before west of UTC.
- Saving a remote CDM or allowing Unshackle's proxies no longer deletes the blank lines and `#` comments that follow that section in `unshackle.yaml`.
- A change made while a Save is still running is no longer marked as saved: the save bar stays up until it is saved, and the off-site backup's "Save and test" only marks its own fields as saved.
- Two jobs that use two Unshackle servers no longer wait on each other forever when "downloads at once" is set: a job waiting for a slot on one server now gives back its idle slot on the other.
- Downloads are no longer refused with "No CDM" for up to 10 minutes after a device is picked, changed or removed in Settings, CDM, or after Unshackle is restarted from the page: the next download reads Unshackle's config afresh.
- A failed "add audio track" no longer leaves a half-written file in the download folder, so Import under Waiting in downloads can no longer replace the library's file with it.
- Restoring a backup whose number settings are not numbers or are outside the range a Save allows (for example a Sync every of 0 hours, or a History to keep of "lots") is now refused with a message naming the setting, before anything is written; before, it was written and the app could not start until `config.yaml` was fixed by hand.
- Picking several hundred episodes at once no longer puts every id in one Sonarr request: they are fetched 200 at a time, so a large catch-up is no longer refused for its URL's length.
- A job paused during its last episode now ends when that episode does, instead of staying "running" until Resume was pressed (Sync now answered that one was already running). A paused job with episodes left still waits for Resume.
- Adding an audio track to an episode saved as an `.mp4` now writes a `.mkv` file, so the name matches the Matroska format and Sonarr replaces the old `.mp4`.
- "Release time set" is now sent once, when the time is written, instead of again for every later episode of the same run.
- A series' start date no longer moves forward each time you Save from the same open page: the page now keeps the date the server set when the series was added, so episodes aired between two Saves are no longer skipped by the automatic sync.
- A series set to send no notifications no longer sends a "Not imported" message when an unexpected error stops an episode from finishing.
- Activity no longer asks the server for the whole history again and again while a download starts or ends: one reload at a time, and its answer is drawn, so the Running list updates even when the history is slow to load.
- A single HTTP 500 answer to a download's status check no longer cancels the download: it counts as a miss, like a 502 to 504, and the download is only given up after 12 misses in a row.
- The diagnostic file no longer keeps the host of a proxy, Sonarr, an Unshackle server or the off-site backup, in the attempt, its command line, its cause or its log.
- An automatic sync interval that does not divide 24 hours (5 or 23, set through the API or the config file) now ends each day with a sync at midnight instead of running unevenly, and the next sync shown on the page matches it.
- Opening several series at once no longer loses their cached where-to-watch suggestions: each one stays cached instead of the last to finish replacing the others, so they are not asked from TMDB again.
- A title linked from amazon.de is now reduced to its Amazon title id like the other Amazon sites, so it no longer shows as a second suggestion next to the same title from amazon.com, amazon.fr or Prime Video.
- A track at a standard height, such as 1998x1080 or 4096x2160, is now classed by that height in a quality ladder instead of a class that matches no step.
- A title ending in a spelled-out number ("Part Two") is no longer matched to the same title with another number ("Part 1"); one to twenty, in English.
- The library folder guess in Settings now works for a Sonarr on Windows: the Sonarr folder it proposes keeps the drive letter and backslashes (`D:\TV`), so it matches the paths that Sonarr reports.
- A local Unshackle whose Python is missing or does not answer no longer stops every health update: Unshackle now shows as down with the cause, and the lights for Sonarr and the other servers still refresh.
- Unshacklarr no longer follows a redirect from unshackle serve: it says which address the redirect points to so you can use that one, and the address in the "did not answer like unshackle serve" message hides any user name and password.
- The one-off preview no longer shows an episode 00 (S01E00) when an episode offset leads before episode 1, as the sync skips it; and Settings > Automation now shows "Next sync at" in the app's time zone setting, as the sync runs, instead of the browser's. The broadcast calendar's dates still follow the browser's time zone.
- The save bar no longer appears when nothing changed: typing in a series' episode offset, season offset or episode table and clearing it again leaves the series as it was, and hiding or showing a series (saved at once) no longer makes Download refuse with "Save your changes first".
- A login cookie with a non-ASCII digit in it (such as `²`) is now refused instead of causing a server error, and two logins in the same second no longer end together: logging one out leaves the other signed in. Logins made before this update stay valid until they expire.
- A series' broadcast calendar day can now be clicked back to its usual number of episodes when that is 4 or more an evening, so a changed day no longer needs the whole schedule reset.
- The schedule's calendar now shows an episode a service puts out days before it airs on its release day when that day is the last one on screen, instead of leaving it out until the next month is opened.
- Opening Stats and then Waiting in downloads (or the other way round) while the first answer is slow no longer draws that late answer under the other title; and the Output terminal now says when it cannot connect (behind a reverse proxy that blocks WebSockets) instead of staying an empty box.
- Added a test that saves the settings as the page received them and checks that nothing changes and no secret is sent back, including proxy credentials in service defaults and in a fallback.
- A Save no longer writes back an older password or a revoked API key changed while it ran, and no longer erases a release time the sync learnt after the page was loaded; the sync's own writes and a Save no longer interleave.
- A redirect from unshackle serve to another route (a login page) is no longer offered as the address to type in Settings, Unshackle.
- An S3 backup bucket or folder holding a `.` or `..` folder is refused with a message instead of being uploaded under another key than the one in Settings.
- With a "downloads at once" limit, a job whose retry runs beside it (picked with another Replace choice) no longer gives up a server's slot while one of its downloads still runs there.
- Where clocks go back two hours (Antarctica/Troll), the automatic sync no longer runs every second for the half hour after the change.
- Closing a series whose numbering was cleared and typed back no longer asks to save, and hiding a series from the Schedule while a Save runs is no longer undone by that Save.
- After a Save, a release time the sync learnt meanwhile shows in the series panel, and moving a series to another service or page no longer keeps the release time learnt for the old one.
- When adding an audio track fails, its clean-up never deletes through a download folder that was swapped for a link to another place.
- Downloading a diagnostic no longer takes minutes when the log holds a long key or license, and no longer shows the start of a secret written just before an e-mail address.
- A download serve no longer knows (a 404) is retried at once even when its message starts with `HTTP 500:`, instead of after 12 more status checks.
- Logging out on two devices at the same moment no longer leaves one of the two sessions usable.
- An error message, a log line or a shown download command no longer shows the end of a password (an address's or a proxy's) that holds an `@`.
- Downloading a diagnostic no longer slows down on a log line holding a long run of web addresses.
- Waiting in downloads no longer lists, imports or deletes through an episode folder that is a link to another place.
- A job and a retry of one of its episodes running side by side no longer free each other's download slot when one ends, so a server never goes over its "downloads at once" limit; an episode queued under a paused job shows as paused.
- A download waiting to be tried again keeps its server's slot, so with a "downloads at once" limit no other job starts there while a download serve never confirmed stopped may still run.
- A link named like an episode's download folder no longer blocks that episode's downloads: the link is removed (never what it points to) and the episode downloads.
- Activity no longer draws older download progress over newer progress when a history reload ends.
- Two syncs of one job (a retry beside it) both waiting for a full server no longer leave the second waiting forever once the first gets in.
- A diagnostic no longer shows a URL's query secrets when both its password and its query hold an `@`.
- **A service's failed login is no longer called a refused API key.** Serve's own reason is shown instead, so you
  don't look for a fault in a key that works. (#25, by mj23au)
- **Service options now reach a remote server.** `-B`, `--atmos` and the others were left out of a download through it.
- **A broadcast's time is the release time when none is set.** An episode is tried the minute it airs, not at the next sync.
- **The gap to the next episode and the release day count from the broadcast's time too.** They were dropped on save without a release time.
- **Video files a service refuses are no longer blamed on its cookies.** The message points to the download's proxy instead.
- **A page open in another tab no longer undoes your changes.** A save only sends what it changed; the same thing
  changed in two places is refused with a message to reload. Settings edited by hand apply without a restart.
- **A Sonarr taken out of Settings no longer blocks saving a series** that had options for it.
- **The real error on Activity.** A failure that only said "exit code 1" now shows the last error it logged.
- **An episode not out yet is no longer a failure.** Unshackle's "No titles found" is read as *not on the service yet*: tried again, and the release-time tries go on.
- **A service's `--profile` stays the service's.** Netflix's `--profile PRK_DO` was taken as an account profile and
  shown before the service in the command.
- **Activity no longer freezes with a large job.** The episodes that don't change are no longer redrawn every second.
- **More episodes found by their title.** "TBC" counts as no title, like "TBA"; TVDB's "PAGE 14 Donjon" is Netflix's
  "Donjon"; a title only translated ("Dungeon", "Donjon") is no longer marked *Other title*.
- **Quality ladders with `--remote`.** A remote download reads the episode's tracks too, so its ladder and languages
  are checked before it starts instead of failing.
- **No false alarm before a premiere.** A new series or season with nothing out yet is no longer told to check its URL.
- **The output's scrollbar can be dragged.** The text covered it when the output was wider than its box.
- **Seasons on the service on a phone.** The field gets the full keyboard, so `=` and `,` can be typed.
- **`--remote` with the official Unshackle.** A download through a remote server and its options now go through
  Unshackle's own API (after 6.0.0); with 6.0.0, Per service says the options are not known and to write them as is.
- **A series downloaded through `--remote` is also listed and searched there.** Its episodes no longer start the
  service here, where it may not be set up (NF stopped with "Service NF exited").
- **Retries with Unshackle after 6.0.0.** A network or service hitch it now answers with 424, and a server about to
  restart, are tried again as before.
- **No more false cookie warnings.** Crave's load balancer cookies (a week) and Apple's `utsdc` (an hour) no longer
  count as the date the login ends.
- **Renaming a Sonarr no longer breaks its pages until Save.** Catch up, Upgrades, the library check and folder
  browser, and a series' episodes keep using the name the server knows, and switch to the new one once it is saved.
- **A second Save from an older tab no longer undoes another tab's change.** After a Save, the page takes the
  settings and series as the server merged them, keeping what you changed while it ran, so its next Save no longer
  sends its older copy back. When another tab renamed a Sonarr, the page asks you to reload it instead.
- **A backup a Save would refuse is no longer restored.** One with an Unshackle server or a Sonarr without a name,
  or a series value out of range, is refused with the reason before anything is written; before, it was written and
  the app could not start again until `config.yaml` was fixed by hand.
- **A tab still running the old page after an update is told to reload.** Its Save no longer replaces every
  setting and series with its old copy, removing those set up on another device: it is refused with a message to
  reload the page.
- **Two Saves at nearly the same moment both stay.** A Save now merges its changes with the settings as they are
  when it writes, so another tab's Save that landed while it waited on Unshackle is no longer written over.
- **A WebDAV backup sent to a login page is a failed backup.** A redirect (a forward-auth proxy's login) is no
  longer followed and recorded as sent: it fails with the host it leads to, and only a stored file counts as sent.
- **One odd cookie file no longer empties the Cookies list.** A cookie dated `inf` is skipped like any other bad
  date, and a file Unshacklarr cannot read shows as Unreadable while the others still show.
- **Translated notifications on Windows.** With a language set, notifications no longer fail to load their
  translations, which are now read as UTF-8 whatever the system's encoding.
- **A queued episode taken out stays out.** Removed or stopped just as its turn came, it no longer downloaded
  while the history said cancelled.
- **Downloads at once is kept when a job pauses.** Pausing a job, or its episode ending while it was paused, no
  longer let one more download run than the limit.
- **A run whose end could not be saved ends anyway.** On a full disk it no longer showed as running, with Delete
  refused, until a restart.
- **Saving Settings no longer sends a download to the wrong server.** One starting during the save could find
  no Unshackle or Sonarr of its own and use the main ones.
- **Mux progress with two downloads muxing at once.** Each shows its own again, instead of none, or another
  client's.
- **A job's output shows its last episode.** It no longer closed just before that episode's log began.
- **Delete and Import in Waiting in downloads leave a running download alone.** On a folder a new download has
  just started into, they now say it is downloading instead of deleting or importing it.
- **Stop stops.** Pressed between two tries, during a fallback try, or on a job's second or later episode before
  its download began, the episode was downloaded and imported anyway; it now ends as stopped.

**🆕 Sonarr 5, on this branch until it is out of beta**
- **Languages.** Your files without your audio languages, read from Sonarr 5's own tracks: watch them for the
  preferred audio, or download them again. In Activity.
- **Titles in your language.** A series whose titles Sonarr gives in English offers, on its page, to have them in
  yours: its episodes then match the service's better.
- **Episode order.** A series Sonarr numbers in another order (DVD, Netflix…) says so in its Numbering; when that
  order changes, its new episodes wait until you confirm the numbering.
- Activity's progress bar no longer steps back for a moment when the history is reloaded: a download the live feed has just drawn keeps its newer progress. (#133)
- Switching quickly between a series' libraries (main and 4K) no longer leaves the other library's episodes on screen: the slower answer is dropped, so Download no longer sends one library's episodes to the other. (#193)
- A download of a series in one library (main or 4K) no longer greys out and marks the same episodes as downloading in the series' other library. (#245)
- Catch up and Upgrades no longer show a slower, older answer under the filter or Sonarr you picked last, and their Download and Replace buttons send the Sonarr their list was fetched for, not the one the picker has moved to. (#194)
- Opening another series while "Test this series" is still asking no longer shows the first series' result in it (or lets Apply write its season map there), and the Test button is no longer stuck waiting for the first series' answer. (#217)
- The library-path check in Settings no longer shows an old result ("Not found here" for `/mnt/t` after you typed `/mnt/tv`): only the newest check's answer is drawn. (#246)
- Hiding the browser tab with the serve log open and coming back no longer replaces the log with the output of a run opened earlier. (#242)
- The Schedule no longer shows seven empty "Nothing that day." columns when a late logo download finishes while a new week or month is still loading: the spinner stays until the shows arrive. (#244)
- Closing and quickly reopening "Suggest services" no longer leaves the first run's workers asking TMDB alongside the new ones or overwriting the progress count. (#254)
- Episodes, Catch up and Upgrades no longer say Sonarr "did not answer" when it takes between 30 seconds and 2 minutes: they wait as long as the Schedule and the server do, and the series search on a service waits 70 seconds instead of 30. (#222)
- An episode that aired just after midnight on 1 January is no longer refused as a year too early: the programme's year is now Sonarr's own air date, or the UTC time converted to your time zone.
- One series with an unreadable start date no longer stops the automatic sync of every series after it, nor makes the missing list fail: Save now refuses a start date that is not a date, and one already stored that way counts as no start date.
- A second Sonarr now gets the same automatic sync as the main one: a series' own broadcast schedule and its early releases (a negative release day) reach it too, so a weekly series Sonarr dates all on its premiere is no longer missed there.
- A failure whose message merely contains "log in" inside another word ("catalog index", "assign in time") is no longer taken for a sign-in problem, so it no longer tries every fallback profile or says the cookies may have expired.
- Hiding an approval code no longer hides ordinary words with it: "enter your code ABCD-1234" hides only the code, not every "your" in the history and in error messages, so a download error such as "connection refused" still matches its retry rule.
- A sign-in question in the bell is now crossed off when the service asks a new one ("wrong code, try again"), and when the download fails or is stopped while it was asking, instead of staying open.
- Quiet hours typed by hand without quotes (`from: 23:00`, which the settings file reads as a number) no longer break every notification and the check that sends the held summary; a time that cannot be read now means no quiet hours.
- The summary of messages held during the quiet hours is no longer lost when every address fails as they end: it is kept and tried again the next minute, and messages that arrived while it was going out are kept too.

### Removed

- **Unshackle's log in Activity**, and the proxy and CDM a download went through. With it, the output's
  Essentials/Debug switch: Settings' debug mode alone says how much the output shows.
- **The `/api/remote/services` route of an older Unshackle fork.** The `--remote` servers are read from Unshackle's
  own `/api/config` and `/api/services?remote=` instead.

## [1.5.0] - 2026-10-17

Several Sonarr at once, the audio of your language added to the files you have, Upgrades that run by themselves,
episodes matched far more reliably, and ready for Unshackle 6. Much of it came from mj23au's issues and code: thank you.

### Added

**📚 More than one Sonarr**
- **Other Sonarr instances.** A second Sonarr, a 4K one say, with its own library, quality ladder and After the
  download; its series are listed too, and its copy comes at the release time as well. In Settings › Sonarr. (#10)
- **Sonarr name.** Each Sonarr named; a badge on each series says which libraries have it, and Series filters by them. (#10)
- **Libraries per series.** In Source, each Sonarr switched on or off for the series, with what it misses. (#10)
- **Episodes, Catch up and Upgrades per Sonarr.** Pick the library, download for it. (#10)

**⬇️ Downloads**
- **Add audio track.** When your language's audio comes out, only that track is downloaded and added to your file, as
  its default audio, with its forced subtitles. A file not from the series' service is asked about in the bell first.
  In Settings › Download options.
- **Library folders picked, not typed.** Sonarr's root folders offered, both sides browsable, a real file to confirm them.
- **Fallback service.** A second service for a series, used when the main one doesn't have the episode.
- **Hybrid (DV + HDR10) in quality ladders.** A step can ask for both layers in one file.
- **Muxing progress.** Activity shows how far Unshackle's mux is and the time left, and folds the tracks once they
  are in. With Docker, mount its work folder (see the example compose).
- **Downloads at once.** How many episodes each Unshackle server downloads together; 1 suits a small NAS. (#10)
- **Download window.** Automatic downloads only between two times. In Settings › Automation.
- **Auto release times.** A series learns when its episodes come out. In Settings › Automation.

**🔎 Finding the right episode**
- **Separate programmes.** For strands like BBC Documentaries: each episode is found by its title, no series URL
  needed; one the service doesn't have says *Not on* it. (#17)
- **Seasons listed as separate shows.** A season the service lists as a show of its own downloads from that show's
  page, which Episodes offers when it finds one. (#21)

**⬆️ Upgrades**
- **Upgrades you choose.** Which series are checked, how long an answer is kept, how far back; one card per series,
  nothing ticked at first, each checkable on its own, replacements shown live. (#10, #18)
- **Check automatically.** Every 7 days, asking only about answers grown old, spread over several checks. In
  Settings › Upgrades. (#23)
- **Check new series.** A series set up with episodes already on disk is checked within the hour. (#23)
- **Other release groups.** A file from another group can be replaced by the same quality too. (#10)

**📡 Sonarr**
- **Season and series finales**, in the Schedule and in the notification.
- **Season names** in Episodes, where Sonarr has them.
- **Room in the library checked too.** Nothing downloads while the series' folder is short of space; you are told once.

**✨ Everywhere**
- **What's new.** Click the version in the header.
- **No spoilers.** Episode titles stay blurred until you click them. In Settings › Interface.
- **Notifications per series.** All, failures only, or none; the bell keeps everything.
- **Remote backup.** Your backups, encrypted, on WebDAV or S3. In Settings › Account.
- **A diagnostic for issues.** One click in Activity, without passwords, keys, addresses or folders.
- **A health check** at `/health`, for Docker and Uptime Kuma.
- **Sign-in codes.** When a service waits for you to sign in, you are told, with the link and the code when
  Unshacklarr runs Unshackle, and with Unshackle 6 its approval messages.
- **Dynamic range in Episodes.** DV, HDR10 or HDR10+ beside each file's codec.

**🆕 Unshackle 6**
- **Its proxies allowed in one click** to Unshacklarr's key, in Settings › Unshackle; on their own when Unshacklarr
  runs Unshackle. Unshackle 5.4 and later still work as before.
- **Its new download options**, each saying it needs 6.0, `--cdm` with the CDM devices you have.
- **A limit of requests** set on the key is waited for, not taken for a lost download.

New options are off until you turn them on, except Upgrades' automatic check (0 days turns it off).

### Changed

- **Faster and lighter.** One call per series for its episodes and files, title matching about three times quicker,
  fewer calls to Sonarr for series with their own schedule, and no repeated waits while a server is down.
- **One import at a time per Sonarr**, so big files don't reach it together. (#10)
- **A busy Unshackle server is waited for** 1, 3 then 10 minutes before a download fails. (#10)
- **Import needed**, with an Import button, instead of a failure when Sonarr didn't import. (#10)
- **Clearer selection in Series.** A check on each poster, the others dimmed.
- **Clearer choices in a series' settings.** Each choice shown once, the one it inherits marked default.
- **One schedule per series.** A series with its own broadcast schedule shows only that one.
- **More from the API.** A download for another Sonarr, as a retry or a replacement, through its own proxy, in the
  codec and height you name. (#10)
- **Updating Unshacklarr alone** (`--no-deps`, in the README and the example compose) leaves Unshackle and its
  downloads running.

### Fixed

**🔎 Finding the right episode**
- **Titles that differ a little are matched:** a typo, a two-part title, a short title at the end of a long one,
  specials the service numbers in its own seasons. (#12, #20)
- **Only the very title moves an episode** to another number: never a close one, a remake from other years, or
  another part. (#12, #17, #20)
- **No wrong season map offered** for a season the service doesn't have yet, or on a page without dates. (#20)
- **A season the numbering gives to another one** is left to it (Koh-Lanta).
- **A service in another language** is no longer taken for yours because a few words are alike.
- **Episode titles in your language again**, now read through Sonarr; a new season not translated yet is no longer
  mistaken for other episodes.
- **A separate programme** is found inside its series when the search only finds the series. (#17)
- **A series' link is found by its title** when the service only links an episode (HBO Max). (#12)
- **No "may be an episode" warning** for a series that is simply new. (#12)

**⬇️ Downloads and imports**
- **Missing subtitles no longer stop a download.** (#16)
- **No second download** of an episode Unshackle may still be fetching, retries included. (#10)
- **Imports are asked again** when Sonarr confirms late, refuses while busy, or says it imported without moving
  anything. (#10)
- **Retry works for another Sonarr's copy**, and Replace anyway holds through a retry or a stop. (#10)
- **An empty episode folder** no longer blocks the episode. (#10)
- **Pausing a waiting job** no longer blocks the downloads after it.
- **A series' own `--range`** (HYBRID) is kept when its quality ladder picks a track.

**⬆️ Upgrades**
- **Only real upgrades.** Episodes offers what Upgrades found, Hybrid DV files aren't listed, and the right episode
  is asked when the service numbers it apart. (#10, #12, #18)
- **A replaced episode leaves the list** for good. (#23)

**✨ Everywhere**
- **A series without a poster** shows its initials. (#22)
- **Activity no longer freezes** when you come back to it after a while in another tab.
- **The service check shows in Episodes** as soon as a suggested link is picked, without a reload.
- **An unreachable Sonarr is told once**, not at every sync.
- **A run that just ended** no longer shows "Interrupted" until a reload. (#17)
- **The Output panel** keeps its newest line in view. (#10)
- **H.266 (VVC) files** are named as such.

## [1.4.0] - 2026-10-07

### Added

- **Automatic backups.** Your settings saved every few days, and restored on a new install. In Settings › Account. (#15)
- **Upgrades.** Replace files your quality ladder says could be better. In Activity › Upgrades. (#11)
- **Catch up.** Download the aired episodes your series still miss, all at once. In Activity › Catch up. (#12)
- **The right episode, checked first.** No download when the service's title says it's another episode. (#12)
- **A language order per quality ladder**, for audio and subtitle tracks (en-AU, then en). (#11)
- **Services for series without a link**, found from their channel (Channel 4, BBC…). (#12)
- **Every Unshackle server watched.** You are told when one goes down and when it is back. (#13)

### Fixed

- **Sonarr links work away from home**, through Tailscale or a VPN. (#14)
- **TMDB links lead to the series**, not to one episode, for iPlayer, Channel 4, ITV and others. (#12)
- **Backups keep the quality ladders.**
- **Widescreen tracks fit their step**: a 1920x800 video counts as 1080p. (#11)
- **An Unshackle server that is down** no longer sends its services to another server. (#13)
- **Another server's downloads folder** is found when left empty. (#13)
- **A link to one episode** is spotted when you test a series. (#12)
- **Activity on a phone** no longer scrolls sideways.

### Changed

- **A series' settings, reordered** into cards, with a bar to jump between them.
- **Clearer texts** throughout, in every language.
- **A new version shows within the hour**, instead of half a day.
- **Cookies and CDM on a remote Unshackle** are said to be managed there, not shown as an error. (#13)

## [1.3.2] - 2026-10-07

### Fixed

- **The resolution stays in the file name** after renaming. (#9, reported by mj23au)

## [1.3.1] - 2026-10-06

### Fixed

- **A service that failed to load** stops its download at once, saying why. (#5, by Artic0din)
- **Closing Activity during a download** no longer logs an error. (#4, by Artic0din)

## [1.3.0] - 2026-10-06

### Added

- **Accepted languages.** An episode without the audio or subtitles you need waits and is tried again.
- **The French dub once it comes.** An episode is downloaded again when your preferred language arrives.
- **Profiles to fall back on.** A refused login is tried again with another account.
- **Ready for the release.** A series is checked 3 hours before its episode, while there is time to fix it.
- **Room kept free.** Nothing is downloaded while the disk runs short, and you are told.
- **Quality ladders.** Choose the quality, codec and range to try, in order. In Settings › Quality. (#8)
- **Download only.** Episodes wait in Activity for you to import them. (#6)
- **More than one Unshackle**, one behind a VPN for example. In Settings › Unshackle. (#7)
- **Find a series on its service** by name, instead of copying its URL.
- **Change several series at once.**
- **Back up and restore the settings** from Account.
- **Sign in through a reverse proxy** (Authelia, Authentik).

### Fixed

- **What's on the service?** shows as soon as a series gets its link.

### Changed

- **A lighter sync**, and a faster Schedule.

## [1.2.3] - 2026-10-05

### Fixed

- **Suggested services** match the ones your Unshackle has (MAX or HMAX, ATV or ATVP). (by Artic0din)
- **Suggest services works again** with TMDB. (by Artic0din)

## [1.2.2] - 2026-10-05

### Fixed

- **One card for repeated failures**, and one notification.
- **A release burst stops** when trying again would fail the same way.

## [1.2.1] - 2026-10-03

### Fixed

- **An anime's new episode is found** even when TMDB only has its Japanese title.

## [1.2.0] - 2026-10-03

### Added

- **Found by its absolute number**, for a service that numbers a series from its first episode.

## [1.1.1] - 2026-10-03

### Fixed

- **A new release shows in the header** again: GitHub refused the check.

## [1.1.0] - 2026-10-03

### Added

- **Found by its title** when the service numbers an episode differently.
- **A new release shows in the header**, its notes one click away.

### Fixed

- **A retry asks for the same episode** as the first try.

## [1.0.0] - 2026-09-30

### Added

- **Jobs.** Episodes picked together form one job in Activity, with a summary at the end.
- **Control over a job**: pause, stop, cancel or retry, one episode or all.
- **Faster batches.** The next download starts while the previous one is imported.
- **Clearer output**, with Unshackle's own log live.
- **Downloads in sight** in Activity and on the series page, never started twice.
- **Episodes in parts** wait for every part before being imported.
- **A service's questions** (a code by e-mail, a PIN) answered from Activity.
- **What's on the service.** See what the service has for each episode, and download what's missing.
- **Matching by number and title**, in Sonarr's, TMDB's or TVDB's words.
- **Change the numbering for one download**, with a live preview.
- **Links** to the series on TVDB, TMDB, its service and Sonarr.
- **A pasted link picks its service.**
- **A series' own broadcast schedule**, when Sonarr's dates are wrong.
- **The CDM page, reworked**: what needs fixing first, devices one per line.
- **CDM choices**: no CDM, remote CDMs, live tests.
- **A series without a CDM** says so before downloading.
- **Its service's options** shown in a series' settings.
- **Edit `unshackle.yaml`** from Settings, with the last ten versions kept.
- **Unshackle 5.5 options**, such as `--remote` and `--server`.
- **An API for other programs**: Home Assistant, Shortcuts or a script.
- **Discord notifications** as cards, with the poster.
- **Notifications** under the bell, grouped by job.
- **Nine languages**, notifications included.
- **A first run in steps**, each checked before the next.
- **Settings, redesigned**, each section opening on where things stand.
- **Notifications by address**: Discord, Telegram, ntfy, Pushover, e-mail or Gotify.
- **Quiet hours**: messages wait, then arrive as one summary.
- **More warnings**: cookies about to expire, a CDM failing its test.
- **Log out other devices** from Account.
- **Tooltips** on every icon button.
- **Large screens** use their whole width.
- **A Docker image on GitHub** at `ghcr.io/ownzzzz/unshacklarr`.

### Changed

- **Release times** count from the day the episode airs.
- **The app opens on the Schedule**, and Settings comes last.
- **The Terminal is now Activity.**
- **Save confirms on its button**, and filters show their counts.
- **A new password is typed twice**, with its strength shown.
- **Files are always written whole**, never half-way.
- **The time zone is searched** like the country.
- **A service without any CDM** is refused before downloading.

### Fixed

- **Activity no longer blinks** during downloads.
- **The top of a series' page** is no longer blurred on iPhone.
- **Two subtitles in one language** are both counted.
- **Notifications can be copied.**
- **One episode is no longer taken for another** when a service numbers its own way.
- **The audio check** recognises every language again.
- **A wrong current password** no longer logs you out.
- **No episode downloaded twice.**
- **No half episode imported.**
- **Downloads that never end** now fail with a reason, and the job goes on.
- **Testing Unshackle** no longer restarts it during downloads.
- **Numbering** typed as S1E6=S2E5 is understood.
- **Series with their own schedule** still get their earlier missing episodes.
- **A proxy's password** no longer shows in commands.
- **The download preview** shows again.
- **A faster, lighter page.**
- **Every language complete.**
- **The Docker image** uses the exact tested versions.
- **Activity keeps updating** after the CDM page was opened.
- **Leaving a series' page** without changes no longer asks to save.

### Security

- **Logging in** resists bursts of wrong passwords, and logging out ends the session.
- **Secrets** reach the browser masked.
- **Nothing from a CDN**, and the page can't be framed by another site.
- **Symbolic links** in shared folders are never followed.
- **A service's message** can no longer freeze the server.
- **The API** takes 100 episodes at a time at most.
- **Every tool in the images** is pinned and checked.
- **oauthlib 4.0.0**, for two advisories.

[1.5.0]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.5.0
[1.4.0]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.4.0
[1.3.2]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.3.2
[1.3.1]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.3.1
[1.3.0]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.3.0
[1.2.3]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.2.3
[1.2.2]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.2.2
[1.2.1]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.2.1
[1.2.0]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.2.0
[1.1.1]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.1.1
[1.1.0]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.1.0
[1.0.0]: https://github.com/OwnzZzZ/Unshacklarr/releases/tag/v1.0.0
