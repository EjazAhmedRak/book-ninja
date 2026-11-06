# Book Ninja Hosting and Deployment Design

**Status:** Proposed implementation plan  
**Scope:** Local validation with Floci and production hosting on AWS

## 1. Purpose and principles

Book Ninja is a React/Vite single-page application backed by a FastAPI and LangChain service. The backend persists conversation state in MongoDB and makes outbound calls to OpenAI, Tavily, HardCover, Google token verification, and LangSmith.

Floci is used as the local AWS-compatible environment for infrastructure and deployment testing. It is not a production public-hosting platform. The production target is AWS, with EKS managing the backend, API Gateway providing public API routing, and S3 plus CloudFront hosting the frontend.

All ebook and audiobook search behaviour in production must be limited to licensed, public-domain, or otherwise authorized sources. The system must not retrieve, host, or direct users to infringing copies.

## 2. Target architecture

```text
                                      +---------------------+
                                      |  Google OAuth        |
                                      +----------+----------+
                                                 |
Users                                            | token
  |                                              v
  +--> app.example.com --> CloudFront --> private S3 bucket --> React/Vite assets
  |
  +--> api.example.com --> API Gateway HTTP API --> VPC Link --> internal ALB
                                                                    |
                                                                    v
                                                        EKS Ingress / Service
                                                                    |
                                                                    v
                                                       FastAPI Book Ninja pods
                                                                    |
                                                   private subnets + NAT Gateway
                                                                    |
             +--------------------+--------------------+-----------+--------------+
             |                    |                    |                          |
             v                    v                    v                          v
          MongoDB              OpenAI               Tavily / HardCover         LangSmith
```

### Architecture decisions

- The frontend is a static Vite build. It is served from a private S3 bucket through CloudFront; it is not deployed to EKS.
- The FastAPI backend is a stateless EKS workload. MongoDB stores threads and agent memory.
- API Gateway HTTP API is the public API entry point. A private VPC Link routes calls to an internal ALB created for the Kubernetes ingress.
- EKS nodes and backend pods are in private subnets. Outbound internet traffic uses a NAT Gateway.
- The MongoDB provider must allowlist the NAT Gateway Elastic IP. No database is exposed from the cluster.
- Secrets live in AWS Secrets Manager and are synchronized into Kubernetes at runtime using External Secrets Operator. No live secret is committed to Git, Terraform variables, Docker images, or GitHub Actions logs.
- Kubernetes NetworkPolicies and an egress proxy or AWS Network Firewall restrict outbound connections. Allow only required providers and observability endpoints.
- Deploy the backend with at least two replicas, resource requests and limits, readiness/liveness probes, a PodDisruptionBudget, and a HorizontalPodAutoscaler.

## 3. Environments

| Environment | Purpose | Platform | Deployment source |
| --- | --- | --- | --- |
| Local | Infrastructure, deployment, and integration validation | Floci + emulated EKS/k3s | Local Git checkout |
| Development | Shared team integration | AWS EKS | `develop` image digest / GitOps overlay |
| Production | User-facing service | AWS EKS | Protected release image digest / GitOps overlay |

Use separate MongoDB databases, LangSmith projects, secrets, and DNS hostnames per environment. Floci uses throwaway credentials and a local endpoint, never real AWS credentials.

## 4. Proposed repository layout

```text
backend/
  Dockerfile
  requirements.txt
  main.py
  tests/
frontend/
  package.json
  src/
infra/
  providers.tf
  variables.tf
  vpc.tf
  ecr.tf
  eks.tf
  iam.tf
  s3_cloudfront.tf
  api_gateway.tf
  secrets.tf
  outputs.tf
  environments/
    local.tfvars
    dev.tfvars
    prod.tfvars
gitops/
  charts/book-ninja/
  environments/local/
  environments/dev/
  environments/prod/
  argocd/application.yaml
.github/workflows/
  frontend-ci.yml
  frontend-deploy.yml
  backend-ci.yml
  backend-image.yml
```

---

# Stage 1 — Infrastructure setup using Terraform

## Goal

Provision the AWS foundation reproducibly, then apply the same resource interfaces against Floci for local validation.

## Terraform components

1. **Provider configuration**
   - Configure the standard AWS provider.
   - Use environment-specific variables.
   - For local validation, configure the AWS service endpoints to Floci at `http://localhost:4566` with throwaway access keys.
   - Use an S3 backend and DynamoDB state lock for real environments. Use local state or an emulated S3 backend in Floci.

