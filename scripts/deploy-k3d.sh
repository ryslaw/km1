#!/usr/bin/env bash
# Rebuild the km1 service images and redeploy them to the local k3d cluster.
# Usage: scripts/deploy-k3d.sh
set -euo pipefail

CLUSTER="km1"
CONTEXT="k3d-${CLUSTER}"
NAMESPACE="km1"
SERVICES=(user-service product-service order-service status-page)

# Work from the repo root, wherever the script is called from.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

images=()
for service in "${SERVICES[@]}"; do
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

for service in "${SERVICES[@]}"; do
  kubectl --context "${CONTEXT}" rollout restart "deployment/${service}" -n "${NAMESPACE}"
done

for service in "${SERVICES[@]}"; do
  kubectl --context "${CONTEXT}" rollout status "deployment/${service}" -n "${NAMESPACE}" --timeout=300s
done

echo "==> Done"
