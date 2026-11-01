# macOS installation and search

1. Quit any running copy of Takeout Restore after safely pausing its upload.
2. Open the DMG. Drag **Takeout Restore** onto **Applications** in the designed window.
3. Open the installed copy from Applications. Eject the disk image afterwards.
4. Existing local accounts, queue and history are outside the app bundle and remain available.

The DMG is a disk image containing the app, not an installer that runs a privileged
script. It uses a real Applications shortcut, fixed icon positions, a hidden background,
retina artwork and saved Finder view settings. No FinderInfo extension-hiding flag is
added to the signed app, in accordance with Apple QA1940. The interface design is this project's
choice; Apple does not prescribe this particular background or layout.

The app uses a standard APPL bundle with name, identifier, executable, icon, version,
minimum OS and photography category. Finder normally registers a copied app with
Launch Services. On first installed launch after an update, this app additionally
refreshes only its own registration using Apple's public LSRegisterURL API. This is
not a Spotlight rebuild and cannot override a user's Spotlight privacy settings.

If Spotlight still omits the app, first open the copy in Applications and check
**System Settings → Spotlight** to ensure Apps results are enabled and Applications
is not excluded from Search Privacy. Apple also documents temporarily adding/removing
a specific folder in Search Privacy to reindex it. Follow that guidance if needed;
the app does not reset the global Spotlight database or change search permissions.

During local investigation, the installed 0.1.1 app had the expected name, identifier
and APPL package type. The available metadata queries returned no app metadata and
reported a read-only index. That did not establish the precise reason the user's
Spotlight search omitted the app; appearance in the user's Spotlight is not verified.
An explicit registration attempt returned macOS status -43 (file not found), despite
the bundle being readable through filesystem tools. The environment could not confirm
a successful registration of that installed copy.

Apple references:

- Install apps: https://support.apple.com/guide/mac-help/mh35835/mac
- Bundle configuration: https://developer.apple.com/documentation/bundleresources/bundle-configuration
- Automatic registration: https://developer.apple.com/library/archive/documentation/Carbon/Conceptual/LaunchServicesConcepts/LSCTasks/LSCTasks.html
- Registration API: https://developer.apple.com/documentation/coreservices/1446350-lsregisterurl
- Spotlight settings and reindexing: https://support.apple.com/en-in/102321

Developer ID signing and notarization remain dependent on maintainer credentials;
see SIGNING.md. A polished DMG does not replace release signing.

- Signature metadata restrictions: https://developer.apple.com/library/archive/qa/qa1940/_index.html


## Reset, recovery and clean uninstall

Use **Settings → Reset & removal**:

- **Reset to default settings** restores this local user's preferences. Accounts,
  source selection, Google sign-in, queue and history remain.
- **Clear all data** removes every local app user, saved Google session, preference,
  queue, history, app log and downloaded browser. The app remains and offers account
  creation again.
- **Uninstall** performs the same cleanup, moves the installed app from Applications
  to Bin using Apple's public Trash API, and closes it. Run the installed copy, not
  the read-only DMG copy. If another user's permissions prevent moving the bundle,
  nothing is erased; resolve those OS permissions and try again.

Clear all data and Uninstall require an app administrator when signed in, macOS device
verification, and a final native confirmation. Pause operations and close any dedicated
restore Chrome window first. Source Takeout media, your Google Photos library, your
personal Chrome profile, explicitly exported reports/recovery keys, OS-managed caches
and system backups are outside this cleanup. An empty single-instance lock file may
remain in `~/Library/Application Support/TakeoutRestore`; it contains no account data.

For a forgotten password, choose **Forgot password?** on the sign-in screen and enter
the saved recovery key. This preserves history and saved Google sign-in. Save the new
key shown at your next sign-in. Existing users receive their first key when they next
successfully sign in after upgrading. An app administrator can reset another user's
password, which preserves history but removes their saved Google sign-in. If no key or
administrator password is available, **Start over on this Mac** on the sign-in screen
removes all app accounts after OS verification, without needing the forgotten app
password.

Dragging a closed app to Bin by itself leaves data in Application Support. macOS does
not notify an exited app so it can erase those files. Use Settings → Uninstall for
clean removal. If you already removed the app, reinstall/open it and use Start over or
Uninstall. No background cleanup agent is installed.

Apple's guidance recommends an app-provided uninstaller/settings option when available:
https://support.apple.com/en-us/102610
Device authentication uses:
https://developer.apple.com/documentation/localauthentication/lapolicy/deviceownerauthentication
