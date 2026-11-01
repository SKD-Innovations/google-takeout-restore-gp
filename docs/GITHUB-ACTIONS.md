# Build all platforms and configure optional signing

You can build Windows and Linux applications from your Mac using GitHub Actions.
GitHub supplies a separate Windows, Mac or Linux computer for each build. You only
need a browser to start the build and download its results.

## 1. What the reported error means

`Failed to persist attestation: Feature not available for the SKD-Innovations organization`
means your GitHub plan does not support saving artifact attestations for this private
repository. An attestation records where an artifact was built. It is separate from
Apple signing, Apple notarization and Windows signing.

Apple credentials cannot fix this GitHub feature restriction. GitHub currently requires
**Enterprise Cloud** for private/internal repository attestations. Public repositories
can use them without that private-repository entitlement. You do not need to change
the repository's visibility or upgrade to build applications: the workflow skips this
optional step on private repositories unless explicitly enabled.

Leave the repository variable `ENABLE_PRIVATE_ATTESTATIONS` unset or `false` unless
you have confirmed Enterprise Cloud support. Do not set it to `true` merely to fix an
attestation error. A requested but unsuccessful attestation still fails the job.

The supplied error occurred in the old **v0.2.0** workflow. Its Mac failures also
included missing signing credentials; its Windows ExifTool failure was corrected
separately. Re-running an old run uses its original source and workflow. It does not
pick up fixes merged into `main`. Published release tags are not moved or rewritten.

[GitHub: artifact attestation availability](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)

## 2. Generate binaries now, with no signing credentials

1. Open this repository on GitHub and choose **Actions**.
2. Select **Build desktop packages** in the left sidebar.
3. Choose **Run workflow** and select branch **main**.
4. Leave **sign_release** unchecked. The signing-platform selection is ignored when
   signing is disabled. Choose **Run workflow**.
5. Open the new run and wait for all four jobs to finish. Native dependency compilation
   can take several minutes, especially on Intel Mac. Inspect a red job's failed step
   if it stops; do not assume every failure means missing signing credentials.
6. On the completed run's summary page, scroll to **Artifacts**. Download the ZIP for
   your platform and extract it. These artifacts are build outputs, distinct from
   the assets published on the repository's Releases page.

| Artifact target | Packages inside |
|---|---|
| `windows-x64-preview` | EXE installer in `installers/`, plus portable ZIP |
| `macos-arm64-preview` | Apple Silicon DMG and portable app ZIP |
| `macos-x64-preview` | Intel Mac DMG and portable app ZIP |
| `linux-x64-preview` | DEB, AppImage and portable tarball |

Artifact names also contain the app version. Each includes `SHA256SUMS` and
`SIGNING-STATUS.json`, which records whether it was signed and whether attestation ran.
No Apple, Microsoft, Google or Linux developer account is required for these unsigned
builds. GitHub Actions must be enabled and your account must have available runner
usage. Unsigned previews can trigger operating-system trust warnings; use the
Developer ID-signed/notarized Mac release for normal Mac distribution. Linux's DEB
is preferred on compatible Ubuntu systems because the package manager resolves system
dependencies; AppImage and portable packages still require compatible system services.

Optional command from your Mac, if GitHub CLI is installed and signed in:

```sh
gh workflow run build.yml --repo SKD-Innovations/google-takeout-restore-gp --ref main
```

Keep Apple signing local if that suits you. GitHub can build unsigned Windows/Linux
packages while your Mac signs and notarizes the Mac DMG using the existing Keychain
profile. [The local Apple release guide](APPLE-RELEASE.md) covers that route. A local
Keychain profile is not automatically available on a GitHub runner.

## 3. Where settings go in GitHub

Use **repository Settings**, not your personal GitHub profile settings.

- **Settings → Environments → New environment:** create `unsigned-build` and
  `release-signing`. The unsigned environment needs no credentials. Open
  `release-signing` to add **Environment secrets** and **Environment variables**.
