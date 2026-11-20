#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
task_kubeconfig="$task_root/infra/local.kubeconfig.json"
python3 "$task_root/infra/scripts/bootstrap_external_secrets.py"
python3 "$task_root/infra/scripts/bootstrap_load_balancer_controller.py"
helm repo add eks https://aws.github.io/eks-charts --force-update
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --version 3.6.3 --namespace load-balancer-system --kubeconfig "$task_kubeconfig" \
  -f "$task_root/gitops/platform/load-balancer-controller/local-values.yaml" \
  -f "$task_root/infra/manual/load-balancer-controller-values.json" --wait --timeout 8m
kubectl --kubeconfig "$task_kubeconfig" wait --for=condition=Established \
  crd/targetgroupbindings.elbv2.k8s.aws --timeout=120s
