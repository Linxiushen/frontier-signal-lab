"""Read public GitHub evidence through the locally authenticated gh CLI.

No third-party Python packages, write APIs, or private repository snapshots.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

UTC = dt.timezone.utc
PROFILE_FIELDS = ("login", "name", "company", "bio", "blog", "html_url", "twitter_username", "updated_at")


def now_iso():
    return dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")


def utc_iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value):
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone, e.g. 2026-10-15T00:00:00Z")
    return result.astimezone(UTC)


def in_window(value, since, until):
    if not value:
        return False
    try:
        return since <= parse_time(value) <= until
    except (ValueError, TypeError):
        return False


def excerpt(value, limit=700):
    return str(value or "")[:limit]


def markdown(value):
    """Escape API-controlled text so it cannot inject Markdown or HTML."""
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~-])", r"\\\1", text)


def source_url(value):
    """Only GitHub HTTPS links are rendered as active report links."""
    value = str(value or "")
    return value if re.fullmatch(r"https://(?:api\.)?github\.com/[^\s<>\[\]()]+", value) else ""


def stamp(data, source, observed):
    return dict(data, source_url=source, observed_at=observed)


class GitHub:
    def __init__(self, errors, runner=None, sleeper=None):
        self.errors = errors
        self.runner = runner or subprocess.run
        self.sleeper = sleeper or time.sleep

    def get(self, endpoint, query=None):
        args = ["gh", "api", "--method", "GET", endpoint]
        if query is not None:
            # GitHub GraphQL reads use POST at the HTTP transport layer; the
            # fixed query below contains only query operations, never mutations.
            args = ["gh", "api", "graphql", "-f", "query=" + query]
        for attempt in range(3):
            try:
                result = self.runner(args, capture_output=True, text=True, encoding="utf-8", timeout=30)
                if result.returncode:
                    raw = result.stderr or ""
                    transient = bool(re.search(r"HTTP 5\d\d|connection|TLS|timeout", raw, re.I))
                    rate_limited = bool(re.search(r"rate limit|HTTP 429", raw, re.I))
                    if transient and not rate_limited and attempt < 2:
                        self.sleeper(2 ** attempt)
                        continue
                    category = "rate_limited" if rate_limited else "request_failed"
                    self.errors.append({"endpoint": endpoint, "category": category, "observed_at": now_iso(), "attempts": attempt + 1})
                    return None
                data = json.loads(result.stdout)
                if isinstance(data, dict) and data.get("errors"):
                    self.errors.append({"endpoint": endpoint, "category": "graphql_partial_or_error", "observed_at": now_iso(), "attempts": attempt + 1})
                    return None
                return data
            except subprocess.TimeoutExpired:
                if attempt < 2:
                    self.sleeper(2 ** attempt)
                    continue
                category = "timeout"
            except (OSError, json.JSONDecodeError, UnicodeError):
                category = "cli_unavailable_or_invalid_response"
            self.errors.append({"endpoint": endpoint, "category": category, "observed_at": now_iso(), "attempts": attempt + 1})
            return None


def actor(item):
    user = item.get("user") or item.get("author") or {}
    return {"login": user.get("login"), "association": item.get("author_association"), "type": user.get("type")}


def event(item, kind, observed):
    fields = ("number", "title", "state", "created_at", "updated_at", "closed_at", "comments")
    result = {key: item.get(key) for key in fields if key in item}
    result.update(kind=kind, body_excerpt=excerpt(item.get("body")), author=actor(item))
    if kind == "pull_request":
        result.update(draft=item.get("draft"), merged_at=item.get("merged_at"), review_comments=item.get("review_comments"), comments_url=item.get("comments_url"), review_comments_url=item.get("review_comments_url"))
    return stamp(result, item.get("html_url"), observed)


def recent_comments(api, repo, issue, observed):
    count = issue.get("comments")
    result = {"status": "complete", "sampling": "Last up to 5 issue comments, at most two pages; includes context outside the scan window; review comments are not sampled.", "reported_total": count, "items": []}
    if count is None:
        result["status"] = "unknown"
        return result
    if count == 0:
        return result
    last = math.ceil(count / 5)
    first = max(1, (count - 5) // 5 + 1)
    found = []
    for page in range(first, last + 1):
        data = api.get(f"repos/{repo}/issues/{issue['number']}/comments?per_page=5&page={page}")
        if data is None:
            result["status"] = "partial"
            continue
        for item in data:
            found.append(stamp({"id": item.get("id"), "author": actor(item), "body_excerpt": excerpt(item.get("body")), "created_at": item.get("created_at"), "updated_at": item.get("updated_at")}, item.get("html_url"), observed))
    result["items"] = found[-5:]
    result["sampled"] = count > 5
    return result


def recent_reviews(api, repo, number, observed):
    data = api.get(f"repos/{repo}/pulls/{number}/reviews?per_page=30&page=1")
    result = {"status": "partial" if data is None else "complete", "truncation_possible": None if data is None else len(data) == 30, "sampling": "Last 5 submitted reviews within the first page of at most 30 reviews; later pages may contain newer reviews and are not fetched; pending reviews and inline diff comments are excluded.", "items": None}
    if data is not None:
        submitted = sorted((r for r in data if r.get("submitted_at")), key=lambda r: r["submitted_at"])
        result["items"] = [stamp({"author": actor(r), "body_excerpt": excerpt(r.get("body")), "submitted_at": r.get("submitted_at"), "state": r.get("state")}, r.get("html_url"), observed) for r in submitted[-5:]]
    return result


def discussions(api, repo, observed):
    owner, name = repo.split("/", 1)
    # Owner/repository names have already passed the strict repository regex.
    query = 'query { repository(owner: "' + owner + '", name: "' + name + '") { discussions(first: 5, orderBy: {field: UPDATED_AT, direction: DESC}) { pageInfo { hasNextPage } nodes { number title url createdAt updatedAt author { login } comments(last: 3) { totalCount pageInfo { hasPreviousPage } nodes { url bodyText createdAt updatedAt author { login } authorAssociation } } } } } }'
    data = api.get(f"graphql:{repo}:discussions", query=query)
    if data is None:
        return {"status": "partial", "items": None, "sampling": "Latest 5 discussions; last 3 top-level comments each; replies are not included."}
    repository = (data.get("data") or {}).get("repository")
    if not repository or "discussions" not in repository:
        api.errors.append({"endpoint": f"graphql:{repo}:discussions", "category": "missing_repository_or_discussions", "observed_at": observed})
        return {"status": "partial", "items": None}
    connection = repository["discussions"]
    items = []
    for item in connection.get("nodes", []):
        comments = item.get("comments") or {}
        entry = stamp({k: item.get(k) for k in ("number", "title", "createdAt", "updatedAt", "author")}, item.get("url"), observed)
        entry["comments"] = {"reported_total": comments.get("totalCount"), "sampled": (comments.get("pageInfo") or {}).get("hasPreviousPage"), "items": [stamp({"author": c.get("author"), "author_association": c.get("authorAssociation"), "body_excerpt": excerpt(c.get("bodyText")), "createdAt": c.get("createdAt"), "updatedAt": c.get("updatedAt")}, c.get("url"), observed) for c in comments.get("nodes", [])]}
        items.append(entry)
    return {"status": "complete", "items": items, "truncated": connection.get("pageInfo", {}).get("hasNextPage"), "sampling": "Latest 5 discussions; last 3 top-level comments each; replies are not included."}


def scan(config, since, until=None, previous=None, api=None):
    until = until or dt.datetime.now(UTC)
    observed = now_iso()
    errors = []
    api = api or GitHub(errors)
    # An injected client must expose the same mutable error list.
    errors = api.errors
    output = {"schema_version": 1, "observed_at": observed, "window": {"since": since.isoformat(), "until": until.isoformat(), "inclusive": True}, "people": [], "repositories": [], "errors": errors, "limits": {"per_endpoint": 30, "issue_comment_threads": 3, "comments_per_thread": 5, "discussion_threads": 5, "discussion_comments": 3}, "interpretation": "Repository activity is upstream activity, not proof of the watched person's contribution. Public hypotheses are not confirmed private research plans."}
    old_people = {p.get("id"): p.get("profile", {}) for p in (previous or {}).get("people", [])}
    for person in config.get("people", []):
        login = person.get("github", "")
        if not re.fullmatch(r"[A-Za-z0-9-]+", login):
            errors.append({"endpoint": "profile", "category": "invalid_login", "observed_at": observed})
            continue
        entry = {"id": person.get("id"), "github": login, "observed_at": observed, "source_url": f"https://github.com/{login}"}
        if isinstance(person.get("affiliation"), dict):
            entry["curated_affiliation"] = {key: person["affiliation"].get(key) for key in ("name", "status", "source_url", "verified_at")}
        profile = api.get(f"users/{login}")
        if profile is None:
            entry["profile"] = None
        else:
            entry["profile"] = stamp({key: profile.get(key) for key in PROFILE_FIELDS}, profile.get("html_url"), observed)
            prior = old_people.get(person.get("id"))
            if prior:
                entry["profile_changes"] = {key: {"before": prior.get(key), "after": profile.get(key)} for key in PROFILE_FIELDS if key != "updated_at" and prior.get(key) != profile.get(key)}
        repos = api.get(f"users/{login}/repos?type=owner&sort=created&direction=desc&per_page=30&page=1")
        entry["discovered_repositories"] = {"status": "partial" if repos is None else "complete", "truncation_possible": None if repos is None else len(repos) == 30, "sampling": "First page of 30 repositories sorted by creation; only explicitly public, non-fork repositories are saved.", "items": None if repos is None else [stamp({key: r.get(key) for key in ("full_name", "description", "created_at", "pushed_at", "updated_at", "fork")}, r.get("html_url"), observed) for r in repos if r.get("private") is False and not r.get("fork") and in_window(r.get("created_at"), since, until)]}
        output["people"].append(entry)
    for watched in config.get("repositories", []):
        repo = watched.get("full_name", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            errors.append({"endpoint": "repository", "category": "invalid_repository_name", "observed_at": observed})
            continue
        metadata = api.get(f"repos/{repo}")
        if metadata is None:
            output["repositories"].append({"full_name": repo, "status": "partial", "observed_at": observed})
            continue
        if metadata.get("private") is not False:
            # Do not retain returned private metadata or fetch further endpoints.
            errors.append({"endpoint": f"repos/{repo}", "category": "repository_not_explicitly_public", "observed_at": observed})
            continue
        entry = stamp({key: metadata.get(key) for key in ("full_name", "description", "created_at", "updated_at", "pushed_at", "default_branch", "has_discussions")}, metadata.get("html_url"), observed)
        entry.update(status="complete", person_ids=watched.get("person_ids", []), license=(metadata.get("license") or {}).get("spdx_id"))
        start_errors = len(errors)
        data = api.get(f"repos/{repo}/commits?since={utc_iso(since)}&until={utc_iso(until)}&per_page=30&page=1")
        entry["commits"] = {"status": "partial" if data is None else "complete", "truncation_possible": None if data is None else len(data) == 30, "sampling": "First page, at most 30 commits; committer dates determine inclusion (author date fallback); upstream authors are retained explicitly.", "items": None if data is None else [stamp({"sha": c.get("sha"), "author_login": (c.get("author") or {}).get("login"), "author_date": c.get("commit", {}).get("author", {}).get("date"), "committer_date": c.get("commit", {}).get("committer", {}).get("date"), "message_excerpt": excerpt(c.get("commit", {}).get("message"), 300)}, c.get("html_url"), observed) for c in data if in_window(c.get("commit", {}).get("committer", {}).get("date") or c.get("commit", {}).get("author", {}).get("date"), since, until)]}
        data = api.get(f"repos/{repo}/issues?state=all&sort=updated&direction=desc&since={utc_iso(since)}&per_page=30&page=1")
        entry["issues"] = {"status": "partial" if data is None else "complete", "truncation_possible": None if data is None else len(data) == 30, "sampling": "First page of 30 updated issues/PRs; PR entries are excluded here. Only first 3 matching issues have last 5 comments sampled.", "items": None}
        if data is not None:
            selected = [i for i in data if "pull_request" not in i and in_window(i.get("updated_at"), since, until)]
            entry["issues"]["items"] = [event(i, "issue", observed) for i in selected]
            for index, issue in enumerate(selected[:3]):
                entry["issues"]["items"][index]["recent_comments"] = recent_comments(api, repo, issue, observed)
        data = api.get(f"repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=30&page=1")
        entry["pull_requests"] = {"status": "partial" if data is None else "complete", "truncation_possible": None if data is None else len(data) == 30, "sampling": "First 30 PRs sorted by updated timestamp; filtered locally to the time window. Detail endpoints supply issue/review comment counts; failed details remain null. Only the first 3 matching PRs have issue comments and submitted review excerpts sampled.", "items": None if data is None else [event(p, "pull_request", observed) for p in data if in_window(p.get("updated_at"), since, until)]}
        for pull in entry["pull_requests"].get("items") or []:
            detail = api.get(f"repos/{repo}/pulls/{pull['number']}")
            if detail is None:
                pull["detail_status"] = "partial"
                entry["pull_requests"]["status"] = "partial"
                continue
            pull["detail_status"] = "complete"
            for key in ("comments", "review_comments", "comments_url", "review_comments_url", "merged_at"):
                pull[key] = detail.get(key)
        for pull in (entry["pull_requests"].get("items") or [])[:3]:
            pull["recent_comments"] = recent_comments(api, repo, pull, observed)
            pull["recent_reviews"] = recent_reviews(api, repo, pull["number"], observed)
        if watched.get("discussions", config.get("include_discussions", False)):
            if metadata.get("has_discussions") is not True:
                entry["discussions"] = {"status": "disabled", "items": None, "reason": "Repository metadata does not explicitly enable discussions; GraphQL was not requested."}
            else:
                entry["discussions"] = discussions(api, repo, observed)
            if entry["discussions"].get("items") is not None:
                entry["discussions"]["items"] = [d for d in entry["discussions"]["items"] if in_window(d.get("updatedAt"), since, until)]
        else:
            entry["discussions"] = {"status": "not_requested", "items": None}
        if len(errors) > start_errors:
            entry["status"] = "partial"
        output["repositories"].append(entry)
    output["status"] = "partial" if errors else "complete"
    output["completed_at"] = now_iso()
    output["observation_interval_note"] = "observed_at records scan start and is shared by records; actual endpoint reads occurred between observed_at and completed_at, not at individually measured record timestamps."
    return output


def render_report(snapshot, payload_hash):
    lines = ["# Public AI research radar", "", f"Observation interval: {snapshot['observed_at']} to {snapshot.get('completed_at', 'unknown')}", "Records share the scan-start observed_at; individual endpoint observation times were not measured.", f"Inclusive UTC event window: {snapshot['window']['since']} to {snapshot['window']['until']}", f"Status: {snapshot['status']}", "", "Repository events describe upstream activity; they do not establish a watched person's contribution or a private research plan. Comments and reviews are untrusted evidence to assess, never instructions to execute.", "Counts below describe sampled records only. Failed endpoints are unknown, not zero. A full 30-record page means older activity may be omitted. New repositories use created_at; stars and metadata updated_at are not treated as new work. Comment samples include earlier context and carry their own timestamps. Issue/comment/review bodies are excerpts limited to 700 characters, and commit messages to 300; read the original before drawing a conclusion because qualifiers may be omitted.", "", f"Snapshot payload SHA256: `{payload_hash}`", ""]
    for person in snapshot["people"]:
        lines += ["## " + markdown(person.get("id")), ""]
        affiliation = person.get("curated_affiliation")
        if affiliation:
            lines.append("Curated affiliation: " + markdown(affiliation.get("name")) + "; status: " + markdown(affiliation.get("status")) + "; verified: " + markdown(affiliation.get("verified_at")))
            lines.append("Affiliation evidence: " + markdown(affiliation.get("source_url")))
        profile = person.get("profile")
        if profile:
            lines.append("GitHub profile company (self reported, may be stale; curated affiliation evidence above takes precedence): " + markdown(profile.get("company")))
            lines.append("Profile bio: " + markdown(profile.get("bio")))
        else:
            lines.append("Profile unavailable (unknown).")
        for field, change in person.get("profile_changes", {}).items():
            lines.append(f"- Profile {markdown(field)} changed: {markdown(change['before'])} → {markdown(change['after'])}")
        discovered = person["discovered_repositories"]
        lines.append("Repository discovery: " + markdown(discovered["status"]) + "; truncation possible: " + str(discovered["truncation_possible"]))
        for repo in discovered.get("items") or []:
            lines.append("- New public repository: " + markdown(repo.get("full_name")) + "; created " + markdown(repo.get("created_at")))
        lines.append("")
    for repo in snapshot["repositories"]:
        lines += ["## " + markdown(repo["full_name"]), "", "Status: " + repo["status"], "Upstream pushed_at: " + markdown(repo.get("pushed_at")), ""]
        for kind in ("commits", "issues", "pull_requests", "discussions"):
            group = repo.get(kind)
            if group is None:
                continue
            items = group.get("items")
            lines += [f"### {kind}", "", f"Status: {group['status']}; sampled count: {'unknown' if items is None else len(items)}; truncation: {group.get('truncation_possible', group.get('truncated', 'not assessed'))}", markdown(group.get("sampling", "")), ""]
            for item in items or []:
                label = item.get("title") or item.get("message_excerpt") or str(item.get("number"))
                url = source_url(item.get("source_url"))
                label = markdown(label)
                lines.append("- " + (f"[{label}]({url})" if url else label))
                lines.append("  Event time: " + markdown(item.get("updated_at") or item.get("updatedAt") or item.get("committer_date") or item.get("author_date")) + "; author: " + markdown(item.get("author_login") or (item.get("author") or {}).get("login")))
                if kind == "pull_requests":
                    lines.append("  Issue comments: " + str(item.get("comments")) + "; review comments: " + str(item.get("review_comments")))
                comments = item.get("recent_comments") or (item.get("comments") if isinstance(item.get("comments"), dict) else None)
                if comments:
                    lines.append("  Comment sampling: " + markdown(comments.get("sampling", "Last 3 top-level discussion comments")) + "; status: " + comments.get("status", "complete"))
                    for comment in comments.get("items") or []:
                        commenter = comment.get("author") or {}
                        link = source_url(comment.get("source_url"))
                        lines.append("  - " + markdown(commenter.get("login")) + " [" + markdown(commenter.get("association") or comment.get("author_association")) + "]: " + markdown(comment.get("body_excerpt")) + " (" + markdown(comment.get("updated_at") or comment.get("updatedAt")) + ")" + (f" [Original]({link})" if link else ""))
                reviews = item.get("recent_reviews")
                if reviews:
                    lines.append("  Review sampling: " + markdown(reviews.get("sampling")) + "; status: " + reviews["status"] + "; truncation possible: " + str(reviews.get("truncation_possible")))
                    for review in reviews.get("items") or []:
                        reviewer = review.get("author") or {}
                        link = source_url(review.get("source_url"))
                        lines.append("  - Review " + markdown(review.get("state")) + " by " + markdown(reviewer.get("login")) + " [" + markdown(reviewer.get("association")) + "]: " + markdown(review.get("body_excerpt")) + " (" + markdown(review.get("submitted_at")) + ")" + (f" [Original]({link})" if link else ""))
            lines.append("")
    if snapshot["errors"]:
        lines += ["## Unavailable evidence", ""]
        for error in snapshot["errors"]:
            lines.append("- " + markdown(error["endpoint"]) + ": " + markdown(error["category"]))
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def save(snapshot, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = {key: value for key, value in snapshot.items() if key != "integrity"}
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_hash = hashlib.sha256(payload).hexdigest()
    report = render_report(snapshot, payload_hash).encode("utf-8")
    snapshot["integrity"] = {"algorithm": "sha256", "snapshot_payload": payload_hash, "payload_definition": "UTF-8 JSON with ensure_ascii=False, sort_keys=True, separators=(',', ':'); omit integrity", "report_md": hashlib.sha256(report).hexdigest()}
    encoded = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (directory / "snapshot.json").write_bytes(encoded)
    (directory / "report.md").write_bytes(report)
    (directory / "SHA256SUMS").write_text(hashlib.sha256(encoded).hexdigest() + "  snapshot.json\n" + hashlib.sha256(report).hexdigest() + "  report.md\n", encoding="utf-8", newline="\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("scan")
    command.add_argument("--config", required=True)
    command.add_argument("--output-dir", default="reports/live")
    command.add_argument("--since-hours", type=float, default=168)
    command.add_argument("--since")
    command.add_argument("--previous")
    args = parser.parse_args(argv)
    try:
        until = dt.datetime.now(UTC)
        if not math.isfinite(args.since_hours) or args.since_hours <= 0:
            raise ValueError("--since-hours must be a finite positive number")
        since = parse_time(args.since) if args.since else until - dt.timedelta(hours=args.since_hours)
        if since > until:
            raise ValueError("--since cannot be in the future")
        config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        previous = json.loads(Path(args.previous).read_text(encoding="utf-8-sig")) if args.previous else None
        snapshot = scan(config, since, until, previous)
        save(snapshot, args.output_dir)
    except OverflowError:
        print("Configuration/output error: --since-hours exceeds the supported datetime range", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError) as exc:
        print("Configuration/output error: " + str(exc), file=sys.stderr)
        return 2
    print(f"Saved {args.output_dir}/snapshot.json and report.md ({snapshot['status']})")
    return 2 if snapshot["errors"] else 0
