# Book Ninja: manual Floci provisioning runbook

Last updated: 2026-11-18.

This is the ongoing record of provisioning performed for Book Ninja. Update it
whenever provisioning is added or changed, including commands, identity,
dependencies, verification, and any Floci-specific behavior.

## Scope and execution rules

This runbook replaces the four Python helpers with AWS CLI commands and also
shows the CLI equivalents of the infrastructure currently managed by Terraform.
No Python script is required to follow the manual path.

The create commands are a **fresh-environment recipe**, not commands to rerun
blindly against the existing environment. Our bucket, IAM users, VPC, cluster,
and repository already exist. Creating another access key rotates nothing: it
creates an additional key. IAM secret access keys are returned at creation;
`list-access-keys` returns metadata, not the secret.

Choose one owner for application infrastructure:

- **Normal project workflow:** create the state/provisioning prerequisites, then
  let Terraform create VPC/EKS/ECR. Use the inspection commands to learn.
- **Manual learning workflow:** create VPC/EKS/ECR with the commands below in a
  separate fresh Floci environment. Do not subsequently run Terraform apply
  against those same resources until they have been imported into its state.

These commands target local Floci, account `000000000000`, region `us-east-1`.
They are not a production AWS deployment recipe. All examples use native CLI
commands directly, without command wrappers. Keep future additions in this form.

## 1. Tools, directory, and emulator

Install missing CLI tools on macOS; start Docker Desktop separately:

```sh
brew install hashicorp/tap/terraform
brew install awscli jq
terraform version
aws --version
kubectl version --client
docker compose version
cd /Users/ejazahmedansari/Desktop/projects/book-ninja-be/infra
```

Run all subsequent commands from `infra/` in the same shell so captured IDs
remain available. `kubectl` was already installed on this machine; install it
with `brew install kubernetes-cli` if missing.

### Seed the bootstrap deployer identity

The actual username is **`floci-deployer`** (hyphen), not `floci_deployer`.
Seeding happens inside Floci at startup, before the AWS CLI is authenticated.
In `infra/docker-compose.floci.yml`, configure the service as follows. The
checked-in file already contains these settings:

```yaml
services:
  floci:
    image: floci/floci:latest
    ports:
      - "4566:4566"
    environment:
      FLOCI_STORAGE_MODE: persistent
      FLOCI_STORAGE_PERSISTENT_PATH: /app/data
      FLOCI_SERVICES_IAM_ENFORCEMENT_ENABLED: "true"
      FLOCI_SERVICES_IAM_SEED_DEPLOYER_PRINCIPAL: "true"
      FLOCI_SERVICES_S3_ENFORCE_AUTH: "true"
    volumes:
      - floci-data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock

volumes:
  floci-data:
```

`FLOCI_SERVICES_IAM_SEED_DEPLOYER_PRINCIPAL` is the setting that:

1. Creates the local `floci-deployer` IAM user if absent.
2. Attaches `arn:aws:iam::aws:policy/AdministratorAccess`.
3. Seeds access key ID `floci` and secret access key `floci` if that key is absent.

This built-in seed is how we obtain the initial administrator used to create
the restricted state and provisioning users. An ordinary `iam create-access-key`
call generates a new key pair; it cannot request the fixed `floci` / `floci` pair.
The Docker socket mount is separately needed for k3s and registry containers.

```sh
docker compose -f docker-compose.floci.yml up -d
docker compose -f docker-compose.floci.yml ps
docker compose -f docker-compose.floci.yml logs --tail=80 floci
```

If Floci was already running before you added the seed setting, recreate its
container so the new environment is applied. A plain `docker restart` does not
apply changes to Compose environment variables:

```sh
docker compose -f docker-compose.floci.yml up -d --force-recreate floci
docker compose -f docker-compose.floci.yml logs --tail=80 floci
```

On first seeding, logs should report `Seeded default IAM deployer user:
floci-deployer` and `Seeded default IAM deployer access key: floci`. Those messages
may be absent on later starts because existing users and keys are preserved.
Recreating the container preserves the named data volume. On our existing setup,
the deployer has already been seeded, so this recreation is unnecessary.

Look for persistent storage and IAM enforcement in the startup log. The named
volume preserves Floci state. `docker compose down` preserves the volume;
adding `-v` deletes it, including the state bucket and IAM data.

## 2. Configure the bootstrap AWS CLI profile

The Compose setting `FLOCI_SERVICES_IAM_SEED_DEPLOYER_PRINCIPAL=true` seeds
`floci-deployer` with local administrator credentials `floci` / `floci`.
These are emulator bootstrap credentials, not a real AWS account's keys.

```sh
export FLOCI_ENDPOINT=http://localhost:4566
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export AWS_PAGER=''
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
umask 077
aws configure set aws_access_key_id floci --profile book-ninja-floci-bootstrap
aws configure set aws_secret_access_key floci --profile book-ninja-floci-bootstrap
aws configure set region us-east-1 --profile book-ninja-floci-bootstrap
export AWS_PROFILE=book-ninja-floci-bootstrap
aws --endpoint-url "$FLOCI_ENDPOINT" sts get-caller-identity
```

Expected ARN: `arn:aws:iam::000000000000:user/floci-deployer`.
Profiles store credentials in your standard local AWS credential files. The
`unset` avoids previously exported keys overriding a selected profile.

Verify the seeded user, administrator attachment, and active key metadata:

```sh
aws --endpoint-url "$FLOCI_ENDPOINT" iam get-user --user-name floci-deployer
aws --endpoint-url "$FLOCI_ENDPOINT" iam list-attached-user-policies --user-name floci-deployer
aws --endpoint-url "$FLOCI_ENDPOINT" iam list-access-keys --user-name floci-deployer
```

Expect `AdministratorAccess` in the policy list and active access key ID `floci`.
The secret is known from the seed configuration, not retrieved by listing keys.
If identity verification fails, check the seed flag and recreate the container
before proceeding; do not delete the persistent volume to fix authentication.