2. **Network (`vpc.tf`)**
   - VPC spanning at least two availability zones in real AWS.
   - Public subnets for NAT Gateway and public-facing AWS endpoints as required.
   - Private subnets for EKS workers, pods, private ALB, and VPC Link targets.
   - Internet Gateway, route tables, and a NAT Gateway with an Elastic IP.
   - Security groups allowing only API Gateway/VPC Link-to-ALB and ALB-to-EKS traffic.

3. **EKS (`eks.tf`)**
   - EKS cluster and managed node group(s), private endpoint access policy appropriate to the environment.
   - IAM roles for the EKS control plane, nodes, AWS Load Balancer Controller, External Secrets Operator, and Argo CD image access.
   - EKS add-ons: VPC CNI, CoreDNS, kube-proxy, metrics server, and EBS CSI driver where persistent storage is needed.

4. **Container registry (`ecr.tf`)**
   - ECR repository for the backend.
   - Immutable image tags and scan-on-push enabled.
   - Lifecycle policy retaining recent release images and deleting old untagged images.

5. **Frontend (`s3_cloudfront.tf`)**
   - Private S3 bucket with versioning, encryption, public-access block, and lifecycle rules.
   - CloudFront distribution with Origin Access Control.
   - ACM certificate and Route 53 records for the frontend domain in production.

6. **API (`api_gateway.tf`)**
   - API Gateway HTTP API with custom domain such as `api.example.com`.
   - VPC Link private integration to the internal ALB/NLB that fronts the Kubernetes ingress.
   - Routes for `/chat`, `/latestThreads`, `/threads/{proxy+}`, `/health`, and OPTIONS preflight.
   - Access logs, request metrics, throttling, and WAF association for production.

7. **Secrets and observability (`secrets.tf`)**
   - Secret placeholders/references for `OPENAI_API_KEY`, `TAVILY_API_KEY`, `HARDCOVER_API_KEY`, `MONGO_URI`, `LANGSMITH_API_KEY`, and `GOOGLE_CLIENT_ID`.
   - CloudWatch log groups, alarms, and dashboards for API Gateway, EKS workload failures, and deployment errors.

## Local Floci validation

1. Start Floci and load its AWS environment variables.
2. Run `terraform init`, `terraform validate`, and `terraform plan` with `local.tfvars`.
3. Apply supported resources to Floci.
4. Create the emulated EKS cluster, retrieve kubeconfig, and validate `kubectl` access.
5. Validate S3 uploads, ECR behaviour, API Gateway routes, and EKS resource provisioning.
6. Keep Floci-specific provider endpoint overrides isolated from production Terraform.

## Completion criteria

- `terraform fmt -check`, `terraform validate`, and environment plans pass.
- Floci provisions the local test infrastructure without using real AWS credentials.
- AWS production plan creates no publicly accessible S3 bucket, database, or EKS node group.

---

# Stage 2 — GitHub Actions setup

## Goal

Create independent, repeatable CI pipelines for frontend and backend, plus guarded release workflows.

## Authentication model

GitHub Actions authenticates to AWS using GitHub OpenID Connect (OIDC) roles. Do not store long-lived AWS access keys in GitHub secrets. GitHub secrets may contain only values that cannot be obtained through OIDC or a runtime secret manager.

## Frontend workflows

### `.github/workflows/frontend-ci.yml`

Run on pull requests and pushes that affect `frontend/**`:

1. Check out source and set up the pinned Node.js version.
2. Run `npm ci`.
3. Run linting.
4. Run `npx vitest run --coverage`.
5. Run `npm run build` using non-sensitive build variables:
   - `VITE_API_BASE_URL`
   - `VITE_GOOGLE_CLIENT_ID`
6. Upload the `dist/` artifact for inspection and downstream deployment.

### `.github/workflows/frontend-deploy.yml`

Run only after successful CI on protected `main` or a release tag:

1. Download or rebuild the verified `dist/` artifact.
2. Assume the environment-specific AWS role through OIDC.
3. Synchronize `dist/` to the private S3 bucket with cache-control headers:
   - long immutable cache time for hashed assets;
   - short cache time for `index.html`.
4. Create a CloudFront invalidation for `index.html` and any non-hashed entry files.
5. Run a smoke test against the deployed frontend URL.

## Backend workflows

### `.github/workflows/backend-ci.yml`

Run on pull requests and pushes that affect `backend/**`:

1. Check out source and set up the pinned Python version.
2. Install locked dependencies.
3. Run formatting and linting checks.
4. Run `pytest --cov=. --cov-fail-under=80`.
5. Build the Docker image to ensure Dockerfile validity.
6. Run a dependency/container vulnerability scan and upload results.

