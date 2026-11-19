#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
task_kubeconfig="$task_root/infra/local.kubeconfig.json"
python3 "$task_root/infra/scripts/bootstrap_argocd.py" --check-local
helm repo add argo https://argoproj.github.io/argo-helm --force-update
helm upgrade --install argocd argo/argo-cd --version 10.18.1 \
  --namespace argocd --create-namespace --kubeconfig "$task_kubeconfig" \
  --values "$task_root/gitops/platform/argocd/local-values.yaml" --wait --timeout 8m
kubectl --kubeconfig "$task_kubeconfig" wait --for=condition=Established \
  crd/applications.argoproj.io crd/appprojects.argoproj.io --timeout=120s
python3 "$task_root/infra/scripts/bootstrap_argocd.py"
