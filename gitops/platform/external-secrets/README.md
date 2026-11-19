# Local External Secrets Operator

This Floci overlay pins Helm chart `external-secrets` 2.15.0. Resources are
checked in for later GitOps adoption; Helm/kubectl currently bootstrap them.

From the repository root:

```sh
python3 infra/scripts/bootstrap_provisioner.py
terraform -chdir=infra plan -var-file=environments/local.tfvars
terraform -chdir=infra apply -var-file=environments/local.tfvars
python3 infra/scripts/configure_kubeconfig.py
bash gitops/platform/external-secrets/install-local.sh
python3 infra/scripts/verify_external_secrets.py
```

Terraform creates a local-only IAM reader with GetSecretValue/DescribeSecret
on exactly the backend runtime ARN. Access keys are generated outside Terraform,
saved in ignored owner-only `infra/local.external-secrets.credentials.json`,
and supplied as a Kubernetes Secret. The bootstrap administrator creates the
key; the operator never receives administrator/provisioning credentials.

The controller watches only `book-ninja`, uses scoped RBAC and controller class
`book-ninja-local`, and disables cluster-wide and push controllers. A namespaced
SecretStore references reader credentials. The ExternalSecret explicitly maps
the six required backend fields to `book-ninja/backend-runtime`. Missing fields
prevent creation of a partial application Secret. Existing values are retained
on upstream errors/deletion. Secret rotation does not restart application pods
that consume environment variables; that remains a rollout responsibility.

## Local networking and identity

The preparation helper creates a `book-ninja/floci-aws` Service and EndpointSlice
pointing at Floci's Docker `infra_default` IPv4 address. Rerun it after container
recreation if the IP changes. This avoids resolving Docker Compose service names
from pods. The helper rejects Kubernetes API endpoints outside loopback.

HTTP endpoint overrides in `local-values.yaml` affect every store this controller
manages. Do not install these values in AWS. Production workload identity
(IRSA/Pod Identity), TLS, and its RBAC remain separate work. Terraform does not
create this static-key user for non-local environments.

## Configuration and verification

The backend Secrets Manager container is empty. SecretStore readiness proves
access; the backend ExternalSecret must remain unready until all six real fields
are supplied. Follow the manual runbook to upload an ignored JSON file. Do not
put application values in Helm values, manifests, Terraform, or Git.

```sh
kubectl --kubeconfig infra/local.kubeconfig.json -n book-ninja get secretstore,externalsecret
kubectl --kubeconfig infra/local.kubeconfig.json -n book-ninja wait \
  --for=condition=Ready externalsecret/backend-runtime --timeout=120s
```

The second command times out until real values exist. Do not dump generated
Secrets to logs. The verification helper instead synchronizes a unique,
non-application probe using a temporary IAM grant, then removes the probe and
grant in a finally block. Backend runtime values remain untouched.

Before destroying the reader user, explicitly revoke its out-of-state access
keys; force_destroy is disabled. Keep the saved key file until reuse/revocation
is complete. See [the manual runbook](../../../docs/FLOCI_MANUAL_PROVISIONING.md)
for native CLI commands and the [ESO AWS documentation](https://external-secrets.io/latest/provider/aws-access/)
for endpoint and authentication settings.
