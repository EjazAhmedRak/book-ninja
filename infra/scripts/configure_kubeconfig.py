"""Write a separate local kubeconfig without embedding IAM secrets."""

import json
import subprocess
import sys

from bootstrap_floci import ROOT, private_file
from floci_aws import environment


def main():
    name = "book-ninja-local"
    result = subprocess.run([
        "aws", "--endpoint-url", "http://localhost:4566", "eks", "describe-cluster",
        "--name", name, "--output", "json",
    ], env=environment(), capture_output=True, text=True, check=True)
    cluster = json.loads(result.stdout)["cluster"]
    config = {
        "apiVersion": "v1", "kind": "Config", "current-context": name,
        "clusters": [{"name": name, "cluster": {
            "server": cluster["endpoint"],
            "certificate-authority-data": cluster["certificateAuthority"]["data"],
        }}],
        "contexts": [{"name": name, "context": {"cluster": name, "user": name}}],
        "users": [{"name": name, "user": {"exec": {
            "apiVersion": "client.authentication.k8s.io/v1beta1",
            "command": sys.executable,
            "args": [str(ROOT / "scripts/floci_aws.py"), "eks", "get-token", "--cluster-name", name],
            "interactiveMode": "Never",
        }}}],
    }
    path = ROOT / "local.kubeconfig.json"
    private_file(path, json.dumps(config, indent=2) + "\n")
    print(f"Kubeconfig ready: {path}")


if __name__ == "__main__":
    main()
