# Book Ninja: manual Floci provisioning runbook

For everyday inspection and debugging, see [Common commands](COMMON_COMMANDS.md).

Last updated: 2026-11-19.

This is the ongoing record of provisioning performed for Book Ninja. Update it
whenever provisioning is added or changed, including commands, identity,
dependencies, verification, and any Floci-specific behavior.

## Scope and execution rules

This runbook replaces the provisioning Python helpers with native CLI commands and also
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

Additional API/ELB permissions use an attached managed policy (section 23),
because extending this inline user policy exceeded IAM's 2 KiB limit.

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
      {"Effect":"Allow","Resource":"arn:aws:iam::000000000000:user/book-ninja-local-external-secrets","Action":[
        "iam:CreateUser","iam:GetUser","iam:DeleteUser","iam:TagUser","iam:UntagUser",
        "iam:ListUserTags","iam:PutUserPolicy","iam:GetUserPolicy","iam:DeleteUserPolicy",
        "iam:ListUserPolicies","iam:ListAttachedUserPolicies"
      ]},
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
and deploying an image are separate actions. Section 20 records the verified
image push/pull and local k3s image execution. Scan-on-push is configuration
metadata in Floci, not evidence of a vulnerability scan.

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

Do not print `get-secret-value` output in shared logs. The local operator and
secret-injection wiring are described in section 19; real runtime values and
production AWS workload identity remain pending.

## 19. Local External Secrets Operator and secret-injection wiring

This step was provisioned on 2026-11-18. Helm chart version: **2.15.0**.
The operator watches only `book-ninja` and uses a dedicated local IAM reader.
The Terraform resources do not create this static-key identity in AWS; real
AWS IRSA/Pod Identity remains separate work. Helm/kubectl bootstrap these Git
manifests now; Argo CD has not taken ownership yet.

### Prerequisites and Terraform path

From the repository root:

```sh
brew install helm
python3 infra/scripts/bootstrap_provisioner.py
terraform -chdir=infra plan -var-file=environments/local.tfvars
terraform -chdir=infra apply -var-file=environments/local.tfvars
python3 infra/scripts/configure_kubeconfig.py
bash gitops/platform/external-secrets/install-local.sh
```

The bootstrap policy update in section 6 grants management of only the reader
user, not arbitrary users. Terraform adds two local resources: IAM user
`book-ninja-local-external-secrets` and inline policy `ReadBackendRuntime`.
It never creates an `aws_iam_access_key` resource or records a reader key in state.

### Manual AWS CLI equivalent of the reader user

Run these only on the alternative fresh manual setup, from `infra/`. On the
existing Terraform-managed environment, skip creation and use the inspection
commands. Section 6's provisioning policy must be refreshed by the bootstrap
administrator before creating the reader user with the provisioning profile.

```sh
export AWS_PROFILE=book-ninja-floci-provisioner
BACKEND_SECRET_ARN=$(aws --endpoint-url "$FLOCI_ENDPOINT" secretsmanager describe-secret \
  --secret-id book-ninja/local/backend --query ARN --output text)
aws --endpoint-url "$FLOCI_ENDPOINT" iam create-user --user-name book-ninja-local-external-secrets \
  --tags Key=Project,Value=book-ninja Key=Environment,Value=local Key=ManagedBy,Value=manual-cli
jq -n --arg arn "$BACKEND_SECRET_ARN" '{Version:"2012-10-17",Statement:[{
  Effect:"Allow",Action:["secretsmanager:GetSecretValue","secretsmanager:DescribeSecret"],Resource:$arn
}]}' > manual/eso-reader-policy.json
aws --endpoint-url "$FLOCI_ENDPOINT" iam put-user-policy \
  --user-name book-ninja-local-external-secrets --policy-name ReadBackendRuntime \
  --policy-document file://manual/eso-reader-policy.json
aws --endpoint-url "$FLOCI_ENDPOINT" iam get-user-policy \
  --user-name book-ninja-local-external-secrets --policy-name ReadBackendRuntime
```

Only the exact backend secret ARN is readable. No list-all, write, provisioning,
or IAM administration permission is attached to this reader. The bootstrap
administrator is used for key creation; the reader never receives bootstrap keys.

Generate a key only if there is no saved active one. This JSON is ignored by
Git. The helper reuses an existing saved active key rather than generating a new
one each time. From `infra/`, the manual equivalent is:

```sh
umask 077
touch local.external-secrets.credentials.json
chmod 600 local.external-secrets.credentials.json
aws --profile book-ninja-floci-bootstrap --endpoint-url "$FLOCI_ENDPOINT" iam create-access-key \
  --user-name book-ninja-local-external-secrets \
  --query 'AccessKey.{AccessKeyId:AccessKeyId,SecretAccessKey:SecretAccessKey}' \
  --output json > local.external-secrets.credentials.json
aws --profile book-ninja-floci-bootstrap --endpoint-url "$FLOCI_ENDPOINT" iam list-access-keys \
  --user-name book-ninja-local-external-secrets
aws configure set aws_access_key_id "$(jq -r '.AccessKeyId' local.external-secrets.credentials.json)" \
  --profile book-ninja-floci-reader
aws configure set aws_secret_access_key "$(jq -r '.SecretAccessKey' local.external-secrets.credentials.json)" \
  --profile book-ninja-floci-reader
aws configure set region us-east-1 --profile book-ninja-floci-reader
aws --profile book-ninja-floci-reader --endpoint-url "$FLOCI_ENDPOINT" secretsmanager describe-secret \
  --secret-id book-ninja/local/backend --query Name
aws --profile book-ninja-floci-reader --endpoint-url "$FLOCI_ENDPOINT" iam list-users
```

The last command must return AccessDenied. Back up a saved key file before an
intentional replacement; do not truncate the existing file on a routine rerun.

### Kubernetes namespace, reader Secret, and Floci endpoint

The checked-in kubeconfig is generated/ignored; the examples below use the
normal `local.kubeconfig.json`. Substitute `manual/kubeconfig` if following the
CLI-only kubeconfig path in section 13.

```sh
kubectl --kubeconfig local.kubeconfig.json create namespace book-ninja --dry-run=client -o yaml \
  | kubectl --kubeconfig local.kubeconfig.json apply -f -
mkdir -p manual
# -j prevents a trailing newline from becoming part of an AWS key in Kubernetes.
jq -jr '.AccessKeyId' local.external-secrets.credentials.json > manual/eso-access-key
jq -jr '.SecretAccessKey' local.external-secrets.credentials.json > manual/eso-secret-key
chmod 600 manual/eso-access-key manual/eso-secret-key
kubectl --kubeconfig local.kubeconfig.json -n book-ninja create secret generic floci-secrets-reader \
  --from-file=access-key-id=manual/eso-access-key --from-file=secret-access-key=manual/eso-secret-key \
  --dry-run=client -o json | kubectl --kubeconfig local.kubeconfig.json apply -f -
FLOCI_IP=$(docker inspect infra-floci-1 --format '{{(index .NetworkSettings.Networks "infra_default").IPAddress}}')
jq -n --arg ip "$FLOCI_IP" '{apiVersion:"v1",kind:"List",items:[
  {apiVersion:"v1",kind:"Service",metadata:{name:"floci-aws",namespace:"book-ninja"},
   spec:{ports:[{name:"aws",port:4566,targetPort:4566}]}},
  {apiVersion:"discovery.k8s.io/v1",kind:"EndpointSlice",
   metadata:{name:"floci-aws-local",namespace:"book-ninja",labels:{
     "kubernetes.io/service-name":"floci-aws",
     "endpointslice.kubernetes.io/managed-by":"book-ninja-local-bootstrap"}},
   addressType:"IPv4",ports:[{name:"aws",port:4566,protocol:"TCP"}],
   endpoints:[{addresses:[$ip],conditions:{ready:true}}]}
]}' > manual/floci-service.json
kubectl --kubeconfig local.kubeconfig.json apply -f manual/floci-service.json
```

