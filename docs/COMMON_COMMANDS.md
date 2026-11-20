# Common commands: Book Ninja and local Floci

Quick reference for daily inspection and debugging. Commands use native CLIs.
For provisioning and credentials setup, see [the manual runbook](FLOCI_MANUAL_PROVISIONING.md).

## Start here

Run from the repository root. Repeat the exports in each new terminal:

```sh
cd /Users/ejazahmedansari/Desktop/projects/book-ninja-be
export KUBECONFIG="$PWD/infra/local.kubeconfig.json"
export APP_BASE_URL=http://127.0.0.1:18000
```

Floci's EKS emulator runs k3s; a version such as `v1.32.2+k3s1` is expected.
The backend Deployment is not installed yet: missing backend pods and the manual
Argo CD preview's `OutOfSync`/`Missing` status are currently expected. Backend
workload commands below apply after deployment and real runtime configuration.
`POD_NAME` in examples is a shell variable you set to an actual pod name.

## Cluster and namespaces

```sh
kubectl config current-context
kubectl config get-contexts
kubectl cluster-info
kubectl get --raw='/readyz?verbose'
kubectl get nodes -o wide
kubectl describe nodes
kubectl get namespaces
kubectl get pods -A -o wide
kubectl get deployments,statefulsets,services -A
kubectl get events -A --sort-by=.lastTimestamp
kubectl top nodes
kubectl top pods -A
kubectl get pods -A --watch
```

`top` depends on Metrics Server. Stop any watch or port-forward with Ctrl-C.
To stop selecting the local kubeconfig in this terminal:

```sh
unset KUBECONFIG
```

## Docker, Floci, and Kubernetes connectivity

```sh
docker info
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker stats --no-stream
docker logs --tail=100 infra-floci-1
docker logs --tail=100 floci-aws-eks-book-ninja-local
docker compose -f infra/docker-compose.floci.yml ps
kubectl --request-timeout=60s get nodes
```

If Docker Desktop is stopped, start it first. For the existing persisted setup:

```sh
open -a Docker
docker compose -f infra/docker-compose.floci.yml up -d
docker start floci-aws-eks-book-ninja-local
kubectl get nodes -o wide
```

Do not use `docker compose down --volumes` to troubleshoot: that removes
persistent Floci data. A kubeconfig certificate/endpoint error after cluster
recreation needs a fresh kubeconfig:

```sh
python3 infra/scripts/configure_kubeconfig.py
```

If the Floci container was recreated, refresh the local Service/EndpointSlice
and existing ESO reader credential wiring. This is a configuration update:

```sh
python3 infra/scripts/bootstrap_external_secrets.py
kubectl -n book-ninja get service floci-aws
kubectl -n book-ninja get endpointslices -l kubernetes.io/service-name=floci-aws
```

## Backend rollout, pods, and logs

```sh
kubectl -n book-ninja get deployments,pods,services,hpa,pdb
kubectl -n book-ninja describe deployment book-ninja-backend
kubectl -n book-ninja rollout status deployment/book-ninja-backend --timeout=120s
kubectl -n book-ninja rollout history deployment/book-ninja-backend
kubectl -n book-ninja get pods -l app.kubernetes.io/name=book-ninja-backend -o wide
kubectl -n book-ninja get events --sort-by=.lastTimestamp
kubectl -n book-ninja logs deployment/book-ninja-backend --tail=100 --timestamps
kubectl -n book-ninja logs -l app.kubernetes.io/name=book-ninja-backend \
  --all-containers=true --prefix=true --tail=100 --timestamps
kubectl -n book-ninja logs deployment/book-ninja-backend --follow --since=10m
```

For a specific pod, set its name from `get pods`:

```sh
POD_NAME=replace-with-actual-pod-name
kubectl -n book-ninja describe pod "$POD_NAME"
kubectl -n book-ninja logs "$POD_NAME" --container=backend --previous --tail=100
kubectl -n book-ninja get pod "$POD_NAME" -o json \
  | jq '.status.containerStatuses[] | {name,ready,restartCount,state,lastState,imageID}'
kubectl -n book-ninja exec "$POD_NAME" -- id
kubectl -n book-ninja exec "$POD_NAME" -- python -c \
  'import socket; print(socket.gethostbyname("kubernetes.default.svc.cluster.local"))'
```

