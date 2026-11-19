# Local Argo CD bootstrap

Argo CD Helm chart **10.18.1** (application **v3.6.1**) runs in `argocd` on local
Floci k3s. The API/UI Service is ClusterIP, TLS stays enabled, and anonymous
access is disabled. Dex, notifications, and ApplicationSet workloads are not
used locally. Resource limits, lower controller concurrency, and startup probes
accommodate the node's two-CPU limit. This is a single-node bootstrap; production
HA, SSO, network restrictions, and controller Kubernetes RBAC hardening remain.

From the repository root:

```sh
bash gitops/platform/argocd/install-local.sh
kubectl --kubeconfig infra/local.kubeconfig.json -n argocd get pods,svc,appprojects
kubectl --kubeconfig infra/local.kubeconfig.json -n argocd port-forward \
  --address 127.0.0.1 svc/argocd-server 8443:443
```

Open `https://127.0.0.1:8443` while port-forwarding. Local Argo CD uses its
generated self-signed certificate. Username: `admin`. The initial password is
saved in owner-only, ignored `infra/manual/argocd-initial-admin-password`; it is
not printed by the bootstrap. Rotate the password after login and remove the
initial Kubernetes Secret/local file once the new credential is secured.

## GitOps boundaries

- `book-ninja-local` permits only this public repository and the `book-ninja`
  namespace. It allows the six resource types in the backend chart; it cannot
  manage Secrets, RBAC resources, namespaces, or other cluster-scoped resources.
- `default` permits no sources/destinations.
- `book-ninja-bootstrap` permits only Application/AppProject metadata in `argocd`
  from the approved repository. Changes to that root path are trusted platform
  administration and need review.

These are Argo CD project restrictions. The chart's standard controller
Kubernetes permissions are broader; the projects do not reduce its service
account's Kubernetes RBAC. No GitHub personal token, IAM credentials, or
application secrets are passed to Argo CD. Repository reads are public HTTPS.

## Preview and root adoption

The backend Application has manual sync, no deletion finalizer, and no automated
policy. Its Helm release name remains `book-ninja`, matching the prepared chart.
The existing preview uses reviewed source commit
`899a871bdcc83d4348993342aec2ca0ee1a8b7b2`, whose chart/overlay already exist on
GitHub. It is expected to be `OutOfSync`/`Missing`: it renders Git but has not
created backend workloads. Registering it does not start an application rollout.

```sh
python3 infra/scripts/bootstrap_argocd.py \
  --preview-revision 899a871bdcc83d4348993342aec2ca0ee1a8b7b2
```

After **this Argo CD change** is reviewed and merged, register the root app and
sync its metadata as documented in section 22 of the manual runbook:

```sh
python3 infra/scripts/bootstrap_argocd.py --activate-root
```

That option checks that the root's project manifests exist on `develop` before
registering the root Application. Root sync adopts the projects and backend
Application, moving the backend source to `develop`. It still leaves backend
sync manual. Do not use `helm upgrade --install book-ninja` alongside Argo CD
after it owns the workload; Argo CD renders Helm and applies the resources.

Backend sync should wait for `ExternalSecret/backend-runtime` Ready, all six
real fields, and the exact image preloaded on the local node. The local publisher
preloads images before its digest-promotion PR. After node recreation, repeat
image verification before syncing. Enabling backend auto-sync and validating
application health/persistence/SSE remain future work.

See [the manual runbook](../../../docs/FLOCI_MANUAL_PROVISIONING.md) for native
Helm/kubectl/curl equivalents and project-denial verification, and
[Argo CD declarative setup](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/)
for source/project behavior.
