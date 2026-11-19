"""Watch trusted develop CI; publish locally and propose the verified image digest."""

import argparse
import base64
import fcntl
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bootstrap_floci import ROOT, private_file
from publish_backend import LOCAL_REPOSITORY, PROJECT
from publish_backend import main as publish
from verify_backend_image import main as verify

REPO = "EjazAhmedRak/book-ninja"
BRANCH = "develop"
OVERLAY = "gitops/environments/local/backend-values.yaml"
STATE = ROOT / "manual/local-publisher-state.json"
SERVICE_LABEL = "io.book-ninja.floci-publisher"


def command(*args, cwd=PROJECT, **kwargs):
    return subprocess.check_output(args, cwd=cwd, text=True, **kwargs).strip()


def api(path):
    return json.loads(command("gh", "api", f"repos/{REPO}/{path}"))


def eligible_run(run, head):
    """Do not execute PR, fork, stale, failed, or incomplete workflow revisions."""
    return (
        bool(re.fullmatch(r"[0-9a-f]{40}", head))
        and run.get("head_sha") == head
        and run.get("head_branch") == BRANCH
        and run.get("event") == "push"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("head_repository", {}).get("full_name") == REPO
        and run.get("path") == ".github/workflows/backend.yml"
    )


def update_overlay(text, receipt, head):
    if (
        receipt.get("revision") != head
        or receipt.get("repository") != LOCAL_REPOSITORY
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", receipt.get("imageDigest", ""))
    ):
        raise RuntimeError("Publication receipt does not match the tested local source")
    replacement = f"image:\n  repository: {LOCAL_REPOSITORY}\n  digest: {receipt['imageDigest']}\n"
    updated, count = re.subn(
        r"(?m)^image:\n  repository: [^\n]+\n  digest: [^\n]+\n", replacement, text
    )
    if count != 1:
        raise RuntimeError("Expected one explicit repository/digest block in the local overlay")
    return updated


def remote_overlay(branch):
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{OVERLAY}?ref={branch}"],
        cwd=PROJECT,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        if "HTTP 404" in result.stderr:
            return None
        raise RuntimeError("Could not inspect the existing promotion branch")
    return base64.b64decode(json.loads(result.stdout)["content"]).decode()


