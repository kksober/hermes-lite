"""Tests for enhanced editing: unified diff, multi-hunk, dry-run, conflict detection."""

from __future__ import annotations


# ---------------------------------------------------------------------------
# parse_unified_diff
# ---------------------------------------------------------------------------


def test_parse_unified_diff_single_hunk() -> None:
    from hermes_lite.coding.patches import parse_unified_diff

    diff = """--- a/app.py
+++ b/app.py
@@ -1,3 +1,3 @@
 def hello():
-    print("old")
+    print("new")
     return True
"""

    parsed = parse_unified_diff(diff)
    assert parsed is not None
    assert parsed.old_path == "app.py"
    assert parsed.new_path == "app.py"
    assert len(parsed.hunks) == 1
    assert parsed.hunks[0].old_start == 1
    assert parsed.hunks[0].old_count == 3
    assert parsed.hunks[0].new_count == 3


def test_parse_unified_diff_multi_hunk() -> None:
    from hermes_lite.coding.patches import parse_unified_diff

    diff = """--- a/app.py
+++ b/app.py
@@ -1,4 +1,4 @@
 line1
-line2
+line2_modified
 line3
 line4
@@ -10,3 +10,3 @@
 line10
-line11
+line11_new
 line12
"""

    parsed = parse_unified_diff(diff)
    assert parsed is not None
    assert len(parsed.hunks) == 2
    assert parsed.hunks[0].old_start == 1
    assert parsed.hunks[1].old_start == 10


def test_parse_unified_diff_no_newline_marker() -> None:
    from hermes_lite.coding.patches import parse_unified_diff

    diff = r"""--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-old
+new
\ No newline at end of file
"""
    parsed = parse_unified_diff(diff)
    assert parsed is not None
    assert len(parsed.hunks) == 1


def test_parse_unified_diff_rejects_garbage() -> None:
    from hermes_lite.coding.patches import parse_unified_diff

    assert parse_unified_diff("garbage") is None
    assert parse_unified_diff("") is None


def test_parse_unified_diff_strips_git_prefix() -> None:
    from hermes_lite.coding.patches import parse_unified_diff

    diff = """--- a/src/app.py
+++ b/src/app.py
@@ -1,1 +1,1 @@
-old
+new
"""
    parsed = parse_unified_diff(diff)
    assert parsed is not None
    assert parsed.old_path == "src/app.py"


# ---------------------------------------------------------------------------
# apply_unified_diff
# ---------------------------------------------------------------------------


