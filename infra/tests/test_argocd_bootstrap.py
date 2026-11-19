"""Argo CD bootstrap must remain local and keep its password out of logs."""

import base64
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap_argocd as bootstrap


class ArgoBootstrapTests(unittest.TestCase):
    def test_remote_api_is_rejected_before_changes(self):
        config = {"clusters": [{"cluster": {"server": "https://production.example.com"}}]}
        with (
            patch.object(sys, "argv", ["bootstrap_argocd"]),
            patch.object(bootstrap, "kubectl", return_value=json.dumps(config)) as kubectl,
        ):
            with self.assertRaisesRegex(RuntimeError, "only for local"):
                bootstrap.main()
            self.assertEqual(kubectl.call_count, 1)

    def test_invalid_preview_revision_is_rejected_before_changes(self):
        config = {"clusters": [{"cluster": {"server": "https://localhost:6443"}}]}
        with (
            patch.object(sys, "argv", ["bootstrap_argocd", "--preview-revision", "feature"]),
            patch.object(bootstrap, "kubectl", return_value=json.dumps(config)) as kubectl,
        ):
            with self.assertRaisesRegex(RuntimeError, "explicit Git commit SHA"):
                bootstrap.main()
            self.assertEqual(kubectl.call_count, 1)

    def test_initial_password_is_owner_only_and_not_printed(self):
        config = {"clusters": [{"cluster": {"server": "https://localhost:6443"}}]}
        secret = {"data": {"password": base64.b64encode(b"fixture-sensitive-password").decode()}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = io.StringIO()
            with (
                patch.object(sys, "argv", ["bootstrap_argocd"]),
                patch.object(bootstrap, "ROOT", root),
                patch.object(
                    bootstrap, "kubectl", side_effect=[json.dumps(config), "", json.dumps(secret)]
                ),
                contextlib.redirect_stdout(stdout),
            ):
                bootstrap.main()
            password = root / "manual/argocd-initial-admin-password"
            self.assertEqual(password.stat().st_mode & 0o777, 0o600)
            self.assertEqual(password.read_text(), "fixture-sensitive-password\n")
            self.assertNotIn("fixture-sensitive-password", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
