# Pytest Layering Reference

Skill-specific aid for choosing a test layer and verifying. Placement, markers,
naming, fixtures, and async rules live in `tests/CONVENTIONS.md` — defer there
instead of duplicating; `tests/README.md` lists directory standards and commands.

## Layer Selection

- Unit: pure logic, service rules, schema validation, repository query construction with fake or mocked sessions.
- Component: FastAPI routing, dependency overrides, middleware, request parsing, response serialization, or exception-to-HTTP mapping.
- Integration: real PostgreSQL, Redis, S3, TaskIQ broker, migrations, or real external providers.
- Smoke: running environment checks through real HTTP.

Prefer the lowest layer that proves the behavior. See `tests/CONVENTIONS.md`
("放置规则" / "Marker 规则") for where the file goes and which markers it needs.

## Verification

Use focused commands first:

```bash
uv run pytest tests/unit/path/to/test_file.py
uv run pytest tests/component/path/to/test_file.py
make qa-test-unit
```
