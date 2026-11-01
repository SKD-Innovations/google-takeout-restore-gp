# Apple release guide — Takeout Restore 0.2.1

For the maintainer. End users should read [USAGE.md](../USAGE.md). This guide covers testing the DMG, signing, notarizing, secure GitHub automation, and the additional work required for a Mac App Store release.

Commands assume you are in the project root and use its `.venv`. Replace example identity/team/repository values with your own. Do not paste certificate private keys, passwords, recovery keys or API-key contents into this repository, chat, screenshots or issue reports. Do not enable shell tracing while handling credentials.

## 1. Choose the distribution channel

**Direct download:** build a Developer ID-signed app, package it as a DMG, notarize it and staple the ticket. This is the distribution route implemented by this codebase. Developer ID notarization is an Apple malware/signing check, not App Review or an App Store listing. [Apple: notarizing software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)

**Mac App Store:** requires a separate compliant build and App Review. Signing/notarizing this DMG does not make it an App Store build, and App Store Connect does not accept this DMG as the app submission.

Apple requires Mac App Store sandboxing and restricts downloading standalone applications or executable code that adds functionality. The current preview has no App Sandbox entitlement and can download/run a standalone browser. **Our assessment: 0.2.1 is not ready for Mac App Store submission.** Resolve those architectural issues before packaging a store candidate. [Apple: App Review Guidelines, especially 2.4.5 and 2.5.2](https://developer.apple.com/app-store/review/guidelines/)

The steps below prepare a direct-download release now. Section 10 describes the separate App Store path without presenting an unsupported signing command as a way around those requirements.

## 2. Review names, identities and prerequisites

- An active Apple Developer Program membership and access to your development team.
- A current compatible Xcode installation, its command-line tools, and completed first-launch setup.
- A **Developer ID Application** certificate with its private key in your login keychain. It signs a directly distributed app and DMG; a Developer ID Installer certificate is only needed if distributing an installer PKG.
- The current bundle identifier is `org.takeoutrestore.desktop`. Register it with your team if available. If you need an identifier you own, change the bundle metadata and identifier checks consistently before release; use `rg 'org.takeoutrestore.desktop' photorestore packaging docs` to find them.
- App version **0.2.1** and matching package/workflow versions. An App Store candidate additionally needs a unique, increasing build number and the correct store signing/provisioning configuration.
- Verify third-party licences, dependency updates and release notes. Confirm the public support mailbox is working and prepare an accurate privacy policy before public distribution.

Inspect your tools and signing identities:

```sh
xcode-select -p
xcrun --find swiftc
xcrun --find notarytool
security find-identity -v -p codesigning
```

If Xcode is installed but a different developer directory is selected, deliberately select yours:

```sh
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
```

This one-time system configuration is a maintainer action, not something end users must do.

## 3. Prepare a build environment

Use a supported Python 3.12 installation on the target Mac/architecture:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/prepare_exiftool.py
.venv/bin/python scripts/prepare_browser.py
.venv/bin/python scripts/collect_licenses.py
```

These preparation commands can download verified build inputs and compile bundled components. ExifTool/Perl and browser manifests are prepared on the build machine. The browser itself is not embedded in the installer. Review `packaging/vendor-lock.json` and pinned Python requirements before changing dependencies.

The PyInstaller spec compiles the small native device-authentication helper, bundles USAGE.md, and generates `photorestore/resources/build.json`. Its deterministic source/dependency fingerprint identifies the source inputs and platform. Incident reports also compute a SHA-256 of the installed launcher. Neither is a substitute for checking a Developer ID signature; the final DMG has its own SHA-256 in `dist/SHA256SUMS`.

## 4. Run the checks and test the preview

```sh
.venv/bin/python -m ruff check photorestore
.venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python scripts/ui_smoke.py --chrome
```

The UI smoke command uses installed Chrome, disposable accounts and local pages with network requests blocked. It must never use a real Google account or send email. The full test suite also exercises local browser fixtures; see the validation notes for environment requirements.

Build an ad-hoc preview for local testing if you do not yet want to use your certificate:

```sh
PYINSTALLER_CONFIG_DIR="$PWD/build/pyinstaller-cache" \
  .venv/bin/python -m PyInstaller --noconfirm packaging/TakeoutRestore.spec
"dist/Takeout Restore.app/Contents/MacOS/TakeoutRestore" --self-test
.venv/bin/python scripts/package_macos.py
```

`--self-test` uses temporary data and checks native UI/bridge behavior and bundled metadata tooling. It does not access the installed user's app data or upload to Google. The packager verifies bundle metadata, strict recursive signatures and the mounted DMG's saved Finder layout.

Use a disposable macOS user and a small copied Takeout sample for acceptance testing:

1. Drag the app into Applications, open that installed copy, eject the DMG and check Finder/Spotlight behavior.
2. Create an account and save its recovery key. Check an upgrade preserves existing accounts/history using a backed-up test profile.
3. Sign in in the dedicated Chrome window, **keep it open**, return to the app and click **I've signed in — Continue**. Check Google Photos is visible first.
4. Run the connection check and upload a small sample. Check Original quality, original dates, locations and video playback directly in Google Photos.
5. Pause/resume and review an uncertain result without blindly re-uploading it. Check large-file, drive-disconnect and network-interruption behavior on test data.
6. Open Help → Read the full usage guide. Check narrow-window text wrapping and the Logs CSV export.
7. Choose Send report; verify the recipient, version, hashes, explanation, ZIP and mail draft. **Inspect the draft and discard it unless you intend to email it.** Confirm cancellation does not open the mail app and no automatic send occurs.
8. Test recovery-key reset and administrator reset separately. Test Clear all data and Uninstall only in the disposable user/profile. Confirm unrelated source files and personal Chrome data survive.
9. Test a signed/notarized build on a clean supported Mac, including an Intel build on Intel hardware if distributing x64. CI success alone does not establish the oldest supported OS version.

## 5. Build with Developer ID signing

Install the certificate/private key through Keychain Access and note the full identity from `security find-identity`. Keep the private key private. Do not use an Apple Development or App Store certificate for this direct-download step.

Set a shell variable containing the public identity name, then rebuild with that identity:

```sh
export MAC_SIGN_IDENTITY='Developer ID Application: YOUR NAME (YOURTEAMID)'
PYINSTALLER_CONFIG_DIR="$PWD/build/pyinstaller-cache" \
  .venv/bin/python -m PyInstaller --clean --noconfirm packaging/TakeoutRestore.spec
codesign --verify --deep --strict --verbose=2 "dist/Takeout Restore.app"
codesign --display --verbose=4 "dist/Takeout Restore.app"
codesign --display --entitlements :- "dist/Takeout Restore.app"
"dist/Takeout Restore.app/Contents/MacOS/TakeoutRestore" --self-test
.venv/bin/python scripts/package_macos.py
```

PyInstaller signs nested Mach-O components and the app using the configured identity and hardened runtime entitlements. Do not replace that with a blanket `codesign --deep --force` signing command. `--deep` above is used for verification. Confirm the displayed authority/team match your real Developer ID rather than an ad-hoc signature, and confirm the runtime flag is present. Review entitlements against the actual dependencies; keep only what they need.

The package script signs the DMG too when `MAC_SIGN_IDENTITY` is set. Select the file for the build architecture:

```sh
APP='dist/Takeout Restore.app'
DMG='dist/TakeoutRestore-0.2.1-macos-arm64-preview.dmg'
codesign --verify --verbose=2 "$DMG"
hdiutil verify "$DMG"
```

For Intel, use `macos-x64` in the filename and build on an Intel runner/Mac. These artifact names retain `preview` until you deliberately change the release naming; a filename does not establish signing or readiness.

Apple describes the certificates, hardened runtime and notarization route in [Signing Mac software with Developer ID](https://developer.apple.com/developer-id/).

## 6. Configure notarization credentials without putting passwords in commands

The local interactive option below stores an app-specific password in Keychain. Enter the secret only at the tool's prompt; the Apple ID/team are not the password:

```sh
xcrun notarytool store-credentials 'TakeoutRestore-Notary' \
  --apple-id 'YOUR_APPLE_ID_EMAIL' \
  --team-id 'YOURTEAMID'
```

Create an app-specific password using Apple's account settings when needed. For CI, prefer the App Store Connect API-key route already implemented by `scripts/sign_macos.py`; the `.p8` key belongs in a protected secret, not the app or repository.

[Apple: notarytool migration and Keychain credentials](https://developer.apple.com/documentation/technotes/tn3147-migrating-to-the-latest-notarization-tool)

## 7. Submit, inspect, staple and verify

Using the variables from section 5:

```sh
xcrun notarytool submit "$DMG" \
  --keychain-profile 'TakeoutRestore-Notary' \
  --wait --timeout 30m --output-format json
```

Save the submission ID and confirm the returned status is **Accepted**. A command completing is not enough if the status reports a rejection. Inspect a failure using the returned submission ID:

```sh
xcrun notarytool log 'YOUR_SUBMISSION_ID' \
  --keychain-profile 'TakeoutRestore-Notary' \
  'build/notarization-log.json'
```

Fix the actual reported issues, rebuild/re-sign/repackage as needed, and submit the resulting new artifact. Do not strip quarantine flags or disable Gatekeeper as a substitute for acceptance.

After acceptance:

```sh
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
codesign --verify --deep --strict --verbose=2 "$APP"
codesign --verify --verbose=2 "$DMG"
spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"
spctl --assess --type execute --verbose=2 "$APP"
hdiutil verify "$DMG"
```

Test the actual downloaded signed/stapled DMG in a clean user environment. Rebuilding or editing the artifact after notarization can invalidate the checked artifact. Do not rerun `package_macos.py` after stapling and assume that its newly generated DMG is the same notarized file.

If you will also distribute the portable ZIP, staple the original app using the ticket generated for its nested code, then regenerate **only the ZIP**, not the DMG:

```sh
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
ditto -c -k --sequesterRsrc --keepParent "$APP" \
  'dist/TakeoutRestore-0.2.1-macos-arm64-portable.zip'
.venv/bin/python scripts/checksums.py
```

Use the x64 filename for an Intel build. ZIP files themselves cannot be stapled. The existing CI workflow notarizes/staples the DMG; if publishing its portable ZIP as an offline-ready primary download, also perform the app-staple/re-ZIP step before final checksums and attestation. It is not currently automatic in CI.

The notarization service checks nested code and publishes tickets; this is separate from App Review. [Apple: customizing notarization](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)

## 8. Automate securely with GitHub Actions

See [SIGNING.md](SIGNING.md) for the exact Windows/Linux settings as well. For macOS:

1. Put this code in your GitHub repository. Protect `main`, release tags and workflow/packaging changes.
2. Create GitHub Environments `unsigned-build` and `release-signing`. Require manual approval and restricted tag deployment for `release-signing`. Restrict who may edit workflow code and create release tags.
3. Export the Developer ID Application certificate **and private key** as a password-protected P12 from Keychain Access.
4. In `release-signing`, configure variable `MAC_SIGN_IDENTITY` and secrets `MAC_CERTIFICATE_P12_BASE64`, `MAC_CERTIFICATE_PASSWORD`, `APPLE_API_KEY_P8_BASE64`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER`.
5. Never store those secrets in `unsigned-build`, pull-request workflows or the app. Use a trusted ephemeral runner. GitHub repository/environment administrators are part of the trust boundary.

To enter base64 key material without printing it in Terminal, copy it directly to your Mac clipboard, paste into the appropriate protected GitHub secret, then clear the clipboard:

```sh
base64 -i '/PRIVATE/PATH/developer-id.p12' | pbcopy
```

```sh
base64 -i '/PRIVATE/PATH/AuthKey_YOURKEYID.p8' | pbcopy
```

After each paste, `pbcopy < /dev/null` clears the current clipboard. The encoded key is still a secret; base64 is not encryption. Clear clipboard-manager history too if you use one. Use GitHub's secret-entry UI or a secure secret provisioning system for passwords, rather than command arguments that can enter shell history.

From a configured repository, the optional GitHub CLI commands are:

```sh
gh workflow run build.yml --ref main
gh run list --workflow build.yml --limit 5
```

Test the unsigned artifacts. After the tested commit is merged into protected `main`, create the release tag deliberately:

```sh
git switch main
git pull --ff-only
git tag -a v0.2.1 -m 'Takeout Restore 0.2.1'
git push origin v0.2.1
```

By default, the tag produces unsigned preview artifacts. Once the protected signing
credentials for all applicable platforms are configured, explicitly request signing:

```sh
gh workflow run build.yml --ref v0.2.1 -f sign_release=true
```

Alternatively set the repository variable `RELEASE_SIGNING_ENABLED=true` to opt into
automatic signing for future version tags. A branch cannot request signing. Review
and approve the release-signing environment only for the intended commit. The workflow checks the tag commit is reachable from `origin/main`, imports the P12 into a temporary keychain, builds/signs the app, signs/packages the DMG, submits with the API key, staples, checksums, and generates provenance attestations on supported GitHub plans. Private repositories skip attestations unless `ENABLE_PRIVATE_ATTESTATIONS=true` is configured. Each artifact records its signing/attestation status in `SIGNING-STATUS.json`. Temporary signing material is removed by cleanup steps.

Download the completed artifacts and verify them on a clean Mac. Publishing a GitHub Release remains a separate maintainer decision; the workflow does not silently publish one. Do not create/reuse the same version tag after changing the tested source; increment version/build metadata for a revised release.

## 9. Publish a direct-download release

Publish the exact tested, Developer ID-signed and notarized/stapled DMG, matching SHA256SUMS, source code, release notes and accurate privacy/support information. Include the usage guide and supported architectures/OS versions. Avoid promising features still recorded only for manual review.

Generate final checksums **after** signing/stapling/re-ZIP changes:

```sh
.venv/bin/python scripts/package_source.py
.venv/bin/python scripts/checksums.py
shasum -a 256 "$DMG"
```

Users can compare the displayed SHA-256 to the entry for that filename in SHA256SUMS. Distribute checksums through a trusted release channel and verify provenance/signatures where available; an unsigned checksum alone is not authentication.

## 10. Separate Mac App Store readiness work

Do not submit 0.2.1's DMG or simply add the sandbox entitlement to its existing signing file. That would not implement sandbox-safe behavior. Before a store build:

- Redesign browser provisioning/execution to meet the store rules; obtain an acceptable integration approach and test it honestly. Do not hide a download/automation path from App Review.
- Implement and test App Sandbox access, container-based app storage and persistent access to chosen Takeout folders using security-scoped bookmarks. Re-audit child-process inheritance, network/CDP access, ExifTool, device authentication and email composition under sandboxing.
- Use a store-specific removal/update model. The current direct-download self-uninstall flow moves the bundle from Applications, which a sandboxed store app should not assume it can do. Store updates must use the store.
- Audit signing of every nested executable/framework, entitlements, provisioning, the bundle identifier and monotonically increasing build number. Use a separate store configuration and appropriate Mac App Store distribution identities/profiles.
- Prepare public privacy/support URLs, screenshots, description, age rating, export-compliance answers and review instructions. Accurately disclose Google website automation and any dependency on external accounts/services. Supply a safe review account/demo workflow as Apple requires.
- Review privacy declarations and required-reason APIs/privacy manifests for the app and bundled dependencies. Evaluate optional support email reports and the sender identity against Apple's actual App Privacy criteria rather than assuming no telemetry means no disclosure.

Apple documents [sandbox configuration](https://developer.apple.com/documentation/xcode/configuring-the-macos-app-sandbox), [persistent file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox) and [App Privacy details](https://developer.apple.com/app-store/app-privacy-details/). Those capabilities require implementation and acceptance tests, not only packaging changes.

Once a compliant, separately signed store app exists, Apple's tools can package a single-app submission. This is an example of the **later packaging step**, not a working conversion command for this preview:

```sh
productbuild \
  --sign '3rd Party Mac Developer Installer: YOUR NAME (YOURTEAMID)' \
  --component 'STORE_BUILD/Takeout Restore.app' /Applications \
  'dist/TakeoutRestore-0.2.1-AppStore.pkg'
pkgutil --check-signature 'dist/TakeoutRestore-0.2.1-AppStore.pkg'
```

The app must already carry the correct Mac App Store app signature, entitlements and provisioning profile before `productbuild` signs the installer. Confirm the exact installed installer identity with `security find-identity -v`; the `-p codesigning` filter omits installer identities. [Apple: packaging Mac software](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution)

Create the app record in App Store Connect with your registered bundle ID. Use Xcode Organizer or **Transporter** to upload the compliant PKG, wait for processing, select the build, complete the listing, then submit for App Review. Uploading a build does not itself publish it. [Apple: upload builds](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds)

`altool` is no longer supported for **notarization**; `notarytool` is the direct-download notarization tool. Do not confuse that with Apple's separately documented store-upload tools. Apple may change requirements; recheck these official pages immediately before a public release or store submission.
