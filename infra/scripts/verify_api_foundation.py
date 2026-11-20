"""Verify local ALB routing with a disposable Docker target, then remove it."""

import json
import re
import subprocess
import time
import uuid

from bootstrap_argocd import check_local
from bootstrap_floci import ROOT, aws
from floci_aws import environment
from publish_backend import LOCAL_REPOSITORY


def main():
    check_local()
    outputs = json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(ROOT), "output", "-json", "api_foundation"], text=True
        )
    )
    if not outputs["alb_arn"].startswith("arn:aws:elasticloadbalancing:us-east-1:000000000000:"):
        raise RuntimeError("Expected the local Floci ALB")
    env = environment()
    link = aws("apigatewayv2", "get-vpc-link", "--vpc-link-id", outputs["vpc_link_id"], env=env)
    if link["VpcLinkStatus"] != "AVAILABLE":
        raise RuntimeError("VPC Link is not available")
    group = outputs["target_group_arn"]
    existing = aws("elbv2", "describe-target-health", "--target-group-arn", group, env=env)
    if existing["TargetHealthDescriptions"]:
        raise RuntimeError("Refusing to attach a disposable probe to an in-use target group")
    receipt = json.loads((ROOT / "manual/backend-image.json").read_text())
    image = receipt["image"]
    if not re.fullmatch(re.escape(LOCAL_REPOSITORY) + r"@sha256:[0-9a-f]{64}", image):
        raise RuntimeError("Expected an already published local image for the HTTP fixture")
    subprocess.run(["docker", "image", "inspect", image], check=True, stdout=subprocess.DEVNULL)
    suffix = uuid.uuid4().hex[:12]
    container = f"book-ninja-alb-probe-{suffix}"
    marker = "non-secret-alb-probe-" + suffix
    target = None
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                container,
                "--network",
                "infra_default",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "64m",
                "--cpus",
                "0.25",
                "--env",
                f"PROBE_MARKER={marker}",
                "--mount",
                f"type=bind,source={ROOT / 'tests/fixtures/alb_probe.py'},target=/probe.py,readonly",
                image,
                "python",
                "-B",
                "/probe.py",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        inspected = json.loads(
            subprocess.check_output(["docker", "inspect", container], text=True)
        )[0]
        address = inspected["NetworkSettings"]["Networks"]["infra_default"]["IPAddress"]
        target = f"Id={address},Port=8000,AvailabilityZone=all"
        aws("elbv2", "register-targets", "--target-group-arn", group, "--targets", target, env=env)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            health = aws(
                "elbv2",
                "describe-target-health",
                "--target-group-arn",
                group,
                "--targets",
                target,
                env=env,
            )["TargetHealthDescriptions"]
            if health and health[0]["TargetHealth"]["State"] == "healthy":
                break
            time.sleep(2)
        else:
            raise RuntimeError("Disposable target did not become healthy")
        # Port 80 is inside Floci's container, not published to the host. Select
        # its ALB by Host header from another container on the same Docker network.
        code = "\n".join(
            [
                "import http.client, json",
                "client=http.client.HTTPConnection('infra-floci-1',80,timeout=15)",
                f"client.request('GET','/routing/check?probe=1',headers={{'Host':{outputs['alb_dns_name']!r},'X-Book-Ninja-Probe':'routing-check'}})",
                "response=client.getresponse()",
                "assert response.status==200, response.status",
                f"assert json.load(response)=={{'marker':{marker!r},'path':'/routing/check?probe=1','header':'routing-check'}}",
                "print('ALB health/routing/path/query/header verification passed.')",
            ]
        )
        subprocess.run(["docker", "exec", container, "python", "-B", "-c", code], check=True)
    finally:
        try:
            if target is not None:
                aws(
                    "elbv2",
                    "deregister-targets",
                    "--target-group-arn",
                    group,
                    "--targets",
                    target,
                    env=env,
                )
        finally:
            subprocess.run(
                ["docker", "rm", "--force", container], check=True, stdout=subprocess.DEVNULL
            )
    remaining = aws("elbv2", "describe-target-health", "--target-group-arn", group, env=env)
    if remaining["TargetHealthDescriptions"]:
        raise RuntimeError("Target group still contains probe metadata after deregistration")
    print(
        "Disposable target/container removed. Application traffic, VPC isolation, and SSE were not tested."
    )


if __name__ == "__main__":
    main()
