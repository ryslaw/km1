#!/usr/bin/env bash
# Rebuild the km1 service images and redeploy them to the local k3d cluster.
# Usage:
# scripts/deploy-k3d.sh - build and deploy all services
# scripts/deploy-k3d.sh [service...] - build and deploy specific services
# Set K3D_CLUSTER to use another cluster (default: km1)
set -euo pipefail

CLUSTER=${K3D_CLUSTER:-"km1"}
CONTEXT="k3d-${CLUSTER}"
NAMESPACE="km1"
ALLOWED_SERVICES=(user-service product-service order-service status-page)
services=()

usage () {
  echo "deploy-k3d.sh - build and deploy all services" >&2
  echo "deploy-k3d.sh [service...] - build and deploy specific services" >&2
  echo "Allowed service names: ${ALLOWED_SERVICES[*]}" >&2
  echo "Set K3D_CLUSTER to use another cluster (default: km1)" >&2
  return
}

die () {
  echo "Error: $1" >&2
  exit 1
}

if (( $# > 0 )); then
  for arg in "$@"; do
    match=0
    for srv in "${ALLOWED_SERVICES[@]}"; do
      if [[ "${srv}" == "${arg}" ]]; then
        match=1
        services+=("${arg}")
        break
      fi
    done
    if [[ $arg == "-h" || $arg == "--help" ]]; then
      usage
      exit 0
    fi
    if [[ $match -eq 0 ]]; then
      usage
      die "argument '${arg}' is incorrect"
    fi
  done
else
  services=("${ALLOWED_SERVICES[@]}")
fi

command -v docker >/dev/null 2>&1 || die "docker not found"
command -v k3d >/dev/null 2>&1 || die "k3d not found"
command -v kubectl >/dev/null 2>&1 || die "kubectl not found"
k3d cluster list "${CLUSTER}" --no-headers >/dev/null 2>&1 ||
  die "k3d cluster '${CLUSTER}' not found"
msg="Secret postgres-credentials not found in namespace ${NAMESPACE}; create it as "
msg+="described in README, Running locally with Kubernetes (k3d), step 4"
kubectl --context "${CONTEXT}" get secret postgres-credentials -n "${NAMESPACE}" \
  >/dev/null 2>&1 || die "${msg}"

# Work from the repo root, wherever the script is called from.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

images=()
for service in "${services[@]}"; do
  image="km1/${service}:local"
  echo "==> Building ${image}"
  docker build -t "${image}" "services/${service}"
  images+=("${image}")
done

echo "==> Importing images into k3d cluster '${CLUSTER}'"
k3d image import "${images[@]}" -c "${CLUSTER}"

echo "==> Applying manifests"
kubectl --context "${CONTEXT}" apply -R -f k8s/

# Same :local tag as before, so the pods only pick up the new images when
# their Deployments are restarted.
for service in "${services[@]}"; do
  kubectl --context "${CONTEXT}" rollout restart "deployment/${service}" \
    -n "${NAMESPACE}"
done

for service in "${services[@]}"; do
  kubectl --context "${CONTEXT}" rollout status "deployment/${service}" \
    -n "${NAMESPACE}" --timeout=300s
done

echo "==> Done"
