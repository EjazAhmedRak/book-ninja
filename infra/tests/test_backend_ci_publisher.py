"""Only successful trusted merge revisions may trigger local publication."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import watch_backend_ci as watcher

SHA = "a" * 40
RUN = {
    "head_sha": SHA,
    "head_branch": "develop",
    "event": "push",
    "status": "completed",
    "conclusion": "success",
    "head_repository": {"full_name": watcher.REPO},
    "path": ".github/workflows/backend.yml",
    "html_url": "https://example.test/ci",
}


class LocalPublisherTests(unittest.TestCase):
    def test_promotion_changes_only_overlay_and_defers_if_develop_advances(self):
        for advanced in (False, True):
            with self.subTest(advanced=advanced), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "manual").mkdir()
                receipt = {
                    "revision": SHA,
                    "repository": watcher.LOCAL_REPOSITORY,
                    "imageDigest": "sha256:" + "c" * 64,
                    "image": "local-image",
                }
                (root / "manual/backend-image.json").write_text(json.dumps(receipt))
                responses = [
                    {"object": {"sha": SHA}},
                    {"workflow_runs": [RUN]},
                    {"object": {"sha": "b" * 40 if advanced else SHA}},
                ]

                def command(*args, **kwargs):
                    if args[:4] == ("git", "worktree", "add", "--detach"):
                        overlay = Path(args[4]) / watcher.OVERLAY
                        overlay.parent.mkdir(parents=True)
                        overlay.write_text(
                            "image:\n  repository: old\n  digest: sha256:old\nconfig:\n  APP_ENV: dev\n"
                        )
                    if args[:3] == ("gh", "pr", "list"):
                        return "[]"
                    if args[:2] == ("git", "rev-parse"):
                        return SHA
                    if args[:3] == ("gh", "pr", "create"):
                        return "https://example.test/promotion"
                    return ""

                state = root / "manual/state.json"
                with (
                    patch.object(watcher, "ROOT", root),
                    patch.object(watcher, "STATE", state),
                    patch.object(watcher, "api", side_effect=responses),
                    patch.object(watcher, "command", side_effect=command) as commands,
                    patch.object(watcher, "publish"),
                    patch.object(watcher, "verify"),
                    patch.object(watcher, "remote_overlay", return_value=None),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    watcher.process(publish_enabled=True)
                    pushes = [
                        c.args for c in commands.call_args_list if c.args[:2] == ("git", "push")
                    ]
                    staged = [
                        c.args for c in commands.call_args_list if c.args[:2] == ("git", "add")
                    ]
                    if advanced:
                        self.assertFalse(pushes)
                        self.assertFalse(state.exists())
                    else:
                        self.assertEqual(staged, [("git", "add", "--", watcher.OVERLAY)])
                        self.assertNotIn("--force", pushes[0])
                        self.assertEqual(
                            json.loads(state.read_text())[SHA], "https://example.test/promotion"
                        )

    def test_only_successful_push_from_current_trusted_branch_is_eligible(self):
        self.assertTrue(watcher.eligible_run(RUN, SHA))
        rejected = [
            {"head_sha": "b" * 40},
            {"event": "pull_request"},
            {"head_branch": "feature"},
            {"status": "in_progress"},
            {"conclusion": "failure"},
            {"head_repository": {"full_name": "fork/book-ninja"}},
            {"path": ".github/workflows/frontend.yml"},
        ]
        for changes in rejected:
            with self.subTest(changes=changes):
                self.assertFalse(watcher.eligible_run({**RUN, **changes}, SHA))

    def test_failed_ci_never_publishes(self):
        responses = [
            {"object": {"sha": SHA}},
            {"workflow_runs": [{**RUN, "conclusion": "failure"}]},
        ]
        with (
            patch.object(watcher, "api", side_effect=responses),
            patch.object(watcher, "publish") as publish,
            patch.object(watcher, "command") as command,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            watcher.process(publish_enabled=True)
            publish.assert_not_called()
            command.assert_not_called()

    def test_dry_run_does_not_build_or_create_a_pr(self):
        responses = [{"object": {"sha": SHA}}, {"workflow_runs": [RUN]}]
        with (
            patch.object(watcher, "api", side_effect=responses),
            patch.object(watcher, "publish") as publish,
            patch.object(watcher, "command") as command,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            watcher.process()
            publish.assert_not_called()
            command.assert_not_called()

    def test_closed_promotion_pr_is_not_reopened_or_republished(self):
        responses = [{"object": {"sha": SHA}}, {"workflow_runs": [RUN]}]
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with (
                patch.object(watcher, "STATE", state),
                patch.object(watcher, "api", side_effect=responses),
                patch.object(
                    watcher,
                    "command",
                    return_value=json.dumps(
                        [{"state": "CLOSED", "url": "https://example.test/pr"}]
                    ),
                ),
                patch.object(watcher, "publish") as publish,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                watcher.process(publish_enabled=True)
                publish.assert_not_called()
                self.assertEqual(json.loads(state.read_text())[SHA], "https://example.test/pr")

    def test_overlay_update_preserves_runtime_configuration(self):
        text = "# keep\nimage:\n  repository: old\n  digest: sha256:old\nconfig:\n  APP_ENV: dev\n"
        receipt = {
            "revision": SHA,
            "repository": watcher.LOCAL_REPOSITORY,
            "imageDigest": "sha256:" + "c" * 64,
        }
        result = watcher.update_overlay(text, receipt, SHA)
        self.assertTrue(result.startswith("# keep\n"))
        self.assertTrue(result.endswith("config:\n  APP_ENV: dev\n"))
        self.assertIn(receipt["imageDigest"], result)
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            watcher.update_overlay(text, {**receipt, "revision": "b" * 40}, SHA)


if __name__ == "__main__":
    unittest.main()