## 3. Create the Terraform state bucket

```sh
aws --endpoint-url "$FLOCI_ENDPOINT" s3api list-buckets
aws --endpoint-url "$FLOCI_ENDPOINT" s3api create-bucket \
  --bucket book-ninja-tfstate
aws --endpoint-url "$FLOCI_ENDPOINT" s3api put-bucket-versioning \
  --bucket book-ninja-tfstate --versioning-configuration '{"Status":"Enabled"}'
aws --endpoint-url "$FLOCI_ENDPOINT" s3api put-public-access-block \
  --bucket book-ninja-tfstate --public-access-block-configuration \
  '{"BlockPublicAcls":true,"IgnorePublicAcls":true,"BlockPublicPolicy":true,"RestrictPublicBuckets":true}'
aws --endpoint-url "$FLOCI_ENDPOINT" s3api get-bucket-versioning \
  --bucket book-ninja-tfstate
aws --endpoint-url "$FLOCI_ENDPOINT" s3api get-public-access-block \
  --bucket book-ninja-tfstate
```

The bucket must exist before initializing an S3 Terraform backend. This is the
`us-east-1` create-bucket form; other real AWS regions need a location constraint.
Versioning preserves previous state objects. Public-access blocking keeps the
state store private. These are the settings our bootstrap actually applies;
it does not configure a custom KMS key.

## 4. Create the DynamoDB state-lock table

```sh
aws --endpoint-url "$FLOCI_ENDPOINT" dynamodb list-tables
aws --endpoint-url "$FLOCI_ENDPOINT" dynamodb create-table \
  --table-name book-ninja-tflock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
aws --endpoint-url "$FLOCI_ENDPOINT" dynamodb wait table-exists \
  --table-name book-ninja-tflock
aws --endpoint-url "$FLOCI_ENDPOINT" dynamodb describe-table \
  --table-name book-ninja-tflock --query 'Table.{status:TableStatus,key:KeySchema}'
```

Terraform uses the string partition key `LockID` for locking. DynamoDB backend
locking is deprecated in current Terraform, but retained to match our deployed
configuration. We have not switched to S3 lock files.

## 5. Create the restricted state IAM user and policy

```sh
aws --endpoint-url "$FLOCI_ENDPOINT" iam create-user \
  --user-name book-ninja-terraform-state
aws --endpoint-url "$FLOCI_ENDPOINT" iam put-user-policy \
  --user-name book-ninja-terraform-state --policy-name TerraformState \
  --policy-document '{
    "Version":"2012-10-17",
    "Statement":[
      {"Effect":"Allow","Action":["s3:ListBucket"],
       "Resource":"arn:aws:s3:::book-ninja-tfstate"},
      {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject"],
       "Resource":"arn:aws:s3:::book-ninja-tfstate/local/*"},
      {"Effect":"Allow","Action":["dynamodb:DescribeTable","dynamodb:GetItem","dynamodb:PutItem","dynamodb:DeleteItem"],
       "Resource":"arn:aws:dynamodb:us-east-1:000000000000:table/book-ninja-tflock"}
    ]
  }'
aws --endpoint-url "$FLOCI_ENDPOINT" iam get-user-policy \
  --user-name book-ninja-terraform-state --policy-name TerraformState
```

### Generate and save the key without printing the secret

Run this only when creating a new key. On the existing setup, keep the current
credential file and skip key creation. `umask 077` makes newly created files
owner-only; `chmod` also handles a pre-existing file before overwriting it.

```sh
touch local.auto.tfvars.json
chmod 600 local.auto.tfvars.json
aws --endpoint-url "$FLOCI_ENDPOINT" iam create-access-key \
  --user-name book-ninja-terraform-state \
  --query '{local_aws_access_key:AccessKey.AccessKeyId,local_aws_secret_key:AccessKey.SecretAccessKey}' \
  --output json > local.auto.tfvars.json
aws --endpoint-url "$FLOCI_ENDPOINT" iam list-access-keys \
  --user-name book-ninja-terraform-state
```

`create-access-key` is exactly where the script obtained the secrets. Its
`AccessKeyId` and `SecretAccessKey` response fields are renamed by `--query`
to the Terraform variable names. `list-access-keys` cannot retrieve a lost secret.
Check that key creation succeeded before continuing; shell redirection truncates
the destination even if the AWS command fails. Back up an existing credential
file before intentionally replacing it.

Configure a profile from that file and test the restricted identity:

```sh
aws configure set aws_access_key_id \
  "$(jq -r '.local_aws_access_key' local.auto.tfvars.json)" --profile book-ninja-floci-state
aws configure set aws_secret_access_key \
  "$(jq -r '.local_aws_secret_key' local.auto.tfvars.json)" --profile book-ninja-floci-state
aws configure set region us-east-1 --profile book-ninja-floci-state
aws --profile book-ninja-floci-state --endpoint-url "$FLOCI_ENDPOINT" sts get-caller-identity
aws --profile book-ninja-floci-state --endpoint-url "$FLOCI_ENDPOINT" \
  s3api list-objects-v2 --bucket book-ninja-tfstate --prefix local/
aws --profile book-ninja-floci-state --endpoint-url "$FLOCI_ENDPOINT" iam list-users
```

The last command must return `AccessDenied`. The identity ARN must end with
`user/book-ninja-terraform-state`. An empty bucket listing is normal before
Terraform writes state. The profile flags above do not change the bootstrap
profile used by subsequent setup commands.

## 6. Create the infrastructure provisioning IAM user

This identity is separate from backend/state access. Its name is historical:
it now provisions EKS/ECR as well as networking. The following policy mirrors
`bootstrap_provisioner.py`; the EKS/ECR grants are broad within the emulator,
not a hardened production IAM policy.

