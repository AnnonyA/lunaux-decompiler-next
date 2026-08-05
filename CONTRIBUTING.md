# Contributing

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check .
mypy
```

## Pull requests

- Keep transport, service, and backend responsibilities separate.
- Add tests for every bug fix.
- Do not commit proprietary or unlicensed native binaries.
- Avoid output-only heuristics without a regression fixture.
- Document externally visible API or CLI changes.

## Test fixtures

Only submit bytecode you are allowed to redistribute. Prefer tiny programs written specifically for the test suite. Record the compiler version and source used to produce each fixture.

## Commit style

Use clear imperative subjects, for example:

```text
Fix Base64 detection for padded input
Add backend capability endpoint
Reject truncated prototype constants
```