Check that `FLOCI_IP` is nonempty and IPv4 before applying. The preparation
helper validates it automatically. The Service has no selector: its EndpointSlice
is managed explicitly. Rerun endpoint preparation after Floci container
recreation if its Docker IP changes. Pods use the Kubernetes DNS address
`floci-aws.book-ninja.svc.cluster.local`, not a Docker Compose hostname.
Do not log Secret manifests or use shell tracing while handling credentials.

### Install the operator and apply the runtime mapping

From `infra/`:

```sh
helm repo add external-secrets https://charts.external-secrets.io --force-update
helm upgrade --install external-secrets external-secrets/external-secrets --version 2.15.0 \
  --namespace external-secrets --create-namespace --kubeconfig local.kubeconfig.json \
  --values ../gitops/platform/external-secrets/local-values.yaml --wait --timeout 5m
kubectl --kubeconfig local.kubeconfig.json wait --for=condition=Established \
  crd/secretstores.external-secrets.io crd/externalsecrets.external-secrets.io --timeout=120s
kubectl --kubeconfig local.kubeconfig.json apply \
  -f ../gitops/environments/local/backend-external-secret.yaml
kubectl --kubeconfig local.kubeconfig.json -n external-secrets get pods
kubectl --kubeconfig local.kubeconfig.json -n book-ninja get secretstore,externalsecret
```

`local-values.yaml` contains only non-secret configuration: local endpoint
overrides, resource limits, scoped RBAC, and controller class `book-ninja-local`.
The SecretStore's controller class matches that value. Its credentials come
from `floci-secrets-reader`. The ExternalSecret maps the six required JSON
properties to `book-ninja/backend-runtime` and refreshes every minute.

The expected current status is **SecretStore Ready, backend ExternalSecret not
Ready**, because real application values are absent. The store may advertise
the AWS provider's generic ReadWrite capability; actual access is constrained
by the IAM policy. No application Secret should be created with missing fields.

After uploading actual values using section 18, wait for the real mapping:

```sh
kubectl --kubeconfig local.kubeconfig.json -n book-ninja annotate externalsecret backend-runtime \
  force-sync="$(date +%s)" --overwrite
kubectl --kubeconfig local.kubeconfig.json -n book-ninja wait \
  --for=condition=Ready externalsecret/backend-runtime --timeout=120s
kubectl --kubeconfig local.kubeconfig.json -n book-ninja get secret backend-runtime
```

Do not print its data. Later application pods can reference it with `envFrom`;
environment-variable consumers need a rollout to pick up rotated values.

### Disposable end-to-end verification

The automated verification helper was run successfully:

```sh
python3 scripts/verify_external_secrets.py
```

It performs the following native operations without reading/modifying backend
runtime values. The commands below show its manual equivalent; use unique probe
names and always execute cleanup, including after a failed wait:

```sh
PROBE="provisioning-probe-$(date +%s)"
REMOTE_PROBE="book-ninja/local/$PROBE"
PROBE_ARN=$(aws --endpoint-url "$FLOCI_ENDPOINT" secretsmanager create-secret \
  --name "$REMOTE_PROBE" --secret-string '{"marker":"non-secret-eso-probe"}' --query ARN --output text)
jq -n --arg arn "$PROBE_ARN" '{Version:"2012-10-17",Statement:[{
  Effect:"Allow",Action:["secretsmanager:GetSecretValue","secretsmanager:DescribeSecret"],Resource:$arn
}]}' > manual/probe-reader-policy.json
aws --profile book-ninja-floci-bootstrap --endpoint-url "$FLOCI_ENDPOINT" iam put-user-policy \
  --user-name book-ninja-local-external-secrets --policy-name "$PROBE" \
  --policy-document file://manual/probe-reader-policy.json
jq -n --arg name "$PROBE" --arg remote "$REMOTE_PROBE" '{
  apiVersion:"external-secrets.io/v1",kind:"ExternalSecret",metadata:{name:$name,namespace:"book-ninja"},
  spec:{refreshInterval:"10s",secretStoreRef:{name:"backend-runtime",kind:"SecretStore"},
    target:{name:$name,creationPolicy:"Owner"},
    data:[{secretKey:"marker",remoteRef:{key:$remote,property:"marker"}}]}
}' > manual/probe-external-secret.json
kubectl --kubeconfig local.kubeconfig.json apply -f manual/probe-external-secret.json
kubectl --kubeconfig local.kubeconfig.json -n book-ninja wait \
  --for=condition=Ready "externalsecret/$PROBE" --timeout=120s
kubectl --kubeconfig local.kubeconfig.json -n book-ninja get secret "$PROBE" \
  -o jsonpath='{.data.marker}' | base64 --decode
# Only this disposable non-secret marker is printed. Never do this to backend-runtime.

# Cleanup exact probe resources, not the real backend secret or reader policy.
kubectl --kubeconfig local.kubeconfig.json -n book-ninja delete externalsecret "$PROBE" --ignore-not-found
kubectl --kubeconfig local.kubeconfig.json -n book-ninja delete secret "$PROBE" --ignore-not-found
aws --endpoint-url "$FLOCI_ENDPOINT" secretsmanager delete-secret --secret-id "$PROBE_ARN" --force-delete-without-recovery
aws --profile book-ninja-floci-bootstrap --endpoint-url "$FLOCI_ENDPOINT" iam delete-user-policy \
  --user-name book-ninja-local-external-secrets --policy-name "$PROBE"
```

The helper uses finally-based cleanup; the manual sequence relies on you to run
the cleanup block even if verification fails. Permanent IAM permission remains
backend-only. AWS workload identity and production installation are not covered
by this local static-key accommodation.

## 20. Backend image publication and workload preparation (2026-11-19)

Completed: publish the backend to local ECR under an immutable Git SHA, pull by
digest, import the exact manifest into k3s, and run a disposable image probe.
Prepared: Helm workload chart. The application release is **not installed**;
real runtime values are still missing. All commands below run from `infra/`.

### Build and publish with the provisioning identity

The helpers are optional conveniences:

```sh
python3 scripts/publish_backend.py
python3 scripts/verify_backend_image.py
```

Their native CLI equivalents follow. Use the existing generated provisioning
profile, not bootstrap administrator keys. The image has no application values
and its build context excludes `.env` files. Commit backend source before using
a Git SHA tag. The current receipt is ignored `manual/backend-image.json`.

```sh
set -euo pipefail
export AWS_PROFILE=book-ninja-floci-provisioner
export AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
FLOCI_ENDPOINT=http://localhost:4566
aws --endpoint-url "$FLOCI_ENDPOINT" sts get-caller-identity
aws --endpoint-url "$FLOCI_ENDPOINT" ecr describe-repositories \
  --repository-names book-ninja-local-backend
mkdir -p manual
test -z "$(git status --porcelain --untracked-files=all -- ../apps/backend)"
IMAGE_REVISION=$(git rev-parse HEAD)
NODE_ARCH=$(kubectl --kubeconfig local.kubeconfig.json get nodes \
  -o 'jsonpath={.items[0].status.nodeInfo.architecture}')
IMAGE_PLATFORM="linux/$NODE_ARCH"
IMAGE_REPOSITORY=localhost:4566/000000000000/us-east-1/book-ninja-local-backend
IMAGE_TAG="$IMAGE_REPOSITORY:$IMAGE_REVISION"
aws --endpoint-url "$FLOCI_ENDPOINT" ecr describe-images \
  --repository-name book-ninja-local-backend > manual/backend-images.json
```

This machine uses `linux/arm64`; production must target its node architecture.
The helper checks that the local nodes share one supported architecture.
The native commands below reuse an existing tag and only build/push a new one:

