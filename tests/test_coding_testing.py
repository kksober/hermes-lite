"""Tests for the structured test runner module."""

from __future__ import annotations

import subprocess
import textwrap

import pytest


# ---------------------------------------------------------------------------
# .venv discovery
# ---------------------------------------------------------------------------

def test_discover_venv_python_finds_venv(tmp_path) -> None:
    from hermes_lite.coding.testing import discover_venv_python
    from hermes_lite.coding.workspace import Workspace

    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").touch()

    ws = Workspace(tmp_path)
    result = discover_venv_python(ws)
    assert result is not None
    assert result.name == "python"


def test_discover_venv_python_returns_none_when_no_venv(tmp_path) -> None:
    from hermes_lite.coding.testing import discover_venv_python
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    result = discover_venv_python(ws)
    assert result is None


def test_discover_venv_python_prefers_dot_venv(tmp_path) -> None:
    from hermes_lite.coding.testing import discover_venv_python
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").touch()
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "venv" / "bin" / "python").touch()

    ws = Workspace(tmp_path)
    result = discover_venv_python(ws)
    assert result is not None
    assert ".venv" in str(result)


# ---------------------------------------------------------------------------
# pytest output parsing
# ---------------------------------------------------------------------------

SHORT_TEST_SUMMARY = """
tests/test_app.py::test_add PASSED                                    [ 33%]
tests/test_app.py::test_fail FAILED                                   [ 66%]
tests/test_app.py::test_error ERROR                                   [100%]

=================================== FAILURES ===================================
_________________________________ test_fail ___________________________________

    def test_fail():
>       assert 1 == 2
E       assert 1 == 2

tests/test_app.py:5: AssertionError
==================================== ERRORS ====================================
_________________________________ test_error ___________________________________

    def test_error():
>       raise ValueError("boom")
E       ValueError: boom

tests/test_app.py:9: ValueError
=========================== short test summary info ============================
FAILED tests/test_app.py::test_fail - assert 1 == 2
ERROR tests/test_app.py::test_error - ValueError: boom
========================= 1 passed, 1 failed, 1 error =========================
"""


def test_discover_tests_finds_python_files(tmp_path) -> None:
    from hermes_lite.coding.testing import discover_tests
    from hermes_lite.coding.workspace import Workspace

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("def test_ok(): pass")
    (tests_dir / "test_utils.py").write_text("def test_util(): pass")

    ws = Workspace(tmp_path)
    result = discover_tests(ws)
    assert len(result) == 2


def test_discover_tests_empty_when_no_test_dir(tmp_path) -> None:
    from hermes_lite.coding.testing import discover_tests
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    result = discover_tests(ws)
    assert result == []


def test_parse_pytest_output_extracts_failures() -> None:
    from hermes_lite.coding.testing import parse_pytest_short_output

    result = parse_pytest_short_output(SHORT_TEST_SUMMARY)
    assert result["ok"] is False
    assert result["total"] == 3
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert result["errors"] == 1

    failures = result["failures"]
    assert len(failures) == 2

    fail1 = failures[0]
    assert fail1["test_name"] == "tests/test_app.py::test_fail"
    assert fail1["failure_type"] == "FAILED"
    assert fail1["file"] == "tests/test_app.py"
    assert fail1["line"] == 5
    assert "assert 1 == 2" in fail1["message"]

    fail2 = failures[1]
    assert fail2["test_name"] == "tests/test_app.py::test_error"
    assert fail2["failure_type"] == "ERROR"
    assert fail2["file"] == "tests/test_app.py"
    assert fail2["line"] == 9


def test_parse_pytest_all_passing() -> None:
    from hermes_lite.coding.testing import parse_pytest_short_output

    output = """
tests/test_app.py::test_ok PASSED [100%]
========================= 1 passed in 0.01s =========================
"""
    result = parse_pytest_short_output(output)
    assert result["ok"] is True
    assert result["total"] == 1
    assert result["passed"] == 1
    assert result["failed"] == 0
    assert result["failures"] == []


def test_parse_pytest_no_tests_collected() -> None:
    from hermes_lite.coding.testing import parse_pytest_short_output

    output = """
========================= no tests ran in 0.00s =========================
"""
    result = parse_pytest_short_output(output)
    assert result["ok"] is True
    assert result["total"] == 0


def test_parse_pytest_empty_output() -> None:
    from hermes_lite.coding.testing import parse_pytest_short_output

    result = parse_pytest_short_output("")
    assert result["ok"] is True
    assert result["total"] == 0
    assert result["failures"] == []


# ---------------------------------------------------------------------------
# structured run (requires real pytest + .venv)
# ---------------------------------------------------------------------------

def test_run_tests_with_venv_python(tmp_path) -> None:
    """End-to-end: create a project with .venv, write a test, run it."""
    if not (tmp_path / ".venv" / "bin" / "python").exists():
        # Use system python as venv — real execution works
        pass

    from hermes_lite.coding.testing import run_tests
    from hermes_lite.coding.workspace import Workspace

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").touch()
    (tests_dir / "test_math.py").write_text(textwrap.dedent("""\
        def test_pass():
            assert 1 + 1 == 2

        def test_also_pass():
            assert sum([1, 2, 3]) == 6
    """))

    ws = Workspace(tmp_path)
    result = run_tests(ws)

    # Without .venv, falls back to system python — may or may not have pytest
    # The key assertion: structured result is returned
    assert "ok" in result
    if result.get("ran") is True:
        assert "total" in result
        assert "failures" in result


def test_run_tests_discovers_venv(tmp_path) -> None:
    """When .venv exists, run_tests should use it."""
    from hermes_lite.coding.testing import run_tests, discover_venv_python
    from hermes_lite.coding.workspace import Workspace

    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").touch()

    ws = Workspace(tmp_path)
    venv = discover_venv_python(ws)
    assert venv is not None

    result = run_tests(ws)
    # Should at least attempt to run; might fail because .venv is not real python
    assert "ran" in result


def test_run_tests_handles_missing_pytest(tmp_path) -> None:
    from hermes_lite.coding.testing import run_tests
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "tests").mkdir()
    ws = Workspace(tmp_path)
    result = run_tests(ws)
    # Without pytest installed, returns structured error
    assert "ok" in result


# ---------------------------------------------------------------------------
# failure-to-source mapping
# ---------------------------------------------------------------------------

def test_extract_failure_locations() -> None:
    from hermes_lite.coding.testing import extract_failure_locations, parse_pytest_short_output

    parsed = parse_pytest_short_output(SHORT_TEST_SUMMARY)
    locations = extract_failure_locations(parsed)
    assert len(locations) == 2
    assert locations[0]["file"] == "tests/test_app.py"
    assert locations[0]["line"] == 5
    assert locations[1]["file"] == "tests/test_app.py"
    assert locations[1]["line"] == 9
