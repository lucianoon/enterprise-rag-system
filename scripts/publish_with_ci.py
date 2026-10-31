"""Publish a feature branch to Entire only after GitHub CI passes for its exact SHA.

This is a local publishing guard, not an Entire server-side merge gate.
Requires Git, GitHub CLI authentication, and an authenticated Entire Git helper.
"""

import argparse
import json
import re
import subprocess
import sys
import time

REQUIRED_JOBS = {"test", "qdrant-legacy", "import-macos"}


def command(*args: str) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=True, timeout=90)
    return result.stdout.strip()


def github_repository(url: str) -> str:
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?", url)
    if not match:
        raise ValueError("The GitHub remote must use github.com HTTPS or SSH without credentials")
    return match[1]


def wait_for_ci(repository: str, branch: str, sha: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = json.loads(command(
            "gh", "run", "list", "--repo", repository, "--workflow", "ci.yml",
            "--branch", branch, "--commit", sha, "--limit", "20",
            "--json", "databaseId,headSha,status,conclusion,url,event",
        ))
        candidates = [
            run for run in runs
            if run["headSha"] == sha and run["event"] in {"push", "workflow_dispatch"}
        ]
        if candidates:
            run = max(candidates, key=lambda item: item["databaseId"])
            print(f"CI {run['status']}: {run['url']}", flush=True)
            if run["status"] == "completed":
                if run["conclusion"] != "success":
                    raise RuntimeError(f"CI did not pass ({run['conclusion']}): {run['url']}")
                details = json.loads(command(
                    "gh", "run", "view", str(run["databaseId"]), "--repo", repository,
                    "--json", "jobs",
                ))
                passed = {
                    job["name"] for job in details["jobs"] if job["conclusion"] == "success"
                }
                if missing := REQUIRED_JOBS - passed:
                    raise RuntimeError(
                        f"Required CI jobs missing or unsuccessful: {sorted(missing)}"
                    )
                return run["url"]
        else:
            print(f"Waiting for CI on {branch} at {sha[:12]}...", flush=True)
        time.sleep(min(10, max(0, deadline - time.monotonic())))
    raise TimeoutError("CI result missing or timed out; nothing was published to Entire")


def publish(github_remote: str, entire_remote: str, base: str, timeout: float) -> str:
    branch = command("git", "branch", "--show-current")
    if not branch or branch == base:
        raise ValueError("Create and check out a feature branch before publishing")
    if command("git", "status", "--porcelain"):
        raise ValueError("Commit or stash pending files before publishing")
    sha = command("git", "rev-parse", "HEAD")
    repository = github_repository(command("git", "remote", "get-url", github_remote))
    entire_url = command("git", "remote", "get-url", entire_remote)
    if not entire_url.startswith("entire://"):
        raise ValueError("The Entire remote must use an entire:// URL")
    command("gh", "auth", "status", "--hostname", "github.com")
    print(f"Publishing {branch} at {sha[:12]} to GitHub for validation...", flush=True)
    command("git", "push", github_remote, f"{sha}:refs/heads/{branch}")
    run_url = wait_for_ci(repository, branch, sha, timeout)
    if command("git", "rev-parse", "HEAD") != sha:
        raise RuntimeError("HEAD changed during CI; publication to Entire was refused")
    if command("git", "branch", "--show-current") != branch:
        raise RuntimeError("The current branch changed during CI; publication was refused")
    if command("git", "status", "--porcelain"):
        raise RuntimeError("Working tree changed during CI; publication was refused")
    command("git", "push", entire_remote, f"{sha}:refs/heads/{branch}")
    command("git", "branch", f"--set-upstream-to={entire_remote}/{branch}", branch)
    print(f"Published the tested commit to Entire. CI: {run_url}", flush=True)
    return run_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-remote", default="github")
    parser.add_argument("--entire-remote", default="origin")
    parser.add_argument("--base", default="main")
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        publish(args.github_remote, args.entire_remote, args.base, args.timeout)
    except subprocess.CalledProcessError as error:
        print(error.stderr or str(error), file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
