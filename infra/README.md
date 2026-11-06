# Terraform infrastructure

This directory begins Stage 1 of `Hosting_Deployment_Design.md`: Terraform provider and state configuration. It does not create cloud resources yet.

## Safety model

- `local_validation = true` targets Floci at `http://localhost:4566` and uses only throwaway `test` credentials.
- AWS environments leave `local_validation = false`, so authentication comes from the standard AWS credential chain (preferably AWS IAM Identity Center or CI OIDC).
- Backend configuration files containing account-specific state locations are ignored by Git. Keep the committed `.example` files as templates only.

## Local Floci validation

Start Floci, then run the following from this directory:

```sh
terraform init
terraform validate
terraform plan -var-file=environments/local.tfvars
```

The root configuration intentionally has no backend block, so local validation keeps state on the workstation and cannot accidentally use a real AWS state bucket.

## AWS development and production

Create private backend files outside Git from the appropriate examples, then initialize with them:

```sh
cp backends/aws.tf.example backend.tf
cp backends/dev.hcl.example backends/dev.hcl
# Edit backends/dev.hcl with the existing state bucket and lock-table names.
terraform init -backend-config=backends/dev.hcl
terraform plan -var-file=environments/dev.tfvars
```

Production follows the same pattern with `prod.hcl` and `prod.tfvars`. The state S3 bucket and DynamoDB lock table must be bootstrapped separately before the first remote Terraform initialization. They must be encrypted, versioned, private, and access-controlled.

## Next infrastructure increment

Add the VPC, subnet, NAT Gateway, route-table, and security-group resources in `vpc.tf`. Keep any Floci service gaps isolated behind `local_validation`; do not weaken production network controls to emulate a local service.