```sh
umask 077
mkdir -p manual
TASK_DOCKER_CONFIG=$(mktemp -d)
trap 'rm -rf "$TASK_DOCKER_CONFIG"' EXIT
aws --endpoint-url "$FLOCI_ENDPOINT" ecr get-login-password \
  | docker --config "$TASK_DOCKER_CONFIG" login \
      --username AWS --password-stdin localhost:4566
if ! jq -e --arg revision "$IMAGE_REVISION" \
  'any(.imageDetails[]?; (.imageTags // []) | index($revision))' \
  manual/backend-images.json >/dev/null; then
  docker build --platform "$IMAGE_PLATFORM" --provenance=false \
    --label "org.opencontainers.image.revision=$IMAGE_REVISION" \
    --tag "$IMAGE_TAG" ../apps/backend
  docker --config "$TASK_DOCKER_CONFIG" push "$IMAGE_TAG"
fi
IMAGE_DIGEST=$(aws --endpoint-url "$FLOCI_ENDPOINT" ecr describe-images \
  --repository-name book-ninja-local-backend --image-ids "imageTag=$IMAGE_REVISION" \
  --query 'imageDetails[0].imageDigest' --output text)
IMAGE_REF="$IMAGE_REPOSITORY@$IMAGE_DIGEST"
docker --config "$TASK_DOCKER_CONFIG" pull --platform "$IMAGE_PLATFORM" "$IMAGE_REF"
docker image inspect "$IMAGE_REF" | jq -e --arg image "$IMAGE_REF" --arg revision "$IMAGE_REVISION" \
  '.[0] | (.RepoDigests | index($image)) != null and
    .Config.Labels["org.opencontainers.image.revision"] == $revision and .Config.User == "appuser"'
jq -n --arg revision "$IMAGE_REVISION" --arg platform "$IMAGE_PLATFORM" \
  --arg repository "$IMAGE_REPOSITORY" --arg imageDigest "$IMAGE_DIGEST" --arg image "$IMAGE_REF" \
  '{revision:$revision,platform:$platform,repository:$repository,imageDigest:$imageDigest,image:$image}' \
  > manual/backend-image.json
rm -rf "$TASK_DOCKER_CONFIG"
trap - EXIT
```

Docker 29 on this machine uses its containerd image store. The literal
`localhost:4566/<account>/<region>/<repository>` path works over HTTP and routes
to the same Floci ECR repository as its advertised subdomain URI. No Docker
insecure-registry setting is required. This path, HTTP, and the preload below
are local-only. Real AWS uses the returned HTTPS ECR URI and IAM-authorized node
pulls. Floci's registry auth and scan settings do not validate production ECR
authorization or scanning. The temporary Docker config is deleted after use.

### Preload the image into local k3s and verify execution

Docker Desktop and k3s have separate containerd image stores. Inside k3s,
`localhost:4566` points at the node, not Floci. Preload and register the digest
reference explicitly rather than changing registry trust or restarting k3s:

```sh
set -o pipefail
docker image save "$IMAGE_TAG" \
  | docker exec -i floci-aws-eks-book-ninja-local ctr -n k8s.io images import -
docker exec floci-aws-eks-book-ninja-local ctr -n k8s.io images list "name==$IMAGE_TAG" \
  | awk -v digest="$IMAGE_DIGEST" 'NR>1 && $3==digest {found=1} END {exit !found}'
docker exec floci-aws-eks-book-ninja-local ctr -n k8s.io images tag --force "$IMAGE_TAG" "$IMAGE_REF"
trap 'kubectl --kubeconfig local.kubeconfig.json delete pod backend-image-probe -n book-ninja --ignore-not-found' EXIT
kubectl --kubeconfig local.kubeconfig.json run backend-image-probe -n book-ninja \
  --image="$IMAGE_REF" --image-pull-policy=Never --restart=Never \
  --overrides='{"spec":{"automountServiceAccountToken":false,"securityContext":{
    "runAsNonRoot":true,"runAsUser":1000,"runAsGroup":1000,"seccompProfile":{"type":"RuntimeDefault"}},
    "containers":[{"name":"backend-image-probe","image":"'"$IMAGE_REF"'","imagePullPolicy":"Never",
      "command":["python","-B","-c","import os, fastapi, uvicorn; assert os.getuid() == 1000; print(\"image-preflight-ok\")"],
      "securityContext":{"allowPrivilegeEscalation":false,"readOnlyRootFilesystem":true,"capabilities":{"drop":["ALL"]}},
      "resources":{"requests":{"cpu":"50m","memory":"64Mi"},"limits":{"cpu":"500m","memory":"256Mi"}}}]}}'
kubectl --kubeconfig local.kubeconfig.json wait \
  --for=jsonpath='{.status.phase}'=Succeeded pod/backend-image-probe -n book-ninja --timeout=120s
kubectl --kubeconfig local.kubeconfig.json logs backend-image-probe -n book-ninja
kubectl --kubeconfig local.kubeconfig.json delete pod backend-image-probe -n book-ninja
trap - EXIT
```

Expected output: `image-preflight-ok`. This confirms image availability and Python
execution as a non-root user with a read-only root filesystem. It does not start
the application, provide fake provider credentials, or test MongoDB/providers.
Repeat preload after node recreation. The helper checks a loopback kubeconfig,
verifies the ECR/tag/imported-manifest digest, uses a unique probe name, and always
attempts probe cleanup. This procedure currently targets the single local node.

### Render and validate the prepared chart

The chart defines a Deployment, ClusterIP Service, ServiceAccount, ConfigMap,
PodDisruptionBudget, and HPA with at least two replicas. Resource limits, UID 1000,
read-only root filesystem, disabled API token mounting, and lightweight `/livez`
probes are configured. It references `backend-runtime` through `envFrom`.
Ingress, network restrictions, namespace quotas, and Argo CD remain future work.

```sh
FRONTEND_ORIGIN=$(terraform output -raw frontend_url)
FRONTEND_ORIGIN=${FRONTEND_ORIGIN%/}
helm lint ../gitops/charts/book-ninja -f ../gitops/environments/local/backend-values.yaml \
  --set-string "image.repository=$IMAGE_REPOSITORY" --set-string "image.digest=$IMAGE_DIGEST" \
  --set-string "config.FRONTEND_ORIGINS=$FRONTEND_ORIGIN"
helm template book-ninja ../gitops/charts/book-ninja -n book-ninja \
  -f ../gitops/environments/local/backend-values.yaml \
  --set-string "image.repository=$IMAGE_REPOSITORY" --set-string "image.digest=$IMAGE_DIGEST" \
  --set-string "config.FRONTEND_ORIGINS=$FRONTEND_ORIGIN" > manual/backend-rendered.yaml
kubectl --kubeconfig local.kubeconfig.json apply --dry-run=server \
  -n book-ninja -f manual/backend-rendered.yaml
```

Helm lint and server-side dry-run passed. The local overlay records the published
digest; update it after a future promotion so Git matches the desired image.
The base chart defaults to `APP_ENV=prod`, while this local overlay uses `dev`.
Process readiness does not prove MongoDB durability: the current application
can fall back to in-memory checkpointing. Test integrations separately before
declaring a rollout usable. Image dependencies and base-image digests remain
unlocked; production release hardening is separate work.

### Future rollout: only after real runtime values are synchronized

The following commands have **not** been executed. First complete section 18,
wait for ESO, and preload the matching published image. These commands install
the release only if the required runtime Secret exists and ESO is ready:

```sh
kubectl --kubeconfig local.kubeconfig.json wait -n book-ninja \
  --for=condition=Ready externalsecret/backend-runtime --timeout=120s \
  && kubectl --kubeconfig local.kubeconfig.json get secret backend-runtime -n book-ninja -o name \
  && helm upgrade --install book-ninja ../gitops/charts/book-ninja \
    --kubeconfig local.kubeconfig.json -n book-ninja \
    -f ../gitops/environments/local/backend-values.yaml \
    --set-string "image.repository=$IMAGE_REPOSITORY" --set-string "image.digest=$IMAGE_DIGEST" \
    --set-string "config.FRONTEND_ORIGINS=$FRONTEND_ORIGIN" --wait --timeout=10m
kubectl --kubeconfig local.kubeconfig.json rollout status deployment/book-ninja-backend \
  -n book-ninja --timeout=120s
kubectl --kubeconfig local.kubeconfig.json get deploy,pods,svc,hpa,pdb -n book-ninja
```

After a successful rollout, use `kubectl port-forward` to the internal Service
for local smoke tests; public API routing is not installed yet. Environment
variable consumers need `kubectl rollout restart deployment/book-ninja-backend
-n book-ninja` after secret rotation. Streaming drain, `/health`, authentication,
and persistence still require verification with real values.

