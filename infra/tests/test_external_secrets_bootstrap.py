"""Local ESO bootstrap guardrails; no cluster or AWS calls."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap_external_secrets as bootstrap


class BootstrapTests(unittest.TestCase):
    def test_remote_cluster_is_rejected_before_accessing_credentials(self):
        config = {"clusters": [{"cluster": {"server": "https://production.example.com"}}]}
        with patch.object(bootstrap, "kubectl", return_value=json.dumps(config)), \
                patch.object(bootstrap, "aws") as aws:
            with self.assertRaisesRegex(RuntimeError, "only for the local"):
                bootstrap.main()
            aws.assert_not_called()

    def test_saved_active_key_is_reused_without_printing_credentials(self):
        config = {"clusters": [{"cluster": {"server": "https://localhost:6500"}}]}
        inspect = [{"NetworkSettings": {"Networks": {"infra_default": {"IPAddress": "172.19.0.2"}}}}]
        credentials = {"AccessKeyId": "fixture-reader", "SecretAccessKey": "fixture-secret"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.external-secrets.credentials.json"
            path.write_text(json.dumps(credentials))
            with patch.object(bootstrap, "ROOT", Path(directory)), \
                    patch.object(bootstrap, "kubectl", return_value=json.dumps(config)), \
                    patch.object(bootstrap.subprocess, "run") as run, \
                    patch.object(bootstrap, "aws") as aws, \
                    patch.object(bootstrap, "apply") as apply, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                run.return_value.stdout = json.dumps(inspect)
                aws.side_effect = [{}, {"AccessKeyMetadata": [{"AccessKeyId": "fixture-reader", "Status": "Active"}]}]
                bootstrap.main()
                self.assertEqual(aws.call_count, 2)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("fixture-secret", output.getvalue())
                slices = [call.args[0] for call in apply.call_args_list if call.args[0]["kind"] == "EndpointSlice"]
                self.assertEqual(slices[0]["endpoints"][0]["addresses"], ["172.19.0.2"])

    def test_failed_secret_apply_does_not_echo_payload(self):
        with patch.object(bootstrap.subprocess, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "invalid Secret with fixture-sensitive-value"
            with self.assertRaises(RuntimeError) as caught:
                bootstrap.kubectl("apply", "-f", "-", payload={"secret": "fixture-sensitive-value"})
            self.assertNotIn("fixture-sensitive-value", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
