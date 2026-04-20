# Kubernetes Deployment

## Overview

The platform ships with complete Kubernetes manifests under `k8s/` that deploy
all services, infrastructure, and the frontend to any conformant cluster.

```
k8s/
├── namespace.yaml
├── configmap.yaml
├── secrets.yaml
├── postgres/
│   ├── init-configmap.yaml   # creates auth + notifications databases on first boot
│   ├── service.yaml          # headless ClusterIP for StatefulSet DNS
│   └── statefulset.yaml      # postgres:15-alpine, 5 Gi PVC
├── rabbitmq/
│   ├── service.yaml          # headless, ports 5672 + 15672
│   └── statefulset.yaml      # rabbitmq:3.12-management, 2 Gi PVC
├── redis/
│   ├── service.yaml          # ClusterIP :6379
│   └── deployment.yaml       # redis:7-alpine, emptyDir
├── auth-service/
│   ├── deployment.yaml       # 2 replicas
│   └── service.yaml          # ClusterIP :8000
├── document-service/
│   ├── deployment.yaml       # 2 replicas
│   ├── service.yaml          # ClusterIP :8000
│   └── hpa.yaml              # autoscale 2–10 pods at 70 % CPU
├── notification-service/
│   ├── deployment.yaml       # 2 replicas
│   └── service.yaml          # ClusterIP :8000
├── api-gateway/
│   ├── deployment.yaml       # 2 replicas
│   ├── service.yaml          # LoadBalancer :80 → :8000
│   └── ingress.yaml          # host: mindcampus.local
└── frontend/
    ├── deployment.yaml       # 1 replica, nginx:1.25-alpine
    └── service.yaml          # LoadBalancer :80
```

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| kubectl | ≥ 1.28 | Apply manifests |
| minikube **or** kind **or** cloud cluster | — | Cluster runtime |
| Docker | ≥ 24 | Build images (optional) |

---

## Quick Start (minikube)

```bash
# 1. Start a local cluster
minikube start --cpus=4 --memory=6g

# 2. Enable ingress and metrics-server addons
minikube addons enable ingress
minikube addons enable metrics-server

# 3. Run the deploy script
bash scripts/k8s-deploy.sh

# 4. In a second terminal, expose LoadBalancer services
minikube tunnel

# 5. Add to /etc/hosts (Linux/Mac) or C:\Windows\System32\drivers\etc\hosts (Windows)
echo "127.0.0.1  mindcampus.local" | sudo tee -a /etc/hosts

# 6. Access the platform
open http://mindcampus.local        # API Gateway
```

---

## Manual Step-by-Step

```bash
# 1. Namespace
kubectl apply -f k8s/namespace.yaml

# 2. Config & secrets
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml

# 3. Infrastructure
kubectl apply -f k8s/postgres/init-configmap.yaml
kubectl apply -f k8s/postgres/
kubectl apply -f k8s/rabbitmq/
kubectl apply -f k8s/redis/

# Wait for infra to be ready
kubectl rollout status statefulset/postgres -n microservice-platform --timeout=120s
kubectl rollout status statefulset/rabbitmq -n microservice-platform --timeout=120s
kubectl rollout status deployment/redis     -n microservice-platform --timeout=90s

# 4. Application services
kubectl apply -f k8s/auth-service/
kubectl apply -f k8s/document-service/
kubectl apply -f k8s/notification-service/
kubectl apply -f k8s/api-gateway/
kubectl apply -f k8s/frontend/

# 5. Verify
kubectl get pods -n microservice-platform
kubectl get svc  -n microservice-platform
```

---

## Using Your Own Docker Images

The manifests default to `maskamyll/mindcampus-*:latest`.
To use your own registry:

```bash
# Build and push all images
export DOCKER_USERNAME=yourdockerhub
export IMAGE_TAG=v1.0.0
BUILD_IMAGES=true bash scripts/k8s-deploy.sh

# Or manually
docker build -t yourdockerhub/mindcampus-api-gateway:v1.0.0 ./api-gateway
docker push  yourdockerhub/mindcampus-api-gateway:v1.0.0
# … repeat for each service
```

Then update the `image:` field in each deployment.yaml, or use:

```bash
kubectl set image deployment/api-gateway \
  api-gateway=yourdockerhub/mindcampus-api-gateway:v1.0.0 \
  -n microservice-platform
```

---

## Secrets Management

`k8s/secrets.yaml` ships with **development placeholder values**.  
For production, replace with your own base64-encoded values:

```bash
# Encode a value
echo -n 'your-strong-secret-key' | base64

# Decode to verify
echo 'base64string' | base64 -d
```

**Production recommendations:**
- Use [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) to safely commit encrypted secrets to git
- Use [HashiCorp Vault](https://www.vaultproject.io/) with the Vault Agent injector
- On cloud: AWS Secrets Manager, GCP Secret Manager, or Azure Key Vault

---

## Scaling

The document-service ships with a HorizontalPodAutoscaler:

```bash
# View current HPA status
kubectl get hpa -n microservice-platform

# Manual scale (overrides HPA temporarily)
kubectl scale deployment document-service --replicas=5 -n microservice-platform

# Watch pods scale up under load
kubectl get pods -n microservice-platform -w
```

HPA config: min 2 replicas → max 10 replicas at 70% average CPU utilisation.

---

## Useful Commands

```bash
# All pods status
kubectl get pods -n microservice-platform

# Follow logs for a service
kubectl logs -f deployment/api-gateway -n microservice-platform

# Exec into a pod
kubectl exec -it deployment/document-service -n microservice-platform -- sh

# Port-forward gateway locally (no minikube tunnel needed)
kubectl port-forward svc/api-gateway 8080:80 -n microservice-platform

# Port-forward frontend locally
kubectl port-forward svc/frontend 5000:80 -n microservice-platform

# Describe a crashing pod
kubectl describe pod <pod-name> -n microservice-platform

# Delete everything and start fresh
kubectl delete namespace microservice-platform
```

---

## Teardown

```bash
# Remove all platform resources
kubectl delete namespace microservice-platform

# This deletes all pods, services, PVCs, secrets, configmaps — everything in the namespace.
```
