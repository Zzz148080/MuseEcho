from __future__ import annotations

import subprocess

import pytest

import tests.unit.test_acceptance_matrix as acceptance_tests
import tests.unit.test_engineering_audit as engineering_tests


def test_acceptance_history_prerequisite_skips_when_git_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acceptance_tests.shutil, "which", lambda _name: None)

    with pytest.raises(pytest.skip.Exception, match="requires Git"):
        acceptance_tests._require_git_history()


def test_acceptance_history_prerequisite_skips_when_required_object_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_name = f"{acceptance_tests.HISTORICAL_EVIDENCE_COMMIT}^{{commit}}"
    monkeypatch.setattr(acceptance_tests.shutil, "which", lambda _name: "git")
    monkeypatch.setattr(
        acceptance_tests.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "cat-file", "-e", object_name],
            returncode=128,
            stderr=f"fatal: Not a valid object name {object_name}\n",
        ),
    )

    with pytest.raises(pytest.skip.Exception, match="retained Git object database"):
        acceptance_tests._require_git_history()


def test_acceptance_history_prerequisite_fails_on_unexpected_git_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acceptance_tests.shutil, "which", lambda _name: "git")
    monkeypatch.setattr(
        acceptance_tests.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "cat-file", "-e", acceptance_tests.HISTORICAL_EVIDENCE_COMMIT],
            returncode=128,
            stderr="fatal: detected dubious ownership in repository\n",
        ),
    )

    try:
        acceptance_tests._require_git_history()
    except pytest.skip.Exception as exc:
        raise AssertionError("unexpected Git errors must not skip the test") from exc
    except pytest.fail.Exception as exc:
        assert "unexpected Git prerequisite failure" in str(exc)
    else:
        raise AssertionError("unexpected Git errors must fail the test")


def test_historical_policy_prerequisite_skips_when_git_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engineering_tests.shutil, "which", lambda _name: None)

    with pytest.raises(pytest.skip.Exception, match="requires Git"):
        engineering_tests._require_historical_policy_git()


def test_historical_policy_prerequisite_skips_when_required_object_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_name = f"{engineering_tests.checker.SECURITY_POLICY_SOURCE_COMMIT}^{{commit}}"
    monkeypatch.setattr(engineering_tests.shutil, "which", lambda _name: "git")
    monkeypatch.setattr(
        engineering_tests.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "cat-file", "-e", object_name],
            returncode=128,
            stderr=f"fatal: Not a valid object name {object_name}\n",
        ),
    )

    with pytest.raises(pytest.skip.Exception, match="retained Git object database"):
        engineering_tests._require_historical_policy_git()


def test_historical_policy_prerequisite_fails_on_unexpected_git_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = engineering_tests.checker.SECURITY_POLICY_SOURCE_COMMIT
    monkeypatch.setattr(engineering_tests.shutil, "which", lambda _name: "git")
    monkeypatch.setattr(
        engineering_tests.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "cat-file", "-e", commit],
            returncode=128,
            stderr="fatal: could not open object database: Permission denied\n",
        ),
    )

    try:
        engineering_tests._require_historical_policy_git()
    except pytest.skip.Exception as exc:
        raise AssertionError("unexpected Git errors must not skip the test") from exc
    except pytest.fail.Exception as exc:
        assert "unexpected Git prerequisite failure" in str(exc)
    else:
        raise AssertionError("unexpected Git errors must fail the test")
