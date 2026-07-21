# Threat Model

## Protected assets

- Selected archives and their filenames
- Remembered clues and exact candidate passwords
- Recovered passwords and extracted contents
- Rule-pack signing keys and update metadata

## Trust boundaries

The desktop UI, candidate engine, and native verifiers run locally. External
boundaries are optional extraction tools and the future rule-pack download host.

## Primary threats

- Accidental publication of real password material
- Malicious or corrupted archives exploiting parsers or extractors
- Path traversal and symbolic-link escape during extraction
- Archive bombs exhausting storage or memory
- Malicious rule-pack updates
- Sensitive passwords appearing in logs, crash reports, or saved sessions
- Misrepresentation that recovery is guaranteed

## Required mitigations

- Synthetic-only public fixtures and automated sensitive-string scans
- Bounded parsing with checksum validation and fuzz testing
- Extraction into a new restricted directory with canonical-path checks
- File-count, output-size, and compression-ratio limits
- Signed manifests and checksummed pack payloads
- Redacted logs and opt-in session persistence
- Clear search-space estimates and honest failure results
