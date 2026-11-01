# Takeout Restore — usage guide

For version **0.2.0**. You do not need to write code, edit configuration files, or use Terminal to operate the app.

## What this app does

Takeout Restore helps copy photos and videos from an extracted Google Takeout backup into Google Photos. It reads the extra information in Takeout’s JSON files, adds supported dates, locations and descriptions to temporary copies, and keeps a record of what happens to each item.

Your original Takeout files are not edited. Keep an independent backup of them. Uploading uses your Google account’s available storage. The app always selects **Original quality** when Google asks about upload quality.

This version records album membership, favorites, archive status and paired-photo relationships for review. It does not automatically recreate those features in Google Photos. A browser confirmation means Google’s website reported completion; check a sample yourself before committing to a large restore.

## Before you begin

- Have a Google Photos account with enough available storage for your restore.
- Download and extract every part of your Google Takeout export. Keep the photos, videos and accompanying JSON files together, preserving the original folders and filenames.
- Use an extracted folder, not a ZIP file. Do not put the app’s own data or downloaded browser inside your source folder.
- Keep the source drive connected, allow enough free working space on your computer, and use a reliable internet connection.
- Installed Google Chrome is preferred. If the app needs a browser component, Setup offers the download; no browser commands are needed.
- Keep the computer awake during long operations. You can safely pause and continue later.

## Install or update

### On a Mac

1. Quit any running copy of Takeout Restore after the current operation has paused.
2. Open the DMG file for your Mac. Apple Silicon Macs use the arm64 download; Intel Macs use the x64 download when available.
3. Drag **Takeout Restore** onto **Applications** in the installation window. When updating, choose to replace the older app.
4. Open Takeout Restore from **Applications**, then eject the installation disk image. Run the installed copy rather than the copy inside the DMG.

Updating preserves your existing local accounts, settings and history. Clearing data is a separate action. A preview may not yet have Developer ID signing/notarization; get releases from a source you trust and follow the supplied release notes. The app does not ask you to disable macOS security settings.

### On Windows or Linux

Use the package for your operating system when available. On Windows, run the setup EXE; it can install Microsoft WebView2 if needed. On Ubuntu, the DEB package is preferred because the package manager can install required system components. Portable builds may need system components that an installer would normally provide.

These instructions describe the shared app interface. Check the release notes for platforms and architectures actually tested in that release.

## Create your local account

1. On first launch, choose a username and a password of at least 12 characters. A memorable passphrase is a good choice.
2. Click **Create account**. The first local account is an administrator.
3. Save the recovery key shown by the app. Choose **Save key to file**, or copy it somewhere private outside the app’s data folder.
4. Click **I’ve saved my key** to continue.

This password belongs to Takeout Restore, not Google. Google sign-in happens separately in Chrome. Anyone with your recovery key can reset your local password, so keep it as private as the password itself.

Existing users upgrading from an older version receive their first recovery key the next time they successfully sign in. You can replace a lost key in **Accounts** while you still know your password.

## Set up your restore

Open **Setup** from the left-hand menu and work through the steps in order.

### 1. Choose your Takeout folder

Click **Choose folder** and select the extracted Google Photos folder. If your export has several parts, extract them so the complete Google Photos folder structure is available. Do not move or rename files after scanning.

### 2. Scan and review

Click **Scan folder**. Large backups can take a long time because the app reads metadata and checks file contents. Leave the app open and wait for the scan to finish, or use **Pause safely**.

Open **Queue** afterwards. Review rejected files or metadata issues before uploading. No upload happens during a scan.

### 3. Prepare the browser

If Setup says your browser is ready, continue to the next step. Otherwise click **Download browser** and wait for the verified download to finish. A broken or interrupted download can be retried.

### 4. Connect to Google Photos — keep Chrome open

1. Click **Open Chrome sign-in**. A dedicated Chrome window opens for this app.
2. Sign in to the Google account you want to restore into. Complete any Google security or two-step verification prompts in Chrome.
3. Wait until **Google Photos is visible** and you can see your library.
4. **Keep that Chrome window open. Do not close it yet.** Switch back to Takeout Restore using its Dock/taskbar icon or the app switcher.
5. In Takeout Restore, click **I’ve signed in — Continue**.
6. Wait for the app to finish connecting. It will close the dedicated browser itself when that connection operation finishes.

