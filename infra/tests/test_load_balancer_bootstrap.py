"""Keep local controller keys private and reuse active credentials."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap_load_balancer_controller as bootstrap


class ControllerBootstrapTests(unittest.TestCase):
    def test_only_floci_is_attached_to_the_existing_node_bridge(self):
        inspected = [
            {"NetworkSettings": {"Networks": {"infra_default": {}}}},
            {"NetworkSettings": {"Networks": {"bridge": {}}}},
        ]
        with (
            patch.object(bootstrap.subprocess, "check_output", return_value=json.dumps(inspected)),
            patch.object(bootstrap.subprocess, "run") as run,
        ):
            bootstrap.ensure_node_network()
            run.assert_called_once_with(
                ["docker", "network", "connect", "bridge", "infra-floci-1"], check=True
            )

    def test_nonlocal_cluster_is_rejected_before_iam_access(self):
        with (
            patch.object(bootstrap, "check_local", side_effect=RuntimeError("nonlocal API")),
            patch.object(bootstrap, "aws") as aws,
        ):
            with self.assertRaisesRegex(RuntimeError, "nonlocal"):
                bootstrap.main()
            aws.assert_not_called()

    def test_active_key_is_reused_privately_and_values_contain_no_keys(self):
        credentials = {
            "AccessKeyId": "fixture-controller-id",
            "SecretAccessKey": "fixture-controller-secret",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "local.load-balancer-controller.credentials.json"
            path.write_text(json.dumps(credentials))
            stdout = io.StringIO()
            with (
                patch.object(bootstrap, "ROOT", root),
                patch.object(bootstrap, "check_local"),
                patch.object(bootstrap, "ensure_node_network"),
                patch.object(
                    bootstrap,
                    "aws",
                    side_effect=[
                        {},
                        {
                            "AccessKeyMetadata": [
                                {"AccessKeyId": "fixture-controller-id", "Status": "Active"}
                            ]
                        },
                    ],
                ) as aws,
                patch.object(bootstrap, "apply") as apply,
                patch.object(bootstrap.subprocess, "check_output", return_value="vpc-fixture"),
                contextlib.redirect_stdout(stdout),
            ):
                bootstrap.main()
            self.assertEqual(aws.call_count, 2)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            values = root / "manual/load-balancer-controller-values.json"
            self.assertEqual(json.loads(values.read_text()), {"vpcId": "vpc-fixture"})
            self.assertNotIn("fixture-controller-secret", stdout.getvalue())
            secret = apply.call_args_list[1].args[0]
            self.assertEqual(secret["metadata"]["namespace"], "load-balancer-system")
            self.assertEqual(
                secret["stringData"]["AWS_SECRET_ACCESS_KEY"], credentials["SecretAccessKey"]
            )


if __name__ == "__main__":
    unittest.main()
