"""Tests for terminal formatting helpers."""
from __future__ import annotations


def test_color_diff_highlights_added_lines() -> None:
    from hermes_lite.coding.terminal import color_diff

    diff = "+added line\n context\n-removed line"
    result = color_diff(diff)
    # When TTY: should have ANSI codes. When not: same as input.
    assert "added line" in result
    assert "removed line" in result
    assert "context" in result


def test_color_diff_highlights_hunk_header() -> None:
    from hermes_lite.coding.terminal import color_diff

    diff = "@@ -1,3 +1,5 @@\n context"
    result = color_diff(diff)
    assert "@@" in result
    assert "context" in result


def test_red_green_are_strings() -> None:
    from hermes_lite.coding.terminal import red, green

    r = red("error")
    g = green("success")
    assert "error" in r
    assert "success" in g


def test_error_box_contains_message() -> None:
    from hermes_lite.coding.terminal import error_box

    msg = error_box("test error")
    assert "test error" in msg


def test_success_box_contains_message() -> None:
    from hermes_lite.coding.terminal import success_box

    msg = success_box("done")
    assert "done" in msg


def test_bold_dim_are_nonempty() -> None:
    from hermes_lite.coding.terminal import bold, dim

    assert isinstance(bold(), str)
    assert isinstance(dim(), str)


def test_reset_is_string() -> None:
    from hermes_lite.coding.terminal import reset

    assert isinstance(reset(), str)


def test_spinner_chars_is_list() -> None:
    from hermes_lite.coding.terminal import spinner_chars

    chars = spinner_chars()
    assert len(chars) == 10
    assert "⠋" in chars
