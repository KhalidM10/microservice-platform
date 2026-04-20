# Microservice Platform

## Overview

An AI-powered document management platform built as a production-grade microservice architecture. The platform enables users to create, search, and intelligently summarize documents using OpenAI GPT-3.5-turbo with an extractive fallback — no API key required to run.

The system uses asynchronous communication via RabbitMQ so that document creation events automatically trigger notifications. A unified API gateway handles JWT authentication, rate limiting, and circuit-breaking for all downstream services.

## Architecture

```
                           ┌─────────────────┐
                           │   api-gateway   │ :8080
                           │  (JWT · rate    │
                           │  limit · proxy) │
                           └────────┬────────┘
                ┌───────────────────┼───────────────────┐
                ▼                   ▼                   ▼
       ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐
       │ document-service│  │  auth-service  │  │notification-service│
       │  :8001 (public) │  │  (internal)    │  │   (internal)       │
       └────────┬────────┘  └───────┬────────┘  └────────┬───────────┘
                │                   │                     │
                └──── RabbitMQ ─────┘              subscribe
                │    document.created queue              │
                ▼                                       ▼
          ┌──────────┐                           ┌──────────┐
          │PostgreSQL│                           │PostgreSQL│
          │ :5432    │                           │(same host│
          └──────────┘                           │ diff db) │
                                                 └──────────┘
      ┌───────────┐  ┌──────────┐
      │Prometheus │  │ Grafana  │
      │   :9090   │  │  :3000   │
      └───────────┘  └──────────┘
```

## Services

| Service              | Port   | Description                                              |
|----------------------|--------|----------------------------------------------------------|
| api-gateway          | 8080   | Single entry point, JWT auth, rate limiting, proxy       |
| document-service     | 8001   | CRUD + AI summarize + semantic search                    |
| auth-service         | internal | Register, login, JWT issue/refresh                    |
| notification-service | internal | RabbitMQ consumer, stores document events              |
| PostgreSQL           | 5432   | Persistent storage for all services                      |
| RabbitMQ             | 5672   | Async messaging; management UI at 15672                  |
| Redis                | 6379   | Rate limiting + AI summary cache                         |
| Prometheus           | 9090   | Metrics scraping from all services                       |
| Grafana              | 3000   | Dashboards; default login: admin/admin                   |

## Quick Start

```bash
# 1. Clone and configure
git clone <repo-url>
cd microservice-platform
cp .env.example .env
# Edit .env — at minimum set a strong SECRET_KEY

# 2. Start all services
docker-compose up --build -d

# 3. Verify
curl http://localhost:8080/health
# → {"gateway":"healthy","auth-service":"healthy",...}

# 4. Open API docs
# document-service: http://localhost:8001/docs
# api-gateway:      http://localhost:8080/docs
```

## Running Tests

Each service has its own virtualenv. Activate it or use the path directly.

```bash
# document-service (82% coverage)
cd document-service
DATABASE_URL="sqlite+aiosqlite:///:memory:" SECRET_KEY="test" \
  APP_NAME="document-service" APP_VERSION="1.0.0" \
  RABBITMQ_URL="amqp://guest:guest@localhost" REDIS_URL="redis://localhost" \
  pytest tests/ -v --cov=src --cov-fail-under=80

# auth-service (86% coverage)
cd auth-service
DATABASE_URL="sqlite+aiosqlite:///:memory:" SECRET_KEY="test" \
  APP_NAME="auth-service" APP_VERSION="1.0.0" \
  pytest tests/ -v --cov=src --cov-fail-under=80

# notification-service (83% coverage)
cd notification-service
DATABASE_URL="sqlite+aiosqlite:///:memory:" SECRET_KEY="test" \
  APP_NAME="notification-service" APP_VERSION="1.0.0" \
  RABBITMQ_URL="amqp://guest:guest@localhost" \
  pytest tests/ -v --cov=src --cov-fail-under=80

# api-gateway (82% coverage)
cd api-gateway
SECRET_KEY="test" APP_NAME="api-gateway" APP_VERSION="1.0.0" \
  REDIS_URL="redis://localhost" \
  pytest tests/ -v --cov=src --cov-fail-under=80
```

