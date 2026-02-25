# Networking Engine

A B2B networking extraction engine — Phase 1: Foundational Infrastructure.

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Copy env
cp .env.example .env

# Run migrations
alembic upgrade head

# Start API
uvicorn src.api.app:app --reload

# Open docs
open http://localhost:8000/docs
```

## CLI

```bash
networking-engine search "John"
networking-engine stats
networking-engine export --format csv --output leads.csv
networking-engine cleanup
```

## Run Tests

```bash
pytest
```

## Project Structure

```
src/
  domain/       # Pure Python entities, value objects, interfaces
  application/  # Use cases and DTOs
  infrastructure/ # DB, HTTP, Celery, config
  api/          # FastAPI routes
cli/            # Typer CLI
tests/          # Unit + integration tests
alembic/        # DB migrations
```
