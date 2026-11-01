# Security model

This is a local desktop preview, not a security-certified product. Report issues
privately through the repository's security advisory facility once a repository is
published; do not attach unredacted databases, cookies or source media to public issues.
No support endpoint or telemetry service is configured.

## Trust boundaries

The trusted application HTML is embedded in a native pywebview window. It does not
load remote scripts, fonts or frames. A restrictive CSP blocks network requests and
form submission. `unsafe-eval` is permitted only because pywebview generates its native
bridge functions with `new Function`; arbitrary inline scripts remain blocked by a
per-launch nonce. No untrusted content is evaluated. Dynamic text is escaped or inserted with `textContent`. The bridge
exports one allowlisted dispatcher; it has no arbitrary filesystem, SQL, subprocess
or browser-evaluation API. Native dialogs select source folders and export destinations.
Normal protected calls require an in-memory random session token; role and account
status are checked in Python. The backend determines the profile, never a client user ID.
Google pages are opened in a dedicated Chrome process with a non-default profile,
without the application bridge. Chrome exposes a temporary loopback CDP endpoint;
other local programs can access that endpoint while it is active. It is closed with
the owned Chrome process. The app never attaches to the normal personal Chrome profile. A Google-account fingerprint binds the queue to its first account.

## Passwords and sessions

Passwords are 12–256 characters and hashed with Argon2id (64 MiB, 3 iterations,
parallelism 2). A random Fernet encryption key protects saved browser storage; that
key is wrapped using a scrypt-derived key (N=32768,r=8,p=1) and a per-user salt.
Password changes rewrap the key. An administrator reset rotates the key and removes
the saved Google session, while preserving history. Rate limiting survives restart
for known accounts; unknown-account throttling is process-local.

Persistent storage includes a streaming AES-256-GCM encrypted archive of the dedicated
Chrome profile, in addition to the Fernet-encrypted Google storage snapshot. Both use
the password-wrapped profile key, with independent nonces/formats. The archive is
authenticated before extraction; cache directories, symlinks and stale CDP endpoints
are omitted. The browser is closed before archiving. An administrator password reset or Disconnect
Google removes both saved credential files. Recovery-key resets preserve the original
profile encryption key and both saved credential files.

While Chrome runs, its unlocked working profile and staged media are present in the
private app data folder. Normal shutdown removes the unlocked profile; after a crash,
startup removes abandoned managed Chrome working directories before accepting logins.
If the dedicated Chrome process survived the app crash, startup instead asks the user
to close that window before it removes the working profile.
A crash can lose the most recent sign-in changes. OS swap/crash dumps and keys in
process memory are outside at-rest encryption. Python cannot guarantee key zeroization
or secure SSD erasure. Use disk encryption and separate OS accounts for untrusted users.

Local SQLite queues/history contain filenames and metadata in plaintext under the OS
user's private data folder. `0700`/`0600` permissions apply on POSIX; Windows uses the
OS user-profile directory's inherited ACLs. The application is not a sandbox against
other software running as that OS user, a local administrator, or filesystem tampering.
Admins manage account access but have no app operation to browse another user's media.
A privileged admin who resets an account can subsequently sign into that account and
read its plaintext history; that is an explicit administrative trust relationship.

## Audit and recovery

Audit records are append-only through the application interface and chained with
SHA-256. Modifications break the chain, but a person with filesystem write access can
rewrite/recompute the entire chain or truncate its tail. Export the head hash to an
independent trusted system if that threat matters. This is tamper-evident relative to
an anchored head, not an immutable external audit service.

SQLite commits the `uploading` state before passing a file to Google. A crash after
that boundary results in `review`, never automatic resubmission. This favors avoiding
silent duplicates over convenience; it cannot create a transaction spanning SQLite
and Google's website. Connection failures before submission use bounded exponential backoff; other
failures require explicit retries. A manual retry starts a new bounded attempt budget. No source or remote deletion operation is implemented.

ExifTool runs without a shell, with `-config ''` to disable arbitrary user Perl config.
Only staged copies are passed to it. Sidecar sizes are limited; source symlinks are
not followed; executable component archives are checksum-checked and traversal-checked.
A hostile process replacing source paths between filesystem checks is outside the
same-OS-user threat boundary. Takeout files and external parsers remain untrusted input:
keep Python, the browser and ExifTool current and test dependency updates before release.

## Release controls

Release signing runs only for `v*` tags whose commits are ancestors of `origin/main`,
inside the protected `release-signing` GitHub Environment. Configure required reviewers,
protected tags, protected main, restricted workflow edits and environment deployment
rules; YAML alone cannot enforce repository administration settings. Pull requests
never receive signing secrets. Actions are SHA-pinned. Windows signing uses Azure OIDC;
Apple keys live only in an ephemeral runner keychain/temp directory and are cleaned up.
Build artifacts have provenance attestations; GitHub artifacts are not automatically
published as public releases. Treat CI, dependency resolution and reviewers as trusted.

Direct Python requirements and third-party archives are version/hash pinned as
applicable. Transitive Python build dependencies and OS build tooling
are **not yet fully locked or reproducible**. A signed artifact does not establish
that all upstream dependencies are safe. A production release needs dependency review,
SBOM review, target-OS tests and a live Google integration acceptance pass.


## Password recovery and explicit removal (0.1.5)