## API Documentation

| Service          | Swagger UI                          |
|------------------|-------------------------------------|
| api-gateway      | http://localhost:8080/docs          |
| document-service | http://localhost:8001/docs          |
| auth-service     | (internal — use via gateway)        |
| notification-service | (internal — use via gateway)    |

## CLI

```bash
pip install typer httpx rich

python cli.py login --email you@example.com
python cli.py create-doc --title "My Doc" --content "Hello world"
python cli.py list-docs --limit 20
python cli.py get-doc --id <uuid>
python cli.py summarize --id <uuid> --max-length 100
python cli.py search --query "machine learning"
python cli.py search --query "neural networks" --semantic
python cli.py logout
```

## CI/CD

GitHub Actions (`.github/workflows/ci-cd.yml`):

| Trigger           | Jobs                                          |
|-------------------|-----------------------------------------------|
| push to main/dev  | test (matrix: 4 services) → build+push → deploy |
| PR to main        | test only                                     |

Required GitHub Secrets: `DOCKER_USERNAME`, `DOCKER_PASSWORD`

## Monitoring

- **Prometheus**: http://localhost:9090 — targets page shows all 4 services
- **Grafana**: http://localhost:3000 — default login `admin/admin`; Prometheus datasource pre-configured
- **Metrics**: All services expose `/metrics` (prometheus-fastapi-instrumentator)

## AI Features

### Summarization
```bash
POST /api/v1/documents/{id}/summarize
{"max_length": 150}
```
- Uses GPT-3.5-turbo if `OPENAI_API_KEY` is set
- Falls back to extractive (first 3 sentences) if no key
- Results cached in Redis for 1 hour

### Semantic Search
```bash
POST /api/v1/documents/search/semantic
{"query": "machine learning concepts", "limit": 10}
```
Uses TF-IDF cosine similarity — no external API needed.

## Security

See [security-design-report.md](security-design-report.md) for the full security analysis including OWASP Top 10 checklist.

## Environment Variables

| Variable                  | Service          | Description                             |
|---------------------------|------------------|-----------------------------------------|
| `SECRET_KEY`              | all              | JWT signing key (keep secret!)          |
| `DOCUMENT_DATABASE_URL`   | document-service | PostgreSQL connection string            |
| `AUTH_DATABASE_URL`       | auth-service     | PostgreSQL connection string            |
| `NOTIFICATION_DATABASE_URL` | notification   | PostgreSQL connection string            |
| `RABBITMQ_URL`            | doc + notif      | amqp://user:pass@host:5672/             |
| `REDIS_URL`               | gateway + doc    | redis://host:6379                       |
| `OPENAI_API_KEY`          | document-service | Optional — falls back if not set        |
| `POSTGRES_USER`           | postgres         | DB superuser                            |
| `POSTGRES_PASSWORD`       | postgres         | DB superuser password                   |
| `POSTGRES_DB`             | postgres         | Initial database name                   |
| `GF_SECURITY_ADMIN_PASSWORD` | grafana       | Grafana admin password                  |

## Deployment (Kubernetes)

```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Create secrets (edit k8s/secrets.yaml with base64-encoded values first)
kubectl apply -f k8s/secrets.yaml

# Deploy all services
kubectl apply -f k8s/

# Check status
kubectl get pods -n microservice-platform
kubectl get svc -n microservice-platform

# Access via ingress (after adding mindcampus.local to /etc/hosts)
curl http://mindcampus.local/health
```

## Reliability

See [reliability-report.md](reliability-report.md) for failure modes, circuit breaker behavior, and runbooks.
