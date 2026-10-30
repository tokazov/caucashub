"""Release gate rejects untested, stale, skipped and untrusted source commits."""
from copy import deepcopy
from pathlib import Path
import json
import re

import pytest

from scripts.verify_frontend_publish import (
    PublicationBlocked, REQUIRED_JOBS, WORKFLOW, validate_input, validate_jobs, verify,
)
from scripts.check_public_visibility import summary

ROOT = Path(__file__).resolve().parents[1]
SHA, OLD_SHA, REPO = "a" * 40, "b" * 40, "owner/project"


def run(**changes):
    result = {"id": 42, "head_sha": SHA, "head_branch": "master", "event": "push",
              "path": WORKFLOW, "status": "completed", "conclusion": "success",
              "head_repository": {"full_name": REPO}, "run_attempt": 1}
    result.update(changes)
    return result


def jobs():
    return [{"name": name, "status": "completed", "conclusion": "success", "head_sha": SHA}
            for name in sorted(REQUIRED_JOBS)]


class GitHub:
    def __init__(self, runs=None, job_rows=None, ref=SHA, final_run=None):
        self.runs = [run()] if runs is None else runs
        self.jobs = jobs() if job_rows is None else job_rows
        self.ref = ref
        self.final = final_run
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        assert path.startswith("/repos/" + REPO + "/")
        if path.endswith("/git/ref/heads/master"):
            return {"object": {"sha": self.ref}}
        if "/workflows/loading-period.yml/runs?" in path:
            assert "head_sha=" + SHA in path and "event=push" in path
            return {"workflow_runs": deepcopy(self.runs)}
        if "/jobs?" in path:
            assert "filter=latest" in path and "per_page=100" in path
            return {"jobs": deepcopy(self.jobs)}
        if re.search(r"/actions/runs/\d+$", path):
            return deepcopy(self.final or max(self.runs, key=lambda row: row["id"]))
        raise AssertionError("Unexpected GitHub request: " + path)


def test_only_exact_green_push_master_can_publish():
    client = GitHub()
    assert verify(REPO, SHA, client) == 42
    assert len(client.calls) == 5


@pytest.mark.parametrize("changes", [
    {"event": "pull_request"}, {"event": "workflow_dispatch"}, {"head_branch": "feature"},
    {"head_repository": {"full_name": "attacker/project"}}, {"head_repository": None},
    {"head_sha": OLD_SHA}, {"path": ".github/workflows/other.yml"}, {"id": "42"},
    {"run_attempt": None},
    {"status": "in_progress", "conclusion": None}, {"conclusion": "failure"},
    {"conclusion": "cancelled"}, {"conclusion": "skipped"},
])
def test_untrusted_or_incomplete_workflow_does_not_authorize_release(changes):
    with pytest.raises(PublicationBlocked):
        verify(REPO, SHA, GitHub(runs=[run(**changes)]))


@pytest.mark.parametrize("invalid", ["master", "a" * 7, "a" * 39, "a" * 41, "A" * 40,
                                     "a" * 40 + "; echo bad", "../master", "", None])
def test_commit_must_be_full_safe_sha(invalid):
    with pytest.raises(PublicationBlocked):
        validate_input(REPO, invalid)


@pytest.mark.parametrize("invalid", [None, "../owner/project", "owner/project/extra", "owner/project?token=x"])
def test_repository_is_not_a_user_controlled_url(invalid):
    with pytest.raises(PublicationBlocked):
        validate_input(invalid, SHA)


def test_stale_commit_is_blocked_before_any_regression_request():
    client = GitHub(ref=OLD_SHA)
    with pytest.raises(PublicationBlocked, match="current master"):
        verify(REPO, SHA, client)
    assert len(client.calls) == 1


def test_newer_running_run_cannot_fall_back_to_old_success():
    with pytest.raises(PublicationBlocked, match="not completed"):
        verify(REPO, SHA, GitHub(runs=[run(), run(id=43, status="in_progress", conclusion=None)]))


@pytest.mark.parametrize("name", sorted(REQUIRED_JOBS))
@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "neutral", None])
def test_each_required_job_must_succeed(name, conclusion):
    rows = jobs()
    next(row for row in rows if row["name"] == name)["conclusion"] = conclusion
    with pytest.raises(PublicationBlocked):
        verify(REPO, SHA, GitHub(job_rows=rows))


