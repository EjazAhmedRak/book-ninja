"""Protect managed IAM versions and avoid routing probes through live targets."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap_provisioner as provisioner
import verify_api_foundation as verifier


class ApiFoundationTests(unittest.TestCase):
    def test_policy_update_never_deletes_the_default_version(self):
        policy = {
            "PolicyName": "book-ninja-local-api-provisioning",
            "Arn": "local-policy",
            "DefaultVersionId": "v1",
        }
        versions = [
            {"VersionId": f"v{i}", "IsDefaultVersion": i == 1, "CreateDate": f"2026-01-0{i}"}
            for i in range(1, 6)
        ]
        with patch.object(
            provisioner,
            "aws",
            side_effect=[
                {"Policies": [policy]},
                {"PolicyVersion": {"Document": {}}},
                {"Versions": versions},
                {},
                {},
                {},
            ],
        ) as aws:
            provisioner.ensure_api_policy("local-user")
            self.assertEqual(
                aws.call_args_list[3].args,
                (
                    "iam",
                    "delete-policy-version",
                    "--policy-arn",
                    "local-policy",
                    "--version-id",
                    "v2",
                ),
            )
            self.assertEqual(aws.call_args_list[4].args[1], "create-policy-version")
            self.assertIn("--set-as-default", aws.call_args_list[4].args)

    def test_unchanged_managed_policy_is_reused(self):
        # Capture the first policy creation, then prove a rerun creates no version/key.
        with patch.object(
            provisioner,
            "aws",
            side_effect=[
                {"Policies": []},
                {"Policy": {"Arn": "local-policy"}},
                {},
            ],
        ) as aws:
            provisioner.ensure_api_policy("local-user")
            document = json.loads(aws.call_args_list[1].args[-1])
        policy = {
            "PolicyName": "book-ninja-local-api-provisioning",
            "Arn": "local-policy",
            "DefaultVersionId": "v1",
        }
        with patch.object(
            provisioner,
            "aws",
            side_effect=[
                {"Policies": [policy]},
                {"PolicyVersion": {"Document": document}},
                {},
            ],
        ) as aws:
            provisioner.ensure_api_policy("local-user")
            self.assertEqual(
                [call.args[1] for call in aws.call_args_list],
                ["list-policies", "get-policy-version", "attach-user-policy"],
            )

    def test_routing_probe_refuses_an_in_use_target_group(self):
        outputs = {
            "alb_arn": "arn:aws:elasticloadbalancing:us-east-1:000000000000:loadbalancer/app/local/1",
            "vpc_link_id": "local-link",
            "target_group_arn": "local-target-group",
        }
        with (
            patch.object(verifier, "check_local"),
            patch.object(verifier.subprocess, "check_output", return_value=json.dumps(outputs)),
            patch.object(verifier, "environment", return_value={}),
            patch.object(
                verifier,
                "aws",
                side_effect=[
                    {"VpcLinkStatus": "AVAILABLE"},
                    {"TargetHealthDescriptions": [{"Target": {"Id": "existing"}}]},
                ],
            ),
            patch.object(verifier.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "in-use target group"):
                verifier.main()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