The app waits for your click; signing in to Google alone does not finish this step. Do not click Continue before Google Photos is visible. You do not need to close your normal personal Chrome windows.

If Google says the browser or app may not be secure, click **Pause safely** in Takeout Restore, wait for the attempt to stop, and close any dedicated window left open. Update Chrome if needed, then try the manual sign-in steps again. If Google continues blocking it, stop and report the issue; the app cannot guarantee that Google will allow every account.

Each local workspace stays bound to the first Google account connected to it. To restore into a different Google account, create a separate local app user. Disconnecting Google does not remove the original account binding.

### 5. Check the connection

Click **Run check**. This checks the selected Google account and upload controls without uploading a test file. Resolve any message before continuing.

### 6. Upload a small sample

Click **Upload sample** and confirm. The app uploads up to five ready items. It makes temporary copies, merges supported metadata, and uploads one item at a time.

When the sample finishes, check those items directly in Google Photos: dates, location, image quality, video playback and the number of items. Some uploaded items may appear under their original photo date rather than at the top of your library.

If the quality-choice window appears, the app selects **Original quality** and continues. If it cannot verify that choice, it stops and asks you to review it.

## Run the full upload

1. Open **Dashboard** or **Queue** and click **Start upload**.
2. Read and accept the confirmation.
3. Keep the source drive connected, the computer awake and internet access available.
4. Watch progress in the app. The dedicated Chrome window may open while an operation runs; leave it under the app’s control.
5. When the operation stops or finishes, check **Queue** for unresolved items. An operation finishing does not mean every item was successfully uploaded.

Click **Pause safely** to stop after the current submitted upload. Wait until the app reports that it has paused before quitting or unplugging the source drive. A large video can take time to finish. Repeatedly force-quitting increases the number of items that need manual review.

## Understand the queue

- **Ready:** scanned and waiting for upload.
- **Preparing:** a temporary copy is being prepared.
- **Uploading:** the item has reached the upload step.
- **Browser confirmed:** Google’s website showed a completion message for that item.
- **Restore details:** an upload was recorded, but Google-only restoration details still need review.
- **Verified by you:** you explicitly marked the item checked in Google Photos.
- **Needs review:** the app could not safely determine whether the upload completed. Check Google Photos before retrying; it may already be there.
- **Failed:** an operation failed. Read its error code and instructions before retrying.
- **Rejected:** a source, format, size or metadata rule prevented normal processing.
- **Skipped:** the item was excluded by a rule or your manual choice.

Use the search field and status filter, then click **Apply**. Queue pages show up to 100 items at a time. The app checks duplicates against this local user’s records, not against every photo already in your Google library.

## Simple and Advanced views

Most people can leave **Advanced view** switched off in the sidebar. Turn it on for queue details, retry/skip/manual verification controls, extra resource settings and diagnostic exports.

Advanced view is an interface option, not a separate administrator permission. Standard users still see only their own workspace. Retrying a **Needs review** item can create a duplicate, so check Google Photos first. **Verified** only updates the local record; it does not change Google Photos.

## Choose your preferences

Open **Settings**, choose your rules, then click **Save preferences**. You can choose what happens to edited copies, duplicates, Live/motion photo pairs, albums, favorites, archived items, descriptions and files above Google’s size limits.

Rules describing preservation for review do not mean the app can automatically apply those Google-only features. Rescan after changing scan rules. Existing upload evidence is kept. Resource and retry controls are available in Advanced view.

**Reset to default settings** restores preferences for the current local user. It keeps accounts, Google sign-in, source selection, queue and history.

## History, logs and support reports

**History & reports** shows past scans, connections and upload operations. **Export report** saves a CSV containing your library’s filenames, restoration details and outcomes. Treat this report as private.

**Logs & diagnostics** shows the audit trail. **Export logs as CSV** saves the complete local audit trail, including error descriptions. Long details wrap; unusually large log entries scroll inside their own cell. Advanced view adds **Export diagnostics**.

**Send report**, next to **Export logs as CSV**, helps report a problem to **sarthakg043@gmail.com**. Unexpected app, component or website failures can also offer a report dialog. Routine problems such as an incorrect password or disconnected source drive do not automatically open it.