def process(publish_enabled=False):
    head = api(f"git/ref/heads/{BRANCH}")["object"]["sha"]
    runs = api(
        f"actions/workflows/backend.yml/runs?branch={BRANCH}&event=push&head_sha={head}&per_page=1"
    )["workflow_runs"]
    if not runs or not eligible_run(runs[0], head):
        print(
            f"Waiting: current {BRANCH} commit {head[:12]} has no successful push CI run.",
            flush=True,
        )
        return
    run = runs[0]
    if not publish_enabled:
        print(f"Eligible source {head}: {run['html_url']}; dry-run, nothing published.", flush=True)
        return
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if head in state:
        print(f"Already processed {head[:12]}: {state[head]}", flush=True)
        return
    branch = f"deploy/floci-backend-{head[:12]}"
    prs = json.loads(
        command(
            "gh",
            "pr",
            "list",
            "--repo",
            REPO,
            "--head",
            branch,
            "--base",
            BRANCH,
            "--state",
            "all",
            "--json",
            "url,state",
        )
    )
    if prs:
        state[head] = prs[0]["url"]
    else:
        command("git", "fetch", "origin", BRANCH)
        if command("git", "rev-parse", f"origin/{BRANCH}") != head:
            print("Develop advanced while checking CI; waiting for its new run.", flush=True)
            return
        with tempfile.TemporaryDirectory(prefix="book-ninja-promotion-") as directory:
            checkout = Path(directory) / "source"
            command("git", "worktree", "add", "--detach", str(checkout), head)
            try:
                publish(checkout)
                verify()
                receipt = json.loads((ROOT / "manual/backend-image.json").read_text())
                overlay = checkout / OVERLAY
                before = overlay.read_text()
                after = update_overlay(before, receipt, head)
                if before == after:
                    state[head] = "Overlay already references the verified image"
                else:
                    overlay.write_text(after)
                    command(
                        "helm",
                        "lint",
                        str(checkout / "gitops/charts/book-ninja"),
                        "-f",
                        str(overlay),
                        "--set-string",
                        "config.FRONTEND_ORIGINS=http://localhost:5173",
                    )
                    # A newer merge must pass its own CI before it can be promoted.
                    if api(f"git/ref/heads/{BRANCH}")["object"]["sha"] != head:
                        print(
                            "Develop advanced during publication; image retained, promotion deferred.",
                            flush=True,
                        )
                        return
                    existing = remote_overlay(branch)
                    if existing is None:
                        command("git", "add", "--", OVERLAY, cwd=checkout)
                        command(
                            "git",
                            "-c",
                            "core.hooksPath=/dev/null",
                            "commit",
                            "-m",
                            f"chore(deploy): promote local backend {head[:12]}",
                            cwd=checkout,
                        )
                        command("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=checkout)
                    elif existing != after:
                        raise RuntimeError(
                            "Promotion branch exists with different content; inspect before retrying"
                        )
                    body = Path(directory) / "pr.md"
                    body.write_text(
                        f"Promote the local backend image built from `{head}` after successful "
                        f"[Backend CI]({run['html_url']}).\n\n"
                        f"Image: `{receipt['image']}`\n\n"
                        "Verified ECR/pull/import digests, non-root image execution on local k3s, "
                        "and Helm lint. Only the local image overlay changes. "
                        "This PR does not install the application or modify runtime secrets. "
                        "Argo CD reconciliation and production release automation remain separate work.\n"
                    )
                    state[head] = command(
                        "gh",
                        "pr",
                        "create",
                        "--repo",
                        REPO,
                        "--base",
                        BRANCH,
                        "--head",
                        branch,
                        "--title",
                        f"chore(deploy): promote local backend {head[:12]}",
                        "--body-file",
                        str(body),
                    )
            finally:
                command("git", "worktree", "remove", "--force", str(checkout))
    private_file(STATE, json.dumps(state, indent=2) + "\n")
    print(f"Processed {head[:12]}: {state[head]}", flush=True)


def service(install):
    """Manage a per-user LaunchAgent; no GitHub runner is registered."""
    path = Path.home() / "Library/LaunchAgents" / f"{SERVICE_LABEL}.plist"
    target = f"gui/{os.getuid()}/{SERVICE_LABEL}"
    loaded = subprocess.run(["launchctl", "print", target], capture_output=True).returncode == 0
    if not install:
        if loaded:
            subprocess.run(["launchctl", "bootout", target], check=True)
        path.unlink(missing_ok=True)
        print("Local publisher LaunchAgent removed; images, PRs, and logs retained.")
        return
    if loaded:
        print("Local publisher LaunchAgent is already loaded.")
        return
    # launchd jobs cannot reliably access Desktop-protected paths. Keep the
    # service and its Git metadata outside Desktop without changing the user's
    # checkout or requiring a broad macOS privacy permission.
    control = Path.home() / ".local/share/book-ninja-floci-publisher"
    if not (control / ".git").exists():
        control.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--branch",
                BRANCH,
                "--single-branch",
                f"https://github.com/{REPO}.git",
                str(control),
            ],
            check=True,
        )
    control_infra = control / "infra"
    for name in (
        "watch_backend_ci.py",
        "publish_backend.py",
        "verify_backend_image.py",
        "bootstrap_external_secrets.py",
        "bootstrap_floci.py",
        "floci_aws.py",
    ):
        source, destination = ROOT / "scripts" / name, control_infra / "scripts" / name
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
    if ROOT.resolve() != control_infra.resolve():
        private_file(
            control_infra / "local.provisioner.auto.tfvars.json",
            (ROOT / "local.provisioner.auto.tfvars.json").read_text(),
        )
        kubeconfig = json.loads((ROOT / "local.kubeconfig.json").read_text())
        for user in kubeconfig["users"]:
            execute = user["user"].get("exec", {})
            execute["args"] = [
                arg.replace(str(PROJECT), str(control)) for arg in execute.get("args", [])
            ]
        private_file(
            control_infra / "local.kubeconfig.json", json.dumps(kubeconfig, indent=2) + "\n"
        )
    (control_infra / "manual").mkdir(exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    for name in ("local-publisher.stdout.log", "local-publisher.stderr.log"):
        log = control_infra / "manual" / name
        if not log.exists():
            private_file(log, "")
        log.chmod(0o600)
    settings = {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [
            sys.executable,
            str(control_infra / "scripts/watch_backend_ci.py"),
            "--watch",
            "--publish",
        ],
        "WorkingDirectory": str(control),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 60,
        "StandardOutPath": str(control_infra / "manual/local-publisher.stdout.log"),
        "StandardErrorPath": str(control_infra / "manual/local-publisher.stderr.log"),
    }
    private_file(path, plistlib.dumps(settings).decode())
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], check=True)
    print(f"Installed {SERVICE_LABEL}; polling successful develop CI every 60 seconds.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish", action="store_true", help="Enable ECR writes and promotion PR creation"
    )
    parser.add_argument(
        "--watch", action="store_true", help="Poll every 60 seconds instead of checking once"
    )
    lifecycle = parser.add_mutually_exclusive_group()
    lifecycle.add_argument(
        "--install", action="store_true", help="Install the macOS background publisher"
    )
    lifecycle.add_argument(
        "--uninstall", action="store_true", help="Remove the background publisher"
    )
    args = parser.parse_args()
    (ROOT / "manual").mkdir(exist_ok=True)
    if args.install or args.uninstall:
        service(args.install)
        return
    # Prevent a background watcher and a manual invocation publishing concurrently.
    with (ROOT / "manual/local-publisher.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("A local publisher is already running") from None
        while True:
            try:
                process(args.publish)
            except Exception as error:
                if not args.watch:
                    raise
                print(
                    f"Publication attempt failed ({type(error).__name__}); retrying in 60s.",
                    flush=True,
                )
            if not args.watch:
                break
            time.sleep(60)


if __name__ == "__main__":
    main()
