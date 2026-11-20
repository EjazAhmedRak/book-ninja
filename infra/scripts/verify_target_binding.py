"""Verify local controller reconciliation with a disposable host-network HTTP pod."""

import json
import re
import subprocess
import time
import uuid

from bootstrap_argocd import check_local
from bootstrap_external_secrets import apply, kubectl
from bootstrap_floci import ROOT, aws
from floci_aws import environment
from publish_backend import LOCAL_REPOSITORY


def main():
    check_local()
    foundation = json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(ROOT), "output", "-json", "api_foundation"], text=True
        )
    )
    vpc = subprocess.check_output(
        ["terraform", "-chdir=" + str(ROOT), "output", "-raw", "vpc_id"], text=True
    ).strip()
    group, env = foundation["target_group_arn"], environment()
    if not group.startswith("arn:aws:elasticloadbalancing:us-east-1:000000000000:"):
        raise RuntimeError("Expected the local target group")
    if aws("elbv2", "describe-target-health", "--target-group-arn", group, env=env)[
        "TargetHealthDescriptions"
    ]:
        raise RuntimeError("Refusing to probe an in-use target group")
    receipt = json.loads((ROOT / "manual/backend-image.json").read_text())
    if not re.fullmatch(re.escape(LOCAL_REPOSITORY) + r"@sha256:[0-9a-f]{64}", receipt["image"]):
        raise RuntimeError("Expected a verified local backend image")
    port = int(
        subprocess.check_output(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "container:floci-aws-eks-book-ninja-local",
                "--read-only",
                "--cap-drop=ALL",
                receipt["image"],
                "python",
                "-B",
                "-c",
                "import socket; s=socket.socket(); s.bind(('0.0.0.0',0)); print(s.getsockname()[1])",
            ],
            text=True,
        )
    )
    name = "target-binding-probe-" + uuid.uuid4().hex[:12]
    marker = "non-secret-" + name
    labels = {"book-ninja.io/probe": name}
    fixture = (ROOT / "tests/fixtures/alb_probe.py").read_text()
    target = None
    try:
        apply(
            {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {"name": name, "namespace": "book-ninja", "labels": labels},
                "spec": {
                    "hostNetwork": True,
                    "dnsPolicy": "ClusterFirstWithHostNet",
                    "restartPolicy": "Never",
                    "terminationGracePeriodSeconds": 5,
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "fixture",
                            "image": receipt["image"],
                            "imagePullPolicy": "Never",
                            "command": ["python", "-B", "-c", fixture],
                            "env": [
                                {"name": "PROBE_MARKER", "value": marker},
                                {"name": "PROBE_PORT", "value": str(port)},
                            ],
                            "readinessProbe": {
                                "httpGet": {"path": "/livez", "port": port},
                                "periodSeconds": 2,
                            },
                            "securityContext": {
                                "readOnlyRootFilesystem": True,
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": {
                                "requests": {"cpu": "25m", "memory": "32Mi"},
                                "limits": {"cpu": "200m", "memory": "128Mi"},
                            },
                        }
                    ],
                },
            }
        )
        kubectl(
            "wait", "--for=condition=Ready", "pod/" + name, "-n", "book-ninja", "--timeout=120s"
        )
        pod = json.loads(kubectl("get", "pod", name, "-n", "book-ninja", "-o", "json"))
        address = pod["status"]["podIP"]
        target = f"Id={address},Port={port},AvailabilityZone=all"
        apply(
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": name, "namespace": "book-ninja"},
                "spec": {"selector": labels, "ports": [{"port": 8000, "targetPort": port}]},
            }
        )
        apply(
            {
                "apiVersion": "elbv2.k8s.aws/v1beta1",
                "kind": "TargetGroupBinding",
                "metadata": {"name": name, "namespace": "book-ninja"},
                "spec": {
                    "targetGroupARN": group,
                    "targetType": "ip",
                    "vpcID": vpc,
                    "serviceRef": {"name": name, "port": 8000},
                },
            }
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            health = aws("elbv2", "describe-target-health", "--target-group-arn", group, env=env)[
                "TargetHealthDescriptions"
            ]
            if any(
                item["Target"]["Id"] == address and item["TargetHealth"]["State"] == "healthy"
                for item in health
            ):
                break
            time.sleep(2)
        else:
            raise RuntimeError(
                "Controller did not register a healthy fixture target; inspect its logs and local routing"
            )
        code = "\n".join(
            [
                "import http.client,json",
                "client=http.client.HTTPConnection('127.0.0.1',80,timeout=15)",
                f"client.request('GET','/binding/check?probe=1',headers={{'Host':{foundation['alb_dns_name']!r},'X-Book-Ninja-Probe':'binding-check'}})",
                "response=client.getresponse()",
                "assert response.status==200,response.status",
                f"assert json.load(response)=={{'marker':{marker!r},'path':'/binding/check?probe=1','header':'binding-check'}}",
                "print('Controller registered the host-network pod; ALB HTTP forwarding passed.')",
            ]
        )
        # The controller image has no Python; use the existing Floci ALB Docker
        # network via a one-shot published backend image without mounting secrets.
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "container:infra-floci-1",
                "--read-only",
                "--cap-drop=ALL",
                receipt["image"],
                "python",
                "-B",
                "-c",
                code,
            ],
            check=True,
        )
    finally:
        failures = []
        cleanup = [
            (
                "binding",
                lambda: kubectl(
                    "delete",
                    "targetgroupbinding",
                    name,
                    "-n",
                    "book-ninja",
                    "--ignore-not-found",
                    "--timeout=60s",
                ),
            ),
            (
                "service",
                lambda: kubectl(
                    "delete", "service", name, "-n", "book-ninja", "--ignore-not-found"
                ),
            ),
            (
                "pod",
                lambda: kubectl(
                    "delete", "pod", name, "-n", "book-ninja", "--ignore-not-found", "--timeout=60s"
                ),
            ),
        ]
        for label, action in cleanup:
            try:
                action()
            except Exception:
                failures.append(label)
        if target is not None:
            remaining = aws(
                "elbv2", "describe-target-health", "--target-group-arn", group, env=env
            )["TargetHealthDescriptions"]
            if any(
                item["Target"]["Id"] == address and item["Target"]["Port"] == port
                for item in remaining
            ):
                aws(
                    "elbv2",
                    "deregister-targets",
                    "--target-group-arn",
                    group,
                    "--targets",
                    target,
                    env=env,
                )
                failures.append("controller deregistration (provisioner fallback used)")
        if failures:
            raise RuntimeError(f"Probe cleanup failed for {name}: {', '.join(failures)}")
    remaining = aws("elbv2", "describe-target-health", "--target-group-arn", group, env=env)[
        "TargetHealthDescriptions"
    ]
    if remaining:
        raise RuntimeError("Probe target group did not return to empty")
    print(
        "Probe binding/service/pod removed; target group empty. Ordinary pod routing, application startup, and SSE remain separate checks."
    )


if __name__ == "__main__":
    main()
