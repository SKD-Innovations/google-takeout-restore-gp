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

## 0.1.5 layout, recovery and removal

- Full local suite: **100 passed**. New coverage checks existing-account schema migration,
  recovery key secrecy/single use/replacement/throttling, disabled accounts, unchanged
  profile encryption keys, export authorization, preference reset scope, app roles,
  device-auth cancellation, native confirmation cancellation, active-job refusal,
  non-macOS password re-verification, cleanup I/O errors and symlink safety.
- Actual embedded HTML/service smoke: all eight screens checked for document overflow
  at 820, 960, 1180 and 1580px; a 1200-character unbroken log value and long event/path
  tested. Export CSV, replacement recovery-key export, forgot-password reset, fresh
  recovery-key issuance, multi-user isolation and admin-only cleanup exercised.
- Cleanup UI tests use a temporary root and mocked OS authorization/confirmation only.
  External test files and exported recovery files survive; all old app accounts and
  profile/runtime content disappear. No existing user account or source media was erased.
- Packaged macOS offline self-test checks the real native WebKit bridge and narrow-window
  log wrapping, disposable account creation, and bundled ExifTool metadata round-trip.
- PyInstaller includes the Swift LocalAuthentication helper as a signed Mach-O executable;
  strict recursive bundle verification and DMG Finder-layout verification run during packaging.
- Interactive Touch ID / macOS-password authorization and moving the actual installed
  application to Bin are **not exercised automatically**. Those require acceptance on a
  disposable macOS account. Native authentication/Trash boundaries are simulated in unit
  tests. Windows/Linux package execution and Developer ID/notarization remain unverified.
- The empty single-instance lock file is retained intentionally. OS-managed caches,
  explicit exports, system backups, Takeout source media and Google Photos remain outside
  app cleanup. Drag-to-Bin alone does not invoke cleanup; use Settings → Uninstall.

## 0.2.0 usage, incident reporting and release documentation

- Full local suite: **114 passed**. New tests cover consent/save cancellation before any
  mail handoff; redaction of paths, filenames, exception text and credentials; ZIP and
  app identity hashes; persisted user-isolated incidents; acknowledgement and duplicate
  suppression; broken-database reporting; startup reports without account-store access;
  invalid export destinations; correctly encoded mailto drafts; native macOS compose-only
  service arguments; profile schema migration; deterministic source fingerprints.
- UI smoke passed with actual embedded HTML and Service against disposable accounts at
  820, 960, 1180 and 1580px. It exercises the bundled usage guide, Send report/Not now,
  ZIP creation, a mocked native email handoff, unexpected-error prompting, CSV export,
  explicit Keep Chrome open instructions, recovery, role isolation and cleanup.
- Packaged Apple Silicon app's offline native self-test passed: WebKit bridge and narrow
  log layout, actual incident dialog, bundled usage guide, generated build fingerprint,
  installed launcher SHA-256, disposable account creation and bundled ExifTool round-trip.
- Strict recursive ad-hoc signature verification passed. Packaging verifies the DMG's
  mounted application signature and Finder layout. This preview has not been signed with
  the maintainer's Developer ID, submitted for notarization, or uploaded to the App Store.
- Email apps were **not opened during automated tests**, and no report was emailed.
  The NSSharingService arguments and URI fallback were tested with mocks. Maintainer
  acceptance should check a real default mail client, ZIP attachment and cancellation;
  discard the draft unless intentionally sending it.
- USAGE.md is bundled and exposed in Help. docs/APPLE-RELEASE.md distinguishes implemented
  Developer ID/DMG distribution from the unimplemented App Sandbox/browser changes needed
  for App Store review, with links to Apple's current primary documentation.
- Actual certificate signing, timestamping, notarization/stapling, Windows/Linux packages,
  Intel execution, oldest-OS compatibility and App Store acceptance remain unverified.

## Windows CI portability correction after 0.2.0 preview

The supplied windows-2022 log was for the earlier 100-test source revision. It reported
two failures: a recovery export test asserted Unix permission mode 0600 on Windows,
and the malformed ZIP-name test used a writer that normalized backslashes before
validation. Windows chmod exposes read/write status rather than POSIX permission bits.
The content/authentication tests now remain active on Windows while POSIX-only mode
assertions run on POSIX; the new support ZIP permission assertion follows the same rule.

ZIP fixtures now preserve their original unsafe names across platforms. The extractor
validates ZipInfo.orig_filename rather than the platform-normalized filename, rejecting
backslashes and NUL bytes before normalization can hide them. A regression simulates
Windows filename normalization on a non-Windows host, and a valid nested archive is
still verified to extract normally. No failing security test has been disabled.

Targeted checks passed (39 tests), the full local suite passed (117 tests), and Ruff
passed. A native Windows GitHub run
must use a newly committed/pushed revision; re-running an old workflow run still tests
that old commit. The Mac preview DMG built before this correction is unchanged; rebuild
release artifacts from the corrected source before signing/publication.


## 0.2.1 Unicode metadata and release packaging

PR #1 restores lossless Windows metadata input using UTF-8 ExifTool argument files
and private UTF-8 description files. Read-back validation remains strict. Regression
coverage includes Unicode paths/text, multi-line and long descriptions, cleanup on
failure, and simulated lossy Windows command-line encoding. Native Windows CI for
that fix passed 130 tests with one POSIX-only filename test skipped; local macOS
passed all 131 tests. PR #1's final source CI passed on Windows, Linux and macOS.

Release preparation centralizes macOS/Linux package versions in pyproject.toml and
updates the Windows installer, UI and usage guide to 0.2.1. Unsigned CI builds no
longer require signing secrets. Signing remains opt-in, tag-restricted and fail-closed.
Private-repository attestations require an explicit supported-plan opt-in; skipped
attestation is recorded rather than presented as verified provenance.

The final 0.2.1 local source suite passed **131 tests** with bundled ExifTool.
Ruff, JavaScript syntax, whitespace checks and actionlint passed. The real UI/service
smoke passed all screens at 820–1580px, recovery/export/reset, role isolation, usage,
incident prompts, ZIP/draft handoff and disposable-data cleanup. Screenshots were
regenerated from the 0.2.1 interface.


The first four-target 0.2.1 package run passed Windows, Apple Silicon macOS and Linux.
Its Intel macOS packaged self-test caught an OpenSSL symbol collision at startup.
The release stayed a draft. The Intel build now explicitly requests static OpenSSL
linkage for cryptography; its packaged self-test remains mandatory.
