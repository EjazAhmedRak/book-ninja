# Backend workload chart

This chart prepares the backend Deployment, internal ClusterIP Service,
ServiceAccount, ConfigMap, PodDisruptionBudget, and CPU HPA. ESO and its runtime
Secret are managed separately. No ingress, public API, NetworkPolicy, namespace
quota, or Argo CD Application is installed here yet.

The local overlay pins the image published from revision
`62d4a037c942bf1b479e1c9c7df0b720dd8fc3fc`. The chart requires an image digest
and explicit frontend origins. Do not put application secrets in Helm values:
the Deployment references `book-ninja/backend-runtime` through `envFrom`.

From the repository root:

```sh
python3 infra/scripts/publish_backend.py
python3 infra/scripts/verify_backend_image.py
FRONTEND_ORIGIN=$(terraform -chdir=infra output -raw frontend_url)
FRONTEND_ORIGIN=${FRONTEND_ORIGIN%/}
helm lint gitops/charts/book-ninja -f gitops/environments/local/backend-values.yaml \
  --set-string config.FRONTEND_ORIGINS="$FRONTEND_ORIGIN"
helm template book-ninja gitops/charts/book-ninja -n book-ninja \
  -f gitops/environments/local/backend-values.yaml \
  --set-string config.FRONTEND_ORIGINS="$FRONTEND_ORIGIN" \
  > infra/manual/backend-rendered.yaml
kubectl --kubeconfig infra/local.kubeconfig.json apply --dry-run=server \
  -n book-ninja -f infra/manual/backend-rendered.yaml
```

Publishing refuses uncommitted backend source, labels the image with its Git SHA,
uses an ephemeral Docker login configuration, and checks ECR and pull digests.
An existing immutable tag is reused rather than overwritten. Update the checked-in
local overlay from `infra/manual/backend-image.json` when promoting another image.

Docker and k3s have separate image stores. The image verification helper imports
the host image into this local single-node cluster, checks its manifest digest,
and runs a disposable Pod with `imagePullPolicy: Never`, no credentials, UID 1000,
and a read-only root filesystem. It imports FastAPI/Uvicorn; it does not start the
application or verify its providers. This preload is a local accommodation:
`localhost:4566` inside a node is not the host registry. After node recreation,
repeat it before deployment. Production needs ECR pull permissions and reachable
HTTPS endpoints instead. No Docker/containerd trust settings are changed.

The actual Helm release is not installed yet: the backend ExternalSecret is
unready because real runtime values are absent. Follow sections 18 and 20 of
[the manual provisioning runbook](../../../docs/FLOCI_MANUAL_PROVISIONING.md)
to supply them, verify the image, and perform the guarded future rollout.

The chart defaults to production application mode and two minimum HPA replicas;
the local overlay explicitly selects development mode. Probes use `/livez` so
provider outages do not cause restart storms. They prove the HTTP process is
serving, not MongoDB persistence or provider availability; `/health` remains the
separate integration diagnostic. Startup probes allow three minutes, Uvicorn
drains for up to 60 seconds, and the pod termination budget is 90 seconds. Streaming
drain behavior still needs rollout testing. Secret changes require a rollout
restart for environment variables to refresh. Application dependencies/base image
are not yet locked by digest; this is local publication, not a production release.