def test_apply_unified_diff_simple(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_unified_diff
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("print('old')\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    diff = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-print('old')
+print('new')
"""
    result = apply_unified_diff(ws, "app.py", diff)
    assert result["ok"] is True
    assert result["hunks_applied"] == 1
    assert (tmp_path / "app.py").read_text() == "print('new')\n"


def test_apply_unified_diff_multi_hunk(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_unified_diff
    from hermes_lite.coding.workspace import Workspace

    content = "line1\nline2\nline3\nline4\nline5\nline6\n"
    (tmp_path / "app.py").write_text(content, encoding="utf-8")
    ws = Workspace(tmp_path)

    diff = """--- a/app.py
+++ b/app.py
@@ -1,3 +1,3 @@
 line1
-line2
+line2_new
 line3
@@ -5,2 +5,2 @@
 line5
-line6
+line6_new
"""
    result = apply_unified_diff(ws, "app.py", diff)
    assert result["ok"] is True
    assert result["hunks_applied"] == 2
    new_content = (tmp_path / "app.py").read_text()
    assert "line2_new" in new_content
    assert "line6_new" in new_content
    assert "line2\n" not in new_content


def test_apply_unified_diff_add_lines(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_unified_diff
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("def run():\n    pass\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    diff = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,4 @@
 def run():
+    \"\"\"Docstring.\"\"\"
+    print("running")
     pass
"""
    result = apply_unified_diff(ws, "app.py", diff)
    assert result["ok"] is True
    new_content = (tmp_path / "app.py").read_text()
    assert "Docstring" in new_content
    assert 'print("running")' in new_content


def test_apply_unified_diff_remove_lines(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_unified_diff
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("debug=1\nreal=2\nlog=3\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    diff = """--- a/app.py
+++ b/app.py
@@ -1,3 +1,2 @@
-debug=1
 real=2
 log=3
"""
    result = apply_unified_diff(ws, "app.py", diff)
    assert result["ok"] is True
    new_content = (tmp_path / "app.py").read_text()
    assert "debug=1" not in new_content
    assert "real=2" in new_content


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def test_apply_unified_diff_dry_run_does_not_write(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_unified_diff
    from hermes_lite.coding.workspace import Workspace

    original = "print('old')\n"
    (tmp_path / "app.py").write_text(original, encoding="utf-8")
    ws = Workspace(tmp_path)

    diff = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-print('old')
+print('new')
"""
    result = apply_unified_diff(ws, "app.py", diff, dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert "patch_preview" in result
    # file must be unchanged
    assert (tmp_path / "app.py").read_text() == original


def test_patch_dry_run_detects_conflict(tmp_path) -> None:
    from hermes_lite.coding.patches import patch_dry_run
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("totally different content\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    diff = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-print('old')
+print('new')
"""
    result = patch_dry_run(ws, "app.py", diff)
    assert result["ok"] is False
    assert result["error"] == "patch_conflict"


# ---------------------------------------------------------------------------
# conflict detection
# ---------------------------------------------------------------------------


def test_apply_unified_diff_reports_conflict(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_unified_diff
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("wrong content here\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    diff = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-something else entirely
+replacement
"""
    result = apply_unified_diff(ws, "app.py", diff)
    assert result["ok"] is False
    assert result["error"] == "patch_conflict"
    assert len(result["conflicts"]) > 0


def test_apply_unified_diff_partial_success(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_unified_diff
    from hermes_lite.coding.workspace import Workspace

    content = "header\nbody\ntrailer\n"
    (tmp_path / "app.py").write_text(content, encoding="utf-8")
    ws = Workspace(tmp_path)

    diff = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
 header
@@ -99,1 +99,1 @@
-missing
+found
"""
    result = apply_unified_diff(ws, "app.py", diff)
    assert result["ok"] is False
    assert result["error"] == "patch_conflict"
    assert result["hunks_applied"] >= 0


def test_apply_unified_diff_fuzzy_match(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_unified_diff
    from hermes_lite.coding.workspace import Workspace

    # Content shifted by 1 line
    (tmp_path / "app.py").write_text("# comment\nprint('old')\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    diff = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-print('old')
+print('new')
"""
    result = apply_unified_diff(ws, "app.py", diff, fuzzy=2)
    assert result["ok"] is True
    new_content = (tmp_path / "app.py").read_text()
    assert "print('new')" in new_content


# ---------------------------------------------------------------------------
# diff_summary
# ---------------------------------------------------------------------------


def test_diff_summary_counts_changes(tmp_path) -> None:
    from hermes_lite.coding.patches import diff_summary
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    old = "line1\nline2_old\nline3\n"
    result = diff_summary(ws, "app.py", old_content=old)

    assert result["ok"] is True
    assert "lines_added" in result
    assert "lines_removed" in result


def test_diff_summary_no_old_content(tmp_path) -> None:
    from hermes_lite.coding.patches import diff_summary
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("content\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    result = diff_summary(ws, "app.py")
    assert result["ok"] is True
    assert "No old content" in result["message"]


# ---------------------------------------------------------------------------
# apply_text_patch (backward compat)
# ---------------------------------------------------------------------------


def test_apply_text_patch_still_works(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_text_patch
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("print('old')\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    result = apply_text_patch(ws, "app.py", "old", "new")
    assert result["ok"] is True
    assert (tmp_path / "app.py").read_text() == "print('new')\n"


def test_apply_text_patch_replace_all(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_text_patch
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("old old old\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    result = apply_text_patch(ws, "app.py", "old", "new", replace_all=True)
    assert result["ok"] is True
    assert (tmp_path / "app.py").read_text() == "new new new\n"