- Restrict `release-signing` to intended version tags. Enable required reviewers and
  other deployment protections where your plan supports them. Protect `main`, release
  tags and workflow changes; signing runs code from the selected release commit.
- **Settings → Secrets and variables → Actions → Variables:** repository-wide switches
  go here using **New repository variable**.

Use these repository switches only when needed:

| Repository variable | Default / purpose |
|---|---|
| `RELEASE_SIGNING_ENABLED` | Unset/`false`: signing stays off unless manually requested. Set `true` only after credentials/protections are ready, to sign future version-tag builds automatically. |
| `RELEASE_SIGNING_PLATFORMS` | `macos`, `windows` or `all`; defaults to `macos`. Used for automatic tag signing. Manual runs have their own platform selector. Linux stays unsigned. |
| `ENABLE_PRIVATE_ATTESTATIONS` | Unset/`false` for your current private-repository setup. `true` requires a supported Enterprise Cloud plan. |

Do not put private keys or passwords in Variables. Secrets belong in the protected
`release-signing` environment. Do not put Google login credentials in GitHub; users
sign into Google through the application's dedicated Chrome window.

[GitHub: deployment environments and plan availability](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)

## 4. Optional: sign and notarize Mac builds in GitHub

You already have a working local Developer ID identity. You can reuse that identity
for CI; you do not need another Apple Developer account.

### A. Export the signing identity from your Mac

Open **Keychain Access → login → My Certificates**. Find
`Developer ID Application: Sarthak Gupta (75TH5B56SD)`. Expand it to confirm that its
private key is present. Export the identity and private key as a password-protected
**.p12** file. Choose an export password and retain it securely. Exporting only a
`.cer` file is insufficient: a runner needs the matching private key to sign.

If no identity exists, create a **Developer ID Application** certificate through
[Apple Developer → Certificates, Identifiers & Profiles](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/)
on the Mac that generates the private key. An Apple Development or Mac App Store
certificate is a different identity and does not replace this direct-download one.

### B. Obtain notarization API credentials from Apple

