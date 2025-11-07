# Gleitzeit Setup with UV

Gleitzeit requires `uv` for dependency management and environment isolation.

## Installation

### 1. Install UV

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with Homebrew
brew install uv
```

### 2. Setup Project

```bash
# Clone the repository
git clone <repo_url> gleitzeit
cd gleitzeit

# Create virtual environment
uv venv .venv

# Install dependencies
uv sync
```

### 3. Run Gleitzeit

Always use the venv Python or `uv run`:

```bash
# Option 1: Direct venv execution
.venv/bin/python -m gleitzeit.cli.main serve

# Option 2: Through uv run
uv run python -m gleitzeit.cli.main serve
```

## Why UV?

1. **Fast** - 10-100x faster than pip
2. **Deterministic** - Lock file ensures exact dependencies
3. **Isolated** - No PYTHONPATH conflicts
4. **Simple** - Single tool for venv + package management

## Troubleshooting

### "Not running in uv virtual environment!"

This means you're using system Python. Always use:
- `.venv/bin/python` instead of `python`
- `uv run python` for automatic venv activation

### Module Import Errors

Ensure you ran `uv sync` after cloning or pulling changes.

### Port Conflicts

Use `--restart` flag to kill existing processes:
```bash
.venv/bin/python -m gleitzeit.cli.main serve --restart
```

## Development

### Adding Dependencies

```bash
# Add to pyproject.toml
uv add <package>

# Update lock file
uv lock
```

### Updating Dependencies

```bash
# Update all
uv sync --upgrade

# Update specific
uv add <package>@latest
```