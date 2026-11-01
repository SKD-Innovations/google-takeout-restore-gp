# Build and distribution

Build on the target OS/architecture; PyInstaller is not a cross-compiler. The workflow
matrix targets Windows x64, macOS arm64/x64 and Linux x64. No Git remote was present
when this codebase was prepared; workflows must be run in the repository you publish.

## Targets

| Target | Package | Prerequisites / constraints |
|---|---|---|
| Windows 10/11 x64 | EXE installer, portable ZIP | Installer provisions WebView2 using a Microsoft-signed bootstrapper; internet required if missing. Portable builds require WebView2 already installed. |
| macOS 13+ arm64/x64 (target) | DMG, `.app` in ZIP | Current browser requires macOS 13+. Verify the oldest claimed OS with the actual release bundle; CI host libraries may impose a newer floor. |
| Ubuntu 22.04+ x64 (target) | `.deb`, AppImage, portable tarball | `.deb` declares GTK/WebKit/browser system dependencies; desktop package manager installs them. AppImage/portable builds need compatible GTK/WebKit system services and must be validated on clean systems. |

The earlier 60–90 MB installer estimate was not a guarantee. The Python runtime,
Playwright driver, native bridge, cryptography and standalone ExifTool all contribute.
Linux bundling can be larger because of WebKit. The browser download is separate and
its size depends on the pinned Playwright release. Do not advertise file sizes until
you measure the actual release artifacts.

## Build sequence

Use Python 3.12 and a dedicated virtual environment. Install `requirements-dev.txt`.
Unix build hosts need a C compiler and make. The build script compiles a checksum-pinned
Perl interpreter and bundles its core libraries, avoiding self-extracting executables
that cannot pass hardened macOS signing validation. Windows uses the vendor's
ExifTool executable distribution including its `exiftool_files` folder.

```sh
python scripts/prepare_exiftool.py
python scripts/prepare_browser.py
python scripts/collect_licenses.py
python -m pytest -q
python -m ruff check photorestore
python -m PyInstaller --noconfirm packaging/TakeoutRestore.spec
```

`prepare_exiftool.py` checks the archive against `packaging/vendor-lock.json` and
bundles a signable interpreter plus core libraries on Unix. `prepare_browser.py` uses the pinned
Playwright dry-run output, downloads the browser **on the build host**, computes its
SHA-256 and embeds the manifest; it does not embed the browser archive. That manifest
is covered by application code signing. End users download the exact same archive,
verify its pinned checksum, and install it atomically. A corrupt download is removed;
interrupted downloads currently restart rather than resuming partial HTTP transfers.
Browser updates require a new application release with a new manifest.

On Windows run `scripts/prepare_webview2.ps1` before compiling
`packaging/windows.iss` with Inno Setup 6. This validates the Microsoft Authenticode
signature before bundling the bootstrapper. If runtime installation fails, Setup
stops with a readable message rather than opening a blank application.

On macOS, package the `.app` in a DMG with an Applications shortcut. On Linux,
`python scripts/package_linux.py` creates the `.deb`, AppImage and portable archive;
appimagetool and the AppImage runtime are checksum-pinned. Neither packaging nor
signing success proves Linux runtime-library compatibility—clean-machine testing is mandatory.

## Validation

```sh
python -m pytest -q
python -m ruff check photorestore
PYTHONPATH=. python scripts/ui_smoke.py --chrome
```

The last command is a development-only smoke test using installed Chrome and temporary
app accounts, exercising the actual UI and backend. Network requests from the test
page are blocked. Omit `--chrome` to use a Playwright-installed test browser. The test
never signs into Google or uploads personal data. Real ExifTool tests run when a tool
is available; CI release builds explicitly point tests at the bundled executable.

Release acceptance must include: starting the signed/unsigned native app on clean
target machines; user creation/reset/lock; component download interruption; browser
login; small real JPG/PNG/HEIC/RAW/MOV/MP4 samples; timezone and GPS display; storage-full
and network-loss cases; crash at each submission boundary; multi-million-file indexing
and disk-pressure tests; mixed-language Takeout data; vendor security/license review.

**Not validated here:** live Google uploads, full real-world Takeout corpus, Windows/
Linux binary execution, code signing/notarization with your credentials, and claimed
minimum OS versions on clean hardware. Do not promote the preview as production-ready.

On new macOS SDKs, Perl's Configure probes may detect `dup3`/`pipe2` declarations
without the APIs existing on the deployment target. The build explicitly disables
those optional APIs, following upstream Perl commit
`1a6f4bf952b80ae330ddc07a2c49d708985b5885`. It does not modify system Perl.


Packaged applications also accept `--self-test` for maintainers and CI. This creates
a disposable account store, checks the actual native bridge and performs a real
bundled-ExifTool metadata round trip without any Google connection. A failing check
exits unsuccessfully. It does not touch an existing user's application data.


The macOS build uses `dmgbuild` (build dependency only) to save Finder icon positions,
window size and a retina installation background without requiring AppleScript control
of Finder. Both local packaging and GitHub Actions call `scripts/package_macos.py`.
See MACOS-INSTALLATION.md for Apple's registration and Spotlight guidance.


The macOS spec also compiles `packaging/AuthorizeReset.swift` with Xcode's `swiftc`
(target macOS 13+) and includes it as a signed native executable. It uses the system
LocalAuthentication framework; there is no downloaded recovery/authentication service.
The compiler cache is kept under `build/swift-module-cache`. Validate interactive
device authentication and uninstall on a disposable macOS user/account before release.
