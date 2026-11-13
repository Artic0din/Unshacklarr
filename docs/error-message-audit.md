# Error message audit

Issue #151 audited every backend module and browser script that can produce or display an error.
The verdicts below describe the shared sink for every message in each file; individual validation messages were kept when they already identify the input, reason, and corrective action.

## Backend

| File | Verdict | Reason |
| --- | --- | --- |
| `backend.py` | Restructured | Unshackle failures now retain the service, HTTP status, reason, and reference; empty and HTML responses become a named HTTP error. |
| `sync.py` | Restructured | Attempt history and notification results redact credentials before persistence or display; unexpected notification failures point to the log instead of showing an internal exception. |
| `web.py` | Restructured | Exception-derived HTTP and JSON messages pass through the shared redactor while existing Sonarr, TMDB, service, CDM, file, and input attribution remains intact. |
| `push.py` | Restructured | Push-service status and safe detail remain visible; HTML and unexpected internal exceptions are replaced with an actionable message while full safe detail stays in the log. |
| `files.py` | Restructured | The shared public-message redactor now covers URL credentials, sensitive query values, authorization headers, API-key headers, and cookies. |
| `cdm.py` | Kept | Each error names the device, configuration rule, or file and says what must change. |
| `cookies.py` | Kept | Each error names the cookie file or service/profile input and gives the corrective action. |
| `offsite.py` | Kept | WebDAV, S3, encryption, and configuration failures already identify the remote system and required correction. |
| `options.py` | Kept | Parser failures already identify the option, rejected value, and expected type. |

## Browser

| File | Verdict | Reason |
| --- | --- | --- |
| `core.js` | Restructured | The shared request path now identifies Unshacklarr, retains HTTP status and reason, suppresses HTML, and tells the person to retry. |
| `setup.js` | Restructured | Startup HTTP failures now use the shared response formatter before the early request result is displayed after translations load. |
| `activity.js` | Restructured | Diagnostic-download failures now use the shared response formatter. |
| `attempts.js` | Kept | Server failures use `api()`; local messages name the affected attempt and action. |
| `bulk.js` | Kept | It has no independent error sink; save failures use the shared save/request path. |
| `cookies-cdm.js` | Kept | Server failures use `api()` and each local state names the cookie or CDM operation. |
| `inbox.js` | Kept | Server failures use `api()` and action failures name the affected notification action. |
| `navigation.js` | Kept | The only blocking message identifies unsaved settings and the required save/discard action. |
| `news.js` | Kept | Loading failures display the shared request reason with a retry action. |
| `quality.js` | Kept | Connection and lookup failures use server detail from `api()` and remain attached to the relevant setting. |
| `schedule.js` | Kept | Failures use `api()` and identify the schedule, calendar, series, or download action. |
| `series.js` | Kept | Failures use `api()` and identify the affected series, episode list, availability lookup, or download. |
| `settings-options.js` | Kept | Failures use `api()` and remain attached to the relevant backup, notification, or account setting. |
| `settings-services.js` | Kept | Failures use `api()` and remain attached to the relevant Unshackle, service, or notification action. |
| `yaml-editor.js` | Kept | Failures use `api()` and remain attached to the editor operation. |
| `index.html` | Kept | Static error labels identify their setting or empty state; runtime detail comes from the audited scripts. |

## Translation and regression coverage

`tools/i18n/extract.py` remains the source of truth for user-visible English text and now avoids catastrophic backtracking on long code literals.
The regenerated English catalog has no stale keys.
Every locale contains the changed error templates with the same placeholders.
Regression tests cover provider/server attribution, HTTP detail preservation, empty and HTML responses, credential redaction, persisted attempt failures, push failures, locale synchronization, and extractor performance.