`--previous` retrieves the last terminated container's logs; it fails if there
is no previous instance. In `describe`, look for `OOMKilled`, failed probes,
missing Secrets, image errors, and scheduling events. Inspect configuration
references without printing environment values:

```sh
kubectl -n book-ninja get deployment book-ninja-backend -o json \
  | jq '.spec.template.spec.containers[] | {name,image,envFrom,startupProbe,readinessProbe,livenessProbe,resources}'
kubectl -n book-ninja describe hpa book-ninja-backend
kubectl -n book-ninja top pods --containers
kubectl -n book-ninja get endpointslices \
  -l kubernetes.io/service-name=book-ninja-backend
```

An empty backend EndpointSlice usually means no matching Ready pod. After
rotating secrets consumed as environment variables, restart the deployed pods:

```sh
kubectl -n book-ninja rollout restart deployment/book-ninja-backend
kubectl -n book-ninja rollout status deployment/book-ninja-backend --timeout=120s
```

This changes the running workload. For an image rollback, revert/promote the
Git image overlay through a reviewed PR and sync Argo CD. Avoid mixing a Helm
CLI release or imperative image edits with an Argo CD-managed workload.

## Reach the API and debug HTTP, CORS, and streaming

After backend deployment, keep this running in one terminal:

```sh
kubectl -n book-ninja port-forward --address 127.0.0.1 svc/book-ninja-backend 18000:8000
```

In another terminal, repeat the exports from "Start here":

```sh
curl --fail-with-body --max-time 10 "$APP_BASE_URL/livez"
curl --fail-with-body --max-time 30 "$APP_BASE_URL/health"
curl --fail-with-body --max-time 10 "$APP_BASE_URL/openapi.json" \
  | jq '.paths | keys'
curl --include --max-time 10 --request OPTIONS "$APP_BASE_URL/chat" \
  --header 'Origin: http://localhost:5173' \
  --header 'Access-Control-Request-Method: POST' \
  --header 'Access-Control-Request-Headers: authorization,content-type'
```

Use the actual browser origin in the CORS check. `/livez` checks the HTTP
process; `/health` calls external integrations and reports their status. A
successful `/livez` does not prove MongoDB persistence or provider availability.
The application can fall back to in-memory checkpoints when MongoDB fails.

For an authenticated SSE request, first save a valid Google ID token header
in ignored, owner-only `infra/manual/google-auth-header` with this format:
`Authorization: Bearer YOUR_GOOGLE_ID_TOKEN`. Then:

```sh
chmod 600 infra/manual/google-auth-header
curl --no-buffer --include --max-time 120 "$APP_BASE_URL/chat" \
  --header @infra/manual/google-auth-header \
  --header 'Content-Type: application/json' \
  --header 'Accept: text/event-stream' \
  --data '{"prompt":"Recommend a science fiction book"}'
```

This creates a conversation and invokes the configured providers. `--no-buffer`
shows events as they arrive. A 401 points to token validation; CORS failures
must be checked against the browser's origin and configured allowed origins.
Do not use verbose curl output with the authentication header when collecting
shared diagnostics, and do not dump Secret data or a pod's environment.

## External Secrets Operator and runtime configuration

```sh
kubectl -n external-secrets get pods
kubectl -n external-secrets logs deployment/external-secrets --tail=100 --timestamps
kubectl -n book-ninja get secretstores,externalsecrets
kubectl -n book-ninja describe secretstore backend-runtime
kubectl -n book-ninja describe externalsecret backend-runtime
kubectl -n book-ninja get secret backend-runtime --ignore-not-found -o name
kubectl -n book-ninja get secret backend-runtime -o json | jq '.data | keys'
```

The last command lists key names only and fails while the Secret is absent.
Until all six real fields are populated in Floci, an unready backend
ExternalSecret and missing application Secret are expected. After updating the
upstream value, force a refresh and wait:

```sh
kubectl -n book-ninja annotate externalsecret backend-runtime \
  force-sync="$(date +%s)" --overwrite
kubectl -n book-ninja wait --for=condition=Ready \
  externalsecret/backend-runtime --timeout=120s
```

