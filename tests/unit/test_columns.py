"""Tests for the comparison of columns.yaml with RGI's column text."""

from __future__ import annotations

from rgi_catalog.columns import CATEGORIES_IN_GUIDE, differences


def _meta(description: str, units: str = "") -> dict[str, str]:
    return {"description": description, "units": units}


def test_rgi_text_has_no_differences() -> None:
    upstream = {
        "area_km2": _meta("Area of the glacier.", "km2"),
        "term_type": _meta("Terminus type." + CATEGORIES_IN_GUIDE),
    }
    described = {
        "area_km2": {"description": "Area of the\n glacier.", "unit": "km2"},
        "term_type": {"description": "Terminus type."},
    }
    assert differences(described, upstream) == []


def test_reworded_and_missing_columns_differ() -> None:
    upstream = {
        "rgi_id": _meta("Unique identifier assigned to a single outline."),
        "area_km2": _meta("Area of the glacier.", "km2"),
        "zmin_m": _meta("Minimum elevation.", "m"),
    }
    described = {
        "rgi_id": {"description": "The identifier of the outline."},
        "area_km2": {"description": "Area of the glacier."},
    }
    assert differences(described, upstream) == [
        (
            "rgi_id",
            "description",
            "Unique identifier assigned to a single outline.",
            "The identifier of the outline.",
        ),
        ("area_km2", "unit", "km2", ""),
        ("zmin_m", "description", "Minimum elevation.", "(none)"),
    ]
