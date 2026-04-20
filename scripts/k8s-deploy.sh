#!/usr/bin/env bash
# Deploys the full platform to a Kubernetes cluster.
# Prerequisites: kubectl configured, cluster running (minikube / kind / cloud).
set -euo pipefail

NAMESPACE="microservice-platform"
REGISTRY="${DOCKER_USERNAME:-maskamyll}"
TAG="${IMAGE_TAG:-latest}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── check kubectl ────────────────────────────────────────────
command -v kubectl &>/dev/null || die "kubectl not found. Install it first."
kubectl cluster-info &>/dev/null   || die "No cluster reachable. Start minikube or configure kubeconfig."

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── optional: build & push images ────────────────────────────
if [[ "${BUILD_IMAGES:-false}" == "true" ]]; then
  info "Building and pushing Docker images..."
  for svc in api-gateway auth-service document-service notification-service frontend; do
    info "  Building $svc..."
    docker build -t "${REGISTRY}/mindcampus-${svc}:${TAG}" "${ROOT}/${svc}"
    docker push "${REGISTRY}/mindcampus-${svc}:${TAG}"
  done
fi

# ── deploy ───────────────────────────────────────────────────
info "1/8  Namespace"
kubectl apply -f "${ROOT}/k8s/namespace.yaml"

info "2/8  ConfigMap"
kubectl apply -f "${ROOT}/k8s/configmap.yaml"

info "3/8  Secrets"
kubectl apply -f "${ROOT}/k8s/secrets.yaml"

info "4/8  PostgreSQL"
kubectl apply -f "${ROOT}/k8s/postgres/init-configmap.yaml"
kubectl apply -f "${ROOT}/k8s/postgres/service.yaml"
kubectl apply -f "${ROOT}/k8s/postgres/statefulset.yaml"

info "5/8  RabbitMQ"
kubectl apply -f "${ROOT}/k8s/rabbitmq/service.yaml"
kubectl apply -f "${ROOT}/k8s/rabbitmq/statefulset.yaml"

info "6/8  Redis"
kubectl apply -f "${ROOT}/k8s/redis/service.yaml"
kubectl apply -f "${ROOT}/k8s/redis/deployment.yaml"

info "  Waiting for infrastructure to be ready..."
kubectl rollout status statefulset/postgres  -n "$NAMESPACE" --timeout=120s
kubectl rollout status statefulset/rabbitmq  -n "$NAMESPACE" --timeout=120s
kubectl rollout status deployment/redis      -n "$NAMESPACE" --timeout=90s

info "7/8  Application services"
kubectl apply -f "${ROOT}/k8s/auth-service/"
kubectl apply -f "${ROOT}/k8s/document-service/"
kubectl apply -f "${ROOT}/k8s/notification-service/"
kubectl apply -f "${ROOT}/k8s/api-gateway/"
kubectl apply -f "${ROOT}/k8s/frontend/"

info "  Waiting for application services to roll out..."
for svc in auth-service document-service notification-service api-gateway frontend; do
  kubectl rollout status deployment/"$svc" -n "$NAMESPACE" --timeout=120s
done

info "8/8  HPA"
kubectl apply -f "${ROOT}/k8s/document-service/hpa.yaml"

# ── summary ──────────────────────────────────────────────────
echo ""
info "Deployment complete."
echo ""
kubectl get pods -n "$NAMESPACE"
echo ""
kubectl get svc  -n "$NAMESPACE"
echo ""

# minikube tunnel tip
if command -v minikube &>/dev/null; then
  warn "Running on minikube — in a separate terminal run: minikube tunnel"
  warn "Then add to /etc/hosts:  127.0.0.1  mindcampus.local"
fi

GATEWAY_IP=$(kubectl get svc api-gateway -n "$NAMESPACE" \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")
FRONTEND_IP=$(kubectl get svc frontend -n "$NAMESPACE" \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

info "API Gateway : http://${GATEWAY_IP}"
info "Frontend    : http://${FRONTEND_IP}"
