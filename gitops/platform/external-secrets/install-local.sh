#!/usr/bin/env bash
set -euo pipefail

task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
task_kubeconfig="$task_root/infra/local.kubeconfig.json"

# The preparation helper verifies this kubeconfig targets the local Floci API.
python3 "$task_root/infra/scripts/bootstrap_external_secrets.py"
helm repo add external-secrets https://charts.external-secrets.io --force-update
helm upgrade --install external-secrets external-secrets/external-secrets \
  --version 2.15.0 \
  --namespace external-secrets --create-namespace \
  --kubeconfig "$task_kubeconfig" \
  --values "$task_root/gitops/platform/external-secrets/local-values.yaml" \
  --wait --timeout 5m
kubectl --kubeconfig "$task_kubeconfig" wait --for=condition=Established \
  crd/secretstores.external-secrets.io crd/externalsecrets.external-secrets.io --timeout=120s
kubectl --kubeconfig "$task_kubeconfig" apply \
  -f "$task_root/gitops/environments/local/backend-external-secret.yaml"
