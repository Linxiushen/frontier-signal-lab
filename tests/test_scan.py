import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from frontier_radar.scan import GitHub, UTC, in_window, main, markdown, parse_time, recent_comments, recent_reviews, render_report, save, scan


class FakeAPI:
    def __init__(self, responses):
        self.responses = responses
        self.errors = []
        self.calls = []

    def get(self, endpoint, query=None):
        self.calls.append(endpoint)
        for prefix, response in self.responses:
            if endpoint.startswith(prefix):
                if response is None:
                    self.errors.append({"endpoint": endpoint, "category": "test_failure"})
                return response
        raise AssertionError(endpoint)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.since = parse_time("2026-10-01T00:00:00Z")
        self.until = parse_time("2026-10-15T00:00:00Z")
        self.config = {"people": [], "repositories": [{"full_name": "o/r"}]}

    def test_private_guard_never_retains_private_metadata(self):
        api = FakeAPI([("repos/o/r", {"private": True, "description": "SECRET"})])
        result = scan(self.config, self.since, self.until, api=api)
        self.assertEqual(api.calls, ["repos/o/r"])
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(result["status"], "partial")

    def test_missing_private_flag_fails_closed(self):
        api = FakeAPI([("repos/o/r", {"full_name": "o/r"})])
        self.assertEqual(scan(self.config, self.since, self.until, api=api)["repositories"], [])

    def test_window_timezone_and_bounds(self):
        self.assertTrue(in_window("2026-10-01T08:00:00+08:00", self.since, self.until))
        self.assertFalse(in_window("2026-09-30T23:59:59Z", self.since, self.until))
        self.assertFalse(in_window("2026-10-15T00:00:01Z", self.since, self.until))
        with self.assertRaises(ValueError):
            parse_time("2026-10-01T00:00:00")

    def test_last_five_comments_cross_page_boundary(self):
        def comment(n):
            return {"id": n, "body": str(n), "html_url": f"https://github.com/o/r/issues/1#issuecomment-{n}"}
        api = FakeAPI([("repos/o/r/issues/1/comments?per_page=5&page=2", [comment(n) for n in range(6, 11)]), ("repos/o/r/issues/1/comments?per_page=5&page=3", [comment(11)])])
        result = recent_comments(api, "o/r", {"number": 1, "comments": 11}, "now")
        self.assertEqual([x["id"] for x in result["items"]], [7, 8, 9, 10, 11])
        self.assertTrue(result["sampled"])
        self.assertEqual(len(api.calls), 2)

    def test_truncation_and_issue_pr_separation(self):
        issues = [{"number": n, "title": "safe", "updated_at": "2026-10-10T00:00:00Z", "comments": 0} for n in range(30)]
        issues[0]["pull_request"] = {}
        api = FakeAPI([("repos/o/r/commits?", []), ("repos/o/r/issues?", issues), ("repos/o/r/pulls?", []), ("repos/o/r", {"private": False, "full_name": "o/r"})])
        result = scan(self.config, self.since, self.until, api=api)
        group = result["repositories"][0]["issues"]
        self.assertTrue(group["truncation_possible"])
        self.assertEqual(len(group["items"]), 29)
        self.assertEqual(sum("recent_comments" in i for i in group["items"]), 3)

    def test_profile_whitelist_and_new_repo_event_cutoff(self):
        profile = {"login": "n", "company": "New lab", "email": "SECRET", "location": "SECRET"}
        repos = [
            {"full_name": "n/new", "private": False, "fork": False, "created_at": "2026-10-02T00:00:00Z"},
            {"full_name": "n/fork", "private": False, "fork": True, "created_at": "2026-10-02T00:00:00Z"},
            {"full_name": "n/private", "private": True, "fork": False, "created_at": "2026-10-02T00:00:00Z"},
            {"full_name": "n/old", "private": False, "fork": False, "created_at": "2020-10-02T00:00:00Z", "updated_at": "2026-10-02T00:00:00Z"},
        ]
        api = FakeAPI([("users/n/repos?", repos), ("users/n", profile)])
        result = scan({"people": [{"id": "n", "github": "n"}]}, self.since, self.until, {"people": [{"id": "n", "profile": {"company": "Old lab"}}]}, api)
        person = result["people"][0]
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(person["profile_changes"]["company"]["before"], "Old lab")
        self.assertEqual([r["full_name"] for r in person["discovered_repositories"]["items"]], ["n/new"])

    def test_commit_window_uses_commit_event_and_pr_counts(self):
        commit = {"sha": "abc", "commit": {"author": {"date": "2020-01-01T00:00:00Z"}, "committer": {"date": "2026-10-02T00:00:00Z"}}}
        pull = {"number": 7, "updated_at": "2026-10-02T00:00:00Z"}
        api = FakeAPI([("repos/o/r/commits?", [commit]), ("repos/o/r/issues?", []), ("repos/o/r/pulls?", [pull]), ("repos/o/r/pulls/7/reviews?", []), ("repos/o/r/issues/7/comments?", []), ("repos/o/r/pulls/7", {"comments": 2, "review_comments": 3}), ("repos/o/r", {"private": False, "full_name": "o/r"})])
        result = scan(self.config, self.since, self.until, api=api)["repositories"][0]
        self.assertEqual(len(result["commits"]["items"]), 1)
        self.assertEqual(result["pull_requests"]["items"][0]["review_comments"], 3)
        self.assertTrue(all("+00:00" not in call for call in api.calls))

    def test_disabled_discussions_do_not_request_graphql(self):
        api = FakeAPI([("repos/o/r/commits?", []), ("repos/o/r/issues?", []), ("repos/o/r/pulls?", []), ("repos/o/r", {"private": False, "full_name": "o/r", "has_discussions": False})])
        config = dict(self.config, include_discussions=True)
        result = scan(config, self.since, self.until, api=api)
        self.assertEqual(result["repositories"][0]["discussions"]["status"], "disabled")
        self.assertFalse(any("graphql" in call for call in api.calls))
        self.assertIn("completed_at", result)

    def test_review_excerpt_retains_maintainer_identity_and_sampling(self):
        data = [{"submitted_at": f"2026-10-{n:02}T00:00:00Z", "body": "maintainer evidence <script>", "state": "CHANGES_REQUESTED", "user": {"login": "m"}, "author_association": "MEMBER", "html_url": "https://github.com/o/r/pull/1#pullrequestreview-1"} for n in range(1, 31)]
        api = FakeAPI([("repos/o/r/pulls/1/reviews?", data)])
        result = recent_reviews(api, "o/r", 1, "now")
        self.assertEqual(len(result["items"]), 5)
        self.assertTrue(result["truncation_possible"])
        self.assertEqual(result["items"][0]["author"]["association"], "MEMBER")
        self.assertIn("later pages", result["sampling"])

    def test_curated_departure_precedes_stale_profile(self):
        api = FakeAPI([("users/n/repos?", []), ("users/n", {"login": "n", "company": "Kimi"})])
        config = {"people": [{"id": "n", "github": "n", "affiliation": {"name": "Left Kimi; next affiliation unverified", "status": "departure_self_announced", "source_url": "https://x.com/n/status/1"}}]}
        result = scan(config, self.since, self.until, api=api)
        report = render_report(result, "hash")
        self.assertIn("departure\\_self", report)
        self.assertIn("takes precedence", report)
        self.assertLess(report.index("Curated affiliation"), report.index("GitHub profile company"))

    def test_artifact_hashes_match_saved_bytes(self):
        api = FakeAPI([])
        result = scan({}, self.since, self.until, api=api)
        with tempfile.TemporaryDirectory() as temp:
            save(result, temp)
            loaded = json.loads((Path(temp) / "snapshot.json").read_text(encoding="utf-8"))
            integrity = loaded.pop("integrity")
            encoded = json.dumps(loaded, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.assertEqual(integrity["snapshot_payload"], hashlib.sha256(encoded).hexdigest())
            self.assertEqual(integrity["report_md"], hashlib.sha256((Path(temp) / "report.md").read_bytes()).hexdigest())

    def test_repeated_save_omits_existing_integrity_and_does_not_mutate(self):
        result = scan({}, self.since, self.until, api=FakeAPI([]))
        result["integrity"] = {"old": "must not enter canonical payload"}
        with tempfile.TemporaryDirectory() as temp:
            save(result, temp)
            initial = (Path(temp) / "snapshot.json").read_bytes()
            loaded = json.loads(initial)
            save(loaded, temp)
            self.assertEqual(initial, (Path(temp) / "snapshot.json").read_bytes())
            self.assertEqual(result["integrity"], {"old": "must not enter canonical payload"})
            integrity = loaded.pop("integrity")
            encoded = json.dumps(loaded, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.assertEqual(integrity["snapshot_payload"], hashlib.sha256(encoded).hexdigest())

    def test_since_hours_nonfinite_and_overflow_exit_two(self):
        with patch("frontier_radar.scan.scan") as operation:
            for value in ("inf", "nan", "1e300", "0", "-1"):
                with self.subTest(value=value):
                    self.assertEqual(main(["scan", "--config", "unused.json", "--since-hours", value]), 2)
            operation.assert_not_called()

    def test_failed_endpoint_is_unknown_and_main_exits_two(self):
        api = FakeAPI([("repos/o/r/commits?", None), ("repos/o/r/issues?", []), ("repos/o/r/pulls?", []), ("repos/o/r", {"private": False, "full_name": "o/r"})])
        result = scan(self.config, self.since, self.until, api=api)
        self.assertIsNone(result["repositories"][0]["commits"]["items"])
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "watchlist.json"
            config.write_text(json.dumps(self.config), encoding="utf-8")
            with patch("frontier_radar.scan.scan", return_value=result):
                self.assertEqual(main(["scan", "--config", str(config), "--output-dir", temp]), 2)
            self.assertTrue((Path(temp) / "snapshot.json").exists())
            self.assertIn("unknown", (Path(temp) / "report.md").read_text())
            self.assertTrue((Path(temp) / "SHA256SUMS").exists())

    def test_api_timeout_retries_are_bounded(self):
        calls = []
        def timeout(*args, **kwargs):
            calls.append(kwargs["timeout"])
            raise subprocess.TimeoutExpired("gh", 30)
        api = GitHub([], runner=timeout, sleeper=lambda _: None)
        self.assertIsNone(api.get("repos/o/r"))
        self.assertEqual(calls, [30, 30, 30])
        self.assertEqual(api.errors[0]["category"], "timeout")

    def test_markdown_does_not_render_foreign_html(self):
        self.assertIn("&lt;script&gt;", markdown("<script>[x](https://evil)"))
        self.assertIn("\\[x\\]", markdown("<script>[x](https://evil)"))


if __name__ == "__main__":
    unittest.main()