This refreshes the Kubernetes Secret; restart existing environment-variable
consumers separately. Do not print `aws secretsmanager get-secret-value` output.

## Argo CD and GitOps

```sh
helm list --kubeconfig "$KUBECONFIG" -A
kubectl -n argocd get pods,services
kubectl -n argocd get applications,appprojects
kubectl -n argocd describe application book-ninja-local-backend
kubectl -n argocd get application book-ninja-local-backend -o json \
  | jq '{source:.spec.source,destination:.spec.destination,sync:.status.sync,health:.status.health,conditions:.status.conditions,operation:.status.operationState}'
kubectl -n argocd logs statefulset/argocd-application-controller --tail=100 --timestamps
kubectl -n argocd logs deployment/argocd-repo-server --tail=100 --timestamps
kubectl -n argocd logs deployment/argocd-server --tail=100 --timestamps
```

Request a fresh Git comparison; this does not sync the workload:

```sh
kubectl -n argocd annotate application book-ninja-local-backend \
  argocd.argoproj.io/refresh=hard --overwrite
```

For the UI, keep this terminal running, then open `https://127.0.0.1:8443`:

```sh
kubectl -n argocd port-forward --address 127.0.0.1 svc/argocd-server 8443:443
```

The local certificate is self-signed. Username is `admin`; the initial password
is in ignored `infra/manual/argocd-initial-admin-password` until rotated. Root
adoption and backend sync are controlled steps in the provisioning runbook.
An `InvalidSpecError` suggests source/destination/project restrictions; a
`ComparisonError` suggests Git access, revision/path, or Helm rendering errors.

## Image publication and local node cache

The optional AWS helper reads the existing local provisioner credentials and
always targets Floci; these commands expose image metadata, not passwords:

```sh
python3 infra/scripts/floci_aws.py ecr describe-images \
  --repository-name book-ninja-local-backend
docker image ls
docker exec floci-aws-eks-book-ninja-local ctr -n k8s.io images list \
  | rg book-ninja-local-backend
kubectl -n book-ninja get deployment book-ninja-backend \
  -o 'jsonpath={.spec.template.spec.containers[0].image}{"\n"}'
```

Floci's registry, host Docker, and k3s image cache are separate. After node
recreation, the image must be preloaded again. These helpers perform writes:
publication builds/pushes if needed; verification imports an image, creates a
disposable probe Pod, and removes it. Run them for the intended source revision:

```sh
python3 infra/scripts/publish_backend.py
python3 infra/scripts/verify_backend_image.py
```

For the installed background publisher, inspect its own control clone's receipt:

```sh
jq '{revision,platform,image}' \
  "$HOME/.local/share/book-ninja-floci-publisher/infra/manual/backend-image.json"
```

It may differ from the primary checkout's `infra/manual/backend-image.json`.
Compare the desired Git overlay, ECR digest, and node cache when debugging
`ErrImagePull`/`ImagePullBackOff`; do not replace an immutable tag or use `latest`.

## Private API foundation

The Regional REST API container, VPC Link V2, internal ALB, and empty target
group exist. Routes, stage deployment, and workload binding are pending; an
empty target group and no API deployments are expected. The ALB listener is
inside Floci's container, without a new published host port.

```sh
terraform -chdir=infra output -json api_foundation > infra/manual/api-foundation.json
python3 infra/scripts/floci_aws.py elbv2 describe-load-balancers \
  --load-balancer-arns "$(jq -r .alb_arn infra/manual/api-foundation.json)"
python3 infra/scripts/floci_aws.py elbv2 describe-target-health \
  --target-group-arn "$(jq -r .target_group_arn infra/manual/api-foundation.json)"
python3 infra/scripts/floci_aws.py apigatewayv2 get-vpc-link \
  --vpc-link-id "$(jq -r .vpc_link_id infra/manual/api-foundation.json)"
python3 infra/scripts/floci_aws.py apigateway get-deployments \
  --rest-api-id "$(jq -r .rest_api_id infra/manual/api-foundation.json)"
```