1. Click **Send report**, or use the offered incident dialog.
2. Read what will be included, then click **Save report & open email**.
3. Choose a location for the diagnostic ZIP outside your Takeout source folder and the app’s data folder. If you cancel, no email opens.
4. Your email application opens a prefilled draft when available. On macOS the app requests that the ZIP be attached. Other clients or the fallback email link may require you to attach it yourself.
5. Check the recipient, contents and attachment. Add what you were doing, what you expected and whether you can reproduce the problem.
6. Click **Send in your email application** when you are ready. Takeout Restore never sends the email itself.

The ZIP includes the version, a source/dependency build fingerprint, the installed launcher’s SHA-256 hash when available, an incident ID, error code, observed failure, safe technical details and summary counts. The ZIP’s own SHA-256 is included in the email draft. These hashes help identify the build and file; they are not proof of code-signing validity or a confirmed root cause.

Reports exclude your media, source filenames and paths, Google account identity, passwords, recovery keys, cookies, browser profiles, screenshots and raw databases. Your email application supplies your sender address when you send. The app cannot automatically prove why every failure occurred; its report distinguishes the observed error from an unconfirmed root cause.

If no email window opens, the ZIP is still saved. Open your email app yourself, address it to the support email above, describe what happened and attach the ZIP. You can read **report.txt** inside it for the incident summary. Reports are optional; choose **Not now** to dismiss the offer.

A force-quit, power loss or native system crash may prevent any dialog appearing. Reopen the app, review the queue, and use Send report. Items with uncertain outcomes remain held for review. Do not send your recovery key, Google password, session files or full database to support.

## Accounts and forgotten passwords

Use **Accounts** to change your password, replace your recovery key or disconnect the saved Google session. Changing your password keeps the saved session. Disconnecting removes saved login credentials but keeps history and the Google account binding.

Administrators can create local users, enable/disable accounts, change roles and reset another user’s password. An administrator reset preserves history but removes that user’s saved Google sign-in and invalidates their old recovery key.

If you forget your password, click **Forgot password?** on the sign-in screen. Enter your username, saved recovery key and a new password. Sign in with the new password, then save the new recovery key shown. This method preserves your history and saved Google sign-in.

If you have no recovery key, ask another local administrator to reset your password. On macOS, **Start over on this Mac** is available on the sign-in screen as a last resort: after device verification and confirmation, it deletes **every local app account and its records** and offers a fresh start. It does not require the forgotten app password. It does not recover the old history.

## Clear data or uninstall

Pause any operation and close the dedicated restore Chrome window before cleanup. These Settings actions require an app administrator when signed in. macOS also asks for device verification and a final confirmation; elsewhere clearing data requires the administrator’s current app password.

- **Reset to default settings:** current-user preferences only; the app and records stay.
- **Clear all data:** removes every local app account, setting, queue, history, log, browser download, incident record and saved Google session. The app remains and offers account creation again.
- **Uninstall:** on macOS, clears that data, moves the installed app from Applications to Bin and closes. On Windows/Linux, clear data here and then remove the app using your operating system’s app manager.

Your Takeout source files, Google Photos library, personal Chrome profile and explicitly exported reports/recovery keys remain. System backups and OS-managed caches are outside this cleanup. A harmless empty lock file may remain to prevent two app instances racing each other.

Dragging a closed Mac app straight to Bin does not run the app’s cleanup. Use **Settings → Uninstall** for clean removal. If you already removed it, reinstall/open it and use the cleanup options. No background cleanup agent is installed.

## Common problems

### The app is waiting after I signed in

Keep the dedicated Chrome window open with Google Photos visible, return to Takeout Restore and click **I’ve signed in — Continue**. Wait for the connection to finish.

### An upload may already be present

Check Google Photos before retrying a Needs review item. Look under the item’s original date. Re-uploading an uncertain item can create a duplicate.

### My external drive disconnected

Pause safely, reconnect the same source drive, then rescan. Do not rename or edit files already in the queue without rescanning.

### The app says a previous Chrome window is still open

Close the dedicated restore Chrome window left by the previous session, then reopen the app. You do not need to close unrelated personal Chrome windows.

### Nothing is ready to upload

Check the queue filters and unresolved statuses. Some items may need review, may be rejected or may already have been recorded. A no-ready-items message does not confirm that every item reached Google Photos.

### An error code appears

Read the description and suggested recovery action. If it looks like an app failure, choose Send report. For uncertain uploads, check Google Photos first. Reinstalling or resetting data is not the first troubleshooting step because it can remove useful local history.
