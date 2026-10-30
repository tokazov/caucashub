"""Fail closed before a manual frontend release. All GitHub requests are GETs.

The supplied SHA must still be master, with a successful *push* validation run
and all expected jobs completed successfully. PR/fork runs cannot authorize a
production release. No checkout, deployment, API tokens, or customer data here.
"""
import argparse
import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WORKFLOW = ".github/workflows/loading-period.yml"
REQUIRED_JOBS = frozenset({
    "regression", "carrier-profile-browser", "publication-browser",
    "deal-completion-browser", "notification-browser", "auth-recovery-browser",
    "address-browser", "validation",
})


class PublicationBlocked(ValueError):
    """The supplied release has not satisfied the publication contract."""


def validate_input(repository, commit):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
        raise PublicationBlocked("A valid GitHub repository is required")
    if not re.fullmatch(r"[a-f0-9]{40}", commit or ""):
        raise PublicationBlocked("Supply the full lowercase 40-character commit SHA")


def trusted_run(run, repository, commit):
    return (isinstance(run, dict)
            and run.get("head_sha") == commit
            and run.get("head_branch") == "master"
            and run.get("event") == "push"
            and run.get("path") == WORKFLOW
            and isinstance(run.get("head_repository"), dict)
            and run["head_repository"].get("full_name", "").lower() == repository.lower()
            and type(run.get("id")) is int and run["id"] > 0
            and type(run.get("run_attempt")) is int and run["run_attempt"] > 0)


def validate_jobs(jobs, commit):
    if not isinstance(jobs, list) or not jobs:
        raise PublicationBlocked("Regression jobs are missing")
    names = [job.get("name") for job in jobs if isinstance(job, dict)]
    if not REQUIRED_JOBS <= set(names) or any(names.count(name) != 1 for name in REQUIRED_JOBS):
        raise PublicationBlocked("A required regression job is missing or duplicated")
    # Also fail on newly added jobs. They must never be silently ignored.
    if any(not isinstance(job, dict) or job.get("status") != "completed"
           or job.get("conclusion") != "success" or job.get("head_sha") != commit
           for job in jobs):
        raise PublicationBlocked("Every regression job must succeed for this exact commit")


def verify(repository, commit, get):
    """Verify using an injected read-only GitHub API client (offline in tests)."""
    validate_input(repository, commit)
    prefix = "/repos/" + repository
    ref = get(prefix + "/git/ref/heads/master")
    if not isinstance(ref, dict) or ref.get("object", {}).get("sha") != commit:
        raise PublicationBlocked("Commit is no longer current master; publication stopped")
    query = urlencode({"head_sha": commit, "event": "push", "per_page": 100})
    response = get(prefix + "/actions/workflows/loading-period.yml/runs?" + query)
    runs = response.get("workflow_runs") if isinstance(response, dict) else None
    if not isinstance(runs, list):
        raise PublicationBlocked("No regression run data")
    candidates = [run for run in runs if trusted_run(run, repository, commit)]
    if not candidates:
        raise PublicationBlocked("No trusted push/master regression for this commit")
    # Never fall back to an earlier green run if a newer execution is not green.
    run = max(candidates, key=lambda row: row["id"])
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise PublicationBlocked("Latest push regression has not completed successfully")
    jobs = []
    for page in range(1, 11):
        query = urlencode({"filter": "latest", "per_page": 100, "page": page})
        response = get(prefix + f'/actions/runs/{run["id"]}/jobs?' + query)
        batch = response.get("jobs") if isinstance(response, dict) else None
        if not isinstance(batch, list):
            raise PublicationBlocked("Regression job data is incomplete")
        jobs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise PublicationBlocked("Too many regression jobs to verify safely")
    validate_jobs(jobs, commit)
    # Catch a rerun started while jobs were being inspected.
    current = get(prefix + f'/actions/runs/{run["id"]}')
    if (not trusted_run(current, repository, commit)
            or current.get("status") != "completed" or current.get("conclusion") != "success"
            or current.get("run_attempt") != run.get("run_attempt")):
        raise PublicationBlocked("Regression changed during verification")
    ref = get(prefix + "/git/ref/heads/master")
    if not isinstance(ref, dict) or ref.get("object", {}).get("sha") != commit:
        raise PublicationBlocked("Master changed during verification")
    return run["id"]


def github_get(token):
    def get(path):
        request = Request("https://api.github.com" + path, headers={
            "Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28", "Cache-Control": "no-cache",
        })
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    return get


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    if (os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or os.environ.get("GITHUB_REF") != "refs/heads/master"):
        parser.error("Production frontend publication requires a manual dispatch from master")
    token = os.environ.get("GH_TOKEN")
    if not token:
        parser.error("A read-only GitHub token is required")
    try:
        run_id = verify(os.environ.get("GITHUB_REPOSITORY"), args.commit, github_get(token))
    except Exception as error:
        # Exception bodies from remote APIs must not leak credentials or data.
        reason = str(error) if isinstance(error, PublicationBlocked) else type(error).__name__
        raise SystemExit("Frontend publication blocked: " + reason) from None
    print(f"Verified exact master commit {args.commit}; all regression jobs passed in run {run_id}.")


if __name__ == "__main__":
    main()
