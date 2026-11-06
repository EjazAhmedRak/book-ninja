"""Bootstrap only the local Floci state store; requires the AWS CLI."""

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "http://localhost:4566"
BUCKET = "book-ninja-tfstate"
TABLE = "book-ninja-tflock"
USER = "book-ninja-terraform-state"
ENV = {
    **os.environ,
    "AWS_ACCESS_KEY_ID": "floci",
    "AWS_SECRET_ACCESS_KEY": "floci",
    "AWS_SESSION_TOKEN": "",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_PAGER": "",
}


def aws(*args, env=ENV):
    result = subprocess.run(
        ["aws", "--endpoint-url", ENDPOINT, "--output", "json", *args],
        env=env, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else {}


def private_file(path, value):
    # Set permissions before writing any credentials, including on reruns.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(value)


def main():
    buckets = aws("s3api", "list-buckets")["Buckets"]
    if BUCKET not in [bucket["Name"] for bucket in buckets]:
        aws("s3api", "create-bucket", "--bucket", BUCKET)
    aws("s3api", "put-bucket-versioning", "--bucket", BUCKET,
        "--versioning-configuration", '{"Status":"Enabled"}')
    aws("s3api", "put-public-access-block", "--bucket", BUCKET,
        "--public-access-block-configuration", json.dumps({
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        }))
    if TABLE not in aws("dynamodb", "list-tables")["TableNames"]:
        aws("dynamodb", "create-table", "--table-name", TABLE,
            "--attribute-definitions", "AttributeName=LockID,AttributeType=S",
            "--key-schema", "AttributeName=LockID,KeyType=HASH",
            "--billing-mode", "PAY_PER_REQUEST")
    aws("dynamodb", "wait", "table-exists", "--table-name", TABLE)
    if USER not in [user["UserName"] for user in aws("iam", "list-users")["Users"]]:
        aws("iam", "create-user", "--user-name", USER)

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["s3:ListBucket"],
             "Resource": f"arn:aws:s3:::{BUCKET}"},
            {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
             "Resource": f"arn:aws:s3:::{BUCKET}/local/*"},
            {"Effect": "Allow", "Action": ["dynamodb:DescribeTable", "dynamodb:GetItem",
                                             "dynamodb:PutItem", "dynamodb:DeleteItem"],
             "Resource": f"arn:aws:dynamodb:us-east-1:000000000000:table/{TABLE}"},
        ],
    }
    aws("iam", "put-user-policy", "--user-name", USER,
        "--policy-name", "TerraformState", "--policy-document", json.dumps(policy))
    credentials_path = ROOT / "local.auto.tfvars.json"
    credentials = json.loads(credentials_path.read_text()) if credentials_path.exists() else None
    keys = aws("iam", "list-access-keys", "--user-name", USER)["AccessKeyMetadata"]
    valid_keys = {key["AccessKeyId"] for key in keys if key["Status"] == "Active"}
    if credentials is None or credentials["local_aws_access_key"] not in valid_keys:
        key = aws("iam", "create-access-key", "--user-name", USER)["AccessKey"]
        credentials = {"local_aws_access_key": key["AccessKeyId"],
                       "local_aws_secret_key": key["SecretAccessKey"]}
        private_file(credentials_path, json.dumps(credentials, indent=2) + "\n")

    backend = {
        "bucket": BUCKET, "key": "local/terraform.tfstate", "region": "us-east-1",
        "dynamodb_table": TABLE, "endpoints": {"s3": ENDPOINT, "dynamodb": ENDPOINT},
        "access_key": credentials["local_aws_access_key"],
        "secret_key": credentials["local_aws_secret_key"],
        "skip_credentials_validation": True, "skip_region_validation": True,
        "skip_requesting_account_id": True, "skip_metadata_api_check": True,
        "use_path_style": True,
    }
    private_file(ROOT / "backends/local.hcl", "\n".join(
        f"{key} = {json.dumps(value)}" for key, value in backend.items()) + "\n")
    private_file(ROOT / "backend.tf", 'terraform {\n  backend "s3" {}\n}\n')
    state_env = {
        **ENV,
        "AWS_ACCESS_KEY_ID": credentials["local_aws_access_key"],
        "AWS_SECRET_ACCESS_KEY": credentials["local_aws_secret_key"],
    }
    identity = aws("sts", "get-caller-identity", env=state_env)
    if not identity["Arn"].endswith(f"user/{USER}"):
        raise RuntimeError("State credentials resolved to an unexpected identity")
    try:
        aws("iam", "list-users", env=state_env)
    except subprocess.CalledProcessError as error:
        if "AccessDenied" not in error.stderr:
            raise
    else:
        raise RuntimeError("IAM enforcement failed: state user can list IAM users")
    print("Floci state bucket, lock table, and restricted IAM user are ready.")
    print("Verified state-user identity and denial of IAM administration.")
    print("Run terraform init -migrate-state -backend-config=backends/local.hcl")


if __name__ == "__main__":
    main()
