"""Prepare local-only ESO reader credentials and an in-cluster Floci endpoint."""

import ipaddress
import json
import subprocess
from urllib.parse import urlparse

from bootstrap_floci import ROOT, aws, private_file

USER = "book-ninja-local-external-secrets"
KUBECONFIG = ROOT / "local.kubeconfig.json"


def kubectl(*args, payload=None):
    result = subprocess.run(
        ["kubectl", "--kubeconfig", str(KUBECONFIG), *args],
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True, text=True,
    )
    if result.returncode:
        # Failed apply diagnostics can echo submitted Secret data. Do not print them.
        raise RuntimeError(f"kubectl {args[0]} failed; inspect cluster status without dumping Secrets")
    return result.stdout


def apply(document):
    kubectl("apply", "-f", "-", payload=document)


def main():
    config = json.loads(kubectl("config", "view", "--minify", "-o", "json"))
    server = urlparse(config["clusters"][0]["cluster"]["server"])
    if server.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("This bootstrap is only for the local Floci Kubernetes API")
    aws("iam", "get-user", "--user-name", USER)
    inspected = subprocess.run(
        ["docker", "inspect", "infra-floci-1"],
        capture_output=True, text=True, check=True,
    )
    address = json.loads(inspected.stdout)[0]["NetworkSettings"]["Networks"]["infra_default"]["IPAddress"]
    if ipaddress.ip_address(address).version != 4:
        raise RuntimeError("Expected a running Floci container with an IPv4 address")
    path = ROOT / "local.external-secrets.credentials.json"
    credentials = json.loads(path.read_text()) if path.exists() else None
    active = {item["AccessKeyId"] for item in aws(
        "iam", "list-access-keys", "--user-name", USER)["AccessKeyMetadata"]
        if item["Status"] == "Active"}
    if credentials is None or credentials["AccessKeyId"] not in active:
        key = aws("iam", "create-access-key", "--user-name", USER)["AccessKey"]
        credentials = {"AccessKeyId": key["AccessKeyId"], "SecretAccessKey": key["SecretAccessKey"]}
    private_file(path, json.dumps(credentials, indent=2) + "\n")

    apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "book-ninja"}})
    apply({"apiVersion": "v1", "kind": "Service", "metadata": {
        "name": "floci-aws", "namespace": "book-ninja"}, "spec": {
        "ports": [{"name": "aws", "port": 4566, "targetPort": 4566}]}})
    apply({"apiVersion": "discovery.k8s.io/v1", "kind": "EndpointSlice", "metadata": {
        "name": "floci-aws-local", "namespace": "book-ninja", "labels": {
            "kubernetes.io/service-name": "floci-aws",
            "endpointslice.kubernetes.io/managed-by": "book-ninja-local-bootstrap"}},
        "addressType": "IPv4", "ports": [{"name": "aws", "port": 4566, "protocol": "TCP"}],
        "endpoints": [{"addresses": [address], "conditions": {"ready": True}}]})
    apply({"apiVersion": "v1", "kind": "Secret", "type": "Opaque", "metadata": {
        "name": "floci-secrets-reader", "namespace": "book-ninja"}, "stringData": {
        "access-key-id": credentials["AccessKeyId"],
        "secret-access-key": credentials["SecretAccessKey"]}})
    print("Local ESO reader Secret and Floci Service/EndpointSlice are ready; no keys printed.")


if __name__ == "__main__":
    main()
