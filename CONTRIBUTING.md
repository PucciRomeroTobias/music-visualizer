# Contributing

Thanks for helping improve music-graph. Bug fixes, tests, documentation, data-pipeline improvements, and visualization performance work are welcome.

## Before opening a pull request

1. Open an issue first for large behavioral or data-model changes.
2. Do not commit API keys, OAuth tokens, cookies, databases, or exported graph datasets.
3. Keep collection jobs resumable and capped to short batches. See `CLAUDE.md` for the project-specific collector conventions.
4. Preserve the mobile-first performance profile of the visualization.

## Local checks

```bash
uv sync --dev
uv run pytest
uv run ruff check src tests
uv run pip-audit

cd viz
npm ci
npm run build
npm audit

cd ../viz-sigma
npm ci
npm run build
npm audit
```

Pull requests should explain the motivation, describe observable behavior changes, and include screenshots for UI changes.
