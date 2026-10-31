"""Publishing must not send untested commits to the Entire remote."""

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "publish_with_ci", Path(__file__).resolve().parents[1] / "scripts/publish_with_ci.py"
)
assert spec is not None and spec.loader is not None
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)

SHA = "a" * 40


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.conclusion = "success"
        self.jobs = publisher.REQUIRED_JOBS.copy()
        self.final_sha = SHA
        self.head_reads = 0
        self.ci_sha = SHA

    def fake_command(self, *args):
        self.calls.append(args)
        if args[:3] == ("git", "branch", "--show-current"):
            return "feature/example"
        if args[:3] == ("git", "status", "--porcelain"):
            return ""
        if args[:3] == ("git", "rev-parse", "HEAD"):
            self.head_reads += 1
            return SHA if self.head_reads == 1 else self.final_sha
        if args[:4] == ("git", "remote", "get-url", "github"):
            return "https://github.com/owner/repository.git"
        if args[:4] == ("git", "remote", "get-url", "origin"):
            return "entire://example.entire.io/et/project/repository"
        if args[:3] == ("gh", "run", "list"):
            return json.dumps([{
                "databaseId": 1, "headSha": self.ci_sha, "event": "push",
                "status": "completed", "conclusion": self.conclusion,
                "url": "https://github.com/owner/repository/actions/runs/1",
            }])
        if args[:3] == ("gh", "run", "view"):
            return json.dumps({"jobs": [
                {"name": name, "conclusion": "success"} for name in self.jobs
            ]})
        return ""

    def publish(self):
        with patch.object(publisher, "command", side_effect=self.fake_command):
            return publisher.publish("github", "origin", "main", 1)

    def entire_pushes(self):
        return [call for call in self.calls if call[:3] == ("git", "push", "origin")]

    def test_success_publishes_the_exact_tested_sha(self):
        self.publish()
        self.assertEqual(self.entire_pushes(), [
            ("git", "push", "origin", f"{SHA}:refs/heads/feature/example")
        ])

    def test_failed_cancelled_and_skipped_runs_never_publish(self):
        for conclusion in ["failure", "cancelled", "skipped", "neutral", "timed_out"]:
            with self.subTest(conclusion=conclusion):
                self.conclusion = conclusion
                with self.assertRaises(RuntimeError):
                    self.publish()
                self.assertEqual(self.entire_pushes(), [])

    def test_missing_macos_job_refuses_successful_workflow(self):
        self.jobs.remove("import-macos")
        with self.assertRaisesRegex(RuntimeError, "import-macos"):
            self.publish()
        self.assertEqual(self.entire_pushes(), [])

    def test_head_change_does_not_publish_untested_changes(self):
        self.final_sha = "b" * 40
        with self.assertRaisesRegex(RuntimeError, "HEAD changed"):
            self.publish()
        self.assertEqual(self.entire_pushes(), [])

    def test_success_for_another_commit_does_not_satisfy_ci(self):
        self.ci_sha = "b" * 40
        with (
            patch.object(publisher.time, "monotonic", side_effect=[0, 0, 2, 2]),
            patch.object(publisher.time, "sleep"),
            self.assertRaises(TimeoutError),
        ):
            self.publish()
        self.assertEqual(self.entire_pushes(), [])


if __name__ == "__main__":
    unittest.main()
