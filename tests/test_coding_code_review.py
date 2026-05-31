"""Tests for structured code review."""
from __future__ import annotations


def test_review_checklist_to_dict() -> None:
    from hermes_lite.coding.subagents import ReviewChecklist

    cl = ReviewChecklist()
    d = cl.to_dict()
    assert "security" in d
    assert "correctness" in d
    assert "style" in d
    assert "tests" in d
    assert all(isinstance(v, list) for v in d.values())


def test_run_code_review_empty_diff() -> None:
    from hermes_lite.coding.subagents import run_code_review
    from hermes_lite.coding.workspace import Workspace
    from pathlib import Path
    import tempfile, os

    with tempfile.TemporaryDirectory() as td:
        ws = Workspace(Path(td))
        result = run_code_review("", ws)
        assert result["ok"] is True
        assert result["findings"] == []


def test_run_code_review_detects_os_system() -> None:
    from hermes_lite.coding.subagents import run_code_review
    from hermes_lite.coding.workspace import Workspace
    from pathlib import Path
    import tempfile

    diff = """@@ -1,0 +1,3 @@
+import os
+os.system("rm -rf /")
+print("done")
"""
    with tempfile.TemporaryDirectory() as td:
        ws = Workspace(Path(td))
        result = run_code_review(diff, ws)
        assert result["ok"] is True
        titles = [f["title"] for f in result["findings"]]
        assert "os.system" in titles


def test_run_code_review_detects_eval() -> None:
    from hermes_lite.coding.subagents import run_code_review
    from hermes_lite.coding.workspace import Workspace
    from pathlib import Path
    import tempfile

    diff = """@@ -1,0 +1,2 @@
+user_input = "2 + 2"
+result = eval(user_input)
"""
    with tempfile.TemporaryDirectory() as td:
        ws = Workspace(Path(td))
        result = run_code_review(diff, ws)
        titles = [f["title"] for f in result["findings"]]
        assert "eval()" in titles


def test_run_code_review_detects_hardcoded_password() -> None:
    from hermes_lite.coding.subagents import run_code_review
    from hermes_lite.coding.workspace import Workspace
    from pathlib import Path
    import tempfile

    diff = """@@ -1,0 +1,3 @@
+password = "admin123"
+api_key = "sk-1234abcd"
+connect()
"""
    with tempfile.TemporaryDirectory() as td:
        ws = Workspace(Path(td))
        result = run_code_review(diff, ws)
        titles = [f["title"] for f in result["findings"]]
        assert "hardcoded secret" in titles or "hardcoded key" in titles


def test_run_code_review_counts_by_severity() -> None:
    from hermes_lite.coding.subagents import run_code_review
    from hermes_lite.coding.workspace import Workspace
    from pathlib import Path
    import tempfile

    diff = """@@ -1,0 +1,5 @@
+import os, hashlib
+password = "secret"
+def risky():
+    os.system("rm -rf /")
+    hashlib.md5(b"weak")
"""
    with tempfile.TemporaryDirectory() as td:
        ws = Workspace(Path(td))
        result = run_code_review(diff, ws)
        assert "counts" in result
        c = result["counts"]
        assert c["total"] > 0
        assert c["high"] > 0


def test_run_code_review_severity_levels() -> None:
    from hermes_lite.coding.subagents import run_code_review
    from hermes_lite.coding.workspace import Workspace
    from pathlib import Path
    import tempfile

    diff = """@@ -1,0 +1,3 @@
+import os
+os.system("echo hi")  # high
+try: pass
+except: pass  # medium
"""
    with tempfile.TemporaryDirectory() as td:
        ws = Workspace(Path(td))
        result = run_code_review(diff, ws)
        severities = {f["severity"] for f in result["findings"]}
        assert "high" in severities


def test_run_code_review_no_false_positive_on_context_lines() -> None:
    from hermes_lite.coding.subagents import run_code_review
    from hermes_lite.coding.workspace import Workspace
    from pathlib import Path
    import tempfile

    # os.system only on context line (no +), should NOT be a finding
    diff = """@@ -1,3 +1,5 @@
 os.system("echo hi")
+print("added line")
"""
    with tempfile.TemporaryDirectory() as td:
        ws = Workspace(Path(td))
        result = run_code_review(diff, ws)
        titles = [f["title"] for f in result["findings"]]
        assert "os.system" not in titles


def test_extract_added_lines_parses_diff() -> None:
    from hermes_lite.coding.subagents import _extract_added_lines

    diff = """--- a/test.py
+++ b/test.py
@@ -1,0 +1,3 @@
+import os
+os.system("rm")
+print("done")
"""
    added = _extract_added_lines(diff)
    assert len(added) == 3
    assert added[0][1] == "import os"
