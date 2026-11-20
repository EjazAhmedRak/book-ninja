"""Prepare local-only controller credentials and dynamic nonsecret Helm values."""

import json
import subprocess

from bootstrap_argocd import check_local
from bootstrap_external_secrets import apply
from bootstrap_floci import ROOT, aws, private_file

USER = "book-ninja-local-load-balancer-controller"
NAMESPACE = "load-balancer-system"


def ensure_node_network():
    inspected = json.loads(
        subprocess.check_output(
            ["docker", "inspect", "infra-floci-1", "floci-aws-eks-book-ninja-local"], text=True
        )
    )
    floci_networks = inspected[0]["NetworkSettings"]["Networks"]
    node_networks = inspected[1]["NetworkSettings"]["Networks"]
    if "bridge" not in node_networks:
        raise RuntimeError("Expected the local k3s node on Docker's bridge network")
    if "bridge" not in floci_networks:
        subprocess.run(["docker", "network", "connect", "bridge", "infra-floci-1"], check=True)


def main():
    check_local()
    aws("iam", "get-user", "--user-name", USER)
    ensure_node_network()
    path = ROOT / "local.load-balancer-controller.credentials.json"
    credentials = json.loads(path.read_text()) if path.exists() else None
    active = {
        key["AccessKeyId"]
        for key in aws("iam", "list-access-keys", "--user-name", USER)["AccessKeyMetadata"]
        if key["Status"] == "Active"
    }
    if credentials is None or credentials["AccessKeyId"] not in active:
        key = aws("iam", "create-access-key", "--user-name", USER)["AccessKey"]
        credentials = {"AccessKeyId": key["AccessKeyId"], "SecretAccessKey": key["SecretAccessKey"]}
    private_file(path, json.dumps(credentials, indent=2) + "\n")
    apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE}})
    apply(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": "Opaque",
            "metadata": {"name": "floci-load-balancer-controller", "namespace": NAMESPACE},
            "stringData": {
                "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
                "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"],
            },
        }
    )
    vpc_id = subprocess.check_output(
        ["terraform", "-chdir=" + str(ROOT), "output", "-raw", "vpc_id"], text=True
    ).strip()
    (ROOT / "manual").mkdir(exist_ok=True)
    private_file(
        ROOT / "manual/load-balancer-controller-values.json", json.dumps({"vpcId": vpc_id}) + "\n"
    )
    print("Local controller credentials and nonsecret VPC values prepared; no keys printed.")


if __name__ == "__main__":
    main()
