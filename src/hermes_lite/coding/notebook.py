"""Jupyter notebook (.ipynb) editing — based on nbformat."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_notebook(path: str) -> dict[str, object]:
    """Read a notebook file, returning parsed JSON or error."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "not_found", "path": path}
    if p.suffix != ".ipynb":
        return {"ok": False, "error": "not_a_notebook", "path": path}
    try:
        nb = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "invalid_json", "detail": str(exc)}
    return {"ok": True, "notebook": nb, "path": str(p.resolve())}


def _write_notebook(path: str, nb: dict) -> dict[str, object]:
    try:
        Path(path).write_text(json.dumps(nb, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": "write_failed", "detail": str(exc)}


def notebook_read_cell(path: str, cell_index: int) -> dict[str, object]:
    """Read a single cell from a notebook by index (0-based)."""
    nb_result = _read_notebook(path)
    if not nb_result["ok"]:
        return nb_result
    nb = nb_result["notebook"]  # type: ignore[index]
    cells = nb.get("cells", [])
    if cell_index < 0 or cell_index >= len(cells):
        return {"ok": False, "error": "cell_index_out_of_range", "total_cells": len(cells)}
    cell = cells[cell_index]
    return {
        "ok": True,
        "cell_index": cell_index,
        "cell_type": cell.get("cell_type", "code"),
        "source": "".join(cell.get("source", [])),
        "metadata": cell.get("metadata", {}),
        "total_cells": len(cells),
    }


def notebook_read_all_cells(path: str) -> dict[str, object]:
    """Read all cells with their sources."""
    nb_result = _read_notebook(path)
    if not nb_result["ok"]:
        return nb_result
    nb = nb_result["notebook"]  # type: ignore[index]
    cells = []
    for i, cell in enumerate(nb.get("cells", [])):
        cells.append({
            "cell_index": i,
            "cell_type": cell.get("cell_type", "code"),
            "source": "".join(cell.get("source", [])),
            "execution_count": cell.get("execution_count"),
        })
    return {"ok": True, "cells": cells, "total": len(cells)}


def notebook_edit_cell(path: str, cell_index: int, source: str, *, cell_type: str = "code") -> dict[str, object]:
    """Replace the source of a cell."""
    nb_result = _read_notebook(path)
    if not nb_result["ok"]:
        return nb_result
    nb = nb_result["notebook"]  # type: ignore[index]
    cells = nb.get("cells", [])
    if cell_index < 0 or cell_index >= len(cells):
        return {"ok": False, "error": "cell_index_out_of_range", "total_cells": len(cells)}
    cells[cell_index]["source"] = source.splitlines(True)
    if cell_type:
        cells[cell_index]["cell_type"] = cell_type
    return _write_notebook(path, nb)


def notebook_insert_cell(path: str, cell_index: int, source: str, *, cell_type: str = "code") -> dict[str, object]:
    """Insert a new cell at the given index."""
    nb_result = _read_notebook(path)
    if not nb_result["ok"]:
        return nb_result
    nb = nb_result["notebook"]  # type: ignore[index]
    cells = nb.get("cells", [])
    if cell_index < 0 or cell_index > len(cells):
        return {"ok": False, "error": "cell_index_out_of_range", "total_cells": len(cells)}
    new_cell = {
        "cell_type": cell_type,
        "metadata": {},
        "source": source.splitlines(True),
    }
    if cell_type == "code":
        new_cell["outputs"] = []
        new_cell["execution_count"] = None
    cells.insert(cell_index, new_cell)
    return _write_notebook(path, nb)


def notebook_delete_cell(path: str, cell_index: int) -> dict[str, object]:
    """Delete a cell by index."""
    nb_result = _read_notebook(path)
    if not nb_result["ok"]:
        return nb_result
    nb = nb_result["notebook"]  # type: ignore[index]
    cells = nb.get("cells", [])
    if cell_index < 0 or cell_index >= len(cells):
        return {"ok": False, "error": "cell_index_out_of_range", "total_cells": len(cells)}
    deleted = cells.pop(cell_index)
    result = _write_notebook(path, nb)
    if result.get("ok"):
        result["deleted_cell_type"] = deleted.get("cell_type", "code")
        result["deleted_source"] = "".join(deleted.get("source", []))[:500]
    return result
