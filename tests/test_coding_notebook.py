"""Tests for Jupyter notebook editing."""
from __future__ import annotations

import json


def test_notebook_read_cell_returns_source(tmp_path) -> None:
    from hermes_lite.coding.notebook import notebook_read_cell

    nb_path = tmp_path / "test.ipynb"
    nb = {
        "cells": [
            {"cell_type": "code", "source": ["print(1)\n", "print(2)\n"], "metadata": {}, "outputs": []},
            {"cell_type": "markdown", "source": ["# Title\n"], "metadata": {}},
        ],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    }
    nb_path.write_text(json.dumps(nb))

    result = notebook_read_cell(str(nb_path), 0)
    assert result["ok"] is True
    assert result["cell_type"] == "code"
    assert "print(1)" in result["source"]


def test_notebook_read_cell_out_of_range(tmp_path) -> None:
    from hermes_lite.coding.notebook import notebook_read_cell

    nb_path = tmp_path / "test.ipynb"
    nb_path.write_text(json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))

    result = notebook_read_cell(str(nb_path), 0)
    assert result["ok"] is False
    assert result["error"] == "cell_index_out_of_range"


def test_notebook_read_cell_not_found(tmp_path) -> None:
    from hermes_lite.coding.notebook import notebook_read_cell

    result = notebook_read_cell(str(tmp_path / "missing.ipynb"), 0)
    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_notebook_read_all_cells(tmp_path) -> None:
    from hermes_lite.coding.notebook import notebook_read_all_cells

    nb_path = tmp_path / "test.ipynb"
    nb = {
        "cells": [
            {"cell_type": "code", "source": ["1\n"], "metadata": {}, "outputs": []},
            {"cell_type": "markdown", "source": ["# Hi\n"], "metadata": {}},
        ],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    }
    nb_path.write_text(json.dumps(nb))

    result = notebook_read_all_cells(str(nb_path))
    assert result["ok"] is True
    assert result["total"] == 2


def test_notebook_edit_cell_replaces_source(tmp_path) -> None:
    from hermes_lite.coding.notebook import notebook_read_cell, notebook_edit_cell

    nb_path = tmp_path / "test.ipynb"
    nb = {
        "cells": [
            {"cell_type": "code", "source": ["old\n"], "metadata": {}, "outputs": []},
        ],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    }
    nb_path.write_text(json.dumps(nb))

    result = notebook_edit_cell(str(nb_path), 0, "new\n", cell_type="markdown")
    assert result["ok"] is True

    # Verify
    cell = notebook_read_cell(str(nb_path), 0)
    assert "new" in cell["source"]
    assert cell["cell_type"] == "markdown"


def test_notebook_insert_cell(tmp_path) -> None:
    from hermes_lite.coding.notebook import notebook_insert_cell, notebook_read_all_cells

    nb_path = tmp_path / "test.ipynb"
    nb = {
        "cells": [
            {"cell_type": "code", "source": ["1\n"], "metadata": {}, "outputs": []},
        ],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    }
    nb_path.write_text(json.dumps(nb))

    result = notebook_insert_cell(str(nb_path), 0, "inserted\n", cell_type="markdown")
    assert result["ok"] is True

    all_cells = notebook_read_all_cells(str(nb_path))
    assert all_cells["total"] == 2
    assert all_cells["cells"][0]["cell_type"] == "markdown"


def test_notebook_delete_cell(tmp_path) -> None:
    from hermes_lite.coding.notebook import notebook_delete_cell, notebook_read_all_cells

    nb_path = tmp_path / "test.ipynb"
    nb = {
        "cells": [
            {"cell_type": "code", "source": ["1\n"], "metadata": {}, "outputs": []},
            {"cell_type": "code", "source": ["2\n"], "metadata": {}, "outputs": []},
        ],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    }
    nb_path.write_text(json.dumps(nb))

    result = notebook_delete_cell(str(nb_path), 0)
    assert result["ok"] is True
    assert "deleted_source" in result

    all_cells = notebook_read_all_cells(str(nb_path))
    assert all_cells["total"] == 1


def test_notebook_not_a_notebook(tmp_path) -> None:
    from hermes_lite.coding.notebook import notebook_read_cell

    py_path = tmp_path / "test.py"
    py_path.write_text("x = 1")

    result = notebook_read_cell(str(py_path), 0)
    assert result["ok"] is False
    assert result["error"] == "not_a_notebook"
