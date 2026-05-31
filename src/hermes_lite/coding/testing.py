"""Structured test runner with .venv discovery and pytest output parsing.

Produces machine-readable failure reports so an LLM agent can locate, fix,
and re-run failing tests in a tight feedback loop.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from hermes_lite.coding.workspace import Workspace


# ---------------------------------------------------------------------------
# .venv discovery
# ---------------------------------------------------------------------------

_VENV_CANDIDATES = [
    ".venv/bin/python",
    ".venv/bin/python3",
    "venv/bin/python",
    "venv/bin/python3",
]


def discover_venv_python(workspace: Workspace) -> Path | None:
    """Return the path to a virtualenv python inside *workspace*, or ``None``."""
    for rel in _VENV_CANDIDATES:
        candidate = workspace.root / rel
        if candidate.exists():
            return candidate
    return None


def _python_exe(workspace: Workspace) -> str:
    """Return the best python to use for the workspace.

    Priority: .venv > venv > python3 (system) > sys.executable (agent's python)
    """
    venv = discover_venv_python(workspace)
    if venv:
        return str(venv)
    # Fall back to system python3, then the python running the agent
    import shutil
    for candidate in ("python3", "python"):
        if shutil.which(candidate):
            return candidate
    import sys
    return sys.executable


# ---------------------------------------------------------------------------
# test discovery
# ---------------------------------------------------------------------------

_TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")


def discover_tests(workspace: Workspace) -> list[str]:
    """Find test files in the workspace."""
    found: list[str] = []
    for search_dir in ("tests", "test"):
        d = workspace.root / search_dir
        if not d.is_dir():
            continue
        for pattern in _TEST_FILE_PATTERNS:
            for match in sorted(d.rglob(pattern)):
                rel = match.relative_to(workspace.root)
                found.append(str(rel))
    # Also look for conftest.py
    for loc in ("tests/conftest.py", "test/conftest.py", "conftest.py"):
        if (workspace.root / loc).exists():
            if loc not in found:
                found.append(loc)
    return found


# ---------------------------------------------------------------------------
# pytest output parsing
# ---------------------------------------------------------------------------

_FAILURE_HEADER = re.compile(r"^_+\s+(.+?)\s+_+$")
_TRACEBACK_LINE = re.compile(r"^(.+?):(\d+):\s+(.+)$")
_SUMMARY_LINE = re.compile(
    r"^(?:FAILED|ERROR)\s+(\S+)\s+-\s+(.+)$"
)
_COUNTS = re.compile(r"(\d+)\s+(passed|failed|error|skipped|warning)", re.IGNORECASE)


def parse_pytest_short_output(output: str) -> dict[str, Any]:
    """Parse pytest short-summary output into structured results."""
    failures: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    errors = 0
    skipped = 0

    lines = output.splitlines()
    in_failures = False
    in_errors = False
    current_section: str | None = None
    current_name: str | None = None
    current_file: str | None = None
    current_line: int | None = None
    current_messages: list[str] = []

    def _flush() -> None:
        nonlocal current_name, current_file, current_line, current_messages
        if current_name and current_section:
            failures.append({
                "test_name": current_name,
                "failure_type": current_section.upper(),
                "file": current_file or "",
                "line": current_line or 0,
                "message": "\n".join(current_messages).strip(),
            })
        current_name = None
        current_file = None
        current_line = None
        current_messages = []

    for line in lines:
        if "== FAILURES ==" in line:
            in_failures = True
            in_errors = False
            _flush()
            continue
        if "== ERRORS ==" in line:
            in_errors = True
            in_failures = False
            _flush()
            continue
        if line.startswith("==") and ("short test summary" in line or "passed" in line.lower()):
            in_failures = False
            in_errors = False
            _flush()
            continue

        if not in_failures and not in_errors:
            continue

        # Match failure header: ________ test_name ________
        mh = _FAILURE_HEADER.match(line.strip())
        if mh:
            _flush()
            current_name = mh.group(1).strip()
            current_section = "FAILED" if in_failures else "ERROR"
            continue

        # Match traceback location: file:line: error
        mt = _TRACEBACK_LINE.match(line.strip())
        if mt and current_name and current_file is None:
            current_file = mt.group(1)
            try:
                current_line = int(mt.group(2))
            except ValueError:
                current_line = None
            current_messages.append(mt.group(3))
            continue

        if current_name:
            current_messages.append(line.strip())

    _flush()

    # Enrich test names from summary lines (which have full qualified names)
    for line in lines:
        ms = _SUMMARY_LINE.match(line.strip())
        if ms:
            qualified = ms.group(1)
            # Try to match by unqualified name (last :: part)
            simple_name = qualified.rsplit("::", 1)[-1] if "::" in qualified else qualified
            for f in failures:
                if f["test_name"] == simple_name:
                    f["test_name"] = qualified
                    break

    # Try count from summary footer
    m = re.search(r"(\d+)\s+passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", output)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+)\s+error", output)
    if m:
        errors = int(m.group(1))
    m = re.search(r"(\d+)\s+skipped", output)
    if m:
        skipped = int(m.group(1))

    total = passed + failed + errors + skipped

    ok = (failed == 0 and errors == 0)

    return {
        "ok": ok,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "failures": failures,
        "raw": output[:4000],
    }


# ---------------------------------------------------------------------------
# test execution
# ---------------------------------------------------------------------------

def run_tests(
    workspace: Workspace,
    *,
    path: str = "",
    extra_args: list[str] | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """Run tests in the workspace and return structured results.

    Parameters
    ----------
    workspace:
        The workspace to run tests in.
    path:
        Optional sub-path to restrict test discovery.
    extra_args:
        Additional pytest arguments (e.g. ``["-x", "--tb=long"]``).
    timeout:
        Maximum seconds before killing the test run.

    Returns
    -------
    Structured dict with ``ran``, ``ok``, ``total``, ``passed``, ``failed``,
    ``errors``, ``failures``, ``raw``, and ``runner`` keys.
    """
    python_exe = _python_exe(workspace)
    args = [python_exe, "-m", "pytest", "-p", "no:cacheprovider"]

    if path:
        args.append(path)
    if extra_args:
        args.extend(extra_args)

    # Always add short traceback for parsing
    if "--tb" not in str(args):
        args.append("--tb=short")

    try:
        proc = subprocess.run(
            args,
            cwd=workspace.root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        combined = stdout + "\n" + stderr

        parsed = parse_pytest_short_output(combined)
        parsed["ran"] = True
        parsed["runner"] = "pytest"
        parsed["exit_code"] = proc.returncode
        parsed["command"] = " ".join(args)
        parsed["python_used"] = python_exe
        return parsed
    except FileNotFoundError:
        return {
            "ran": False,
            "ok": False,
            "error": "pytest_not_found",
            "message": f"pytest is not installed for python: {python_exe}",
            "runner": "pytest",
            "python_used": python_exe,
        }
    except subprocess.TimeoutExpired:
        return {
            "ran": False,
            "ok": False,
            "error": "timeout",
            "message": f"Tests timed out after {timeout}s",
            "runner": "pytest",
        }
    except Exception as exc:
        return {
            "ran": False,
            "ok": False,
            "error": "execution_error",
            "message": str(exc),
            "runner": "pytest",
        }


# ---------------------------------------------------------------------------
# failure-to-source mapping
# ---------------------------------------------------------------------------

def extract_failure_locations(parsed_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract file:line locations from a parsed pytest result.

    Each entry has ``file``, ``line``, ``test_name``, ``failure_type``, and
    ``message`` — exactly what an LLM needs to locate and fix a failure.
    """
    locations: list[dict[str, Any]] = []
    for f in parsed_result.get("failures", []):
        if f.get("file") and f.get("line"):
            locations.append({
                "file": f["file"],
                "line": f["line"],
                "test_name": f.get("test_name", ""),
                "failure_type": f.get("failure_type", ""),
                "message": f.get("message", ""),
            })
    return locations


_TRACEBACK_FILE_RE = re.compile(
    r'^\s*File "(.+?)", line (\d+), in (\S+)'
)
_TRACEBACK_ASSERT_RE = re.compile(r"^\s*(?:> )?(.+?Error|AssertionError):?\s*(.*)")


def debug_error(
    workspace: Workspace,
    traceback_text: str,
    *,
    context_lines: int = 5,
) -> dict[str, Any]:
    """Parse a traceback string and return source context around each frame.

    For each ``File "...", line N, in <name>`` frame, reads *context_lines*
    before and after the referenced line.  Also extracts the final error type
    and message.

    Returns
    -------
    ``{ok, frames: [{file, line, function, context}], error_type, error_message}``
    """
    frames: list[dict[str, Any]] = []
    error_type = ""
    error_message = ""

    for line in traceback_text.splitlines():
        m = _TRACEBACK_FILE_RE.search(line)
        if m:
            fpath = m.group(1)
            lineno = int(m.group(2))
            func = m.group(3)
            # Read source context
            src_path = workspace.root / fpath
            context = ""
            if src_path.exists():
                try:
                    src_lines = src_path.read_text(encoding="utf-8").splitlines()
                    start = max(0, lineno - context_lines - 1)
                    end = min(len(src_lines), lineno + context_lines)
                    context = "\n".join(
                        f"{i + 1}: {src_lines[i]}"
                        for i in range(start, end)
                    )
                except (OSError, UnicodeDecodeError):
                    context = f"(could not read {fpath})"
            else:
                context = f"(could not read {fpath})"
            frames.append({
                "file": fpath,
                "line": lineno,
                "function": func,
                "context": context[:2000],
            })
            continue
        ma = _TRACEBACK_ASSERT_RE.match(line)
        if ma:
            error_type = ma.group(1)
            error_message = ma.group(2)
            continue

    return {
        "ok": True,
        "frames": frames,
        "frame_count": len(frames),
        "error_type": error_type,
        "error_message": error_message,
    }
