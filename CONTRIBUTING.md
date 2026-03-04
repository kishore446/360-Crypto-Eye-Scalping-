# Contributing to 360 Crypto Eye Scalping

## Development Setup

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd 360-Crypto-Eye-Scalping-
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   .venv\Scripts\activate     # Windows
   ```

3. **Install development dependencies**
   ```bash
   pip install -r requirements-dev.txt
   ```

4. **Copy the environment template**
   ```bash
   cp .env.example .env
   # Edit .env and fill in your TELEGRAM_BOT_TOKEN, etc.
   ```

5. **Run tests**
   ```bash
   pytest tests/ -v
   ```

6. **Lint and type-check**
   ```bash
   ruff check .
   mypy bot/ config.py
   ```

## Code Style

- Line length: 100 characters (configured in `pyproject.toml`)
- Python 3.12+
- Type hints required for all public functions
- Docstrings for all public classes and functions

## Pull Request Process

1. Fork the repo and create a feature branch from `main`
2. Ensure all tests pass: `pytest tests/ -v`
3. Add tests for any new functionality
4. Update `CHANGELOG.md` under `[Unreleased]`
5. Open a pull request with a clear description of changes