The routing smoke helper creates a disposable Docker target and temporarily
registers it with the ALB, then removes it. Run only while the target group is
unused; it is not a read-only inspection or an application/SSE test:

```sh
python3 infra/scripts/verify_api_foundation.py
```

## CI and the background local publisher

```sh
gh pr list --repo EjazAhmedRak/book-ninja
gh run list --repo EjazAhmedRak/book-ninja --workflow backend.yml --branch develop --limit 10
gh run view RUN_ID --repo EjazAhmedRak/book-ninja
gh run view RUN_ID --repo EjazAhmedRak/book-ninja --log-failed
launchctl print "gui/$(id -u)/io.book-ninja.floci-publisher"
tail -n 50 "$HOME/.local/share/book-ninja-floci-publisher/infra/manual/local-publisher.stdout.log"
tail -n 50 "$HOME/.local/share/book-ninja-floci-publisher/infra/manual/local-publisher.stderr.log"
```

Replace `RUN_ID` with the numeric ID from `gh run list`. The publisher accepts
successful push CI for the current `develop` head. It skips PR/fork/stale/failed
runs. An overlay-only merge intentionally does not rebuild and can leave the
publisher waiting for the next qualifying source change.

After changing publisher helpers, provisioner keys, or cluster kubeconfig,
refresh its service snapshot from this checkout:

```sh
python3 infra/scripts/watch_backend_ci.py --uninstall
python3 infra/scripts/watch_backend_ci.py --install
```

This stops/reinstalls the local service; it can create future image promotion
PRs after qualifying CI. To inspect CI once without publication, stop the
watcher first and run `python3 infra/scripts/watch_backend_ci.py` without flags.

## Frontend hosting and local app development

```sh
FRONTEND_URL=$(terraform -chdir=infra output -raw frontend_url)
curl --include --max-time 15 "$FRONTEND_URL"
python3 infra/scripts/floci_aws.py cloudfront get-distribution \
  --id "$(terraform -chdir=infra output -raw frontend_distribution_id)"
python3 infra/scripts/floci_aws.py s3api list-objects-v2 \
  --bucket "$(terraform -chdir=infra output -raw frontend_bucket_name)" \
  --query 'Contents[].{Key:Key,Size:Size}'
```

Hosting infrastructure exists; actual frontend asset publication is still
pending. For local development, after installing dependencies and configuring
the ignored application `.env` files:

```sh
npm run dev:backend
npm run dev:frontend
# Or run both:
npm run dev
```

The local API runs on port 8000; the frontend runs on 5173. To point the frontend
at the Kubernetes port-forward instead, run:

```sh
VITE_API_BASE_URL=http://127.0.0.1:18000 npm run dev:frontend
```

Vite build variables are compiled into assets; changing them after a hosted
build requires a rebuild. To run existing checks:

```sh
npm run test:backend
npm run test:frontend
npm run build:frontend
npm --workspace apps/frontend run typecheck
python3 -m unittest discover -s infra/tests -p 'test_*.py' -v
```

## Symptom lookup

| Symptom | First checks |
| --- | --- |
| Connection refused / TLS handshake timeout | Docker/Floci/k3s status, kubeconfig endpoint, node CPU/memory, recent k3s logs |
| `Pending` pod | `describe pod`, events, requests/limits, available node resources |
| `CreateContainerConfigError` | Runtime Secret presence and ESO conditions |
| `CrashLoopBackOff` | Previous container logs, exit reason, OOM/probe events |
| `ImagePullBackOff` | Exact digest, local k3s cache, image preload receipt |
| Service has no endpoints | Service selectors and matching Ready pods |
| API works in curl but fails in browser | CORS origin and frontend build-time API URL |
| Chat returns 401 | Valid Google ID token and matching client ID |
| Chat stream appears buffered | `curl --no-buffer`, direct port-forward, then ingress/API path when installed |
| Threads disappear after restart | MongoDB connectivity and in-memory checkpoint fallback |
| Argo CD preview is `Missing` | Expected before first backend sync; inspect sync policy and runtime readiness |
| Publisher keeps waiting | Latest `develop` SHA has no qualifying successful push CI; check path filters and service logs |
