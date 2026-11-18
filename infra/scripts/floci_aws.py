"""Run AWS CLI commands against Floci with the local provisioning identity."""

import json
import os
import subprocess
import sys

from bootstrap_floci import ROOT


def environment():
    credentials = json.loads((ROOT / "local.provisioner.auto.tfvars.json").read_text())
    return {
        **os.environ,
        "AWS_ACCESS_KEY_ID": credentials["local_provisioning_access_key"],
        "AWS_SECRET_ACCESS_KEY": credentials["local_provisioning_secret_key"],
        "AWS_SESSION_TOKEN": "", "AWS_DEFAULT_REGION": "us-east-1", "AWS_PAGER": "",
    }


if __name__ == "__main__":
    raise SystemExit(subprocess.call(
        ["aws", "--endpoint-url", "http://localhost:4566", *sys.argv[1:]],
        env=environment(),
    ))
