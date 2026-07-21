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
- Downloadable rule packs must be checksummed and signed before installation.
- No release may contain real user passwords, archive hashes, or private files.

ArchiveKey is alpha software. Review recovery and extraction destinations before
using it with irreplaceable data.
