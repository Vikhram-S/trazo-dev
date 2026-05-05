# Contributing to Trazo

Thank you for your interest in contributing! Trazo is community-driven and we welcome all contributions.

## Getting Started

### Prerequisites
- Python 3.10+
- Git

### Development Setup

```bash
git clone https://github.com/Vikhram-S/trazo-dev
cd trazo

# Install with all dev dependencies
pip install -e ".[dev,ui]"

# Install pre-commit hooks (runs ruff on every commit)
pre-commit install
```

### Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=trazo --cov-report=term-missing

# Specific file
pytest tests/test_tracer.py -v -k "test_trace_decorator"
```

### Running the Demo

```bash
python examples/openai_chain.py
trazo view
trazo ui
```

---

## How to Contribute

### 🐛 Bug Reports

Open an issue with:
- Python version and OS
- Trazo version (`trazo --version`)
- Minimal reproduction script
- Expected vs actual behavior

### 💡 Feature Requests

Open an issue tagged `enhancement`. Describe:
- The problem you're solving
- Your proposed API/behavior
- Alternatives you considered

### 🔧 Pull Requests

1. Fork the repo and create a branch: `git checkout -b feat/my-feature`
2. Write your code and tests
3. Ensure all checks pass:
   ```bash
   ruff check trazo tests
   ruff format trazo tests
   pytest tests/ -v
   ```
4. Open a PR with a clear description

### Commit Style

Use [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation only
- `test:` adding tests
- `refactor:` code change without feature/fix
- `chore:` build, CI, tooling

---

## Adding an Integration

Trazo supports auto-instrumentation of LLM SDKs via monkey-patching. To add a new integration:

1. Create `trazo/integrations/<provider>_patch.py`
2. Follow the pattern in `trazo/integrations/openai_patch.py`
3. Export from `trazo/integrations/__init__.py`
4. Add a `tz.instrument_<provider>()` function in `trazo/__init__.py`
5. Test manually via a small script in `examples/` (like `openai_chain.py` or `ollama_agent.py`)

Key requirements:
- Must work when the SDK is NOT installed (graceful import failure)
- Must not double-patch (check for `_pw_patched` attribute)
- Must correctly set `tokens_in`, `tokens_out`, `cost_usd`, `model`, `provider`

---

## Architecture Notes

- **`tracer.py`**: Uses `contextvars.ContextVar` for span propagation — this is what makes parent-child linking work across async boundaries. Never use threading.local() for span context.
- **`collector.py`**: The background flush worker means tracing is non-blocking. Don't add synchronous I/O to the hot path.
- **`storage.py`**: All queries go through `_connection()`. Never hold a connection reference across function calls.
- **`differ.py`**: The similarity computation is intentionally simple (n-gram TF) to avoid ML dependencies. The `sentence-transformers` upgrade path is opt-in only.

---

## Code Style

- Type annotations everywhere (`from __future__ import annotations`)
- Pydantic v2 models for all data structures
- No magic numbers — define named constants
- Docstrings on all public functions and classes
- `ruff` for formatting and linting (configured in `pyproject.toml`)

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
