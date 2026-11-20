# Local target-group controller

AWS Load Balancer Controller chart/image **3.6.3** runs as one replica in
`load-balancer-system`, watching `book-ninja`. Terraform owns the ALB/listener/
target group; this controller registers and deregisters Service endpoints.
It has no IAM permission to create load balancers or change security groups.

From the repository root:

```sh
python3 infra/scripts/bootstrap_provisioner.py
terraform -chdir=infra plan -var-file=environments/local.tfvars
terraform -chdir=infra apply -var-file=environments/local.tfvars
bash gitops/platform/load-balancer-controller/install-local.sh
python3 infra/scripts/verify_target_binding.py
```

Terraform creates a local-only IAM user and policy. The bootstrap administrator
generates/reuses its key in ignored owner-only
`infra/local.load-balancer-controller.credentials.json`. It is supplied through
a namespaced Kubernetes Secret and `envFrom`; no key goes into Terraform state,
Helm values, or Git. Chart `envSecretName` expects different key names and is not
used. Production needs workload identity rather than this local static-key setup.

EC2/ELB/STS endpoints point at the existing `floci-aws.book-ninja` Service. Region
and VPC are explicit, IMDS is disabled, Service mutation/readiness injection and
Gateway controllers are disabled, and no IngressClass is created. The controller
still uses its chart's Kubernetes RBAC; watch scope is not a namespace-only RBAC
guarantee. Its IAM write scope is only the existing target-group ARN.

## Local networking and verification limits

The bootstrap attaches Floci to the k3s node's existing Docker `bridge` network
if needed, retaining its Compose/VPC networks. No host port is published. Rerun
bootstrap after Floci recreation; this extra attachment is not in Compose.

The verification fixture uses a temporary **host-network** pod and an available
port in the Linux node network, not port 8000 on the Mac. A ClusterIP Service and
TargetGroupBinding make the controller register the endpoint and the ALB health
checker verify it. A temporary client container checks path/query/header
forwarding. The binding is deleted first so the controller deregisters its target;
the Service/pod are removed and the target group must return to empty. Cleanup
attempts all resources even if one operation fails, reporting any failures.

The helper refuses an in-use target group. No real application credentials are
used. This verifies reconciliation and the host-network fixture path; ordinary
k3s overlay-pod reachability, AWS VPC/SG enforcement, the real application, and
API Gateway/SSE are separate checks. Do not copy `hostNetwork` into the backend.

## Opt-in backend binding

The backend chart defaults `targetGroupBinding.enabled` to false. Enabling it
requires `targetGroupBinding.targetGroupARN` and `targetGroupBinding.vpcID` and
renders a seventh resource, referencing `book-ninja-backend:8000` with IP targets.
Keep its values in the reviewed local overlay when ready to enable real traffic.

The backend AppProject now declares permission for this resource type. After
these manifests merge, sync root metadata before enabling the backend binding.
The live project is not changed by installing the controller. Runtime values,
image availability, pod reachability, and workload SG/routing must be verified
before application sync. The backend remains undeployed during this increment.

See section 24 of [the manual runbook](../../../docs/FLOCI_MANUAL_PROVISIONING.md)
for native IAM, Helm, kubectl, Docker, and fixture commands, and the official
[controller configuration](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/deploy/configurations/)
and [TargetGroupBinding guide](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/targetgroupbinding/targetgroupbinding/).
