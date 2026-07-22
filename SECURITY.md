# Security Policy

ArchiveKey is intended only for recovering archives that the operator owns or
is explicitly authorized to access.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability that could expose archive
contents, passwords, local files, or update-signing material. Use GitHub's
private security-advisory feature for the repository. Include the affected
version, reproduction steps, impact, and any proposed mitigation.

## Security principles

- Archive contents, password clues, and recovered passwords stay local.
- Recovered passwords are not written to logs by default.
- The original archive is never modified.
- Extraction is performed only after independent password verification.
- Downloaded data packs must be plain text, size-bounded, and schema-validated;
  any executable update content must be cryptographically signed.
- Automatic installers must match GitHub's SHA-256 digest and a detached Ed25519
  signature pinned in the application. Unsigned releases may be announced but
  must never be installed automatically.
- No release may contain real user passwords, archive hashes, or private files.

The Ed25519 private update key is never committed. The repository stores only
the public verification key. GitHub Actions receives the private key through the
`ARCHIVEKEY_UPDATE_SIGNING_KEY_B64` repository secret. The maintainer's recovery
copy is protected by Windows DPAPI outside the repository.

ArchiveKey is alpha software. Review recovery and extraction destinations before
using it with irreplaceable data.