On first successful sign-in after this update (including new users), a 256-bit random
recovery key is issued and shown once. Accounts can replace it after verifying the
current password. Only its SHA-256 digest and an independently encrypted copy of the
profile key are stored; the plaintext recovery key is never written to app logs or the
database. The high-entropy key derives a domain-separated Fernet wrapping key. A native
Save dialog can export the recovery key to a user-selected private file with mode 0600
on POSIX. The exported file is explicitly outside automatic app cleanup.

The unauthenticated recovery endpoint proves possession of that key, validates the
account is enabled, rewraps the same profile encryption key with the new password,
invalidates the recovery key and resets password lockout counters in one SQLite
transaction. Invalid attempts are audited without input values. Known-account recovery
throttling persists in SQLite; unknown-account throttling is process-local. A new
recovery key is issued at the next successful password sign-in. Recovery does not reset
a Google password. An administrator reset remains separate: it rotates the profile
key, invalidates any recovery key and removes saved Google credentials.

Reset to default settings changes only the current user's preferences. Clear all data
and Uninstall require idle workers, an authenticated app administrator when signed in,
and an additional authorization boundary. On macOS the signed bundled Swift helper
uses Apple's LocalAuthentication deviceOwnerAuthentication policy: Touch ID or the OS
account authentication mechanism, never a password prompt implemented by this app.
A separate native confirmation lists the full destructive scope. A locked-out user
can choose Start over on the sign-in screen on macOS, using the same OS verification
and native confirmation. This intentionally trusts the operating-system account owner
to erase all local app accounts. It does not give access to their decrypted sessions.
Elsewhere, an app administrator must re-enter their current app password to clear data;
password recovery keys work on every platform.

Cleanup closes app file-log handlers, retains the single-instance lock during removal,
and deletes only children of the trusted app data folder without following symlinks.
It removes all accounts, queues, history, logs, settings, encrypted sessions and browser
downloads. The empty application.lock file is retained to avoid concurrent-launch races;
it has no account or configuration content. Source media, Google Photos, personal
Chrome profiles, explicit exports, OS-managed caches, system backups and crash dumps
are not deleted. This is ordinary filesystem deletion, not secure media erasure.

On macOS Uninstall uses the public NSFileManager Trash API for only the verified bundle
identifier in /Applications or the user's Applications folder, then removes app data
and closes. If moving the app fails, account data is kept. If subsequent data cleanup
fails, GPP-111 is shown; the app is already in Bin and can be restored or reinstalled to
retry. On Windows/Linux app data can be cleared here and the platform package manager
removes the installed application. No resident cleanup helper, Finder monitor, root
script, launch agent or login item is installed. Dragging a closed app to Bin alone
cannot run app code and therefore does not invoke this cleanup.


## Optional incident email reports (0.2.0)

There is no app email sender, SMTP credential, automatic telemetry or automatic report
upload. A reportable unexpected error records a private per-profile incident and may
show a dialog. Routine authentication/configuration/source errors do not trigger that
dialog. Reportability is a practical error-code classification, not a determination of
user fault or a proven root cause. A process crash or force-quit may prevent a dialog;
manual Send report remains available after restarting.

Creating a report requires explicit consent, an idle worker and a native Save dialog.
The backend selects the report identity and fixed recipient, never a frontend email
address or arbitrary attachment path. Exports must be ZIPs outside the app data and
selected source folders; symlink destinations are rejected. A temporary file is
atomically renamed over the user-chosen destination after generation. Cancelling Save
never invokes mail composition. Reports are explicit exports and survive app cleanup.

The bundle contains an incident ID/time, version/build fingerprint, installed launcher
SHA-256 when packaged, OS/architecture, safe code locations/exception classes, summary
counts and audit head when available. Raw logs are not copied: recent event fields are
strictly filtered. Source paths, media filenames, photo hashes, usernames, Google
identity, credentials, recovery keys, session archives, screenshots, raw databases,
exception messages, locals and environment variables are excluded. The observed error
and its catalogue explanation are distinguished from an unconfirmed root cause.

The source/dependency fingerprint is generated during packaging from allowlisted code,
UI, build input and component-manifest files. It is not a whole installed-bundle hash,
signature-validation result or DMG hash. The runtime launcher SHA-256 identifies only
that executable. The ZIP's SHA-256 is computed after writing and put in the email draft.
Public release artifact hashes are generated separately after signing/notarization.

NSSharingService's composeEmail service is used on the macOS main thread with a local
file URL attachment, fixed recipient and generated subject/body. It hands off for user
review; the app does not claim delivery. The fallback opens a percent-encoded mailto
URI with subject/body only, and clearly asks the user to attach the saved ZIP. If no
handler is available, the ZIP remains and the UI gives manual reporting instructions.
The user's email client/network/provider and sender identity are outside the app's
no-telemetry boundary once the user chooses to open/send a draft.

Profile schema version 2 adds bounded incident records; migration preserves existing
items, account keys and audit chains. Incidents remain isolated by profile and are
cleared from memory at logout. Repeated identical incidents are deduplicated for five
minutes and the popup can be acknowledged. A current authenticated user can report
database damage using their existing unexpired session token even if the account DB
cannot be read; no new login or administrative action is authorized by that fallback.
Before login/startup, only an unpredictable current-process incident capability can
request a report, and no profile database/history is included. Damaged-database reports
remain useful by omitting unavailable database aggregates. Exports and native draft
handoff do not require Advanced view.

The support mailbox owner must establish appropriate retention/deletion and privacy
practices before publishing. User-initiated support email is optional but still needs
accurate privacy disclosures for the distribution channel.
