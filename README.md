# Microservice Platform

## Overview

An AI-powered document management platform built as a production-grade microservice
architecture covering all phases of a full cloud-native course: single service,
distributed communication, CI/CD, observability, security, and AI integration.

Users register, authenticate via JWT, create and search documents, and receive
automatic notifications through RabbitMQ event streaming. Documents can be
summarised by GPT-3.5-turbo (or an extractive fallback) and searched semantically
via TF-IDF cosine similarity — no external API required for core functionality.

## Architecture

```
                           ┌─────────────────────┐
         Client            │     api-gateway      │  :8080
       ──────────────────► │  JWT · rate-limit    │
                           │  security-headers    │
                           │  circuit-breaker     │
                           └──────────┬───────────┘
              ┌────────────────────────┼──────────────────────┐
              ▼                        ▼                       ▼
   ┌──────────────────┐   ┌───────────────────┐  ┌────────────────────────┐
   │ document-service │   │   auth-service    │  │  notification-service  │
   │  :8001 (public)  │   │   (internal)      │  │      (internal)        │
   │  CRUD + AI + JWT │   │  JWT issue/verify │  │  RabbitMQ consumer     │
   └────────┬─────────┘   └────────┬──────────┘  └──────────┬─────────────┘
            │  publishes            │                         │ subscribes
            │  document.created     └──── PostgreSQL ─────────┘
            │                            (shared host,
            ▼                             3 databases)
        RabbitMQ ─────────────────────────────────────►  notification-service
        :5672 / :15672                                    (consumes & stores)

   ┌────────────┐   ┌─────────────┐   ┌─────────┐
   │ Prometheus │   │   Grafana   │   │  Redis  │
   │   :9090    │   │    :3000    │   │  :6379  │
   └────────────┘   └─────────────┘   └─────────┘
      scrapes all 4 services /metrics    rate-limit + AI cache
```

## Services

| Service              | Port     | Description                                        |
|----------------------|----------|----------------------------------------------------|
| api-gateway          | 8080     | Single entry point — JWT, rate limit, proxy        |
| document-service     | 8001     | CRUD, AI summarize, semantic search                |
| auth-service         | internal | Register, login, JWT issue/refresh                 |
| notification-service | internal | RabbitMQ consumer, stores document events          |
| PostgreSQL           | 5432     | Persistent storage (3 databases)                   |
| RabbitMQ             | 5672     | Async messaging; management UI at :15672           |
| Redis                | 6379     | Rate limiting + AI summary cache (1 h TTL)         |
| Prometheus           | 9090     | Metrics scraping from all services                 |
| Grafana              | 3000     | Dashboards — login admin/admin                     |

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/KhalidM10/microservice-platform.git
cd microservice-platform
cp .env.example .env
# Edit .env — at minimum set a strong SECRET_KEY

# 2. Start all services
docker-compose up --build -d

# 3. Verify gateway health
curl http://localhost:8080/health
# → {"gateway":"healthy","auth-service":"healthy",...}

# 4. Open interactive API docs
#   api-gateway:      http://localhost:8080/docs
#   document-service: http://localhost:8001/docs
```

## Running Tests

```bash
# All services at once (cross-platform script)
bash scripts/run-tests.sh

# Individual service (Windows venv)
cd document-service
DATABASE_URL="sqlite+aiosqlite:///:memory:" SECRET_KEY="test" \
  APP_NAME="document-service" APP_VERSION="1.0.0" \
  RABBITMQ_URL="amqp://guest:guest@localhost" REDIS_URL="redis://localhost" \
  pytest tests/ -v --cov=src --cov-fail-under=80

cd auth-service
DATABASE_URL="sqlite+aiosqlite:///:memory:" SECRET_KEY="test" \
  APP_NAME="auth-service" APP_VERSION="1.0.0" \
  pytest tests/ -v --cov=src --cov-fail-under=80

cd notification-service
DATABASE_URL="sqlite+aiosqlite:///:memory:" SECRET_KEY="test" \
  APP_NAME="notification-service" APP_VERSION="1.0.0" \
  RABBITMQ_URL="amqp://guest:guest@localhost" \
  pytest tests/ -v --cov=src --cov-fail-under=80

cd api-gateway
SECRET_KEY="test" APP_NAME="api-gateway" APP_VERSION="1.0.0" \
  REDIS_URL="redis://localhost" \
  pytest tests/ -v --cov=src --cov-fail-under=80