```sh
aws --endpoint-url "$FLOCI_ENDPOINT" iam create-user \
  --user-name book-ninja-network-provisioner
aws --endpoint-url "$FLOCI_ENDPOINT" iam put-user-policy \
  --user-name book-ninja-network-provisioner --policy-name LocalNetworkProvisioning \
  --policy-document '{
    "Version":"2012-10-17",
    "Statement":[
      {"Effect":"Allow","Resource":"*","Action":[
        "ec2:Describe*","ec2:CreateVpc","ec2:DeleteVpc","ec2:ModifyVpcAttribute",
        "ec2:CreateSubnet","ec2:DeleteSubnet","ec2:ModifySubnetAttribute",
        "ec2:CreateInternetGateway","ec2:DeleteInternetGateway","ec2:AttachInternetGateway","ec2:DetachInternetGateway",
        "ec2:CreateRouteTable","ec2:DeleteRouteTable","ec2:CreateRoute","ec2:DeleteRoute","ec2:ReplaceRoute",
        "ec2:AssociateRouteTable","ec2:DisassociateRouteTable","ec2:AllocateAddress","ec2:ReleaseAddress",
        "ec2:CreateNatGateway","ec2:DeleteNatGateway","ec2:CreateSecurityGroup","ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress","ec2:RevokeSecurityGroupIngress",
        "ec2:AuthorizeSecurityGroupEgress","ec2:RevokeSecurityGroupEgress","ec2:CreateTags","ec2:DeleteTags"
      ]},
      {"Effect":"Allow","Action":["eks:*","ecr:*"],"Resource":"*"},
      {"Effect":"Allow","Action":["s3:*"],"Resource":["arn:aws:s3:::book-ninja-local-frontend-*","arn:aws:s3:::book-ninja-local-frontend-*/*"]},
      {"Effect":"Allow","Action":["cloudfront:*"],"Resource":"*"},
      {"Effect":"Allow","Action":["secretsmanager:*"],"Resource":"arn:aws:secretsmanager:us-east-1:000000000000:secret:book-ninja/local/*"},
      {"Effect":"Allow","Resource":"arn:aws:iam::000000000000:role/book-ninja-local-*","Action":[
        "iam:CreateRole","iam:GetRole","iam:DeleteRole","iam:TagRole","iam:UntagRole",
        "iam:ListRolePolicies","iam:ListAttachedRolePolicies","iam:ListInstanceProfilesForRole",
        "iam:AttachRolePolicy","iam:DetachRolePolicy","iam:PassRole"
      ]}
    ]
  }'
```

Generate this user's key only if it does not already have a saved active key:

```sh
touch local.provisioner.auto.tfvars.json
chmod 600 local.provisioner.auto.tfvars.json
aws --endpoint-url "$FLOCI_ENDPOINT" iam create-access-key \
  --user-name book-ninja-network-provisioner \
  --query '{local_provisioning_access_key:AccessKey.AccessKeyId,local_provisioning_secret_key:AccessKey.SecretAccessKey}' \
  --output json > local.provisioner.auto.tfvars.json
aws configure set aws_access_key_id \
  "$(jq -r '.local_provisioning_access_key' local.provisioner.auto.tfvars.json)" --profile book-ninja-floci-provisioner
aws configure set aws_secret_access_key \
  "$(jq -r '.local_provisioning_secret_key' local.provisioner.auto.tfvars.json)" --profile book-ninja-floci-provisioner
aws configure set region us-east-1 --profile book-ninja-floci-provisioner
export AWS_PROFILE=book-ninja-floci-provisioner
aws --endpoint-url "$FLOCI_ENDPOINT" sts get-caller-identity
```

This profile plus `--endpoint-url` replaces `floci_aws.py`. Keep credentials out
of Markdown, Git, and command transcripts. All generated project credential
files are already ignored by Git.

## 7. Configure Terraform backend files manually (normal Terraform path)

This section replaces the file-writing part of `bootstrap_floci.py`. Use an
editor to create the ignored files below. Do not run both this manual variant
and the script expecting byte-identical backend files: the script embeds keys,
whereas this manual variant references the state profile configured above.

`infra/backend.tf`:

```hcl
terraform {
  backend "s3" {}
}
```

`infra/backends/local.hcl`:

```hcl
bucket         = "book-ninja-tfstate"
key            = "local/terraform.tfstate"
region         = "us-east-1"
profile        = "book-ninja-floci-state"
dynamodb_table = "book-ninja-tflock"
endpoints = {
  s3       = "http://localhost:4566"
  dynamodb = "http://localhost:4566"
}
skip_credentials_validation = true
skip_region_validation      = true
skip_requesting_account_id  = true
skip_metadata_api_check     = true
use_path_style              = true
```

The state profile is used by the backend; the generated provisioning variables
are used by the AWS provider. Terraform does not pass provider credentials to
its backend. Its `*.auto.tfvars.json` files are loaded automatically.

For a first migration from local state:

```sh
chmod 600 backend.tf backends/local.hcl
terraform init -migrate-state -backend-config=backends/local.hcl
terraform fmt -check -recursive
terraform validate
terraform test
terraform plan -var-file=environments/local.tfvars
terraform apply -var-file=environments/local.tfvars
terraform output
```

Review the plan before confirming apply. Do not combine `-reconfigure` with
`-migrate-state`. If only changing the authentication configuration of an
already configured backend, use `init -reconfigure` after confirming the bucket
and state key still identify the same state. **If Terraform did the apply,
skip create commands in sections 8-12 and use their describe commands only.**

## 8. Manual VPC and subnet creation (alternative to Terraform)

Use the provisioning profile from section 6. The `$(...)` expressions capture
resource IDs without hardcoding IDs from our machine. Keep this shell open.

