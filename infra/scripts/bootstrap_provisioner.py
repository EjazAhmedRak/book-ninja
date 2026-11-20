"""Create the local infrastructure provisioner, separate from state access."""

import json

from bootstrap_floci import ROOT, aws, private_file


def ensure_api_policy(user):
    """Use an attached managed policy: the existing user inline grant is near 2 KiB."""
    name = "book-ninja-local-api-provisioning"
    document = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Action": ["elasticloadbalancing:*"], "Resource": "*",
    }, {
        "Effect": "Allow", "Action": ["apigateway:GET", "apigateway:POST", "apigateway:PUT",
                                     "apigateway:PATCH", "apigateway:DELETE"],
        "Resource": ["arn:aws:apigateway:us-east-1::/restapis*",
                     "arn:aws:apigateway:us-east-1::/vpclinks*"],
    }]}
    policies = aws("iam", "list-policies", "--scope", "Local")["Policies"]
    existing = next((policy for policy in policies if policy["PolicyName"] == name), None)
    if existing is None:
        arn = aws("iam", "create-policy", "--policy-name", name,
                  "--policy-document", json.dumps(document))["Policy"]["Arn"]
    else:
        arn = existing["Arn"]
        current = aws("iam", "get-policy-version", "--policy-arn", arn,
                      "--version-id", existing["DefaultVersionId"])["PolicyVersion"]["Document"]
        if current != document:
            versions = aws("iam", "list-policy-versions", "--policy-arn", arn)["Versions"]
            if len(versions) >= 5:
                oldest = min((version for version in versions if not version["IsDefaultVersion"]),
                             key=lambda version: version["CreateDate"])
                aws("iam", "delete-policy-version", "--policy-arn", arn,
                    "--version-id", oldest["VersionId"])
            aws("iam", "create-policy-version", "--policy-arn", arn,
                "--policy-document", json.dumps(document), "--set-as-default")
    aws("iam", "attach-user-policy", "--user-name", user, "--policy-arn", arn)


def main():
    user = "book-ninja-network-provisioner"
    if user not in [item["UserName"] for item in aws("iam", "list-users")["Users"]]:
        aws("iam", "create-user", "--user-name", user)
    actions = [
        "Describe*", "CreateVpc", "DeleteVpc", "ModifyVpcAttribute",
        "CreateSubnet", "DeleteSubnet", "ModifySubnetAttribute",
        "CreateInternetGateway", "DeleteInternetGateway", "AttachInternetGateway",
        "DetachInternetGateway", "CreateRouteTable", "DeleteRouteTable",
        "CreateRoute", "DeleteRoute", "ReplaceRoute", "AssociateRouteTable",
        "DisassociateRouteTable", "AllocateAddress", "ReleaseAddress",
        "CreateNatGateway", "DeleteNatGateway", "CreateSecurityGroup",
        "DeleteSecurityGroup", "AuthorizeSecurityGroupIngress",
        "RevokeSecurityGroupIngress", "AuthorizeSecurityGroupEgress",
        "RevokeSecurityGroupEgress", "CreateTags", "DeleteTags",
    ]
    policy = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Action": [f"ec2:{action}" for action in actions],
        "Resource": "*",
    }, {
        "Effect": "Allow", "Action": ["eks:*", "ecr:*"], "Resource": "*",
    }, {
        "Effect": "Allow", "Action": ["s3:*"],
        "Resource": ["arn:aws:s3:::book-ninja-local-frontend-*",
                     "arn:aws:s3:::book-ninja-local-frontend-*/*"],
    }, {
        "Effect": "Allow", "Action": ["cloudfront:*"], "Resource": "*",
    }, {
        "Effect": "Allow", "Action": ["secretsmanager:*"],
        "Resource": "arn:aws:secretsmanager:us-east-1:000000000000:secret:book-ninja/local/*",
    }, {
        "Effect": "Allow", "Action": [
            "iam:CreateUser", "iam:GetUser", "iam:DeleteUser", "iam:TagUser", "iam:UntagUser",
            "iam:ListUserTags", "iam:PutUserPolicy", "iam:GetUserPolicy", "iam:DeleteUserPolicy",
            "iam:ListUserPolicies", "iam:ListAttachedUserPolicies",
        ], "Resource": "arn:aws:iam::000000000000:user/book-ninja-local-external-secrets",
    }, {
        "Effect": "Allow", "Action": [
            "iam:CreateRole", "iam:GetRole", "iam:DeleteRole", "iam:TagRole", "iam:UntagRole",
            "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
            "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PassRole",
        ], "Resource": "arn:aws:iam::000000000000:role/book-ninja-local-*",
    }]}
    aws("iam", "put-user-policy", "--user-name", user,
        "--policy-name", "LocalNetworkProvisioning", "--policy-document", json.dumps(policy))
    ensure_api_policy(user)
    path = ROOT / "local.provisioner.auto.tfvars.json"
    saved = json.loads(path.read_text()) if path.exists() else None
    active = {item["AccessKeyId"] for item in aws(
        "iam", "list-access-keys", "--user-name", user)["AccessKeyMetadata"]
        if item["Status"] == "Active"}
    if saved is None or saved["local_provisioning_access_key"] not in active:
        key = aws("iam", "create-access-key", "--user-name", user)["AccessKey"]
        saved = {"local_provisioning_access_key": key["AccessKeyId"],
                 "local_provisioning_secret_key": key["SecretAccessKey"]}
    private_file(path, json.dumps(saved, indent=2) + "\n")
    print("Local infrastructure provisioner ready; credentials saved in an ignored owner-only file.")


if __name__ == "__main__":
    main()
