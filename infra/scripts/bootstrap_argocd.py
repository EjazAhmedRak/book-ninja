"""Bootstrap local Argo CD projects and privately save its initial admin password."""

import argparse
import base64
import json
import re
import subprocess
from urllib.parse import urlparse

from bootstrap_external_secrets import apply, kubectl
from bootstrap_floci import ROOT, private_file


def check_local():
    config = json.loads(kubectl("config", "view", "--minify", "-o", "json"))
    if urlparse(config["clusters"][0]["cluster"]["server"]).hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RuntimeError("This Argo CD bootstrap is only for local Floci")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-local", action="store_true")
    parser.add_argument(
        "--preview-revision", help="Render an available Git commit in Argo CD without syncing"
    )
    parser.add_argument(
        "--activate-root",
        action="store_true",
        help="Register root Application after its manifests merge",
    )
    args = parser.parse_args()
    check_local()
    if args.check_local:
        print("Verified local Kubernetes API endpoint.")
        return
    if args.preview_revision and not re.fullmatch(r"[0-9a-f]{40}", args.preview_revision):
        raise RuntimeError("Preview revision must be an explicit Git commit SHA")
    if args.preview_revision and args.activate_root:
        raise RuntimeError("Choose preview or root activation, not both")
    kubectl("apply", "-f", str(ROOT.parent / "gitops/argocd/local/projects.yaml"))
    value = kubectl(
        "get",
        "secret",
        "argocd-initial-admin-secret",
        "-n",
        "argocd",
        "--ignore-not-found",
        "-o",
        "json",
    )
    if value.strip():
        password = base64.b64decode(json.loads(value)["data"]["password"]).decode()
        (ROOT / "manual").mkdir(exist_ok=True)
        private_file(ROOT / "manual/argocd-initial-admin-password", password + "\n")
        print(
            "Initial admin password saved to ignored owner-only infra/manual/argocd-initial-admin-password."
        )
    if args.preview_revision:
        subprocess.run(
            [
                "gh",
                "api",
                "repos/EjazAhmedRak/book-ninja/contents/gitops/charts/book-ninja/Chart.yaml"
                f"?ref={args.preview_revision}",
                "--silent",
            ],
            check=True,
        )
        application = json.loads(
            kubectl(
                "create",
                "--dry-run=client",
                "-f",
                str(ROOT.parent / "gitops/argocd/local/backend-application.yaml"),
                "-o",
                "json",
            )
        )
        application["spec"]["source"]["targetRevision"] = args.preview_revision
        application["metadata"]["annotations"] = {"book-ninja.io/bootstrap-mode": "manual-preview"}
        apply(application)
        print(
            "Registered manual-sync backend preview. No sync operation or automated policy was enabled."
        )
    if args.activate_root:
        subprocess.run(
            [
                "gh",
                "api",
                "repos/EjazAhmedRak/book-ninja/contents/gitops/argocd/local/projects.yaml"
                "?ref=develop",
                "--silent",
            ],
            check=True,
        )
        kubectl("apply", "-f", str(ROOT.parent / "gitops/argocd/root-application.yaml"))
        print("Registered root Application for merged develop; sync remains manual.")
    print("Scoped projects ready; no workload was synced.")


if __name__ == "__main__":
    main()
