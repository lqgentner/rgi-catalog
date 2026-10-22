"""Run every SQL recipe in the published documentation against a base URL.

Set ``RGI_QUERY_BASE`` to the root that serves the catalog and its data: the
local preview (``http://localhost:8000``) before upload, or the public base
after it. A recipe must run without error and return at least one row, unless
the line before its fence is ``<!-- expect-empty -->``.
"""

from __future__ import annotations

import os
import re

import duckdb
import pytest
import yaml

from rgi_catalog.paths import CATALOG, METADATA

PUBLIC_BASE = yaml.safe_load((METADATA / "catalog.yaml").read_text())["public_base"]
FENCE = re.compile(r"(<!-- expect-empty -->\n)?```sql\n(.*?)```", re.DOTALL)
BASE = os.environ.get("RGI_QUERY_BASE", "").rstrip("/")


def _recipes() -> list[tuple[str, str, bool]]:
    out = []
    for doc in sorted([*CATALOG.rglob("AGENTS.md"), *CATALOG.rglob("README.md")]):
        for i, match in enumerate(FENCE.finditer(doc.read_text())):
            out.append((f"{doc.relative_to(CATALOG)}#{i}", match.group(2), bool(match.group(1))))
    return out


RECIPES = _recipes()


def test_documentation_has_recipes() -> None:
    assert len(RECIPES) >= 5


@pytest.mark.skipif(not BASE, reason="set RGI_QUERY_BASE")
@pytest.mark.parametrize(
    ("sql", "empty"), [(r[1], r[2]) for r in RECIPES], ids=[r[0] for r in RECIPES]
)
def test_documented_query_runs(sql: str, empty: bool) -> None:
    con = duckdb.connect()
    con.sql("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    rows = con.sql(sql.replace(PUBLIC_BASE, BASE)).fetchall()
    if not empty:
        assert rows, "the recipe returned no rows"