```sh
export AWS_PROFILE=book-ninja-floci-provisioner
VPC_ID=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-vpc \
  --cidr-block 10.60.0.0/16 \
  --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=book-ninja-local},{Key=Project,Value=book-ninja},{Key=Environment,Value=local},{Key=ManagedBy,Value=manual-cli}]' \
  --query Vpc.VpcId --output text)
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 wait vpc-available --vpc-ids "$VPC_ID"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-support '{"Value":true}'
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-hostnames '{"Value":true}'

PUBLIC_A=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-subnet --vpc-id "$VPC_ID" \
  --cidr-block 10.60.0.0/20 --availability-zone us-east-1a --query Subnet.SubnetId --output text)
PUBLIC_B=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-subnet --vpc-id "$VPC_ID" \
  --cidr-block 10.60.16.0/20 --availability-zone us-east-1b --query Subnet.SubnetId --output text)
PRIVATE_A=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-subnet --vpc-id "$VPC_ID" \
  --cidr-block 10.60.128.0/20 --availability-zone us-east-1a --query Subnet.SubnetId --output text)
PRIVATE_B=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-subnet --vpc-id "$VPC_ID" \
  --cidr-block 10.60.144.0/20 --availability-zone us-east-1b --query Subnet.SubnetId --output text)

for SUBNET_ID in "$PUBLIC_A" "$PUBLIC_B" "$PRIVATE_A" "$PRIVATE_B"; do
  aws --endpoint-url "$FLOCI_ENDPOINT" ec2 modify-subnet-attribute \
    --subnet-id "$SUBNET_ID" --no-map-public-ip-on-launch
  aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$SUBNET_ID" \
    --tags Key=Project,Value=book-ninja Key=Environment,Value=local Key=ManagedBy,Value=manual-cli
done
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$PUBLIC_A" --tags Key=Name,Value=book-ninja-local-public-1 Key=kubernetes.io/role/elb,Value=1
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$PUBLIC_B" --tags Key=Name,Value=book-ninja-local-public-2 Key=kubernetes.io/role/elb,Value=1
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$PRIVATE_A" --tags Key=Name,Value=book-ninja-local-private-1 Key=kubernetes.io/role/internal-elb,Value=1
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$PRIVATE_B" --tags Key=Name,Value=book-ninja-local-private-2 Key=kubernetes.io/role/internal-elb,Value=1
```

Public subnets are public because of their route table, not automatic public-IP
assignment. Keep `10.42/16` (k3s pods) and `10.100/16` (services) separate from
the VPC range.

## 9. Internet Gateway, routes, Elastic IP, and NAT

```sh
IGW_ID=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-internet-gateway \
  --query InternetGateway.InternetGatewayId --output text)
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 attach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID"
PUBLIC_RT=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-route-table \
  --vpc-id "$VPC_ID" --query RouteTable.RouteTableId --output text)
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-route --route-table-id "$PUBLIC_RT" --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 associate-route-table --route-table-id "$PUBLIC_RT" --subnet-id "$PUBLIC_A"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 associate-route-table --route-table-id "$PUBLIC_RT" --subnet-id "$PUBLIC_B"

EIP_ID=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 allocate-address --domain vpc --query AllocationId --output text)
NAT_ID=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-nat-gateway \
  --subnet-id "$PUBLIC_A" --allocation-id "$EIP_ID" --query NatGateway.NatGatewayId --output text)
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_ID"
PRIVATE_RT_A=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-route-table --vpc-id "$VPC_ID" --query RouteTable.RouteTableId --output text)
PRIVATE_RT_B=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-route-table --vpc-id "$VPC_ID" --query RouteTable.RouteTableId --output text)
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-route --route-table-id "$PRIVATE_RT_A" --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_ID"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-route --route-table-id "$PRIVATE_RT_B" --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_ID"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 associate-route-table --route-table-id "$PRIVATE_RT_A" --subnet-id "$PRIVATE_A"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 associate-route-table --route-table-id "$PRIVATE_RT_B" --subnet-id "$PRIVATE_B"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 describe-nat-gateways --nat-gateway-ids "$NAT_ID"
```

This is the local one-NAT topology. AWS Terraform configuration uses a NAT in
each AZ instead. Floci's Elastic IP is emulated, not the actual internet source
IP of your laptop. NAT routing alone does not enforce a provider/domain allowlist.

For parity with Terraform, tag these resources as well:

```sh
for RESOURCE_ID in "$IGW_ID" "$PUBLIC_RT" "$PRIVATE_RT_A" "$PRIVATE_RT_B" "$EIP_ID" "$NAT_ID"; do
  aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$RESOURCE_ID" \
    --tags Key=Project,Value=book-ninja Key=Environment,Value=local Key=ManagedBy,Value=manual-cli
done
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$IGW_ID" --tags Key=Name,Value=book-ninja-local
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$PUBLIC_RT" --tags Key=Name,Value=book-ninja-local-public
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$PRIVATE_RT_A" --tags Key=Name,Value=book-ninja-local-private-1
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$PRIVATE_RT_B" --tags Key=Name,Value=book-ninja-local-private-2
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$EIP_ID" "$NAT_ID" --tags Key=Name,Value=book-ninja-local-nat-1
```

## 10. Security groups for the future private API path

