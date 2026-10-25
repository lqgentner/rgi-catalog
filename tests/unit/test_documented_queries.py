"""Run every SQL and Python recipe in the published documentation against a base URL.

Set ``RGI_QUERY_BASE`` to the root that serves the catalog and its data: the
local preview (``http://localhost:8000``) before upload, or the public base
after it. A recipe must run without error and return at least one row, unless
the line before its fence is ``<!-- expect-empty -->``. A Python recipe must
leave a non-empty GeoDataFrame in its namespace.
"""

from __future__ import annotations

import os
import re

import duckdb
import geopandas as gpd
import pytest
import yaml

from rgi_catalog.paths import CATALOG, METADATA

PUBLIC_BASE = yaml.safe_load((METADATA / "catalog.yaml").read_text())["public_base"]
FENCE = re.compile(r"(<!-- expect-empty -->\n)?```(sql|python)\n(.*?)```", re.DOTALL)
BASE = os.environ.get("RGI_QUERY_BASE", "").rstrip("/")


def _recipes() -> list[tuple[str, str, str, bool]]:
    out = []
    for doc in sorted([*CATALOG.rglob("AGENTS.md"), *CATALOG.rglob("README.md")]):
        for i, match in enumerate(FENCE.finditer(doc.read_text())):
            name = f"{doc.relative_to(CATALOG)}#{i}"
            out.append((name, match.group(2), match.group(3), bool(match.group(1))))
    return out


RECIPES = _recipes()


def test_documentation_has_recipes() -> None:
    assert len(RECIPES) >= 5


@pytest.mark.skipif(not BASE, reason="set RGI_QUERY_BASE")
@pytest.mark.parametrize(
    ("language", "code", "empty"),
    [(r[1], r[2], r[3]) for r in RECIPES],
    ids=[r[0] for r in RECIPES],
)
def test_documented_recipe_runs(language: str, code: str, empty: bool) -> None:
    code = code.replace(PUBLIC_BASE, BASE)
    if language == "python":
        namespace: dict[str, object] = {}
        exec(code, namespace)  # noqa: S102
        frames = [v for v in namespace.values() if isinstance(v, gpd.GeoDataFrame)]
        assert frames, "the recipe made no GeoDataFrame"
        if not empty:
            assert all(len(f) for f in frames), "the recipe returned no rows"
        return
    con = duckdb.connect()
    con.sql("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    rows = con.sql(code).fetchall()
    if not empty:
        assert rows, "the recipe returned no rows"
