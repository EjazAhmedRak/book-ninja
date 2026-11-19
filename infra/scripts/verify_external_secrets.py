"""Exercise local ESO with a disposable, non-application secret and clean up."""

import base64
import json
import subprocess
import uuid

from bootstrap_floci import ENV, ROOT, aws
from bootstrap_external_secrets import USER, apply, kubectl, main as prepare
from floci_aws import environment


def main():
    prepare()  # Includes the local-cluster guard and never prints credentials.
    credentials = json.loads((ROOT / "local.external-secrets.credentials.json").read_text())
    reader_env = {**ENV, "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
                  "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"]}
    aws("secretsmanager", "describe-secret", "--secret-id", "book-ninja/local/backend", env=reader_env)
    try:
        aws("iam", "list-users", env=reader_env)
    except subprocess.CalledProcessError as error:
        if "AccessDenied" not in error.stderr:
            raise
    else:
        raise RuntimeError("Reader unexpectedly has IAM administration access")

    suffix = uuid.uuid4().hex[:12]
    name = f"provisioning-probe-{suffix}"
    policy_name = f"ProvisioningProbe-{suffix}"
    remote = f"book-ninja/local/{name}"
    marker = f"non-secret-eso-check-{suffix}"
    arn = aws("secretsmanager", "create-secret", "--name", remote,
              "--secret-string", json.dumps({"marker": marker}), env=environment())["ARN"]
    policy_created = False
    try:
        policy = {"Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Action": ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
            "Resource": arn}]}
        aws("iam", "put-user-policy", "--user-name", USER,
            "--policy-name", policy_name, "--policy-document", json.dumps(policy))
        policy_created = True
        kubectl("wait", "--for=condition=Ready", "secretstore/backend-runtime",
                "-n", "book-ninja", "--timeout=120s")
        apply({"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret",
               "metadata": {"name": name, "namespace": "book-ninja"}, "spec": {
                   "refreshInterval": "10s", "secretStoreRef": {"name": "backend-runtime", "kind": "SecretStore"},
                   "target": {"name": name, "creationPolicy": "Owner"},
                   "data": [{"secretKey": "marker", "remoteRef": {"key": remote, "property": "marker"}}]}})
        kubectl("wait", "--for=condition=Ready", f"externalsecret/{name}",
                "-n", "book-ninja", "--timeout=120s")
        synced = json.loads(kubectl("get", "secret", name, "-n", "book-ninja", "-o", "json"))
        if base64.b64decode(synced["data"]["marker"]).decode() != marker:
            raise RuntimeError("ESO synchronization returned unexpected content")
        print("ESO synchronized the disposable probe; backend runtime values were untouched.")
    finally:
        failures = []
        cleanup = [
            ("ExternalSecret", lambda: kubectl("delete", "externalsecret", name, "-n", "book-ninja", "--ignore-not-found")),
            ("probe Secret", lambda: kubectl("delete", "secret", name, "-n", "book-ninja", "--ignore-not-found")),
            ("remote probe", lambda: aws("secretsmanager", "delete-secret", "--secret-id", arn,
                                         "--force-delete-without-recovery", env=environment())),
        ]
        if policy_created:
            cleanup.append(("temporary IAM grant", lambda: aws("iam", "delete-user-policy",
                "--user-name", USER, "--policy-name", policy_name)))
        for label, action in cleanup:
            try:
                action()
            except Exception:
                failures.append(label)
        if failures:
            raise RuntimeError(f"Cleanup failed for {name}: {', '.join(failures)}")
    print("Probe resources and temporary IAM grant removed; reader remains backend-only.")


if __name__ == "__main__":
    main()
