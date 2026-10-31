"""Compare read-only Git operations against two remotes with identical refs."""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


def command(args: list[str], timeout: int = 90) -> tuple[str, float]:
    started = time.perf_counter()
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        check=True,
    )
    return result.stdout.strip(), time.perf_counter() - started


def refs(url: str) -> tuple[list[str], float]:
    output, elapsed = command(["git", "ls-remote", "--heads", "--tags", url])
    return sorted(output.splitlines()), elapsed


def summarize(samples: list[float]) -> dict[str, float | int]:
    return {
        "n": len(samples),
        "median_seconds": statistics.median(samples),
        "mean_seconds": statistics.mean(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-remote", default="github")
    parser.add_argument("--entire-remote", default="origin")
    parser.add_argument("--refs-runs", type=int, default=7)
    parser.add_argument("--clone-runs", type=int, default=3)
    parser.add_argument("--fetch-runs", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.refs_runs, args.clone_runs, args.fetch_runs) < 1:
        parser.error("sample counts must be positive")

    urls = {
        name: command(["git", "remote", "get-url", remote])[0]
        for name, remote in [("github", args.github_remote), ("entire", args.entire_remote)]
    }
    baseline = {name: refs(url)[0] for name, url in urls.items()}
    if baseline["github"] != baseline["entire"]:
        raise RuntimeError("The remotes must have identical branches and tags before measuring")
    operations = ("ls_remote", "clone_bare", "fetch_no_changes")
    samples: dict[str, dict[str, list[float]]] = {
        name: {operation: [] for operation in operations} for name in urls
    }
    observations: list[dict] = []
    report = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "git": command(["git", "--version"])[0],
            "entire": command(["entire", "--version"])[0],
        },
        "urls": urls,
        "refs": baseline["github"],
        "refs_sha256": hashlib.sha256("\n".join(baseline["github"]).encode()).hexdigest(),
        "method": {
            "order": "alternate github/entire then entire/github each round",
            "warmup": "one discarded round per host for each operation",
            "clone": "git clone --bare --quiet --no-local URL NEW_TEMP_DIRECTORY",
            "fetch": "git -C BARE fetch --quiet --no-tags origin +refs/heads/*:refs/heads/*",
            "scope": "end-to-end wall clock including process, network, transport and auth",
            "cache": "fresh clone destinations; client/server caches are not flushed",
            "excluded": "push, concurrent throughput, agent productivity, cost and availability",
        },
        "observations": observations,
    }

    def measure(operation: str, runs: int, action) -> None:
        for round_index in range(-1, runs):
            names = list(urls) if round_index % 2 == 0 else list(reversed(urls))
            for name in names:
                elapsed = action(name, round_index)
                observations.append({
                    "operation": operation,
                    "host": name,
                    "round": round_index,
                    "warmup": round_index == -1,
                    "seconds": elapsed,
                })
                if round_index >= 0:
                    samples[name][operation].append(elapsed)
                print(f"{operation} {name} round={round_index}: {elapsed:.3f}s", flush=True)

    with tempfile.TemporaryDirectory(prefix="git-host-comparison-") as temporary:
        clones: dict[str, Path] = {}
        clone_inventory = {}

        def list_refs(name: str, _round: int) -> float:
            actual, elapsed = refs(urls[name])
            if actual != baseline[name]:
                raise RuntimeError(f"Refs changed during measurement: {name}")
            return elapsed

        def clone(name: str, round_index: int) -> float:
            destination = Path(temporary) / f"{name}-{round_index}.git"
            _, elapsed = command([
                "git", "clone", "--bare", "--quiet", "--no-local", urls[name], str(destination)
            ])
            output, _ = command([
                "git", "-C", str(destination), "for-each-ref",
                "--format=%(objectname)%09%(refname)", "refs/heads", "refs/tags",
            ])
            if sorted(output.splitlines()) != baseline[name]:
                raise RuntimeError(f"Clone refs do not match source: {name}")
            clones[name] = destination
            clone_inventory[name] = {
                "commits": int(command([
                    "git", "-C", str(destination), "rev-list", "--count", "--all"
                ])[0]),
                "pack_bytes": sum(
                    path.stat().st_size for path in destination.glob("objects/pack/*")
                ),
            }
            return elapsed

        def fetch(name: str, _round: int) -> float:
            return command([
                "git", "-C", str(clones[name]), "fetch", "--quiet", "--no-tags", "origin",
                "+refs/heads/*:refs/heads/*",
            ])[1]

        measure("ls_remote", args.refs_runs, list_refs)
        measure("clone_bare", args.clone_runs, clone)
        measure("fetch_no_changes", args.fetch_runs, fetch)
        report["clone_inventory"] = clone_inventory

    final_refs = {name: refs(url)[0] for name, url in urls.items()}
    report["refs_unchanged_after"] = final_refs == baseline
    report["summary"] = {
        name: {operation: summarize(values) for operation, values in rows.items()}
        for name, rows in samples.items()
    }
    report["comparison"] = {
        operation: {
            "github_over_entire_median": (
                statistics.median(samples["github"][operation])
                / statistics.median(samples["entire"][operation])
            ),
            "entire_time_change_percent": (
                statistics.median(samples["entire"][operation])
                / statistics.median(samples["github"][operation]) - 1
            ) * 100,
        }
        for operation in operations
    }
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["comparison"], indent=2), flush=True)
    if not report["refs_unchanged_after"]:
        raise RuntimeError("Remote refs changed; results cannot be treated as a fixed comparison")


if __name__ == "__main__":
    main()
