# Production Hardening

## Overview

The production configuration is a Docker Compose **override file** layered on top of the base `docker-compose.yml`:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The override adds resource limits, removes exposed infrastructure ports, disables debug mode, enables multi-worker uvicorn, and forces all secrets to be supplied explicitly (no insecure defaults).

---

## Hardening checklist

| Area | What changed |
|---|---|
| **Non-root containers** | All Python services run as `appuser` (UID non-root) |
| **Debug mode off** | `DEBUG=false` on every service |
| **Multi-worker uvicorn** | `--workers 2` on all Python services |
| **No access logs in prod** | `--no-access-log` (structured JSON logs only) |
| **Infrastructure ports closed** | Postgres, Redis, RabbitMQ ports not bound to host |
| **Grafana admin exposed** | RabbitMQ management (15672) also closed |
| **Redis password** | `requirepass` set, all services use `redis://:$PASS@redis` |
| **Resource limits** | Memory + CPU caps on every container |
| **Log rotation** | `json-file` driver, 10 MB × 3 files per service |
| **Secrets without defaults** | `POSTGRES_PASSWORD`, `SECRET_KEY`, etc. have no fallback |
| **Hardened nginx** | `server_tokens off`, security headers, gzip, cache-control |
| **Nginx health probe** | `/healthz` for k8s/load-balancer liveness checks |

---

## Setup

### 1. Create your `.env` file

```bash
cp .env.production.example .env
# Edit every value — especially:
#   POSTGRES_PASSWORD, SECRET_KEY, RABBITMQ_DEFAULT_PASS,
#   REDIS_PASSWORD, GF_SECURITY_ADMIN_PASSWORD
```

Generate a strong `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Start the production stack

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 3. Smoke test

```bash
curl http://localhost:8080/health
# → {"gateway":"healthy","auth-service":"healthy",...}
```

---

## Resource limits (per container)

| Service | Memory | CPU |
|---|---|---|
| postgres | 512 MB | 0.50 |
| rabbitmq | 256 MB | 0.25 |
| redis | 160 MB | 0.25 |
| document-service | 512 MB | 0.50 |
| auth-service | 256 MB | 0.25 |
| notification-service | 256 MB | 0.25 |
| api-gateway | 256 MB | 0.50 |
| frontend (nginx) | 64 MB | 0.10 |
| prometheus | 512 MB | 0.50 |
| grafana | 256 MB | 0.25 |

Adjust `deploy.resources.limits` in `docker-compose.prod.yml` to match your host.

---

## Non-root Dockerfiles

All four Python service Dockerfiles now:

1. Build pip packages in a builder stage (unchanged)
2. Create a dedicated system user `appuser:appgroup` in the runtime stage
3. Copy built packages into `/home/appuser/.local`
4. Set `USER appuser` before `CMD`

```dockerfile
RUN groupadd -r appgroup && useradd -r -g appgroup -m appuser
...
COPY --from=builder /root/.local /home/appuser/.local
RUN chown -R appuser:appgroup /app
USER appuser
```

---

## Hardened nginx (`frontend/nginx.conf`)

Key directives:

```nginx
server_tokens off;                  # hide nginx version
gzip on;                            # compress text/css/js
expires 1y; add_header Cache-Control "public, immutable";  # static assets
add_header X-Frame-Options "SAMEORIGIN";
add_header X-Content-Type-Options "nosniff";
add_header X-XSS-Protection "1; mode=block";
add_header Referrer-Policy "strict-origin-when-cross-origin";
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()";
```

HTML responses get `Cache-Control: no-cache` so the SPA shell is always fresh.

---

## What is NOT included (next steps for a real deployment)

- **TLS termination** — add a reverse proxy (Caddy / nginx / Traefik) with Let's Encrypt in front of port 8080 and 5000
- **Secrets manager** — replace `.env` with Vault / AWS Secrets Manager / Docker Swarm secrets
- **Postgres backups** — pgdump cron job or managed database (RDS, Supabase, Neon)
- **Horizontal scaling** — increase `--workers` or add replicas via Docker Swarm / Kubernetes
