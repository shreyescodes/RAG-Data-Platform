# Contributing

## Setup

```bash
make install        # backend dev dependencies, frontend packages, pre-commit hooks
```

See the [README](README.md#local-development) for database and environment
setup.

## Workflow

1. Branch from `main` using a descriptive name such as `feat/sql-cache` or
   `fix/history-pagination`.
2. Make the change with tests. Bug fixes should include a test that fails
   without the fix.
3. Run `make check` (lint, format check, `mypy --strict`, all tests).
4. Commit using [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`). Pre-commit runs
   ruff and eslint on staged files.
5. Open a pull request. CI must pass before review.

## Conventions

**Backend**

- Code is fully type-annotated and must pass `mypy --strict`.
- Use `logging` with `%`-style arguments. `print` is linted out.
- Raise `PlatformError` subclasses for expected failures, and give each a
  `user_message` that is safe to show clients.
- Inject external services (LLM, HTTP, market data) so tests can replace them
  with the fakes in `tests/fakes.py`. Tests must not hit the network.

**Database changes**

1. Edit the models in `app/db/models.py`, including `info={"description": ...}`
   for anything the LLM should understand.
2. Generate a migration with `alembic revision --autogenerate -m "..."`.
3. Review the migration, then apply it with `alembic upgrade head`.
4. Run `alembic check`, which must report no changes.
5. Rebuild the schema index with `python -m app.cli index-schema`.

**Frontend**

- Keep components small and presentational. Data fetching lives in `hooks/`
  and `api/`.
- Never put secrets in `VITE_*` variables; they are compiled into the bundle.

## Releasing

Bump the version in `backend/app/__init__.py`, `backend/pyproject.toml` and
`frontend/package.json`, then tag `vX.Y.Z` on `main`.