## 21. Automatic local publication after successful CI (2026-11-19)

GitHub-hosted runners cannot reach this Mac's Floci at `localhost:4566`.
The repository is public, so local publication uses a per-user macOS publisher,
not a registered self-hosted GitHub Actions runner. GitHub still runs CI; the
local process polls the Actions API every 60 seconds using the existing `gh`
login. It only accepts a successful **push** run of `backend.yml` from this
repository for the current `develop` head. PR/fork, stale, incomplete, and failed
runs cannot trigger publication. It does not publish `main` to AWS.

The flow is: merge -> hosted CI -> local source rebuild -> Floci ECR -> digest
verification and k3s image probe -> image-overlay PR to `develop`. The local
ARM64 image is rebuilt from the tested source, not downloaded from the hosted
CI runner. No release artifact reuse or production signing/scanning is implied.
The PR changes only `gitops/environments/local/backend-values.yaml`; it is not
auto-merged. Argo CD and application deployment remain separate work.

Backend CI now also checks PRs targeting `develop`, runs provisioning helper
tests and Helm validation, and watches backend/chart/helper changes. Pushes
that change only the image overlay are deliberately excluded, preventing
promotion-merge -> rebuild -> promotion loops. Overlay PRs still receive checks.

### Tools and foreground operation

From `infra/`, using the same local credentials and kubeconfig as prior sections:

```sh
brew install gh actionlint
gh auth status
actionlint ../.github/workflows/backend.yml
python3 scripts/watch_backend_ci.py
# Explicit one-shot publication after a qualifying CI run:
python3 scripts/watch_backend_ci.py --publish
# Or run continuously in the terminal (stop with Ctrl-C):
python3 scripts/watch_backend_ci.py --watch --publish
```

The first invocation only inspects CI. `--publish` enables image writes, a
promotion branch push, and PR creation. Publication uses the generated local
provisioner identity, never a real AWS key. GitHub reads/writes use the local
`gh` login; no GitHub token is placed in GitHub Actions secrets, manifests,
Terraform, or a LaunchAgent plist. The Mac must be awake, Docker/Floci running,
and its existing GitHub login available. GitHub App/OIDC release automation for
production is future work.

### Native CLI equivalent of the CI gate and isolated source checkout

The following is the manual equivalent of the publisher's gate. Stop if any
verification fails. Current `develop` initially has no matching CI run because
the preceding infrastructure-only merge did not trigger the old path filter.
Do not substitute an older successful run for the current head.

```sh
set -euo pipefail
TASK_REPO=EjazAhmedRak/book-ninja
TASK_HEAD=$(gh api "repos/$TASK_REPO/git/ref/heads/develop" --jq .object.sha)
gh api "repos/$TASK_REPO/actions/workflows/backend.yml/runs?branch=develop&event=push&head_sha=$TASK_HEAD&per_page=1" \
  > manual/local-publisher-ci.json
jq -e --arg sha "$TASK_HEAD" --arg repo "$TASK_REPO" '
  .workflow_runs[0] | .head_sha==$sha and .head_branch=="develop" and
  .event=="push" and .status=="completed" and .conclusion=="success" and
  .head_repository.full_name==$repo and .path==".github/workflows/backend.yml"' \
  manual/local-publisher-ci.json >/dev/null
git fetch origin develop
test "$(git rev-parse origin/develop)" = "$TASK_HEAD"
TASK_CHECKOUT_PARENT=$(mktemp -d)
TASK_SOURCE_ROOT="$TASK_CHECKOUT_PARENT/source"
git worktree add --detach "$TASK_SOURCE_ROOT" "$TASK_HEAD"
trap 'git worktree remove --force "$TASK_SOURCE_ROOT"; rm -rf "$TASK_CHECKOUT_PARENT"' EXIT
```

Run the native ECR login/build/push/pull/import/probe commands from section 20
in this same `infra/` control directory, with `IMAGE_REVISION=$TASK_HEAD`. Change
the build command's context to the isolated tested source as follows; keep the
same immutable-tag reuse check, platform, temporary Docker config, and digest
verification from that section. Do not copy credentials into the source checkout:

```sh
docker build --platform "$IMAGE_PLATFORM" --provenance=false \
  --label "org.opencontainers.image.revision=$TASK_HEAD" \
  --tag "$IMAGE_TAG" "$TASK_SOURCE_ROOT/apps/backend"
```

For the optional helper equivalent, use
`python3 scripts/publish_backend.py --source-root "$TASK_SOURCE_ROOT"` followed
by `python3 scripts/verify_backend_image.py`. Both retain credentials and the
receipt in the control checkout's ignored files. The source checkout stays clean.

### Native CLI equivalent of proposing the verified digest

Continue only after section 20's digest and k3s probe verification has succeeded.
These are remote write commands; the installed publisher invokes them only
after the trusted CI gate above. If the branch/PR already exists, inspect/reuse
it rather than force-pushing or reopening a rejected promotion.

```sh
test "$(gh api "repos/$TASK_REPO/git/ref/heads/develop" --jq .object.sha)" = "$TASK_HEAD"
TASK_PROMOTION_BRANCH="deploy/floci-backend-$(printf '%s' "$TASK_HEAD" | cut -c1-12)"
gh pr list --repo "$TASK_REPO" --base develop --head "$TASK_PROMOTION_BRANCH" \
  --state all --json url,state > manual/local-publisher-prs.json
jq -e 'length==0' manual/local-publisher-prs.json >/dev/null
TASK_OVERLAY="$TASK_SOURCE_ROOT/gitops/environments/local/backend-values.yaml"
sed -i '' -e "s@^  repository: .*@  repository: $IMAGE_REPOSITORY@" \
  -e "s@^  digest: .*@  digest: $IMAGE_DIGEST@" "$TASK_OVERLAY"
helm lint "$TASK_SOURCE_ROOT/gitops/charts/book-ninja" -f "$TASK_OVERLAY" \
  --set-string config.FRONTEND_ORIGINS=http://localhost:5173
git -C "$TASK_SOURCE_ROOT" add -- gitops/environments/local/backend-values.yaml
git -C "$TASK_SOURCE_ROOT" -c core.hooksPath=/dev/null commit \
  -m "chore(deploy): promote local backend $(printf '%s' "$TASK_HEAD" | cut -c1-12)"
git -C "$TASK_SOURCE_ROOT" push origin "HEAD:refs/heads/$TASK_PROMOTION_BRANCH"
cat > manual/local-publisher-pr.md <<EOF
Promote the local backend built from $TASK_HEAD after successful Backend CI.
Verified image: $IMAGE_REF
ECR/pull/import digests, the local image execution probe, and Helm lint passed.
Only the local image overlay changes. Application rollout remains separate.
EOF
gh pr create --repo "$TASK_REPO" --base develop --head "$TASK_PROMOTION_BRANCH" \
  --title "chore(deploy): promote local backend $(printf '%s' "$TASK_HEAD" | cut -c1-12)" \
  --body-file manual/local-publisher-pr.md
git worktree remove --force "$TASK_SOURCE_ROOT"
rm -rf "$TASK_CHECKOUT_PARENT"
trap - EXIT
```

The script also handles an already-current digest without an empty commit,
reuses a matching promotion branch after a retry, remembers completed/closed
PRs in ignored `manual/local-publisher-state.json`, and uses a local lock to
prevent concurrent publisher instances. It rechecks `develop` before promotion
and defers if a newer merge appeared during the build. It never force-pushes.
For a digest already in the overlay, skip the manual commit/push/PR commands.

### Background service and its native equivalent

Install the per-user LaunchAgent using the helper from `infra/`:

```sh
python3 scripts/watch_backend_ci.py --install
launchctl print "gui/$(id -u)/io.book-ninja.floci-publisher"
tail -n 10 "$HOME/.local/share/book-ninja-floci-publisher/infra/manual/local-publisher.stdout.log"
```