### `.github/workflows/backend-image.yml`

Run after successful backend CI on protected `main` or release tags:

1. Assume the ECR push role through OIDC.
2. Build a multi-stage backend image.
3. Tag it with the immutable Git commit SHA and release version where applicable.
4. Push to ECR.
5. Resolve and record the image digest.
6. Update only the environment-specific GitOps image digest and open/merge a reviewed deployment change, or commit via a protected release bot.

## Completion criteria

- Pull requests cannot merge when applicable lint, test, coverage, build, or security checks fail.
- Releases are restricted to protected branches/tags and use OIDC.
- The backend release updates a digest, never a mutable `latest` image reference.

---

# Stage 3 — Argo CD setup

## Goal

Install Argo CD once per cluster and make Git the source of truth for application state.

## Bootstrap activities

1. Provision EKS first through Terraform.
2. Install Argo CD into a dedicated `argocd` namespace using a pinned Helm chart version.
3. Configure Argo CD administrative access through SSO or a securely stored bootstrap credential; disable anonymous administration.
4. Configure repository credentials using a deploy key, GitHub App, or workload identity. Do not use a personal access token.
5. Create an `AppProject` that limits Book Ninja to its namespace, approved repositories, and approved destination cluster(s).
6. Apply the root `Application`/ApplicationSet that watches the `gitops/` directory.
7. Enable automated sync for development. Require a manual sync or approved promotion for production.

## Kubernetes platform components

Install and manage these components through the cluster bootstrap:

- AWS Load Balancer Controller for internal ALB provisioning.
- External Secrets Operator for Secrets Manager synchronization.
- Metrics Server for HPA.
- Network-policy-capable CNI/configuration.
- Cert-manager if Kubernetes-managed certificates are needed.

## Completion criteria

- Argo CD reports healthy and synced for its root application.
- Book Ninja manifests are reconciled from Git, not manually applied.
- Argo CD access is least-privilege and audit logs are retained.

---

# Stage 4 — Continuous deployment using Argo CD

## Goal

Deploy a tested, immutable backend image to EKS after a reviewed GitOps change.

## Deployment model

1. Backend CI builds, tests, scans, and pushes an image to ECR.
2. The release workflow writes the ECR **digest** to the target environment overlay, for example `gitops/environments/dev/values.yaml`.
3. A pull request/release approval promotes that exact digest to the next environment.
4. Argo CD observes the Git change and reconciles the Helm chart/Kustomize overlay.
5. Kubernetes performs a rolling deployment only after the new pod passes readiness checks.
6. Argo CD health checks, API smoke tests, and observability alerts confirm the release.
7. Roll back by reverting the GitOps image-digest commit; Argo CD reconciles the previous known-good version.

## Backend container requirements

- Use a multi-stage, non-root Docker build.
- Pin Python dependency versions and avoid build tools in the final runtime image.
- Expose the FastAPI application on a configurable port, normally `8000`.
- Include `/health` for liveness/readiness, while limiting expensive third-party checks to a separate diagnostic/readiness strategy if necessary.
- Supply configuration only through runtime environment variables and secret references.
- Add graceful termination handling so streaming requests are drained during rolling updates.

## Application manifest requirements

- Namespace: `book-ninja`.
- Deployment, Service, Ingress, HPA, PodDisruptionBudget, ServiceAccount, ExternalSecret, NetworkPolicy, and resource quota/limit range.
- `ClusterIP` service only; the ingress controller is the sole route into the workload.
- Use separate overlays for `local`, `dev`, and `prod`.
- Local overlay may use Floci/local registry accommodations but must preserve the production manifest contract.

## Completion criteria

- A merged release commit results in an Argo CD-managed deployment without direct `kubectl apply`.
- Failed readiness checks stop rollout progress.
- Reverting the GitOps commit restores the prior release.

---

# Stage 5 — Application networking setup

## Goal

Expose only the required public endpoints while enabling controlled egress to required services.

## Inbound traffic

| Layer | Responsibility | Exposure |
| --- | --- | --- |
| CloudFront | Serves frontend over HTTPS | Public: `app.example.com` |
| S3 | Stores static frontend files | Private; CloudFront Origin Access Control only |
| API Gateway HTTP API | Public API domain, request controls, routing | Public: `api.example.com` |
| VPC Link | Private API Gateway-to-load-balancer connection | Private |
| Internal ALB / Kubernetes Ingress | Routes API paths to Book Ninja service | Private |
| Kubernetes Service | Stable in-cluster address for FastAPI pods | ClusterIP only |

