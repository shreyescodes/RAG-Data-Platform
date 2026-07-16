# Contributing Guidelines

Thank you for your interest in contributing! This document outlines standard practices for development.

## Development Setup

1. **Install Dev Dependencies:**
   ```bash
   make install
   ```
2. **Setup Pre-commit Hooks:**
   ```bash
   pre-commit install
   ```

## Workflow

1. **Create a branch**: `git checkout -b feature/your-feature-name`
2. **Write tests**: Please ensure you write tests for any new endpoints or logic.
3. **Format & Lint**:
   ```bash
   make format
   make lint
   ```
4. **Run tests**:
   ```bash
   make test
   ```
5. **Commit**: Pre-commit hooks will automatically run `ruff` and whitespace checks.

## Pull Requests

- Describe what your PR accomplishes.
- Ensure GitHub Actions (CI) passes successfully before requesting review.