```sh
LINK_SG=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-security-group --vpc-id "$VPC_ID" \
  --group-name book-ninja-local-vpc-link --description 'API Gateway VPC Link ENIs' --query GroupId --output text)
ALB_SG=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-security-group --vpc-id "$VPC_ID" \
  --group-name book-ninja-local-internal-alb --description 'Internal ALB accepts only VPC Link traffic' --query GroupId --output text)
BACKEND_SG=$(aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-security-group --vpc-id "$VPC_ID" \
  --group-name book-ninja-local-backend --description 'Backend targets accept only internal ALB traffic' --query GroupId --output text)

# Remove the default IPv4 allow-all egress rule from each newly created group.
for GROUP_ID in "$LINK_SG" "$ALB_SG" "$BACKEND_SG"; do
  aws --endpoint-url "$FLOCI_ENDPOINT" ec2 revoke-security-group-egress --group-id "$GROUP_ID" \
    --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]'
  aws --endpoint-url "$FLOCI_ENDPOINT" ec2 create-tags --resources "$GROUP_ID" \
    --tags Key=Project,Value=book-ninja Key=Environment,Value=local Key=ManagedBy,Value=manual-cli
done
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 authorize-security-group-egress --group-id "$LINK_SG" \
  --ip-permissions "[{\"IpProtocol\":\"tcp\",\"FromPort\":80,\"ToPort\":80,\"UserIdGroupPairs\":[{\"GroupId\":\"$ALB_SG\"}]}]"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 authorize-security-group-ingress --group-id "$ALB_SG" --protocol tcp --port 80 --source-group "$LINK_SG"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 authorize-security-group-egress --group-id "$ALB_SG" \
  --ip-permissions "[{\"IpProtocol\":\"tcp\",\"FromPort\":8000,\"ToPort\":8000,\"UserIdGroupPairs\":[{\"GroupId\":\"$BACKEND_SG\"}]}]"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 authorize-security-group-ingress --group-id "$BACKEND_SG" --protocol tcp --port 8000 --source-group "$ALB_SG"
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 describe-security-groups --group-ids "$LINK_SG" "$ALB_SG" "$BACKEND_SG"
```

If a default rule is already absent, inspect the group before skipping its
revoke command. The path is VPC Link -> ALB TCP 80 -> backend TCP 8000.
These groups reserve future connections; they are not yet attached to a running
Book Ninja service. Backend egress, ALB, and VPC Link still need implementation.

## 11. EKS IAM roles, cluster, and node group

Create roles before the resources that reference them:

```sh
CLUSTER_ROLE=$(aws --endpoint-url "$FLOCI_ENDPOINT" iam create-role \
  --role-name book-ninja-local-eks-cluster \
  --tags Key=Project,Value=book-ninja Key=Environment,Value=local Key=ManagedBy,Value=manual-cli \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"eks.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  --query Role.Arn --output text)
aws --endpoint-url "$FLOCI_ENDPOINT" iam attach-role-policy --role-name book-ninja-local-eks-cluster \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy
NODE_ROLE=$(aws --endpoint-url "$FLOCI_ENDPOINT" iam create-role \
  --role-name book-ninja-local-eks-nodes \
  --tags Key=Project,Value=book-ninja Key=Environment,Value=local Key=ManagedBy,Value=manual-cli \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  --query Role.Arn --output text)
for POLICY in AmazonEKSWorkerNodePolicy AmazonEKS_CNI_Policy AmazonEC2ContainerRegistryReadOnly; do
  aws --endpoint-url "$FLOCI_ENDPOINT" iam attach-role-policy \
    --role-name book-ninja-local-eks-nodes --policy-arn "arn:aws:iam::aws:policy/$POLICY"
done

aws --endpoint-url "$FLOCI_ENDPOINT" eks create-cluster \
  --name book-ninja-local --kubernetes-version 1.32 --role-arn "$CLUSTER_ROLE" \
  --no-bootstrap-self-managed-addons \
  --resources-vpc-config "subnetIds=$PRIVATE_A,$PRIVATE_B,endpointPrivateAccess=true,endpointPublicAccess=true" \
  --tags Project=book-ninja,Environment=local,ManagedBy=manual-cli
aws --endpoint-url "$FLOCI_ENDPOINT" eks wait cluster-active --name book-ninja-local
aws --endpoint-url "$FLOCI_ENDPOINT" eks describe-cluster --name book-ninja-local \
  --query 'cluster.{status:status,endpoint:endpoint,version:version}'

aws --endpoint-url "$FLOCI_ENDPOINT" eks create-nodegroup \
  --cluster-name book-ninja-local --nodegroup-name book-ninja-local-workers \
  --node-role "$NODE_ROLE" --subnets "$PRIVATE_A" "$PRIVATE_B" \
  --instance-types t3.medium --scaling-config minSize=1,maxSize=3,desiredSize=1 \
  --tags Project=book-ninja,Environment=local,ManagedBy=manual-cli
aws --endpoint-url "$FLOCI_ENDPOINT" eks wait nodegroup-active \
  --cluster-name book-ninja-local --nodegroup-name book-ninja-local-workers
aws --endpoint-url "$FLOCI_ENDPOINT" eks describe-nodegroup \
  --cluster-name book-ninja-local --nodegroup-name book-ninja-local-workers
```

Local Floci runs a real k3s Docker container; AZ/node-group values partly model
AWS metadata rather than creating a multi-AZ Kubernetes deployment. k3s supplies
CoreDNS and metrics-server; the AWS CNI policy attachment does not install the
AWS VPC CNI locally. AWS Terraform configuration uses a private API endpoint,
two desired/minimum workers, and default addon bootstrapping instead.

Observed compatibility issue: Floci 2.4.0 created the cluster while provider
5.100.0's create call kept retrying. Check `describe-cluster` before retrying
creation. If Terraform failed but the cluster is ACTIVE, stop the apply
gracefully and reconcile it with:

```sh
terraform import -var-file=environments/local.tfvars aws_eks_cluster.main book-ninja-local
terraform plan -var-file=environments/local.tfvars
```

Do not import into an address already present in state or accept a replacement
plan without understanding it. Local addon bootstrapping is explicitly disabled
in our Terraform configuration to avoid a replacement difference after import.

## 12. ECR backend repository