Sign into [App Store Connect](https://appstoreconnect.apple.com/) with the appropriate
team. Open **Users and Access → Integrations → App Store Connect API**. Obtain a
**team API key** authorized for notarization, with the least privileged role permitted by
Apple and your team policy. Download its private `.p8` key, and note its **Key ID** and
team **Issuer ID**. Apple permits the private-key download only once. Keep it securely.

This workflow supplies an Issuer ID and expects a team key; individual keys use a
different authentication form. The API key authorizes notarization. It does not replace
the P12 identity used to sign the application.

[Apple: create App Store Connect API keys](https://developer.apple.com/documentation/AppStoreConnectAPI/creating-api-keys-for-app-store-connect-api)

### C. Add these values to `release-signing`

| Name | GitHub type | What to enter / where it comes from |
|---|---|---|
| `MAC_SIGN_IDENTITY` | Environment variable | `Developer ID Application: Sarthak Gupta (75TH5B56SD)`; full matching Keychain identity |
| `MAC_CERTIFICATE_P12_BASE64` | Environment secret | Single-line base64 of the exported P12 file |
| `MAC_CERTIFICATE_PASSWORD` | Environment secret | The password chosen when exporting that P12, not your Apple ID password |
| `APPLE_API_KEY_P8_BASE64` | Environment secret | Single-line base64 of the downloaded App Store Connect `.p8` key |
| `APPLE_API_KEY_ID` | Environment secret | The API key's Key ID from App Store Connect |
| `APPLE_API_ISSUER` | Environment secret | The team Issuer ID (UUID) from App Store Connect, not Apple Team ID `75TH5B56SD` |

To copy one-line base64 directly to your Mac clipboard without printing the key,
replace the quoted filename and run the corresponding command:

```sh
base64 -i '/PRIVATE/PATH/developer-id.p12' | tr -d '\r\n' | pbcopy
```

```sh
base64 -i '/PRIVATE/PATH/AuthKey_YOURKEYID.p8' | tr -d '\r\n' | pbcopy
```

Paste into that secret's value field. Clear the clipboard after each paste:

```sh
pbcopy < /dev/null
```

Clear any clipboard-manager history too. Base64 is an encoding, not encryption. Do not
commit these files, send them in support reports, or paste their contents into a chat.
GitHub cannot recover a secret value for you after saving it; keep your own secure copy.

### D. Run Mac-only signing

After preparing a **new version tag containing the updated workflow**, choose that
tag under Actions → Build desktop packages → Run workflow. Check **sign_release**
and select **macos** under **signing_platform**. Approve the protected environment
when applicable. Both Mac architectures are signed/notarized; Windows and Linux still
build unsigned and do not require Windows signing credentials.

A signing request on a branch is rejected. The tag must match the project's version
and point to a commit reachable from `main`. Once signing is requested for a platform,
missing credentials fail that platform's job; it does not silently downgrade to an
unsigned release. Sign only code you have reviewed.

Do not reuse or move the published v0.2.1 tag to adopt a new workflow. Start unsigned
builds from `main` now, and adopt these signing options in the next version tag.
The existing v0.2.1 DMG was already signed and notarized locally.

## 5. Optional: sign Windows builds

Windows binaries can be built without a certificate. For trusted distribution, this
workflow supports **Azure Artifact Signing** using GitHub OIDC. A locally purchased
certificate is not automatically usable by that cloud service. Confirm provider
eligibility for your country and legal entity before purchasing signing services.

1. In the [Azure portal](https://portal.azure.com/), set up an Artifact Signing account,
   complete identity validation and create a public-trust certificate profile. Follow
   [Microsoft's setup guide](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).
2. Under **Microsoft Entra ID → App registrations**, create an application/service
   principal for this repository's signing workflow. Note its Application (client) ID
   and Directory (tenant) ID. Obtain Subscription ID from the signing resource's
   subscription/overview page.
3. Add a federated credential for GitHub's environment `release-signing`:
   issuer `https://token.actions.githubusercontent.com`,
   subject `repo:SKD-Innovations/google-takeout-restore-gp:environment:release-signing`,
   audience `api://AzureADTokenExchange`.
4. Give that service principal the **Artifact Signing Certificate Profile Signer**
   role scoped to the intended certificate profile. A client secret is not required.
   Follow the [provider's OIDC guide](https://github.com/Azure/artifact-signing-action/blob/main/docs/OIDC.md).
5. Add these **Environment variables** in GitHub's `release-signing` environment:

| Name | Source |
|---|---|
| `AZURE_CLIENT_ID` | Entra application → Application (client) ID |
| `AZURE_TENANT_ID` | Entra application → Directory (tenant) ID |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription containing the signing account |
| `AZURE_SIGNING_ENDPOINT` | Signing account's regional service endpoint |
| `AZURE_SIGNING_ACCOUNT` | Artifact Signing account name |
| `AZURE_CERTIFICATE_PROFILE` | Public-trust certificate profile name |

For a new reviewed version tag, request signing with **signing_platform = windows**, or
**all** after both Apple and Windows credentials are configured. The workflow signs
application executables and the installer. Linux remains unsigned; operating an apt
repository would need separate repository-metadata signing.

## 6. Node.js 24 and workflow maintenance

The desktop engine and interface are Python and embedded HTML/JavaScript. Playwright
also ships a Node executable for its browser driver. The current pinned Playwright
package provides **Node v24.22.1** on the checked local Mac; CI checks that its bundled
Node major version is **24** on every target.

The GitHub workflow actions are separate from that bundled driver. Their pins have
been migrated to versions that declare Node 24: checkout, setup-python, upload-artifact
and Azure login. The provenance wrapper's nested attest action and the Windows signing
action's nested cache action also declare Node 24. The signing action itself runs
PowerShell. Upgrading a system `node` or adding setup-node would not change an action's
own declared JavaScript runtime.

Actions remain pinned to full commit hashes. Future changes should review release
notes, `action.yml` and nested actions, then run source CI and the actual native package
matrix. A runtime upgrade is not a claim that every dependency is vulnerability-free.
