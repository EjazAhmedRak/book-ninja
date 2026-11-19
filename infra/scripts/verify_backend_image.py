"""Preload the verified Floci image into local k3s and run a disposable image probe."""

import json
import re
import subprocess
import uuid
from urllib.parse import urlparse

from bootstrap_external_secrets import apply, kubectl
from bootstrap_floci import ROOT, aws
from floci_aws import environment
from publish_backend import LOCAL_REPOSITORY, REPOSITORY, output

NODE = "floci-aws-eks-book-ninja-local"


def main():
    config = json.loads(kubectl("config", "view", "--minify", "-o", "json"))
    if urlparse(config["clusters"][0]["cluster"]["server"]).hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RuntimeError("Image preload is only supported on local Floci")
    receipt = json.loads((ROOT / "manual/backend-image.json").read_text())
    digest, revision = receipt["imageDigest"], receipt["revision"]
    if (
        receipt["repository"] != LOCAL_REPOSITORY
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        or not re.fullmatch(r"[0-9a-f]{40}", revision)
    ):
        raise RuntimeError("Invalid local image publication receipt")
    remote = aws(
        "ecr",
        "describe-images",
        "--repository-name",
        REPOSITORY,
        "--image-ids",
        f"imageTag={revision}",
        env=environment(),
    )["imageDetails"][0]
    if remote["imageDigest"] != digest:
        raise RuntimeError("Receipt no longer matches the immutable ECR tag")
    tag, image = f"{LOCAL_REPOSITORY}:{revision}", f"{LOCAL_REPOSITORY}@{digest}"
    # k3s has a separate containerd image store, and localhost there is not the
    # host's registry. Preload explicitly without changing daemon trust/mirrors.
    saver = subprocess.Popen(["docker", "image", "save", tag], stdout=subprocess.PIPE)
    try:
        imported = subprocess.run(
            ["docker", "exec", "-i", NODE, "ctr", "-n", "k8s.io", "images", "import", "-"],
            stdin=saver.stdout,
        )
    finally:
        saver.stdout.close()
        saved = saver.wait()
    if imported.returncode or saved:
        raise RuntimeError("Local image import failed")
    records = output(
        "docker", "exec", NODE, "ctr", "-n", "k8s.io", "images", "list", f"name=={tag}"
    )
    if not any(
        len(fields) >= 3 and fields[0] == tag and fields[2] == digest
        for fields in map(str.split, records.splitlines()[1:])
    ):
        raise RuntimeError("Imported image manifest does not match the ECR digest")
    subprocess.run(
        ["docker", "exec", NODE, "ctr", "-n", "k8s.io", "images", "tag", "--force", tag, image],
        check=True,
    )
    name = f"backend-image-probe-{uuid.uuid4().hex[:12]}"
    try:
        apply(
            {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {"name": name, "namespace": "book-ninja"},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 1000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "probe",
                            "image": image,
                            "imagePullPolicy": "Never",
                            "command": [
                                "python",
                                "-B",
                                "-c",
                                "import os, fastapi, uvicorn; assert os.getuid() == 1000; print('image-preflight-ok')",
                            ],
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "64Mi"},
                                "limits": {"cpu": "500m", "memory": "256Mi"},
                            },
                        }
                    ],
                },
            }
        )
        kubectl(
            "wait",
            "--for=jsonpath={.status.phase}=Succeeded",
            "pod/" + name,
            "-n",
            "book-ninja",
            "--timeout=120s",
        )
        if kubectl("logs", name, "-n", "book-ninja").strip() != "image-preflight-ok":
            raise RuntimeError("Image execution probe returned unexpected output")
        print(
            "Verified digest-pinned image execution as UID 1000 with a read-only filesystem on k3s."
        )
    finally:
        kubectl("delete", "pod", name, "-n", "book-ninja", "--ignore-not-found")
    print("Probe removed. Backend application startup and external integrations remain untested.")


if __name__ == "__main__":
    main()
