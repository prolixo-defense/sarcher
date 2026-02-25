# Sarcher — B2B Networking Engine

A full-stack B2B lead extraction, enrichment, and outreach automation system built in four phases. Extracts contacts from corporate websites, LinkedIn, and business directories; enriches them via Apollo.io and Hunter.io; and runs multi-step outreach campaigns with AI-assisted reply handling and GDPR compliance built in.

---

## Features

### Phase 1 — Lead Infrastructure
- Lead ingestion with deduplication and confidence scoring
- SQLite database (PostgreSQL-swappable via `DATABASE_URL`)
- Alembic migrations, auto-run on API startup
- FastAPI REST API with OpenAPI docs
- Celery + Redis task queue (sync fallback when Redis unavailable)

### Phase 2 — Scraping Engine
- TLS fingerprint rotation via `curl_cffi` (browser TLS profiles + UA rotation)
- Playwright browser automation with stealth mode
- Human behavior simulation: mouse movements, typing cadence, scroll patterns
- Proxy rotation with sticky sessions and cooldown
- Adapters: corporate team pages, LinkedIn profiles, business directories

### Phase 3 — LLM Extraction & Enrichment
- HTML → Markdown preprocessing pipeline (trafilatura → BeautifulSoup → markdownify → tiktoken)
- Structured LLM extraction via `litellm` + `instructor` (OpenAI, Anthropic, local models)
- Apollo.io and Hunter.io enrichment with waterfall fallback
- Monthly credit budget enforcement per provider
- Async batch enrichment with concurrency control

### Phase 4 — Outreach Automation
- Multi-step email sequences with configurable delays and conditions
- Jinja2 templates with YAML frontmatter (6 built-in templates)
- LinkedIn connection/message automation via Playwright
- AI reply pipeline: sentiment classification → objection handling → draft generation
- RAG store (ChromaDB + sentence-transformers) seeded from local knowledge base
- All AI-generated responses saved as `DRAFT` — human approval required before sending
- GDPR compliance: suppression list, opt-out processing, DSAR export/delete
- `robots.txt` compliance checking with 24h cache
- DAG-based workflow orchestration with topological sort, parallel execution, and retry
- APScheduler with SQLite job store for persistent cron jobs

---

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Install Playwright browser
playwright install chromium

# Copy and edit environment config
cp .env.example .env

# Apply database migrations
alembic upgrade head

# Start the API
uvicorn src.api.app:app --reload

# Open interactive docs
open http://localhost:8000/docs
```

---

## CLI

```bash
# Scraping
python3 -m cli.main scrape example.com --source-type website --sync

# Lead management
python3 -m cli.main search "John"
python3 -m cli.main stats
python3 -m cli.main export --format csv --output leads.csv

# Campaigns
python3 -m cli.main campaign-create "Q1 Outreach" --template initial_outreach
python3 -m cli.main campaign-start <campaign-id>

# Review and approve AI drafts
python3 -m cli.main drafts
python3 -m cli.main approve <draft-id>

# Compliance
python3 -m cli.main opt-out user@example.com
python3 -m cli.main dsar-export user@example.com

# Orchestration
python3 -m cli.main run-pipeline
python3 -m cli.main dashboard

# Seed RAG knowledge base
python3 -m cli.main seed-knowledge ./data/knowledge_base/
```

---

## Project Structure

```
src/
  domain/               # Pure Python entities, enums, repository interfaces
  application/
    use_cases/          # IngestLead, CreateCampaign, SendOutreach, HandleResponse, ProcessOptOut
    schemas/            # Pydantic DTOs for all operations
    services/           # Deduplication, etc.
  infrastructure/
    database/           # SQLAlchemy models, migrations, repositories
    scrapers/           # HTTP scraper, browser scraper, adapters, humanization
    fingerprint/        # TLS profile + user-agent rotation
    proxy/              # Proxy pool management
    llm/                # LLM client, extraction engine, prompt templates
    enrichment/         # Apollo, Hunter, credit manager, enrichment pipeline
    outreach/           # EmailSender, TemplateEngine, LinkedInOutreach, SequenceManager
    ai_agents/          # SentimentAnalyzer, RAGStore, ObjectionHandler, SDRAgent
    compliance/         # GDPRManager, RobotsChecker, ToSChecker
    orchestration/      # DAGRunner, WorkflowScheduler, workflow definitions
    config/             # Settings (pydantic-settings)
    task_queue/         # Celery tasks
  api/
    routes/             # leads, tasks, campaigns, compliance, workflows, dashboard
cli/                    # Typer CLI (main.py)
tests/
  unit/                 # 200+ unit tests
  integration/          # Integration tests with in-memory SQLite
alembic/                # DB migrations (4 versions)
data/
  templates/            # Jinja2 email/LinkedIn templates with YAML frontmatter
  knowledge_base/       # RAG source documents (objections, value props, case studies)
```

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy DB URL | `sqlite:///./data/networking.db` |
| `REDIS_URL` | Celery broker URL | `redis://localhost:6379/0` |
| `OPENAI_API_KEY` | LLM provider key | — |
| `ANTHROPIC_API_KEY` | Alternative LLM key | — |
| `APOLLO_API_KEY` | Apollo.io enrichment | — |
| `HUNTER_API_KEY` | Hunter.io enrichment | — |
| `SMTP_HOST` | Outbound SMTP host | — |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USER` | SMTP username | — |
| `SMTP_PASSWORD` | SMTP password | — |
| `SMTP_FROM_EMAIL` | From address | — |
| `RESPECT_ROBOTS_TXT` | Honour robots.txt | `true` |
| `MONTHLY_APOLLO_CREDIT_LIMIT` | Apollo monthly cap | `1000` |
| `MONTHLY_HUNTER_CREDIT_LIMIT` | Hunter monthly cap | `500` |

---

## Running Tests

```bash
pytest                    # all tests
pytest tests/unit/        # unit tests only
pytest tests/integration/ # integration tests only
pytest -v --tb=short      # verbose with short tracebacks
```

247 tests, 1 skipped (macOS Python 3.14 SSL cert path — not a code defect).

---

## Architecture

Clean Architecture with strict layer separation:

```
domain → application → infrastructure → api/cli
```

- **Domain** has zero external dependencies
- **Application** depends only on domain interfaces
- **Infrastructure** implements interfaces with real I/O
- **API/CLI** composes use cases and calls them

All AI-generated outreach content is saved as `DRAFT` status and requires explicit human approval before being sent. No message is ever sent automatically without a human in the loop.