Configure the frontend with `VITE_API_BASE_URL=https://api.example.com`. Configure CORS on the API to permit only the exact frontend origins for each environment, required methods, and the `Authorization` header. Never use wildcard origins with authenticated requests.

## API routes

| Public route | Backend behaviour | Authentication |
| --- | --- | --- |
| `POST /chat` | SSE/streaming chat agent response | Google ID token |
| `GET /latestThreads` | Recent user threads | Google ID token |
| `GET /threads/{thread_id}/messages` | Thread rehydration | Google ID token |
| `GET /health` | Lightweight service health | Public or restricted, no secret detail |

Validate SSE behaviour through API Gateway, VPC Link, ALB, ingress, and FastAPI before production launch. Configure timeouts and buffering to preserve streaming semantics.

## Outbound traffic and egress controls

The backend requires outbound HTTPS access to:

- MongoDB managed endpoint;
- OpenAI API;
- Tavily and approved book-search/scraping APIs;
- HardCover API;
- LangSmith;
- Google OAuth token-verification endpoints;
- approved lawful audiobook/ebook providers only.

Egress design:

1. Route private-subnet traffic through NAT Gateway(s).
2. Record the NAT Elastic IP and allowlist it at MongoDB.
3. Apply Kubernetes default-deny egress policy, then allow DNS and approved destinations through the egress control layer.
4. Use an egress proxy or AWS Network Firewall where domain-level outbound controls and auditability are required.
5. Apply application-level host allowlists and request timeouts/retries. Do not allow arbitrary user-supplied URLs to be fetched.
6. Set API Gateway throttling, WAF rules, request body limits, and backend concurrency limits to protect LLM and search-provider quotas.

## DNS and certificates

- Use Route 53 public hosted-zone records for `app.example.com` and `api.example.com`.
- Use ACM certificates in `us-east-1` for CloudFront and the correct API Gateway region for the API custom domain.
- Enforce HTTPS and redirect HTTP to HTTPS.

## Completion criteria

- The backend is not directly public from Kubernetes.
- Only approved frontend origins can call authenticated APIs.
- The service can reach required providers, while arbitrary egress is denied or audited.

---

# Stage 6 — Access the application

## User access flow

1. A user opens `https://app.example.com`.
2. CloudFront retrieves the frontend from the private S3 origin.
3. The user signs in with Google OAuth.
4. The frontend retains the Google credential only in memory and sends it as `Authorization: Bearer <token>` to `https://api.example.com`.
5. API Gateway routes the request privately to the EKS backend.
6. The backend validates the Google token, retrieves thread state from MongoDB, and streams the agent response back to the browser.

## Operator access

| Role | Access method | Scope |
| --- | --- | --- |
| Developer | Floci local environment and development GitOps overlay | Local/dev only |
| Platform operator | AWS IAM SSO and EKS/Kubernetes RBAC | Infrastructure and platform components |
| Release manager | Protected GitHub environments and GitOps approval | Production promotion |
| Application operator | Argo CD SSO/RBAC | View/sync approved applications, no cluster-admin by default |

## Pre-launch checklist

- [ ] DNS, ACM certificates, CloudFront, S3, and API Gateway custom domains work over HTTPS.
- [ ] Google OAuth authorized origins and redirect URIs match the frontend domain.
- [ ] MongoDB permits only the NAT egress IP and uses TLS.
- [ ] Secrets are injected at runtime and are absent from Git history, container layers, logs, and Terraform plans.
- [ ] Frontend build passes lint, tests, coverage, and production build checks.
- [ ] Backend passes unit/integration tests, coverage threshold, Docker build, image scan, and health checks.
- [ ] Argo CD application is synced and healthy.
- [ ] `/chat` SSE works through the entire production request path.
- [ ] API rate limits, WAF rules, CORS, authentication, logging, monitoring, and alerting are verified.
- [ ] Egress is restricted to required legal and operational destinations.

## Implementation order

1. Add source applications and dependency lock files, since the current project checkout contains design briefs only.
2. Create the backend Dockerfile and local container smoke test.
3. Build Terraform modules and validate them against Floci.
4. Add frontend and backend CI workflows.
5. Bootstrap the Floci EKS cluster and Argo CD.
6. Add Helm/Kustomize manifests and GitOps applications.
7. Validate local end-to-end deployment.
8. Apply reviewed Terraform to AWS development, configure DNS/secrets, and promote through the GitOps flow.
