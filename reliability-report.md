# Reliability Report

## SLO Targets

| Metric     | Target  |
|------------|---------|
| Uptime     | 99.9%   |
| P95 Latency| < 500ms |
| P99 Latency| < 1s    |
| Error Rate | < 0.1%  |

## Failure Modes and Mitigations

### 1. Database (PostgreSQL) Failure

**What fails**: document-service, auth-service, notification-service cannot read/write data.

**How handled**:
- SQLAlchemy `pool_pre_ping=True` detects stale connections before use
- `get_db()` dependency uses try/except/rollback — no partial writes
- On connection error: service returns HTTP 503 (not 500)
- docker-compose `depends_on: condition: service_healthy` prevents startup before DB is ready

**Recovery procedure**:
```bash
docker-compose restart postgres
# Wait for healthcheck to pass
docker-compose ps  # verify postgres is healthy
# Services auto-reconnect via pool_pre_ping
```

### 2. RabbitMQ Failure

**What fails**: document-service cannot publish events; notification-service cannot consume events.

**How handled**:
- Publishing is wrapped in `try/except` — if RabbitMQ is down, a warning is logged but the HTTP 201 is still returned to the client
- Consumer (`notification-service`) logs a warning on startup if RabbitMQ is unavailable; the HTTP API continues to work
- `aio_pika.connect_robust()` automatically reconnects when RabbitMQ recovers

**Recovery procedure**:
```bash
docker-compose restart rabbitmq
# notification-service will automatically reconnect via connect_robust
# Any events published while RabbitMQ was down are lost (not replicated)
# Future: use persistent queues + publisher confirms for guaranteed delivery
```

### 3. Downstream Service Failure (api-gateway)

**What fails**: api-gateway cannot reach document-service, auth-service, or notification-service.

**How handled**:
- `tenacity` retry decorator: 3 attempts with exponential backoff (1s, 2s, 4s max 10s)
- If all retries exhausted: returns HTTP 503 `{"error": "service temporarily unavailable", "service": "..."}`
- `/health` aggregates downstream health — returns "unhealthy" for degraded services without crashing

**Recovery procedure**:
```bash
docker-compose start document-service  # restart the failed service
# api-gateway will route successfully on next request
```

### 4. Redis Failure

**What fails**: Rate limiting stops working; AI summaries lose cache.

**How handled**:
- Rate limit middleware catches Redis exceptions and falls through (no rate limiting applied)
- AI service summary caching silently skips on Redis error
- Service continues to function without Redis — just without caching/rate limiting

**Recovery procedure**:
```bash
docker-compose restart redis
# Rate limiting and caching automatically resume
```

### 5. OpenAI API Failure

**What fails**: AI summarization via GPT-3.5-turbo fails.

**How handled**:
- `try/except` around OpenAI call — falls back to extractive summarization
- Response always includes `model_used` field indicating which path was taken
- No dependency on external API for core functionality

## Recovery Runbook

### Complete Platform Restart
```bash
docker-compose down
docker-compose up -d
# Wait for health checks
docker-compose ps  # all should show "healthy"
curl http://localhost:8001/health  # document-service
curl http://localhost:8080/health  # api-gateway (aggregated)
```

### Individual Service Restart
```bash
docker-compose restart <service-name>
# Options: document-service, auth-service, notification-service, api-gateway
```

### Check Service Logs
```bash
docker-compose logs -f document-service
docker-compose logs -f --tail=100 api-gateway
```

### Database Recovery
```bash
# View postgres logs
docker-compose logs postgres

# Connect to database directly
docker-compose exec postgres psql -U postgres -d documents

# Check tables
\dt
SELECT count(*) FROM documents;
```

### Monitor in Production
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)
- RabbitMQ UI: http://localhost:15672 (admin/password)

## Architecture Resilience

```
                    [api-gateway] ─── retry(3x) ──→ [document-service]
                         │                               │
                         │                               ↓
                    [Redis]                         [PostgreSQL]
                    rate limit                      pool_pre_ping
                    caching                         
                         │
                    [RabbitMQ] ─── connect_robust ──→ [notification-service]
                    durable queue
```

Each layer of the platform has an independent failure mode with a graceful degradation path.
