# Changelog

Every change worth knowing, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/): until 1.0.0, a minor version may change how things work.

## [Unreleased]

### Security

- **aiohttp 3.14.4.** Eight advisories fixed, three of them high: the server no longer waits without end for a
  request's headers, can no longer be made to use too much memory, CPU or file descriptors, and parses requests more
  strictly. (#24)
- **certifi 2026.10.23.** The emSign root certificates, whose intermediate keys were compromised, are no longer
  trusted for Unshacklarr's own HTTPS connections (a critical advisory).

### Added

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

### Changed

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

### Fixed

- A release day from 8 to 13 days before airing can now be picked (the list skipped them), instead of a suggested one saving as "the day it airs".
- Settings, Per service no longer stays blank when one service's options cannot be loaded (Unshackle down, or a service it no longer has): the list shows, and the stale entry can be removed.
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

**🆕 Sonarr 5, on this branch until it is out of beta**
- **Languages.** Your files without your audio languages, read from Sonarr 5's own tracks: watch them for the
  preferred audio, or download them again. In Activity.
- **Titles in your language.** A series whose titles Sonarr gives in English offers, on its page, to have them in
  yours: its episodes then match the service's better.
- **Episode order.** A series Sonarr numbers in another order (DVD, Netflix…) says so in its Numbering; when that
  order changes, its new episodes wait until you confirm the numbering.
The episode list and a running download's track list now draw on iPhones before iOS 17.4, where "What's on…?" results and the live track list used to stop the page drawing.
"What's on…?" for a series that is in no main Sonarr now asks the Sonarr you are viewing (for example 4K), not always the first, so its badges match that library's episodes.
Reloading on Settings, Automation or Interface no longer throws, so the installed app keeps pull-to-reload on those pages.
Download and Sync no longer say "Save your changes first" for 1.6 seconds after a Save: they only wait when something is really unsaved.
The account password you type to download or restore a backup is now cleared from the form afterwards.
Backup and diagnostic downloads no longer fail on Safari: the file is kept for 30 seconds after the click instead of being released at once.
Tapping a push notification now opens the bell even when the app's window cannot be navigated: it opens a new window on it.
Activity no longer grows in memory while its tab stays open: what the page keeps per download (time left, bar widths, posters, unfolded tracks) is dropped once the download leaves the list.
Typing in the series search no longer redraws every poster on each key: the wall updates once you pause for 150 ms, so large libraries stay smooth.
"Change and download…" no longer shows "Pick a service and its URL first" on a series that only has season pages.

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