def test_missing_and_duplicate_required_jobs_fail_closed():
    for rows in (jobs()[:-1], jobs() + [jobs()[0]], [], [None]):
        with pytest.raises(PublicationBlocked):
            validate_jobs(rows, SHA)


def test_new_security_job_failure_is_not_ignored():
    rows = jobs() + [{"name": "new-security-check", "status": "completed",
                      "conclusion": "failure", "head_sha": SHA}]
    with pytest.raises(PublicationBlocked):
        validate_jobs(rows, SHA)


def test_job_for_another_commit_or_still_running_is_rejected():
    for changes in ({"head_sha": OLD_SHA}, {"status": "in_progress"}):
        rows = jobs()
        rows[0].update(changes)
        with pytest.raises(PublicationBlocked):
            validate_jobs(rows, SHA)


@pytest.mark.parametrize("changes", [{"run_attempt": 2}, {"status": "in_progress"}, {"conclusion": "failure"}])
def test_rerun_started_during_gate_check_is_rejected(changes):
    with pytest.raises(PublicationBlocked, match="changed during verification"):
        verify(REPO, SHA, GitHub(final_run=run(**changes)))


def test_github_failure_never_turns_into_release_permission():
    def broken(_):
        raise TimeoutError("read failed")
    with pytest.raises(TimeoutError):
        verify(REPO, SHA, broken)


def test_master_moving_during_verification_is_rejected():
    client = GitHub()
    def moving(path):
        result = client(path)
        if len(client.calls) > 1 and path.endswith("/git/ref/heads/master"):
            return {"object": {"sha": OLD_SHA}}
        return result
    with pytest.raises(PublicationBlocked, match="Master changed"):
        verify(REPO, SHA, moving)


@pytest.mark.parametrize("event,ref", [("push", "refs/heads/master"),
                                      ("workflow_run", "refs/heads/master"),
                                      ("workflow_dispatch", "refs/heads/feature")])
def test_cli_never_runs_on_automatic_or_non_master_context(monkeypatch, event, ref):
    from scripts import verify_frontend_publish as gate
    monkeypatch.setattr("sys.argv", ["gate", "--commit", SHA])
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.setattr(gate, "github_get", lambda token: pytest.fail("Must not call GitHub"))
    with pytest.raises(SystemExit):
        gate.main()


def test_remote_errors_cannot_print_a_token(monkeypatch, capsys):
    from scripts import verify_frontend_publish as gate
    secret = "test-token-never-log"
    monkeypatch.setattr("sys.argv", ["gate", "--commit", SHA])
    for name, value in {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/master",
                        "GITHUB_REPOSITORY": REPO, "GH_TOKEN": secret}.items():
        monkeypatch.setenv(name, value)
    def broken(_):
        raise RuntimeError("Remote error containing " + secret)
    monkeypatch.setattr(gate, "github_get", lambda _: broken)
    with pytest.raises(SystemExit) as error:
        gate.main()
    captured = capsys.readouterr()
    assert secret not in str(error.value) + captured.out + captured.err
    assert "RuntimeError" in str(error.value)


def test_a_legitimately_empty_marketplace_passes_post_release_smoke():
    result = summary({"total_users": 0, "companies": 0}, {"total": 0, "offers": []},
                     {"total": 0, "offers": []}, {"total": 0})
    assert result["transport_total"] == 0 and result["release_schema_seen"] is True


@pytest.mark.parametrize("directory,current", [
    ({"total": 1, "offers": [{}]}, {"total": 0, "offers": []}),
    ({"total": 0, "offers": []}, {"total": 1, "offers": [{"dates_expired": False}]}),
    ({"total": 1, "offers": [{"dates_expired": True}]}, {"total": 1, "offers": [{"dates_expired": True}]}),
    ({"total": -1, "offers": []}, {"total": 0, "offers": []}),
    ({"total": True, "offers": []}, {"total": 0, "offers": []}),
])
def test_post_release_smoke_keeps_schema_and_freshness_checks(directory, current):
    with pytest.raises(ValueError):
        summary({"total_users": 1, "companies": 1}, directory, current, {"total": 0})