The helper writes an owner-only plist to
`~/Library/LaunchAgents/io.book-ninja.floci-publisher.plist`. macOS prevented
launchd from starting in the Desktop checkout, so the service uses a separate
clone at `~/.local/share/book-ninja-floci-publisher`. It copies only its six
helper modules and the existing local provisioner credentials/kubeconfig,
preserving owner-only credential permissions and updating the kubeconfig's
credential-helper path to this control clone. No state-user, bootstrap, ESO
reader, or application credentials are copied. Logs/state/receipts live in
that clone's ignored `infra/manual/`. The user's working branch is untouched.
The service was observed running and logging the expected wait for qualifying CI.

After changing publisher code, rotating provisioner keys, or recreating the
cluster, stop the service and reinstall it from the primary checkout to refresh
its helper snapshot and kubeconfig. A repeated install while loaded is a no-op.

The native service installation equivalent is shown below. Use either the
helper or this recipe, not both. No AWS/GitHub secrets belong in the plist.

```sh
TASK_PROJECT_ROOT=$(git rev-parse --show-toplevel)
TASK_CONTROL_ROOT="$HOME/.local/share/book-ninja-floci-publisher"
if [ ! -d "$TASK_CONTROL_ROOT/.git" ]; then
  git clone --branch develop --single-branch https://github.com/EjazAhmedRak/book-ninja.git \
    "$TASK_CONTROL_ROOT"
fi
for TASK_HELPER in watch_backend_ci.py publish_backend.py verify_backend_image.py \
  bootstrap_external_secrets.py bootstrap_floci.py floci_aws.py; do
  cp "$TASK_PROJECT_ROOT/infra/scripts/$TASK_HELPER" "$TASK_CONTROL_ROOT/infra/scripts/$TASK_HELPER"
done
umask 077
cp local.provisioner.auto.tfvars.json "$TASK_CONTROL_ROOT/infra/local.provisioner.auto.tfvars.json"
chmod 600 "$TASK_CONTROL_ROOT/infra/local.provisioner.auto.tfvars.json"
jq --arg old "$TASK_PROJECT_ROOT" --arg new "$TASK_CONTROL_ROOT" \
  '(.users[].user.exec.args) |= map(if startswith($old + "/") then $new + ltrimstr($old) else . end)' \
  local.kubeconfig.json > "$TASK_CONTROL_ROOT/infra/local.kubeconfig.json"
chmod 600 "$TASK_CONTROL_ROOT/infra/local.kubeconfig.json"
TASK_PYTHON=$(command -v python3)
TASK_AGENT="$HOME/Library/LaunchAgents/io.book-ninja.floci-publisher.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$TASK_CONTROL_ROOT/infra/manual"
touch "$TASK_CONTROL_ROOT/infra/manual/local-publisher.stdout.log" \
  "$TASK_CONTROL_ROOT/infra/manual/local-publisher.stderr.log"
chmod 600 "$TASK_CONTROL_ROOT/infra/manual/local-publisher.stdout.log" \
  "$TASK_CONTROL_ROOT/infra/manual/local-publisher.stderr.log"
cat > "$TASK_AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.book-ninja.floci-publisher</string>
  <key>ProgramArguments</key><array><string>$TASK_PYTHON</string>
    <string>$TASK_CONTROL_ROOT/infra/scripts/watch_backend_ci.py</string>
    <string>--watch</string><string>--publish</string></array>
  <key>WorkingDirectory</key><string>$TASK_CONTROL_ROOT</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$TASK_CONTROL_ROOT/infra/manual/local-publisher.stdout.log</string>
  <key>StandardErrorPath</key><string>$TASK_CONTROL_ROOT/infra/manual/local-publisher.stderr.log</string>
</dict></plist>
EOF
chmod 600 "$TASK_AGENT"
plutil -lint "$TASK_AGENT"
launchctl bootstrap "gui/$(id -u)" "$TASK_AGENT"
```

Stop/remove the service when required; published images, PRs, and logs remain:

```sh
python3 scripts/watch_backend_ci.py --uninstall
# Native equivalent (do not repeat if the helper already removed it):
launchctl bootout "gui/$(id -u)/io.book-ninja.floci-publisher"
rm "$HOME/Library/LaunchAgents/io.book-ninja.floci-publisher.plist"
```

Activation status: PR #11 merged, its push CI passed, and the publisher completed
the first real publication for `d380d5c37680`, opening promotion PR #12 at
https://github.com/EjazAhmedRak/book-ninja/pull/12. The initial live inspection
correctly skipped the then-untested head. Unit tests cover the CI gate,
dry-run behavior, closed PR reuse, source/digest integrity, promotion changes,
and advancement of `develop` during publication.

## 22. Argo CD platform and manual backend preview (2026-11-19)

Installed pinned Helm chart `argo/argo-cd` **10.18.1**, Argo CD **v3.6.1**, in
namespace `argocd`. Source: the official Argo Helm repository. No AWS resources
or IAM permissions were added in this increment; use the existing Kubernetes
bootstrap/admin access. All commands below run from `infra/`.

The API/UI is a ClusterIP Service with TLS and authentication. Anonymous access
and exec are disabled. The local install uses one controller/server/repo-server
and Redis, with no Dex, notifications, or active ApplicationSet controller.
The node has two CPUs; initial discovery caused probe timeouts, so the overlay
limits status/operation concurrency and gives components six minutes of startup
probe tolerance with five-second probe timeouts. It retains liveness checks.

### Native Helm/kubectl installation

The helper path is `bash ../gitops/platform/argocd/install-local.sh`. Its native
equivalent follows. First verify the kubeconfig targets this local loopback API:

```sh
kubectl --kubeconfig local.kubeconfig.json config view --minify -o json \
  | jq -e '.clusters[0].cluster.server | test("^https://(localhost|127\\.0\\.0\\.1|\\[::1\\]):")' >/dev/null
helm repo add argo https://argoproj.github.io/argo-helm --force-update
helm template argocd argo/argo-cd --version 10.18.1 -n argocd \
  -f ../gitops/platform/argocd/local-values.yaml > manual/argocd-rendered.yaml
helm upgrade --install argocd argo/argo-cd --version 10.18.1 \
  --namespace argocd --create-namespace --kubeconfig local.kubeconfig.json \
  -f ../gitops/platform/argocd/local-values.yaml --wait --timeout 8m
kubectl --kubeconfig local.kubeconfig.json wait --for=condition=Established \
  crd/applications.argoproj.io crd/appprojects.argoproj.io --timeout=120s
kubectl --kubeconfig local.kubeconfig.json apply -f ../gitops/argocd/local/projects.yaml
kubectl --kubeconfig local.kubeconfig.json -n argocd get pods,svc,appprojects
```

Three AppProjects are configured: `default` denies all sources/destinations;
`book-ninja-local` permits only the approved Book Ninja GitHub repository,
in-cluster destination `book-ninja`, and Deployment, Service, ConfigMap,
ServiceAccount, HPA, and PodDisruptionBudget; `book-ninja-bootstrap` permits only
Application/AppProject metadata in `argocd` from the same repository. The latter
is trusted platform configuration. Backend sources cannot grant themselves that
project through their permitted resource types. No backend Secret, IAM key,
GitHub token, or repository credential is passed to Argo CD; the repo is public.

Project restrictions govern Argo CD applications. The Helm chart's standard
controller service-account Kubernetes permissions are broader and have not
been reduced to namespace-only RBAC. HA, SSO, network controls, and production
controller permissions remain future work.

### Save the initial login privately and access the UI

The Python bootstrap performs the following without printing the password:

```sh
umask 077
mkdir -p manual
kubectl --kubeconfig local.kubeconfig.json -n argocd get secret argocd-initial-admin-secret \
  -o 'jsonpath={.data.password}' | base64 --decode > manual/argocd-initial-admin-password
chmod 600 manual/argocd-initial-admin-password
kubectl --kubeconfig local.kubeconfig.json -n argocd port-forward \
  --address 127.0.0.1 svc/argocd-server 8443:443
```

Keep that terminal open and visit `https://127.0.0.1:8443`. It uses a local
self-signed certificate. Username is `admin`; use the ignored private password
file. Rotate the password after login, secure the new value, then delete
`argocd-initial-admin-secret` and its obsolete local password file. That rotation
has not been performed automatically. Re-running the bootstrap after rotation
does not recreate a missing initial password Secret.

