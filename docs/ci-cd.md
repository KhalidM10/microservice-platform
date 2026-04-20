# CI/CD Pipeline

## Overview

GitHub Actions runs a four-job pipeline on every push and pull request.

```
push / PR
    │
    ├── test  (parallel matrix: 4 services)
    ├── lint  (ruff, non-blocking)
    │
    │   [only on push events]
    │
    └── build (parallel matrix: 5 services → Docker Hub)
            │
            │   [only on main branch]
            │
            └── deploy (kubectl apply → rollout → smoke test)
```

---

## Jobs

### 1. `test` — Runs on every push and PR

Runs `pytest` for each Python service in parallel with coverage enforcement.

| Service | Min Coverage |
|---|---|
| document-service | 80 % |
| auth-service | 80 % |
| notification-service | 80 % |
| api-gateway | 80 % |

- Uses `actions/cache` to cache pip packages by `requirements.txt` hash
- Uploads `coverage.xml` to Codecov (non-blocking if token not set)
- `fail-fast: false` — all services run even if one fails

### 2. `lint` — Runs on every push and PR

Runs `ruff` across all four service `src/` directories.  
Currently non-blocking (`|| true`) — reports issues but does not fail the build.  
To enforce, remove the `|| true`.

### 3. `build` — Runs on push events only (not PRs)

Builds and pushes Docker images for all 5 services (including frontend).

| Branch | Tags pushed |
|---|---|
| `main` | `latest`, `<short-sha>`, `main` |
| `develop` | `<short-sha>`, `develop` |

Uses GitHub Actions cache (`type=gha`) for Docker layer caching — subsequent
builds are significantly faster when only Python code changes.

### 4. `deploy` — Runs on push to `main` only

Applies all k8s manifests then updates each deployment's image to the new SHA.

Steps:
1. Decode `KUBECONFIG_B64` secret → `~/.kube/config`
2. `kubectl apply` all manifests (namespace → infra → services)
3. `kubectl set image` to pin each deployment to the exact SHA
4. `kubectl rollout status` — waits up to 120 s per deployment
5. Smoke test — `curl /health` on the LoadBalancer IP
6. Posts a deployment summary table to the GitHub Actions job summary

---

## Required GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|---|---|
| `DOCKER_USERNAME` | Your Docker Hub username |
| `DOCKER_PASSWORD` | Docker Hub password or access token |
| `KUBECONFIG_B64` | Base64-encoded kubeconfig for your cluster |

### Generating `KUBECONFIG_B64`

```bash
# For minikube
cat ~/.kube/config | base64 -w0

# For a cloud cluster (GKE example)
gcloud container clusters get-credentials <cluster> --region <region>
cat ~/.kube/config | base64 -w0
```

Paste the output as the `KUBECONFIG_B64` secret value.

---

## Triggering a Manual Deploy

The pipeline supports `workflow_dispatch` with a `deploy` toggle:

1. Go to **Actions → CI/CD Pipeline → Run workflow**
2. Check **"Deploy to Kubernetes after build"**
3. Click **Run workflow**

This builds and deploys without needing a commit.

---

## Adding Codecov (Optional)

1. Sign in at [codecov.io](https://codecov.io) with your GitHub account
2. Add your repo
3. Copy the upload token
4. Add it as a GitHub secret: `CODECOV_TOKEN`

The workflow already calls `codecov/codecov-action` — it will pick up the token automatically.

---

## Branch Strategy

| Branch | Tests | Build | Deploy |
|---|---|---|---|
| `main` | ✅ | ✅ | ✅ |
| `develop` | ✅ | ✅ | ❌ |
| PR → `main` | ✅ | ❌ | ❌ |
| PR → `develop` | ✅ | ❌ | ❌ |

---

## Local Workflow Simulation

```bash
# Run the same test command the CI runs
cd document-service
DATABASE_URL="sqlite+aiosqlite:///./test.db" SECRET_KEY="test" \
  APP_NAME="document-service" APP_VERSION="1.0.0" \
  RABBITMQ_URL="amqp://guest:guest@localhost" REDIS_URL="redis://localhost" \
  pytest tests/ --cov=src --cov-fail-under=80

# Run ruff lint
pip install ruff
ruff check document-service/src auth-service/src --select E,F,W --ignore E501
```