def test_regression_covers_every_master_push_and_pr_without_production_dependency():
    source = (ROOT / WORKFLOW).read_text(encoding="utf-8")
    trigger = source.split("permissions:", 1)[0]
    assert "push:" in trigger and "branches: [master]" in trigger and "pull_request:" in trigger
    assert "paths:" not in trigger and "paths-ignore:" not in trigger
    actual_jobs = set(re.findall(r"^  ([a-z][a-z0-9-]*):$", source.split("\njobs:\n", 1)[1], re.MULTILINE))
    assert actual_jobs == REQUIRED_JOBS
    assert "test_ci_publish_gate.py" in source
    assert "wait_for_api_release" not in source and "railway.app" not in source
    assert "CLOUDFLARE_API_TOKEN" not in source and "wrangler" not in source
    aggregate = source.split("  validation:\n", 1)[1]
    assert "if: ${{ always() }}" in aggregate
    for name in REQUIRED_JOBS - {"validation"}:
        assert "      - " + name + "\n" in aggregate
    assert 'job["result"] != "success"' in aggregate
    assert "continue-on-error" not in source


def test_only_manual_single_publisher_checks_exact_source_and_all_gates():
    workflow_dir = ROOT / ".github/workflows"
    publishers = [path for path in workflow_dir.glob("*.yml") if "wrangler@" in path.read_text(encoding="utf-8")]
    assert [path.name for path in publishers] == ["deploy-pages.yml"]
    source = publishers[0].read_text(encoding="utf-8")
    trigger = source.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger and "required: true" in trigger
    assert "workflow_run:" not in trigger and "\n  push:" not in trigger
    assert "if: github.ref == 'refs/heads/master'" in source
    assert "ref: ${{ inputs.commit }}" in source
    assert 'test "$(git rev-parse HEAD)" = "$EXPECTED_RELEASE_SHA"' in source
    assert source.count("scripts/verify_frontend_publish.py") == 2
    assert "python -m scripts.check_public_visibility" in source
    assert source.count("scripts/wait_for_api_release.py") == 2
    assert '--commit-hash "$EXPECTED_RELEASE_SHA"' in source
    assert '--commit-hash "${{ github.sha }}"' not in source
    assert source.index("scripts/verify_frontend_publish.py") < source.index("Checkout only the verified commit")
    assert source.rindex("scripts/verify_frontend_publish.py") < source.index("npx wrangler@")
    assert "persist-credentials: false" in source and "actions: read" in source
    # Secrets only enter the actual publisher step, after both readiness checks.
    assert source.index("CLOUDFLARE_API_TOKEN") > source.index("npx wrangler@")


def test_ci_restore_has_matching_clients_and_explicit_disposable_postgres():
    source = (ROOT / WORKFLOW).read_text(encoding="utf-8").split("  carrier-profile-browser:", 1)[0]
    assert "image: postgres:18" in source and "runs-on: ubuntu-24.04" in source
    assert "TEST_POSTGRES_URL: postgresql://postgres:postgres@127.0.0.1:5432/postgres" in source
    assert "PG_BIN: /usr/lib/postgresql/18/bin" in source
    assert "POSTGRES_BIN: /usr/lib/postgresql/18/bin" in source
    assert "apt-get install -y postgresql-client-18" in source
    assert 'test -x "$PG_BIN/$tool"' in source
    assert "for tool in pg_dump pg_restore psql" in source
    assert "grep -Eq 'PostgreSQL\\) 18([. ]|$)'" in source
    assert source.index("Require PostgreSQL 18 archive") < source.index("python -m pytest")
    assert "PGHOST: 127.0.0.1" in source and "PGDATABASE: postgres" in source
    assert "COMMENT ON DATABASE postgres IS 'caucashub-disposable-restore-admin-v1'" in source
    assert source.index("Mark only disposable PostgreSQL service") < source.index("python -m pytest")
    assert "tests/test_database_backup.py" in source and "test_local_backup_connection.py" not in source


def test_aggregate_job_rejects_any_non_success():
    for result in ("failure", "skipped", "cancelled", "success"):
        needs = {name: {"result": "success"} for name in REQUIRED_JOBS - {"validation"}}
        needs["regression"]["result"] = result
        source = (ROOT / WORKFLOW).read_text(encoding="utf-8").split("  validation:\n", 1)[1]
        script = source.split("          python - <<'PY'\n", 1)[1].rsplit("          PY", 1)[0]
        script = "\n".join(line[10:] for line in script.splitlines())
        from unittest.mock import patch
        with patch.dict("os.environ", {"JOB_RESULTS": json.dumps(needs)}):
            if result == "success":
                exec(compile(script, "validation workflow", "exec"), {})
            else:
                with pytest.raises(SystemExit):
                    exec(compile(script, "validation workflow", "exec"), {})
