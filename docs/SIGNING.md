# Secure signing automation

The workflow builds unsigned preview packages through `workflow_dispatch` and signs
version-tag builds through a separate protected GitHub Environment. Signing credentials
are not included in this codebase or in end-user applications.

## GitHub setup

1. Push the codebase to your chosen GitHub repository, with `main` as its protected branch.
2. Protect `main`, the `v*` tag namespace, `.github/workflows/**`, packaging scripts and
   dependency locks. Require independent review of signing/build changes.
3. Create `release-signing` with required reviewers and restrict allowed deployment
   tags. Create `unsigned-build` without secrets. Restrict who can create release tags.
4. Put secrets only in `release-signing`. Pin/review action updates rather than following
   moving action tags. Repository administrators remain trusted.
5. Run unsigned builds and validate the actual packages before tagging. A version tag
   must point to a commit reachable from `origin/main`; the workflow checks this.
6. Review the release-signing approval, then download and verify artifacts/provenance.
   Publishing a GitHub release is deliberately a separate maintainer action.

## Apple Developer ID

Use **Developer ID Application**, not an iOS development or Mac App Store certificate.
Export the certificate and private key as a password-protected `.p12` using Keychain
Access. Do not commit it or paste it into logs. Store its base64 encoding and password
in the environment secrets below. Create an App Store Connect API key with the least
privilege accepted by Apple's notarization service; use its `.p8`, key ID and issuer.

| Name | Type |
|---|---|
| `MAC_SIGN_IDENTITY` (full `Developer ID Application: ... (TEAMID)` identity) | Environment variable |
| `MAC_CERTIFICATE_P12_BASE64` | Secret |
| `MAC_CERTIFICATE_PASSWORD` | Secret |
| `APPLE_API_KEY_P8_BASE64` | Secret |
| `APPLE_API_KEY_ID` | Secret |
| `APPLE_API_ISSUER` | Secret |

The runner imports the certificate into an ephemeral keychain. PyInstaller signs nested
Mach-O components and the app with hardened runtime; `codesign --verify --deep --strict`
checks the result. The notarization script uses `notarytool` with the API key, requires
an `Accepted` response, staples the ticket and validates it. Temporary key material is
removed even when a later step fails. Avoid shell tracing and untrusted self-hosted runners.

The DMG is the primary notarized distribution. The portable ZIP contains the signed
app; validate Gatekeeper behavior separately and staple the app before repackaging
if you distribute it as a primary offline installation method.

Apple documentation: https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution

## Windows: cloud HSM signing

The provided workflow uses Azure Artifact Signing (the action's historical repository
name remains `trusted-signing-action`). Complete provider eligibility/identity checks
before purchasing another certificate; cloud signing and a separately purchased token
certificate are different provisioning routes.

Create a Microsoft Entra application/federated credential scoped to
`repo:OWNER/REPO:environment:release-signing`, and grant only the signer role for the
chosen certificate profile. Do not use a long-lived Azure client secret. Configure:

| Environment variable | Value |
|---|---|
| `AZURE_CLIENT_ID` | Federated application client ID |
| `AZURE_TENANT_ID` | Tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Subscription ID |
| `AZURE_SIGNING_ENDPOINT` | Provider region endpoint |
| `AZURE_SIGNING_ACCOUNT` | Signing account name |
| `AZURE_CERTIFICATE_PROFILE` | Public-trust certificate profile |

The workflow authenticates with GitHub OIDC, signs executable files before packaging,
then signs the installer. Configure artifact signing access to reject unrelated
repositories/environments. Timestamping is handled by the provider action. If you
choose DigiCert KeyLocker or SignPath, replace both signing steps with that provider's
HSM-backed workflow and keep the same approval/tag boundaries. Do not export a private
key from hardware or place a newly issued hardware-bound signing key into GitHub secrets.

Microsoft documentation: https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-signing-integrations

## Linux and provenance

The workflow generates GitHub/Sigstore build-provenance attestations with OIDC for
version-tag artifacts and creates SHA256SUMS after signing/notarization. This is
keyless artifact attestation, not a distribution-repository `.deb` signature. If you
operate an apt repository, sign its Release metadata with a separately managed
repository signing key. Do not confuse checksums alone with authentication.

GitHub documentation: https://docs.github.com/en/actions/concepts/security/artifact-attestations
