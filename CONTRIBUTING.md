# Contributing

Contributions are welcome when they improve authorized, local password recovery.

## Ground rules

- Use only synthetic passwords and synthetic encrypted fixtures in commits.
- Do not submit real user archives, salts, hashes, clues, or recovered passwords.
- Do not add lists obtained from breaches or sources without redistribution rights.
- Preserve local-only operation and explicit authorization confirmation.
- Add tests for candidate rules, parsers, and security-sensitive extraction changes.

## Development

```powershell
python -m unittest discover -s tests -v
python -m compileall -q archivekey app.py
```

Open a focused pull request describing the user impact, design choice, tests, and
any security or privacy considerations.