### Preview the backend source without starting pods

The current live preview pins commit
`899a871bdcc83d4348993342aec2ca0ee1a8b7b2`, which is reviewed PR #11's source.
The Application is manual-sync, has no deletion finalizer, and intentionally
does not deploy the backend. The canonical Git Application follows `develop`
once the root configuration below has been reviewed/merged.

The helper is `python3 scripts/bootstrap_argocd.py --preview-revision <full-sha>`.
The equivalent native commands validate the chart source exists, render a local
Application with an explicit revision, and register it:

```sh
ARGO_PREVIEW_REVISION=899a871bdcc83d4348993342aec2ca0ee1a8b7b2
gh api "repos/EjazAhmedRak/book-ninja/contents/gitops/charts/book-ninja/Chart.yaml?ref=$ARGO_PREVIEW_REVISION" \
  --jq .sha >/dev/null
kubectl --kubeconfig local.kubeconfig.json create --dry-run=client \
  -f ../gitops/argocd/local/backend-application.yaml -o json \
  | jq --arg revision "$ARGO_PREVIEW_REVISION" '.spec.source.targetRevision=$revision |
      .metadata.annotations={"book-ninja.io/bootstrap-mode":"manual-preview"}' \
  > manual/argocd-backend-preview.json
kubectl --kubeconfig local.kubeconfig.json apply -f manual/argocd-backend-preview.json
kubectl --kubeconfig local.kubeconfig.json -n argocd get application book-ninja-local-backend
kubectl --kubeconfig local.kubeconfig.json -n book-ninja get deployment book-ninja-backend --ignore-not-found
```

Expected: `OutOfSync`/`Missing` with the desired chart rendered, and no backend
Deployment. The source uses the committed local image overlay and explicit
public frontend origin parameter. Runtime values are still absent, so do not
sync this backend yet. The frontend origin in the Application must be updated
if the local CloudFront distribution changes.

### API authentication and Git-render verification

With the port-forward running, the following checks reveal metadata only.
The `--insecure` flag below is only for this loopback self-signed Argo CD server:

```sh
curl --insecure --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  https://127.0.0.1:8443/api/v1/applications
umask 077
trap 'rm -f manual/argocd-api-token manual/argocd-api-header' EXIT
jq -n --rawfile password manual/argocd-initial-admin-password \
  '{username:"admin",password:($password | rtrimstr("\n"))}' \
  | curl --insecure --silent --show-error --fail-with-body \
      -H 'Content-Type: application/json' --data-binary @- https://127.0.0.1:8443/api/v1/session \
  | jq -erj .token > manual/argocd-api-token
printf 'Authorization: Bearer ' > manual/argocd-api-header
cat manual/argocd-api-token >> manual/argocd-api-header
printf '\n' >> manual/argocd-api-header
curl --insecure --silent --show-error --fail \
  --header @manual/argocd-api-header \
  https://127.0.0.1:8443/api/v1/applications/book-ninja-local-backend \
  | jq '{name:.metadata.name,sync:.status.sync,health:.status.health,conditions:.status.conditions}'
curl --insecure --silent --show-error --fail --header @manual/argocd-api-header \
  https://127.0.0.1:8443/api/v1/applications/book-ninja-local-backend/manifests \
  | jq '{renderedManifestCount:(.manifests | length)}'
rm -f manual/argocd-api-token manual/argocd-api-header
trap - EXIT
```

The unauthenticated request must return 401 or 403; authenticated reads must
succeed. The backend chart renders six resources. This confirms public Git
fetch and Helm rendering, not a running application or provider health.

### Verify project destination restrictions

Create a disposable manual-sync Application targeting the forbidden `default`
namespace, observe `InvalidSpecError`, then delete it. No sync is requested:

```sh
jq '.metadata.name="book-ninja-project-denial-probe" | del(.metadata.annotations) |
    .spec.destination.namespace="default"' manual/argocd-backend-preview.json \
  > manual/argocd-project-denial-probe.json
trap 'kubectl --kubeconfig local.kubeconfig.json -n argocd delete application book-ninja-project-denial-probe --ignore-not-found' EXIT
kubectl --kubeconfig local.kubeconfig.json apply -f manual/argocd-project-denial-probe.json
kubectl --kubeconfig local.kubeconfig.json -n argocd wait \
  --for=jsonpath='{.status.conditions[0].type}'=InvalidSpecError \
  application/book-ninja-project-denial-probe --timeout=120s
kubectl --kubeconfig local.kubeconfig.json -n argocd delete application book-ninja-project-denial-probe
trap - EXIT
```

### Root Application adoption after this change merges

The root watches only `gitops/argocd/local` and manages the project definitions
and backend Application. It does not include its own manifest recursively.
Its metadata sync is manual, and the child backend also stays manual. These
commands were executed after PR #13 merged the configuration into `develop`;
the helper checks availability before registering the root:

```sh
python3 scripts/bootstrap_argocd.py --activate-root
# Native equivalent of the guarded registration:
gh api 'repos/EjazAhmedRak/book-ninja/contents/gitops/argocd/local/projects.yaml?ref=develop' \
  --jq .sha >/dev/null \
  && kubectl --kubeconfig local.kubeconfig.json apply -f ../gitops/argocd/root-application.yaml
kubectl --kubeconfig local.kubeconfig.json -n argocd patch application book-ninja-local-root \
  --type merge -p '{"operation":{"sync":{"prune":false}}}'
kubectl --kubeconfig local.kubeconfig.json -n argocd get applications
```

Root sync changes backend source tracking to `develop`; it does not sync the
child workload. Before backend sync, supply real runtime values (section 18),
wait for ESO Ready (section 19), and verify/preload the selected digest (section
20). Once Argo CD owns the backend, use Argo CD sync rather than installing the
same workload with Helm CLI. Automatic backend sync, application rollout/SSE/
persistence validation, and production identity/networking remain future work.

## 23. Private API foundation and root adoption (2026-11-19)

Root metadata adoption completed after PR #13 merged: `book-ninja-local-root`
is **Synced / Healthy / Succeeded**. The backend follows `develop`, still with
manual sync and no Deployment. Section 22 records the commands; no backend sync
was run because real runtime values remain missing.

### Streaming correction and scope

AWS HTTP APIs do not support response streaming. Chat's production design now
uses a **Regional REST API** with a streaming HTTP proxy integration and **VPC
Link V2** to an internal ALB. V2 identifies the link generation, not an HTTP API.
Terraform owns the ALB/listener/IP target group; a future Load Balancer Controller
TargetGroupBinding will bind the existing group to the Kubernetes Service.

This increment created five resources: Regional REST API container, V2 link,
internal ALB, port-80 listener, and empty IP target group on port 8000 with
`/livez` checks. No routes, stage, integration, TargetGroupBinding, or public
API domain is deployed. An API ID alone is not a working application endpoint.
ALB idle timeout is 300 seconds; production deletion protection is enabled.

Floci documents `STREAM` metadata but buffers API execution; its documented
REST VPC-link operations are legacy V1. The current Terraform provider direct
integration schema lacks newer streaming/integration-target fields. Future
integration work needs validated provider/OpenAPI support and AWS SSE timing
tests. Do not substitute an invalid V1-to-ALB integration or claim local SSE
validation. No streaming API stage was deployed in this increment.

