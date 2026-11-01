# Engineering review of the original pipeline

The original script is preserved in `legacy-pipeline.py.txt` with its personal path
redacted. The desktop application replaces its execution path rather than layering
a UI over unsafe assumptions.

| Original issue | Replacement |
|---|---|
| Absolute personal source path and fixed folder names | Native folder picker and per-user persisted configuration |
| Filename + size treated as identical content | Streaming SHA-256 by default; weaker rule is explicit |
| Entire source signatures/records accumulated in memory | SQLite indexes and per-file scan commits |
| Fuzzy common-prefix JSON selection could choose wrong metadata | Exact known naming patterns or unique exact title; ambiguity stops the item |
| `executor.map` results ignored, allowing failed metadata jobs to upload | Metadata subprocess result and requested tag read-back checked before submission |
| UTC dates without explicit original-time offsets | UTC source timestamp plus EXIF offsets, XMP dates and QuickTime UTC handling |
| Negative altitude could get wrong reference | Numeric ExifTool altitude-reference assignment and negative-altitude regression test |
| Shared scratch filenames could collide | Per-item temporary staging directory |
| Copying before protected error handling | Staging included in durable state/error handling with disk/identity checks |
| Source could change after indexing | Size/mtime and full content hash rechecked during staging |
| “No items uploaded” accepted as done | Explicit unknown/rejected outcomes, never success |
| Batch completion could mark unconfirmed members completed | One submission and evidence record per item |
| Network idleness counted generic batchexecute requests | No success inferred from generic network activity |
| Timed-out submissions immediately retried | Commit submission boundary; unknown outcome requires manual reconciliation |
| Retry-exhausted records remained PENDING | Pre-submission network retries use bounded backoff; exhausted items become failed |
| Entire scratch tree removed at startup regardless of active instance | Application file lock; profile-scoped recovery and cleanup |
| Chrome debug server exposed on TCP 9222 | Temporary loopback CDP port, dedicated non-default Chrome profile, automatic process ownership/cleanup |
| No authenticated application boundary | Password-protected local accounts, roles and token-checked dispatcher |
| Console-only failure output | Stable error catalogue, run history, structured logs and redacted diagnostics |

## Validation evidence

The automated suite exercises account isolation, password wrapping/reset, login
throttling, sidecar matching and ambiguity, duplicate metadata conflict, edited rules,
source changes, symlinks, storage failures, submission crash recovery, bounded retries,
false/stale browser confirmations, ZIP traversal/symlinks, CSV formula escaping and
redacted diagnostics. Real ExifTool round trips cover JPEG, PNG and TIFF with UTC dates,
Unicode descriptions and below-sea-level coordinates.

The UI smoke test uses the actual service with disposable accounts. The native macOS
smoke test additionally verifies that WebKit can call the real pywebview bridge under
the shipped CSP. Neither test contacts Google. Live-service correctness requires a
separate controlled integration test; selectors and login acceptance cannot be proven
by unit tests or by a successful binary build.

## Open production work

- Implement and live-validate cloud album creation, favorites/archive changes and
  native paired-photo restoration, or retain their explicit manual-review behavior.
- Live-test Google login and upload evidence across accounts, languages and UI variants.
- Validate every claimed OS/architecture package, installer, browser download and minimum OS.
- Test a representative large export corpus, very large videos, unsupported/corrupt media,
  power loss, source-drive disconnect, disk exhaustion and Google storage exhaustion.
- Lock and audit transitive dependencies; review runtime licenses/SBOM and signing provenance.
- Complete independent security review and accessibility testing; add localization and a
  maintained support/update channel before a public stable release.

These are release gates, not claims that the current preview has already met them.