```sh
aws --endpoint-url "$FLOCI_ENDPOINT" ecr create-repository \
  --repository-name book-ninja-local-backend --image-tag-mutability IMMUTABLE \
  --image-scanning-configuration scanOnPush=true \
  --tags Key=Project,Value=book-ninja Key=Environment,Value=local Key=ManagedBy,Value=manual-cli
aws --endpoint-url "$FLOCI_ENDPOINT" ecr put-lifecycle-policy \
  --repository-name book-ninja-local-backend --lifecycle-policy-text '{"rules":[{
    "rulePriority":1,"description":"Remove untagged images after seven days",
    "selection":{"tagStatus":"untagged","countType":"sinceImagePushed","countUnit":"days","countNumber":7},
    "action":{"type":"expire"}
  }]}'
aws --endpoint-url "$FLOCI_ENDPOINT" ecr describe-repositories \
  --repository-names book-ninja-local-backend
aws --endpoint-url "$FLOCI_ENDPOINT" ecr get-lifecycle-policy \
  --repository-name book-ninja-local-backend
```

This creates the repository and its settings. Building, pushing, scanning,
and deploying an image are separate actions. We have built the backend image
locally, but have not verified an image push or scanner behavior in Floci.

## 13. Configure kubectl without the Python helpers

Keep `AWS_PROFILE=book-ninja-floci-provisioner`; use a real generated local IAM
key, not the public bootstrap pair. AWS CLI can generate the endpoint, CA, and
token-exec configuration itself:

```sh
mkdir -p manual
aws --profile book-ninja-floci-provisioner --endpoint-url "$FLOCI_ENDPOINT" \
  eks update-kubeconfig --name book-ninja-local --kubeconfig manual/kubeconfig \
  --alias book-ninja-local --user-alias book-ninja-local
chmod 600 manual/kubeconfig
aws --endpoint-url "$FLOCI_ENDPOINT" sts get-caller-identity
kubectl --kubeconfig manual/kubeconfig get nodes
kubectl --kubeconfig manual/kubeconfig wait --for=condition=Ready nodes --all --timeout=120s
kubectl --kubeconfig manual/kubeconfig -n kube-system rollout status deployment/coredns --timeout=120s
kubectl --kubeconfig manual/kubeconfig -n kube-system rollout status deployment/metrics-server --timeout=120s
kubectl --kubeconfig manual/kubeconfig top nodes
```

`update-kubeconfig` records an AWS CLI `eks get-token` exec command and the chosen
profile. Token generation signs a request locally; it does not need to call real
AWS STS. Floci validates the resulting token. Unlike `configure_kubeconfig.py`,
this manual variant reads credentials from the AWS profile instead of the
project's JSON file. Both keep raw IAM secrets out of kubeconfig. Refresh the
kubeconfig after cluster recreation because its CA or endpoint can change.

The `manual/` directory is ignored by Git. Do not check in credentials or tokens.

## 14. Backend build and checks completed so far

These are Docker/test commands, not AWS provisioning. From `infra/`:

```sh
docker build -t book-ninja-backend:floci-dev ../apps/backend
env PYTHONPATH=../apps/backend/src ../apps/backend/venv/bin/python \
  -m pytest ../apps/backend/tests/test_health.py -q
```

The backend virtual environment must already have its requirements installed.
The runtime image now copies only `src/`, excludes local environment files from
its build context, and offers `/livez` for lightweight Kubernetes probes.
The `/health` endpoint remains the integration diagnostic route. A successful
image build is not an application deployment.

## 15. Inspect the existing Terraform-managed setup

For the current environment, prefer these read-only commands over recreation:

```sh
terraform output
terraform state list
terraform plan -var-file=environments/local.tfvars -detailed-exitcode
aws --endpoint-url "$FLOCI_ENDPOINT" ec2 describe-vpcs --filters Name=tag:Project,Values=book-ninja
aws --endpoint-url "$FLOCI_ENDPOINT" eks describe-cluster --name book-ninja-local
aws --endpoint-url "$FLOCI_ENDPOINT" ecr describe-repositories --repository-names book-ninja-local-backend
```

Plan exit code 0 means no changes, 2 means a nonempty plan, and 1 means an error.
If a new shell lost the resource ID variables, recover existing IDs from
`terraform output` rather than repeating create commands. Shell variables are
temporary and are not Terraform state. `terraform state pull` reads the remote
snapshot but may reveal sensitive values as the system grows.

## 16. Restart the persisted local environment

On 2026-11-18 Docker Desktop was stopped as well as the Floci container. Start
the daemon first, then Floci; do not recreate volumes or IAM keys:

```sh
open -a Docker
# Wait until this succeeds; Docker Desktop may take a little time to start.
docker info --format '{{.ServerVersion}}'
docker compose -f docker-compose.floci.yml up -d
docker compose -f docker-compose.floci.yml ps
aws --endpoint-url "$FLOCI_ENDPOINT" eks describe-cluster --name book-ninja-local
kubectl --kubeconfig manual/kubeconfig get nodes
terraform plan -var-file=environments/local.tfvars -detailed-exitcode
```

Use the provisioning profile from section 6. If this is a new shell, export
`FLOCI_ENDPOINT=http://localhost:4566`, `AWS_REGION=us-east-1`, and
`AWS_PROFILE=book-ninja-floci-provisioner` again. The normal helper-generated
kubeconfig path is `local.kubeconfig.json`; `manual/kubeconfig` refers to section
13's CLI-generated variant. Refresh it after endpoint or CA changes.

## 17. Private frontend S3 and CloudFront

Identity: the local provisioning user. Its policy now includes frontend-bucket
access limited to `book-ninja-local-frontend-*`, CloudFront management, and the
backend Secrets Manager path. On an existing setup, reapply the updated section
6 policy using `--profile book-ninja-floci-bootstrap`; do not create another
user or access key. Alternatively, our updated `bootstrap_provisioner.py`
refreshes the policy while reusing its saved active key.

The normal path is Terraform: review the nine-resource addition and apply it.
The following commands are the **alternative manual path in a fresh emulator**.
Terraform uses a generated unique bucket suffix; the manual name below uses
`manual` as its suffix and still matches the scoped IAM policy.

