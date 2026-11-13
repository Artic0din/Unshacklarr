# Error message audit

Issue #151 audited every backend module and browser script that can produce or display an error.
The inventory unit is a function or shared display sink, not a file.
Sites with the same verdict and reason share a row only when every function is named in that row.

## Backend

| Site | Verdict | Reason |
| --- | --- | --- |
| `files.py:no_credentials` | Restructured | The public-message boundary masks URL credentials, sensitive query values, authorization and API-key headers, and cookies. |
| `backend.py:response_error` | Restructured | Unshackle responses retain a safe reason and support reference; empty or HTML responses become a named HTTP failure. |
| `backend.py:Unshackle.call` | Restructured | Failures identify Unshackle or the streaming service, keep HTTP status and safe detail, and distinguish provider login rejection from the internal API key. |
| `sync.py:send_to` | Restructured | Notification transport failures keep safe delivery detail; unknown internals point to the log instead of reaching the person. |
| `sync.py:inbox_add` | Restructured | Every persisted inbox title and body passes through the credential redactor. |
| `sync.py:notify_series`, `notify`, `send_held`, `deliver` | Restructured | Every immediate, quiet-hours, local-push, and external notification path receives redacted content before storage or delivery. |
| `sync.py:trace`, `EpisodeRun.say` | Restructured | Every text line written to Activity output is redacted before display and persistence. |
| `sync.py:EpisodeRun.finish` | Restructured | Attempt-card cause and detail are redacted before history persistence. |
| `sync.py:tell_failure`, `run_episodes`, `finishing_loop` | Restructured | Expected and unexpected download/import exceptions converge on the audited output, history, and notification sinks. |
| `push.py:Push.send` | Restructured | Push-service status and safe detail remain visible; HTML and unexpected internals become an actionable message while safe detail stays in the log. |
| `web.py:service_options`, `series_search`, `suggest` | Restructured | Service discovery and search exceptions are redacted before their HTTP response. |
| `web.py:unshackle_health`, `server_health` | Restructured | Health-card errors are redacted before JSON serialization and notification reuse. |
| `web.py:state` | Restructured | The page-state response redacts an unavailable Unshackle server's exception before JSON serialization. |
| `web.py:cdm_details` | Restructured | CDM detail failures retain the actionable compatibility message or a redacted Unshackle reason. |
| `web.py:restart_unshackle` | Restructured | Restart failures keep safe server detail and identify Unshackle as the failing party. |
| `web.py:list_cookies`, `save_cookies`, `delete_cookies` | Restructured | Cookie-file errors are redacted while preserving the file or requested operation. |
| `web.py:cdm_test`, `cdm_reprovision`, `list_cdm`, `cdm_action` | Restructured | CDM endpoint failures are redacted while retaining the device operation and upstream reason. |
| `web.py:send_offsite` | Restructured | Backup errors are redacted before JSON persistence and notification delivery. |
| `web.py:unshackle_yaml`, `allow_proxies` | Restructured | Configuration errors are redacted while retaining the invalid file or proxy action. |
| `web.py:unshackle_maintenance`, `cancel_job`, `stop_run`, `stop_job`, `answer_run` | Restructured | Runtime-control failures are redacted while retaining the requested action and Unshackle reason. |
| `web.py:probe_series`, `probe` | Restructured | Availability-probe failures are redacted before page JSON and keep the affected series or season context. |
| `web.py:leftover_action`, `push_subscribe` | Restructured | Waiting-download and push-subscription errors are redacted while retaining the requested action. |
| `web.py:setup_restore`, `test_sonarr`, `test_unshackle`, `setup` | Restructured | Setup checks identify Sonarr or Unshackle, keep safe connection detail, and point back to the supplied settings. |
| `cdm.py:regular`, `describe`, `choose`, `remote_save`, `remote_delete`, `add`, `delete`, `allow_proxies` | Kept | Each validation error names the device, configuration rule, or file and says what must change. |
| `cookies.py:check_name`, `parse`, `from_json`, `normalise`, `path_for`, `save`, `delete` | Kept | Each validation error names the cookie file or service/profile input and gives the corrective action. |
| `offsite.py:decrypt`, `webdav_put`, `s3_put`, `send` | Kept | WebDAV, S3, encryption, and configuration errors identify the remote system and required correction without exposing stored credentials. |
| `options.py:convert`, `from_dl_config`, `to_params` | Kept | Parser failures identify the option, rejected value, and expected type. |

## Browser

| Site | Verdict | Reason |
| --- | --- | --- |
| `core.js:responseError` | Restructured | The shared formatter preserves safe response detail, suppresses HTML, and otherwise names Unshacklarr with HTTP status and retry action. |
| `core.js:api` | Restructured | Timeout and connection failures identify Unshacklarr and give the next action; every non-success response uses `responseError`. |
| `setup.js` startup state request | Restructured | The early request uses `responseError` before its result is displayed after translations load. |
| `activity.js:downloadDiagnostic` | Restructured | Diagnostic-download failures use `responseError` instead of exposing an empty or HTML body. |
| `attempts.js` request and action catches | Kept | Server failures use `api`; local messages name the affected attempt and action. |
| `bulk.js` save path | Kept | It has no independent error sink; failures use the shared save/request path. |
| `cookies-cdm.js` request and validation catches | Kept | Server failures use `api`; local states name the cookie or CDM operation. |
| `inbox.js` request and action catches | Kept | Server failures use `api`; action failures name the affected notification action. |
| `navigation.js` unsaved-settings blocker | Kept | The blocking message identifies unsaved settings and the required save/discard action. |
| `news.js` loading catch | Kept | Loading failures display the shared request reason with a retry action. |
| `quality.js` connection and lookup catches | Kept | Failures use `api` detail and remain attached to the relevant setting. |
| `schedule.js` request and action catches | Kept | Failures use `api` and identify the schedule, calendar, series, or download action. |
| `series.js` request and action catches | Kept | Failures use `api` and identify the affected series, episode list, availability lookup, or download. |
| `settings-options.js` save and test catches | Kept | Failures use `api` and remain attached to the relevant backup, notification, or account setting. |
| `settings-services.js` save and test catches | Kept | Failures use `api` and remain attached to the relevant Unshackle, service, or notification action. |
| `yaml-editor.js` load and save catches | Kept | Failures use `api` and remain attached to the editor operation. |
| `index.html` static error labels | Kept | Each label identifies its setting or empty state; runtime detail comes from the audited scripts. |

## Translation and regression coverage

`tools/i18n/extract.py` remains the source of truth for user-visible English text and now avoids catastrophic backtracking on long code literals.
The regenerated English catalog has no stale keys.
Every locale contains the changed error templates with the same placeholders.
Regression tests cover provider/server attribution, HTTP detail preservation, empty and HTML responses, credential redaction, persisted attempt failures, push failures, locale synchronization, and extractor performance.
