"""Publish a clean backend revision to local Floci, verify its digest, record receipt."""

import argparse
import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path

from bootstrap_floci import ROOT, aws, private_file
from floci_aws import environment

PROJECT = ROOT.parent
REPOSITORY = "book-ninja-local-backend"
# Docker 29's containerd store supports plain HTTP on literal localhost. Floci's
# path-style endpoint addresses the same account/region repository as its URI.
LOCAL_REPOSITORY = f"localhost:4566/000000000000/us-east-1/{REPOSITORY}"


def output(*args, cwd=PROJECT):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def main(project=PROJECT):
    if output(
        "git", "status", "--porcelain", "--untracked-files=all", "--", "apps/backend", cwd=project
    ):
        raise RuntimeError("Commit backend source changes before publishing a Git SHA tag")
    revision = output("git", "rev-parse", "HEAD", cwd=project)
    env = environment()
    repository = aws("ecr", "describe-repositories", "--repository-names", REPOSITORY, env=env)[
        "repositories"
    ][0]
    if (
        repository["registryId"] != "000000000000"
        or repository["imageTagMutability"] != "IMMUTABLE"
    ):
        raise RuntimeError("Expected the immutable local Floci repository")
    node_info = json.loads(
        output(
            "kubectl",
            "--kubeconfig",
            str(ROOT / "local.kubeconfig.json"),
            "get",
            "nodes",
            "-o",
            "json",
        )
    )
    architectures = {node["status"]["nodeInfo"]["architecture"] for node in node_info["items"]}
    if len(architectures) != 1 or not architectures <= {"arm64", "amd64"}:
        raise RuntimeError("Local publisher requires a single supported node architecture")
    platform = f"linux/{architectures.pop()}"
    tag = f"{LOCAL_REPOSITORY}:{revision}"
    # Describe all tags so the empty repository is handled without catching or
    # hiding authorization, network, or AWS CLI failures.
    images = aws("ecr", "describe-images", "--repository-name", REPOSITORY, env=env)["imageDetails"]
    existing = [image for image in images if revision in image.get("imageTags", [])]
    if not existing:
        subprocess.run(
            [
                "docker",
                "build",
                "--platform",
                platform,
                "--provenance=false",
                "--label",
                f"org.opencontainers.image.revision={revision}",
                "--tag",
                tag,
                str(project / "apps/backend"),
            ],
            check=True,
            cwd=project,
        )
    auth = aws("ecr", "get-authorization-token", env=env)["authorizationData"][0]
    username, password = base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
    # Keep the disposable ECR login out of the user's persistent Docker config.
    with tempfile.TemporaryDirectory(prefix="book-ninja-ecr-") as docker_config:
        docker = ["docker", "--config", docker_config]
        subprocess.run(
            [*docker, "login", "--username", username, "--password-stdin", "localhost:4566"],
            input=password,
            text=True,
            check=True,
            capture_output=True,
        )
        if not existing:
            subprocess.run([*docker, "push", tag], check=True)
        details = aws(
            "ecr",
            "describe-images",
            "--repository-name",
            REPOSITORY,
            "--image-ids",
            f"imageTag={revision}",
            env=env,
        )["imageDetails"]
        digest = details[0]["imageDigest"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise RuntimeError("ECR returned an invalid image digest")
        image = f"{LOCAL_REPOSITORY}@{digest}"
        subprocess.run([*docker, "pull", "--platform", platform, image], check=True)
    inspected = json.loads(output("docker", "image", "inspect", image))[0]
    if image not in inspected.get("RepoDigests", []):
        raise RuntimeError("Pulled image digest does not match ECR")
    if inspected["Config"].get("Labels", {}).get("org.opencontainers.image.revision") != revision:
        raise RuntimeError("Published image revision label does not match its Git SHA tag")
    if inspected["Config"].get("User") in {None, "", "root", "0", "0:0"}:
        raise RuntimeError("Backend image must run as a non-root user")
    receipt = {
        "revision": revision,
        "platform": platform,
        "repository": LOCAL_REPOSITORY,
        "imageDigest": digest,
        "image": image,
    }
    (ROOT / "manual").mkdir(exist_ok=True)
    private_file(ROOT / "manual/backend-image.json", json.dumps(receipt, indent=2) + "\n")
    print(f"Verified local backend image: {image}")
    print("Receipt saved to infra/manual/backend-image.json; no application values were used.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=PROJECT,
        help="Clean source checkout; local credentials remain in the control checkout",
    )
    main(parser.parse_args().source_root.resolve())