```sh
export AWS_PROFILE=book-ninja-floci-provisioner
FRONTEND_BUCKET=book-ninja-local-frontend-manual
aws --endpoint-url "$FLOCI_ENDPOINT" s3api create-bucket --bucket "$FRONTEND_BUCKET"
aws --endpoint-url "$FLOCI_ENDPOINT" s3api put-bucket-versioning \
  --bucket "$FRONTEND_BUCKET" --versioning-configuration '{"Status":"Enabled"}'
aws --endpoint-url "$FLOCI_ENDPOINT" s3api put-bucket-encryption --bucket "$FRONTEND_BUCKET" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws --endpoint-url "$FLOCI_ENDPOINT" s3api put-public-access-block --bucket "$FRONTEND_BUCKET" \
  --public-access-block-configuration '{"BlockPublicAcls":true,"IgnorePublicAcls":true,"BlockPublicPolicy":true,"RestrictPublicBuckets":true}'
aws --endpoint-url "$FLOCI_ENDPOINT" s3api put-bucket-lifecycle-configuration --bucket "$FRONTEND_BUCKET" \
  --lifecycle-configuration '{"Rules":[{"ID":"retire-old-versions","Status":"Enabled","Filter":{},"NoncurrentVersionExpiration":{"NoncurrentDays":30},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":7}}]}'
aws --endpoint-url "$FLOCI_ENDPOINT" s3api put-bucket-tagging --bucket "$FRONTEND_BUCKET" \
  --tagging '{"TagSet":[{"Key":"Project","Value":"book-ninja"},{"Key":"Environment","Value":"local"},{"Key":"ManagedBy","Value":"manual-cli"}]}'
OAC_ID=$(aws --endpoint-url "$FLOCI_ENDPOINT" cloudfront create-origin-access-control \
  --origin-access-control-config '{"Name":"book-ninja-local-frontend","OriginAccessControlOriginType":"s3","SigningBehavior":"always","SigningProtocol":"sigv4"}' \
  --query OriginAccessControl.Id --output text)
mkdir -p manual
jq -n --arg bucket "$FRONTEND_BUCKET" --arg oac "$OAC_ID" --arg ref "book-ninja-manual-$(date +%s)" '{
  CallerReference:$ref, Comment:"book-ninja-local frontend", Enabled:true,
  DefaultRootObject:"index.html", IsIPV6Enabled:true, PriceClass:"PriceClass_100",
  Origins:{Quantity:1,Items:[{Id:"frontend-s3",DomainName:($bucket+".s3.us-east-1.amazonaws.com"),
    OriginAccessControlId:$oac,S3OriginConfig:{OriginAccessIdentity:""}}]},
  DefaultCacheBehavior:{TargetOriginId:"frontend-s3",ViewerProtocolPolicy:"allow-all",
    AllowedMethods:{Quantity:3,Items:["GET","HEAD","OPTIONS"],CachedMethods:{Quantity:2,Items:["GET","HEAD"]}},
    Compress:true,MinTTL:0,DefaultTTL:300,MaxTTL:31536000,
    ForwardedValues:{QueryString:false,Cookies:{Forward:"none"}}},
  CustomErrorResponses:{Quantity:2,Items:[
    {ErrorCode:403,ResponseCode:"200",ResponsePagePath:"/index.html",ErrorCachingMinTTL:0},
    {ErrorCode:404,ResponseCode:"200",ResponsePagePath:"/index.html",ErrorCachingMinTTL:0}]},
  Restrictions:{GeoRestriction:{RestrictionType:"none",Quantity:0}},
  ViewerCertificate:{CloudFrontDefaultCertificate:true}
}' > manual/frontend-distribution.json
DISTRIBUTION_ID=$(aws --endpoint-url "$FLOCI_ENDPOINT" cloudfront create-distribution \
  --distribution-config file://manual/frontend-distribution.json --query Distribution.Id --output text)
DISTRIBUTION_ARN="arn:aws:cloudfront::000000000000:distribution/$DISTRIBUTION_ID"
aws --endpoint-url "$FLOCI_ENDPOINT" cloudfront tag-resource --resource "$DISTRIBUTION_ARN" \
  --tags 'Items=[{Key=Project,Value=book-ninja},{Key=Environment,Value=local},{Key=ManagedBy,Value=manual-cli}]'
jq -n --arg bucket "$FRONTEND_BUCKET" --arg arn "$DISTRIBUTION_ARN" '{
  Version:"2012-10-17",Statement:[{Sid:"CloudFrontReadOnly",Effect:"Allow",
    Principal:{Service:"cloudfront.amazonaws.com"},Action:"s3:GetObject",
    Resource:("arn:aws:s3:::"+$bucket+"/*"),Condition:{StringEquals:{"AWS:SourceArn":$arn}}}]
}' > manual/frontend-bucket-policy.json
aws --endpoint-url "$FLOCI_ENDPOINT" s3api put-bucket-policy --bucket "$FRONTEND_BUCKET" \
  --policy file://manual/frontend-bucket-policy.json
aws --endpoint-url "$FLOCI_ENDPOINT" cloudfront wait distribution-deployed --id "$DISTRIBUTION_ID"
```

CloudFront signs origin requests; only that distribution's service principal
can read the bucket anonymously on a viewer's behalf. S3 website hosting and
public ACLs are not enabled. HTTP viewer access is local-only; AWS Terraform
redirects viewers to HTTPS. Custom domains and ACM certificates remain future
work. The local URL uses the emulator's DNS alias and port 4566.

### Delivery and direct-S3 negative test

On the **existing Terraform-managed setup**, obtain the real generated names:

```sh
FRONTEND_BUCKET=$(terraform output -raw frontend_bucket_name)
DISTRIBUTION_ID=$(terraform output -raw frontend_distribution_id)
```

