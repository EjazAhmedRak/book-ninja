"""Publication preconditions must fail before image writes or execution."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import publish_backend as publisher
import verify_backend_image as verifier


class PublicationGuards(unittest.TestCase):
    def test_uncommitted_backend_cannot_be_published_under_a_git_sha(self):
        with (
            patch.object(publisher, "output", return_value=" M apps/backend/src/main.py"),
            patch.object(publisher, "environment") as environment,
            patch.object(publisher, "aws") as aws,
        ):
            with self.assertRaisesRegex(RuntimeError, "Commit backend source"):
                publisher.main()
            environment.assert_not_called()
            aws.assert_not_called()

    def test_remote_cluster_cannot_receive_a_local_image_probe(self):
        config = {"clusters": [{"cluster": {"server": "https://production.example.com"}}]}
        with (
            patch.object(verifier, "kubectl", return_value=json.dumps(config)),
            patch.object(verifier, "aws") as aws,
            patch.object(verifier.subprocess, "Popen") as save,
        ):
            with self.assertRaisesRegex(RuntimeError, "only supported on local"):
                verifier.main()
            aws.assert_not_called()
            save.assert_not_called()

    def test_digest_mismatch_stops_before_preloading_or_creating_pods(self):
        config = {"clusters": [{"cluster": {"server": "https://localhost:6443"}}]}
        receipt = {
            "repository": publisher.LOCAL_REPOSITORY,
            "imageDigest": "sha256:" + "a" * 64,
            "revision": "1" * 40,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manual").mkdir()
            (root / "manual/backend-image.json").write_text(json.dumps(receipt))
            with (
                patch.object(verifier, "ROOT", root),
                patch.object(verifier, "kubectl", return_value=json.dumps(config)),
                patch.object(verifier, "environment", return_value={}),
                patch.object(
                    verifier,
                    "aws",
                    return_value={"imageDetails": [{"imageDigest": "sha256:" + "b" * 64}]},
                ),
                patch.object(verifier.subprocess, "Popen") as save,
                patch.object(verifier, "apply") as apply,
            ):
                with self.assertRaisesRegex(RuntimeError, "no longer matches"):
                    verifier.main()
                save.assert_not_called()
                apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
