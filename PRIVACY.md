# Privacy

ArchiveKey performs recovery locally. The application does not need to upload an
archive, filename, password clue, generated candidate, or recovered password.

Telemetry is not implemented in the alpha release. Future telemetry, if any,
must be disabled by default and must never contain archive or password data.

Downloaded rule packs are public data. Update requests can reveal the application
version and requested pack identifier to the hosting provider, but never local
archive information. Offline operation remains supported.

Software-update checks are optional. When enabled, ArchiveKey contacts only its
official GitHub releases endpoint at most once every 24 hours and sends its
installed version in the request user agent. Manual checks remain available when
automatic checks are disabled. No archive, path, clue, candidate, recovered
password, device identifier, or telemetry is transmitted.

Users should treat recovery logs and saved sessions as sensitive. Public bug
reports must use synthetic archives and synthetic passwords.