Sources: [AWS streaming](https://docs.aws.amazon.com/apigateway/latest/developerguide/response-transfer-mode.html),
[REST private integrations](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-private-integration.html),
[Floci API Gateway](https://github.com/floci-io/floci/blob/main/docs/services/api-gateway.md),
and [Floci ELB](https://github.com/floci-io/floci/blob/main/docs/services/elb.md).

### Managed IAM grant: bootstrap identity

From `infra/`, the helper `python3 scripts/bootstrap_provisioner.py` retains the
old inline grant and adds/updates an attached managed policy. It reuses the
active provisioner key. Native equivalent, using the existing bootstrap profile:

```sh
export AWS_PROFILE=book-ninja-floci-bootstrap
export AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
FLOCI_ENDPOINT=http://localhost:4566
umask 077
mkdir -p manual
cat > manual/api-provisioning-policy.json <<'EOF'
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["elasticloadbalancing:*"],"Resource":"*"},
  {"Effect":"Allow","Action":["apigateway:GET","apigateway:POST","apigateway:PUT","apigateway:PATCH","apigateway:DELETE"],
   "Resource":["arn:aws:apigateway:us-east-1::/restapis*","arn:aws:apigateway:us-east-1::/vpclinks*"]}
]}
EOF
API_POLICY_ARN=$(aws --endpoint-url "$FLOCI_ENDPOINT" iam list-policies --scope Local \
  --query "Policies[?PolicyName=='book-ninja-local-api-provisioning'].Arn | [0]" --output text)
if [ "$API_POLICY_ARN" = None ] || [ -z "$API_POLICY_ARN" ]; then
  API_POLICY_ARN=$(aws --endpoint-url "$FLOCI_ENDPOINT" iam create-policy \
    --policy-name book-ninja-local-api-provisioning \
    --policy-document file://manual/api-provisioning-policy.json --query Policy.Arn --output text)
else
  API_POLICY_VERSION=$(aws --endpoint-url "$FLOCI_ENDPOINT" iam get-policy \
    --policy-arn "$API_POLICY_ARN" --query Policy.DefaultVersionId --output text)
  aws --endpoint-url "$FLOCI_ENDPOINT" iam get-policy-version --policy-arn "$API_POLICY_ARN" \
    --version-id "$API_POLICY_VERSION" --query PolicyVersion.Document --output json > manual/api-current-policy.json
  if ! diff -q <(jq -S . manual/api-current-policy.json) <(jq -S . manual/api-provisioning-policy.json) >/dev/null; then
    aws --endpoint-url "$FLOCI_ENDPOINT" iam list-policy-versions --policy-arn "$API_POLICY_ARN" \
      > manual/api-policy-versions.json
    if [ "$(jq '.Versions | length' manual/api-policy-versions.json)" -ge 5 ]; then
      API_OLDEST_VERSION=$(jq -r '[.Versions[] | select(.IsDefaultVersion==false)] |
        sort_by(.CreateDate) | .[0].VersionId' manual/api-policy-versions.json)
      aws --endpoint-url "$FLOCI_ENDPOINT" iam delete-policy-version \
        --policy-arn "$API_POLICY_ARN" --version-id "$API_OLDEST_VERSION"
    fi
    aws --endpoint-url "$FLOCI_ENDPOINT" iam create-policy-version --policy-arn "$API_POLICY_ARN" \
      --policy-document file://manual/api-provisioning-policy.json --set-as-default
  fi
fi
aws --endpoint-url "$FLOCI_ENDPOINT" iam attach-user-policy \
  --user-name book-ninja-network-provisioner --policy-arn "$API_POLICY_ARN"
aws --endpoint-url "$FLOCI_ENDPOINT" iam list-attached-user-policies --user-name book-ninja-network-provisioner
```

Never delete the current default policy version. The helper removes only the
oldest nondefault version when all five slots are occupied. Local ELB permissions
are broad service-level access, not production IAM hardening. No state-user or
ESO-reader grant changed and no access key was created.

### Terraform path and private plan handling

Both `apigateway` and `apigatewayv2` endpoints explicitly target Floci. The
separate V2 endpoint override is required even though the API is REST.

```sh
python3 scripts/bootstrap_provisioner.py
terraform fmt -check -recursive
terraform validate
terraform test
terraform plan -var-file=environments/local.tfvars -out=api-foundation.tfplan
chmod 600 api-foundation.tfplan
terraform apply api-foundation.tfplan
terraform output -json api_foundation > manual/api-foundation.json
```

The ignored saved plan may contain sensitive Terraform inputs. Eleven tests
pass, covering private subnets/SGs, IP targets/health, Regional API type, and
production deletion protection. Plan-phase mock overrides use the installed
Terraform 1.17.1. Apply created five resources and changed/destroyed none.

### Native resource creation: fresh manual environment only

These commands are the alternative to Terraform, not commands to repeat on the
existing managed resources. Use the VPC/private subnet/SG IDs from earlier manual
sections. This example looks up those existing prerequisite IDs through Terraform;
substitute the captured IDs if using the entirely manual ownership path.

```sh
export AWS_PROFILE=book-ninja-floci-provisioner
API_PRIVATE_SUBNET_1=$(terraform output -json private_subnet_ids | jq -r '.[0]')
API_PRIVATE_SUBNET_2=$(terraform output -json private_subnet_ids | jq -r '.[1]')
API_VPC_ID=$(terraform output -raw vpc_id)
API_ALB_SG=$(terraform output -json security_group_ids | jq -r .alb)
API_LINK_SG=$(terraform output -json security_group_ids | jq -r .vpc_link)
API_ALB_ARN=$(aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 create-load-balancer \
  --name book-ninja-local-api --type application --scheme internal \
  --subnets "$API_PRIVATE_SUBNET_1" "$API_PRIVATE_SUBNET_2" --security-groups "$API_ALB_SG" \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)
aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 modify-load-balancer-attributes \
  --load-balancer-arn "$API_ALB_ARN" \
  --attributes Key=idle_timeout.timeout_seconds,Value=300 Key=deletion_protection.enabled,Value=false
API_TARGET_ARN=$(aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 create-target-group \
  --name book-ninja-local-api --protocol HTTP --port 8000 --target-type ip --vpc-id "$API_VPC_ID" \
  --health-check-protocol HTTP --health-check-port traffic-port --health-check-path /livez \
  --health-check-interval-seconds 15 --health-check-timeout-seconds 5 \
  --healthy-threshold-count 2 --unhealthy-threshold-count 2 --matcher HttpCode=200 \
  --query 'TargetGroups[0].TargetGroupArn' --output text)
aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 modify-target-group-attributes \
  --target-group-arn "$API_TARGET_ARN" --attributes Key=deregistration_delay.timeout_seconds,Value=60
aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 create-listener \
  --load-balancer-arn "$API_ALB_ARN" --protocol HTTP --port 80 \
  --default-actions "Type=forward,TargetGroupArn=$API_TARGET_ARN"
API_LINK_ID=$(aws --endpoint-url "$FLOCI_ENDPOINT" apigatewayv2 create-vpc-link \
  --name book-ninja-local-api --subnet-ids "$API_PRIVATE_SUBNET_1" "$API_PRIVATE_SUBNET_2" \
  --security-group-ids "$API_LINK_SG" --query VpcLinkId --output text)
API_REST_ID=$(aws --endpoint-url "$FLOCI_ENDPOINT" apigateway create-rest-api \
  --name book-ninja-local-api --endpoint-configuration types=REGIONAL --query id --output text)
```

Terraform uses unique `bnapi-` names rather than these explicit manual names.
Set production deletion protection true. Real AWS workload security-group
attachment and routing must be validated before binding targets; defining a
reserved backend group does not attach it to EKS pods/nodes.

### Inspect without creating anything

```sh
export AWS_PROFILE=book-ninja-floci-provisioner
terraform output -json api_foundation > manual/api-foundation.json
API_ALB_ARN=$(jq -r .alb_arn manual/api-foundation.json)
API_TARGET_ARN=$(jq -r .target_group_arn manual/api-foundation.json)
API_LINK_ID=$(jq -r .vpc_link_id manual/api-foundation.json)
API_REST_ID=$(jq -r .rest_api_id manual/api-foundation.json)
aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 describe-load-balancers --load-balancer-arns "$API_ALB_ARN"
aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 describe-listeners --load-balancer-arn "$API_ALB_ARN"
aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 describe-target-health --target-group-arn "$API_TARGET_ARN"
aws --endpoint-url "$FLOCI_ENDPOINT" apigatewayv2 get-vpc-link --vpc-link-id "$API_LINK_ID"
aws --endpoint-url "$FLOCI_ENDPOINT" apigateway get-rest-api --rest-api-id "$API_REST_ID"
aws --endpoint-url "$FLOCI_ENDPOINT" apigateway get-deployments --rest-api-id "$API_REST_ID"
```

Expected: active internal ALB, AVAILABLE link, empty target group, no API
deployments. Listener port 80 exists inside Floci's container and is not
published as a new host port. Floci stores SG/subnet declarations but does not
enforce AWS network isolation; forwarding success is not a security proof.

### Disposable ALB routing verification

The helper `python3 scripts/verify_api_foundation.py` rejects nonlocal Kubernetes
APIs and in-use target groups. It runs the published local image with an
overridden standard-library HTTP fixture command, without importing application
configuration or supplying provider credentials. Native equivalent:

```sh
test "$(aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 describe-target-health \
  --target-group-arn "$API_TARGET_ARN" --query 'length(TargetHealthDescriptions)' --output text)" = 0
API_PROBE_IMAGE=$(jq -r .image manual/backend-image.json)
API_PROBE_NAME="book-ninja-alb-probe-$(date +%s)"
API_PROBE_MARKER="non-secret-$API_PROBE_NAME"
docker run --detach --name "$API_PROBE_NAME" --network infra_default \
  --read-only --cap-drop=ALL --security-opt no-new-privileges --memory 64m --cpus 0.25 \
  --env "PROBE_MARKER=$API_PROBE_MARKER" \
  --mount "type=bind,source=$PWD/tests/fixtures/alb_probe.py,target=/probe.py,readonly" \
  "$API_PROBE_IMAGE" python -B /probe.py
API_PROBE_IP=$(docker inspect "$API_PROBE_NAME" --format '{{(index .NetworkSettings.Networks "infra_default").IPAddress}}')
API_PROBE_TARGET="Id=$API_PROBE_IP,Port=8000,AvailabilityZone=all"
trap 'aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 deregister-targets --target-group-arn "$API_TARGET_ARN" --targets "$API_PROBE_TARGET"; docker rm --force "$API_PROBE_NAME"' EXIT
aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 register-targets \
  --target-group-arn "$API_TARGET_ARN" --targets "$API_PROBE_TARGET"
aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 wait target-in-service \
  --target-group-arn "$API_TARGET_ARN" --targets "$API_PROBE_TARGET"
API_ALB_DNS=$(jq -r .alb_dns_name manual/api-foundation.json)
docker exec "$API_PROBE_NAME" python -B -c '
import http.client,json,sys
c=http.client.HTTPConnection("infra-floci-1",80,timeout=15)
c.request("GET","/routing/check?probe=1",headers={"Host":sys.argv[1],"X-Book-Ninja-Probe":"routing-check"})
r=c.getresponse()
assert r.status==200,r.status
assert json.load(r)=={"marker":sys.argv[2],"path":"/routing/check?probe=1","header":"routing-check"}
print("ALB routing verified")
' "$API_ALB_DNS" "$API_PROBE_MARKER"
aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 deregister-targets \
  --target-group-arn "$API_TARGET_ARN" --targets "$API_PROBE_TARGET"
docker rm --force "$API_PROBE_NAME"
trap - EXIT
aws --endpoint-url "$FLOCI_ENDPOINT" elbv2 describe-target-health --target-group-arn "$API_TARGET_ARN"
```

The probe became healthy and preserved path, query, and custom header through
the ALB. Cleanup removed its target/container and left the group empty. This
does not test Kubernetes registration, API Gateway forwarding, VPC security,
or SSE. Do not run probes against a group serving real application traffic.

## 24. Maintenance notes and future provisioning log

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

Next increment on 2026-11-18:

- Added a dedicated local runtime-secret reader and generated its key outside state/Git.
- Installed pinned ESO chart 2.15.0 with scoped RBAC, local endpoints, and resource limits.
- Added SecretStore and explicit backend ExternalSecret mappings.
- Verified end-to-end synchronization using a cleaned-up disposable probe.
- All nine Terraform tests and three bootstrap tests passed; the final plan had no drift.
- Confirmed the controller cannot list Secrets in `default`; the reader retains only
  its backend read policy after probe cleanup.
- Actual backend configuration remains empty; its ExternalSecret is intentionally unready.

Added on 2026-11-19:

- Published backend revision `62d4a037c942bf1b479e1c9c7df0b720dd8fc3fc` as `linux/arm64`.
- ECR, Docker pull, and k3s import matched digest
  `sha256:f402409d9ca7d4b88c706e6ddd0d4d9e1586f10d5a1c573c0ce0cc3e93bd465e`.
- Reused the immutable tag on a second publication run without replacement.
- Ran and removed a non-root, read-only filesystem image probe in k3s.
- Prepared the Helm workload chart; lint and server dry-run passed, release not installed.
- Verified the chart rejects mutable image references and missing frontend origins.
- Six Python guard tests pass, including dirty source, remote-cluster, and image-digest checks.

Next automation increment on 2026-11-19:

- Updated Backend CI for `develop` PRs, helper tests, and workload chart checks.
- Added CI-gated local image publication and digest-promotion PR automation.
- Kept GitHub CI hosted; no self-hosted GitHub runner is registered.
- Installed a running per-user publisher outside Desktop; it correctly waits for qualifying CI.
- Twelve helper tests, workflow actionlint, Helm lint, and runbook shell checks passed.
- PR #11 merged and the first real automated publication opened promotion PR #12.

Argo CD increment on 2026-11-19:

- Installed chart 10.18.1 / Argo CD v3.6.1 with private TLS access and anonymous login disabled.
- Added restricted backend/bootstrap projects and disabled the default project.
- Registered a manual backend preview and prepared the Git root Application.
- All four platform pods are Ready with zero restarts after local probe/concurrency tuning.
- Verified unauthenticated API returns 401, authenticated Git/Helm renders six resources,
  and the project denies a forbidden destination; removed the denial probe.
- Fifteen Python tests, workflow validation, chart rendering, and 57 runbook shell blocks pass.
- PR #13 merged and root metadata adoption completed; the root is Synced/Healthy.

Private API increment on 2026-11-19:

- Root GitOps metadata adopted and verified Synced/Healthy after PR #13 merged.
- Corrected the gateway design to Regional REST for response streaming.
- Added an attached API/ELB managed IAM grant, reusing the existing access key.
- Provisioned internal ALB/listener, empty IP target group, V2 link, and REST API metadata.
- Verified ALB health/routing with a disposable target and cleaned up the probe.
- Routes/stage, Kubernetes target binding, actual application traffic, and SSE remain pending.

Private API increment on 2026-11-19: five foundation resources were applied;
eleven Terraform tests and eighteen Python tests passed. The disposable ALB
probe verified health, path/query/header forwarding, and cleanup. The final
Terraform plan reported no drift. Root metadata is Synced/Healthy; no backend
workload, API integration/stage, or SSE deployment is claimed.

Not provisioned yet; add exact commands and verification here as implemented:

- [ ] Real application values in Secrets Manager (local ESO wiring is provisioned).
- [x] Local backend image publication and digest verification (section 20).
- [ ] Application rollout and smoke tests (core workload chart prepared).
- [ ] Frontend application build and asset publication (hosting infrastructure exists).
- [x] Private ALB, VPC Link V2, and Regional REST API foundation (section 23).
- [ ] Streaming integration/routes/stage, Kubernetes target binding, and SSE verification.
- [x] Root GitOps metadata adoption (section 22).
- [ ] Backend GitOps sync and production CI/CD (local publisher and Argo CD platform installed).
- [ ] Egress restrictions, remaining production controls, and AWS validation.

Future entries must include date, purpose, executing identity, commands in
dependency order, generated/ignored files, verification results, and differences
between local Floci and AWS. Keep this file aligned with Terraform and scripts.

References: [AWS CLI update-kubeconfig](https://docs.aws.amazon.com/cli/latest/reference/eks/update-kubeconfig.html)
and [Floci EKS behavior](https://github.com/floci-io/floci/blob/main/docs/services/eks.md),
[Floci ECR behavior](https://github.com/floci-io/floci/blob/main/docs/services/ecr.md),
and [Kubernetes probe behavior](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/).
