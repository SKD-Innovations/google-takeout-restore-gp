# Validation record — 1 November 2026

Host: macOS 26.6.2, Apple Silicon; Python 3.12.7. This records local evidence, not a
claim of production certification or cross-platform acceptance.

| Check | Result |
|---|---|
| Automated backend/contract tests | 47 passed |
| Real metadata round trips | Bundled ExifTool 13.60; JPEG, PNG, TIFF; UTC dates, Unicode descriptions, negative altitude |
| Static checks | Ruff passes for application code; Python compilation and JavaScript syntax checks pass |
| UI smoke | Actual UI and service; account creation, all screens, settings, Advanced view, sign-out and account isolation pass |
| Native WebKit bridge | Hidden native window with disposable account store passes under the shipped CSP |
| Browser component | Playwright 1.64.1; revision 1248 archive hash, safe extraction and offline launch pass |
| Packaged macOS application | PyInstaller bundle built; offline native/account/bundled-metadata self-test passes |
| Local bundle integrity | `codesign --verify --deep --strict` passes with an ad-hoc signature |
| macOS distribution artifacts | ARM64 DMG and portable ZIP produced; disk-image checksum verification passes |
| Workflow configuration | CI/build YAML parses; third-party actions pinned to verified commit SHAs |

The macOS preview has **no Developer ID distribution signature or notarization**.
It is a local test artifact, not a publicly trusted signed release. The workflow
supports your future signing credentials; no credentials were accessed here.

Not performed: real Google login/upload, cloud-library reconciliation, Windows/Linux
execution, clean minimum-OS validation, million-file/terabyte stress testing, independent
security audit or accessibility certification. The cloud-only restoration features
listed as unavailable in README remain unavailable; tests do not substitute for them.


## Real-use sign-in finding

A user observed Google's “This browser or app may not be secure” rejection when
signing in through the automated browser. This invalidates any assumption that the
offline tests establish real Google login compatibility. The browser connection is
therefore blocked for affected accounts. A regression patch detects this state as
GPP-410, stops immediately, avoids saving a rejected session and halts further queue
processing. It does not bypass or resolve Google's sign-in decision.


## 0.1.1 CDP restoration

Restored the original launch-then-attach Chrome flow, with manual sign-in before
Playwright attachment and reuse of Chrome's default browser context. Offline testing
with installed Chrome passed CDP attachment, default-context reuse, persistent test
cookies across Chrome restarts, AES-GCM encrypted profile storage and cleanup of the
unlocked working directory. A real Google sign-in still requires user verification.


The 0.1.1 regression suite has 58 passing tests, including encrypted-profile integrity,
manual confirmation before CDP attachment, default-context reuse and handling an
abandoned Chrome window after a crash. The UI smoke test also verifies the Continue
control. Existing local queue/history schemas are unchanged; reconnect once in Setup
to create the dedicated encrypted Chrome profile.


## 0.1.2 backup quality dialog

Added automatic Original quality selection and verification, followed by Continue,
for Google's recognized backup-quality dialog. Local browser tests cover both radio
implementations, either initially selected choice, hidden/repeated prompts, unrelated
Continue buttons, missing/nonfunctional Original quality controls and an upload
sequence in which the quality dialog appears after file selection. No test contacts
Google or uploads real media. The supplied screenshot establishes the visible dialog
wording; its live DOM was not accessed.

The complete 0.1.2 suite passes 68 tests, including 10 real-browser quality-dialog
and upload-sequence tests.


## 0.1.3 logs and macOS packaging

The complete suite passes 73 tests. CSV export was exercised through the real UI
and service, including Simple view, full audit history, user isolation and spreadsheet
formula protection. Uploads cannot start with no eligible items; unresolved queues
record a Review required outcome with confirmed counts. Future failure audit entries
include redacted stage/cause types. Historical records are preserved.

The rebuilt native app passes its offline self-test and signature-integrity check.
The designed DMG contains saved Finder view settings, real draggable app/Applications
icons, retina artwork, and explicit bundle naming/category/version metadata.
Launch Services registration could not be confirmed in this environment (status -43);
actual Spotlight discovery after user installation remains a user-side validation step.
See MACOS-INSTALLATION.md for Apple references and supported troubleshooting.

The final 0.1.3 disk image was mounted read-only and checked for its Applications
shortcut, fixed icon coordinates, background settings and the packaged app's strict
signature integrity. The first layout build exposed a FinderInfo attribute caused by
extension hiding; that step was removed per Apple QA1940. The rebuilt mounted copy
passes verification, and the packaging script now enforces that check on every build.


## 0.1.4 completion-card wording

88 tests pass (76 backend/contract tests and 12 real-browser UI contract tests).
New fixtures cover the supplied “You backed up 1 item” wording, line wrapping,
non-breaking spaces, rejection of zero/multiple-item and stale confirmations, and
a two-item queue that commits each upload receipt before closing its completion
card and advancing. Unrelated Close buttons are not clicked. These are offline
fixtures; existing review records remain unchanged and need user reconciliation.