On the manual path, keep the variables captured above instead. Upload the
non-secret test fixture, then compare CloudFront access with direct S3:

```sh
aws --endpoint-url "$FLOCI_ENDPOINT" s3 cp tests/fixtures/frontend-probe.txt \
  "s3://$FRONTEND_BUCKET/.well-known/frontend-probe.txt" --cache-control no-store
CF_HOST="$(printf '%s' "$DISTRIBUTION_ID" | tr '[:upper:]' '[:lower:]').cloudfront.localhost.floci.io"
curl --fail --resolve "$CF_HOST:4566:127.0.0.1" "http://$CF_HOST:4566/.well-known/frontend-probe.txt"
curl -s -o /dev/null -w '%{http_code}\n' "http://localhost:4566/$FRONTEND_BUCKET/.well-known/frontend-probe.txt"
```

Expected: CloudFront returns the fixture, direct unsigned S3 returns 403.
`--resolve` lets curl test the local host alias without relying on external DNS.
This verifies infrastructure delivery, not a Book Ninja frontend deployment.
The retained fixture is a smoke-test object and contains no credentials.

For eventual frontend publication after a configured build (not yet performed):

```sh
aws --endpoint-url "$FLOCI_ENDPOINT" s3 sync ../apps/frontend/dist/ "s3://$FRONTEND_BUCKET/" \
  --exclude index.html --cache-control 'public,max-age=31536000,immutable'
aws --endpoint-url "$FLOCI_ENDPOINT" s3 cp ../apps/frontend/dist/index.html "s3://$FRONTEND_BUCKET/index.html" \
  --cache-control 'no-cache' --content-type text/html
aws --endpoint-url "$FLOCI_ENDPOINT" cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" --paths /index.html
```

## 18. Backend Secrets Manager container

Terraform creates only the secret metadata; it does not supply a secret value.
The manual equivalent, using the provisioning profile, is:

```sh
aws --endpoint-url "$FLOCI_ENDPOINT" secretsmanager create-secret \
  --name book-ninja/local/backend \
  --description 'Backend runtime JSON; populate separately before application deployment' \
  --tags Key=Project,Value=book-ninja Key=Environment,Value=local Key=ManagedBy,Value=manual-cli
aws --endpoint-url "$FLOCI_ENDPOINT" secretsmanager describe-secret --secret-id book-ninja/local/backend
```

No application value is supplied at creation. Floci 2.4.0 records a synthetic
`AWSCURRENT` version for this request, but its SecretString length was verified
as zero without printing its contents. A version label therefore does not prove
runtime configuration has been populated. The seven-day recovery window in Terraform applies if a future destroy schedules
deletion; creation itself does not schedule deletion.

Before application rollout, prepare an ignored owner-only `manual/backend-runtime.json`
with actual `OPENAI_API_KEY`, `TAVILY_API_KEY`, `HARDCOVER_API_KEY`, `MONGO_URI`,
`LANGSMITH_API_KEY`, and `GOOGLE_CLIENT_ID` values. Do not use example keys.
The future upload command is shown below for completeness; it has not been run:

```sh
chmod 600 manual/backend-runtime.json
aws --endpoint-url "$FLOCI_ENDPOINT" secretsmanager put-secret-value \
  --secret-id book-ninja/local/backend --secret-string file://manual/backend-runtime.json
```

Do not print `get-secret-value` output in shared logs. External Secrets Operator,
its IAM role, and Kubernetes secret injection are not implemented yet.

## 19. Maintenance notes and future provisioning log

Completed and verified on 2026-11-12:

- Persistent Floci with enforced IAM/S3 authentication.
- State S3 bucket, DynamoDB locking, separate state/provisioning IAM identities.
- VPC `10.60/16`, two public/private subnet pairs, one local NAT, private-path SGs.
- EKS/k3s cluster, node-group metadata, cluster/node roles, and backend ECR repository.
- Ready Kubernetes node, healthy CoreDNS/metrics-server, and no Terraform drift.
- Five Terraform tests, four backend health tests, and a successful backend image build.

During setup, an empty initial VPC/cluster using the colliding `10.42/16` range
was removed and replaced. No Book Ninja workloads had been deployed. The current
Terraform precondition rejects that range. Internet Gateways must be detached
before deleting a VPC; Terraform now replaces the gateway when the VPC changes.
Floci retained the k3s volume while replacing the empty cluster.

Added on 2026-11-18:

- Restarted Docker Desktop and Floci; persisted cluster and Terraform state recovered.
- Private frontend S3 with encryption, versioning, lifecycle, and public-access blocking.
- CloudFront distribution with signed OAC origin access and SPA fallback configuration.
- Backend Secrets Manager metadata without application values in Terraform state.
- Scoped provisioning permissions and two additional mock-provider tests.
- Delivery smoke test returned the fixture through CloudFront and 403 directly
  from unsigned S3. All seven Terraform tests passed and a final plan was empty.

Not provisioned yet; add exact commands and verification here as implemented:

- [ ] Application configuration and Secrets Manager/External Secrets.
- [ ] Backend image publication and digest verification.
- [ ] Kubernetes application manifests and rollout smoke tests.
- [ ] Frontend application build and asset publication (hosting infrastructure exists).
- [ ] API Gateway, VPC Link, internal ALB, ingress, and SSE verification.
- [ ] Argo CD/GitOps and CI/CD.
- [ ] Egress restrictions, remaining production controls, and AWS validation.

Future entries must include date, purpose, executing identity, commands in
dependency order, generated/ignored files, verification results, and differences
between local Floci and AWS. Keep this file aligned with Terraform and scripts.

References: [AWS CLI update-kubeconfig](https://docs.aws.amazon.com/cli/latest/reference/eks/update-kubeconfig.html)
and [Floci EKS behavior](https://github.com/floci-io/floci/blob/main/docs/services/eks.md).