```

**Coverage summary:** document-service 82% · auth-service 86% · notification-service 83% · api-gateway 82%

## API Documentation

| Service          | Swagger UI                        |
|------------------|-----------------------------------|
| api-gateway      | http://localhost:8080/docs        |
| document-service | http://localhost:8001/docs        |
| auth-service     | via gateway only (internal)       |
| notification-service | via gateway only (internal)   |

## Full API Flow

```bash
# Register
curl -X POST http://localhost:8080/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"Password123","full_name":"Your Name"}'

# Login — capture token
TOKEN=$(curl -s -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"Password123"}' \
  | python3 -c "import sys,json; sys.stdout.write(json.load(sys.stdin)['access_token'])")

# Create document
curl -X POST http://localhost:8080/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"My Doc","content":"Long text here...","tags":["demo"]}'

# AI summarize
curl -X POST http://localhost:8080/api/v1/documents/{id}/summarize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_length":100}'

# Semantic search
curl -X POST http://localhost:8080/api/v1/documents/search/semantic \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"machine learning concepts","limit":5}'

# Notifications (auto-created by RabbitMQ event)
curl http://localhost:8080/api/v1/notifications \
  -H "Authorization: Bearer $TOKEN"
```

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

| Trigger           | Jobs                                               |
|-------------------|----------------------------------------------------|
| push to main/dev  | test (matrix: 4 services) → build+push → deploy   |
| PR to main        | test only                                          |

Required GitHub Secrets: `DOCKER_USERNAME`, `DOCKER_PASSWORD`

Docker Hub images: `{DOCKER_USERNAME}/mindcampus-{service}:{sha}`

## Monitoring

- **Prometheus**: http://localhost:9090 — targets page shows all 4 services green
- **Grafana**: http://localhost:3000 — login `admin/admin`
  - Dashboard **"AI Document Platform"** auto-provisioned on startup
  - Panels: request rate, error rate, P95/P99 latency, service health stats
- All services expose `/metrics` via prometheus-fastapi-instrumentator
- Distributed tracing via OpenTelemetry SDK (TracerProvider on every service)

## AI Features

See [docs/ai-features.md](docs/ai-features.md) for full documentation.

| Feature | Endpoint | Model |
|---|---|---|
| Summarization | `POST /documents/{id}/summarize` | GPT-3.5-turbo / extractive fallback |
| Semantic search | `POST /documents/search/semantic` | TF-IDF cosine similarity |

## Security

See [security-design-report.md](security-design-report.md) for the full report.

- JWT (HS256): access 30 min · refresh 7 days
- bcrypt password hashing
- Rate limiting: 10/100/1000 req/min (guest/user/admin) via Redis
- Security headers: HSTS, CSP, X-Frame-Options, X-XSS-Protection
- Circuit breaker: tenacity 3× retry → 503
- OWASP Top 10 checklist in the report

See [reliability-report.md](reliability-report.md) for failure modes and runbooks.

## Environment Variables

| Variable                    | Service          | Description                          |
|-----------------------------|------------------|--------------------------------------|
| `SECRET_KEY`                | all              | JWT signing key (keep secret!)       |
| `DOCUMENT_DATABASE_URL`     | document-service | PostgreSQL connection string         |
| `AUTH_DATABASE_URL`         | auth-service     | PostgreSQL connection string         |
| `NOTIFICATION_DATABASE_URL` | notification     | PostgreSQL connection string         |
| `RABBITMQ_URL`              | doc + notif      | amqp://user:pass@host:5672/          |
| `REDIS_URL`                 | gateway + doc    | redis://host:6379                    |
| `OPENAI_API_KEY`            | document-service | Optional — falls back if not set     |
| `POSTGRES_USER`             | postgres         | DB superuser                         |
| `POSTGRES_PASSWORD`         | postgres         | DB superuser password                |
| `POSTGRES_DB`               | postgres         | Initial database name                |
| `GF_SECURITY_ADMIN_PASSWORD`| grafana          | Grafana admin password               |

## Deployment (Kubernetes)

```bash
# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Apply ConfigMap
kubectl apply -f k8s/configmap.yaml

# 3. Create secrets (edit k8s/secrets.yaml with base64 values first)
#    echo -n 'value' | base64
kubectl apply -f k8s/secrets.yaml

# 4. Deploy infrastructure (postgres, rabbitmq)
kubectl apply -f k8s/postgres/
kubectl apply -f k8s/rabbitmq/

# 5. Deploy all services
kubectl apply -f k8s/document-service/
kubectl apply -f k8s/auth-service/
kubectl apply -f k8s/notification-service/
kubectl apply -f k8s/api-gateway/

# 6. Check status
kubectl get pods -n microservice-platform
kubectl get svc -n microservice-platform

# 7. Access (add mindcampus.local → cluster IP in /etc/hosts)
curl http://mindcampus.local/health
```

HPA on document-service auto-scales 2→10 replicas at 70% CPU.
