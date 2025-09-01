# Development Guide

## Code Formatting & Linting

This project uses [Ruff](https://docs.astral.sh/ruff/) for both linting and formatting to ensure consistent code quality.

### Configuration Files

- **`.ruff.toml`** - Main Ruff configuration (used by IDEs)
- **`pyproject.toml`** - Project configuration including Ruff settings
- **`.vscode/settings.json`** - VS Code specific settings
- **`.editorconfig`** - Universal IDE configuration

### IDE Setup

#### VS Code

1. Install the [Ruff extension](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff)
2. The `.vscode/settings.json` file will automatically configure format-on-save

#### Other IDEs

Most modern IDEs support `.ruff.toml` and `.editorconfig` automatically.

### Code Quality Rules

#### Enabled Rules

- **E/W**: pycodestyle errors and warnings
- **F**: pyflakes (unused imports, variables, etc.)
- **I**: isort (import sorting)
- **N**: PEP 8 naming conventions
- **UP**: pyupgrade (modern Python syntax)
- **RUF**: Ruff-specific rules
- **B**: flake8-bugbear (common bugs)
- **C4**: flake8-comprehensions
- **PIE**: flake8-pie
- **SIM**: flake8-simplify
- **TCH**: flake8-type-checking

#### Ignored Rules

- **RUF006**: Allow fire-and-forget `asyncio.create_task()`
- **E501**: Line length handled by formatter
- **SIM103/105/108**: Prefer explicit code over overly clever shortcuts

### Development Workflow

```bash
# Format code
make fmt

# Lint code
make lint

# Run tests
make test

# Run all quality checks
make precommit
```

### Line Length

- **88 characters** (Black/Ruff standard)
- Configured in both formatter and editor rulers

### Import Sorting

- First-party imports: `bot.*`
- Auto-sorted within sections
- Trailing commas preserved

### Format on Save

Your IDE should automatically:

1. Format code with Ruff
2. Organize imports
3. Fix auto-fixable lint issues
4. Show remaining lint issues inline

This ensures your code always matches the `make lint` requirements.
