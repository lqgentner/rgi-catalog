"""Lossless typing of upstream columns.

Every cast here checks that it changes no value, and raises
:class:`LossyCastError` otherwise. Floats are never cast: they stay float64.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Integer, boolean and date columns of the G and C attribute tables. Text
# columns stay text, and float columns stay float64. The I table has no such
# column: its length_m is a float, unlike the L table's.
UPSTREAM_DTYPES: dict[str, str] = {
    "anlys_id": "uint32",
    "subm_id": "uint16",
    "src_date": "timestamp",
    "utm_zone": "uint8",
    "is_rgi6": "bool",
    "primeclass": "uint8",
    "conn_lvl": "uint8",
    "surge_type": "uint8",
    "term_type": "uint8",
    "aspect_sec": "uint8",
    "lmax_m": "uint32",
}
# Integer and boolean columns of the L attribute table.
CENTERLINE_DTYPES: dict[str, str] = {
    "segment_id": "uint8",
    "is_main": "bool",
    "outflow_id": "int8",
    "strahler_n": "uint8",
    "length_m": "uint32",
}


class LossyCastError(Exception):
    """A cast would change at least one value."""


def narrow_int(s: pd.Series, dtype: str) -> pd.Series:
    """Cast to a narrower integer type, refusing any change of value.

    Parameters
    ----------
    s
        Integer values, or floats that hold integers. Nulls need a nullable
        ``dtype`` such as ``"UInt16"``.
    dtype
        The target pandas dtype name.

    Returns
    -------
    pd.Series
        The cast series.

    Raises
    ------
    LossyCastError
        If a value does not round-trip.
    """
    try:
        out = s.astype(pd.api.types.pandas_dtype(dtype))
    except (ValueError, TypeError, OverflowError) as exc:
        msg = f"{s.name}: cannot cast to {dtype} ({exc})"
        raise LossyCastError(msg) from exc
    present = s.notna()
    if (out.isna() != ~present).any():
        msg = f"{s.name}: cast to {dtype} changes which values are null"
        raise LossyCastError(msg)
    back = out[present].astype("float64").to_numpy()
    if not np.array_equal(back, s[present].astype("float64").to_numpy()):
        msg = f"{s.name}: cast to {dtype} changes values"
        raise LossyCastError(msg)
    return out


def to_bool(s: pd.Series) -> pd.Series:
    """Cast 0/1 integers to booleans.

    Parameters
    ----------
    s
        Values that are each 0 or 1.

    Returns
    -------
    pd.Series
        Booleans.

    Raises
    ------
    LossyCastError
        If a value is not 0 or 1.
    """
    if not s.isin([0, 1]).all():
        msg = f"{s.name}: values other than 0 and 1"
        raise LossyCastError(msg)
    return s.astype(bool)


def to_timestamp(s: pd.Series) -> pd.Series:
    """Parse ISO 8601 text to ``datetime64[us]``.

    Parameters
    ----------
    s
        Text such as ``"2003-08-13T00:00:00"``, or nulls.

    Returns
    -------
    pd.Series
        Timestamps without a time zone.

    Raises
    ------
    LossyCastError
        If a non-null value does not parse, or does not format back to itself.
    """
    out = pd.to_datetime(s, format="ISO8601", errors="coerce").astype("datetime64[us]")
    present = s.notna()
    if out[present].isna().any():
        msg = f"{s.name}: values that do not parse as dates"
        raise LossyCastError(msg)
    back = out[present].dt.strftime("%Y-%m-%dT%H:%M:%S")
    if not (back.to_numpy() == s[present].to_numpy()).all():
        msg = f"{s.name}: dates that do not format back to the published text"
        raise LossyCastError(msg)
    return out


def type_upstream(df: pd.DataFrame, dtypes: dict[str, str] = UPSTREAM_DTYPES) -> pd.DataFrame:
    """Apply a dtype table to the columns that ``df`` has.

    Parameters
    ----------
    df
        An upstream attribute table.
    dtypes
        The target dtype by column: :data:`UPSTREAM_DTYPES` or
        :data:`CENTERLINE_DTYPES`.

    Returns
    -------
    pd.DataFrame
        A typed copy.
    """
    out = df.copy()
    for column, dtype in dtypes.items():
        if column not in out.columns:
            continue
        if dtype == "bool":
            out[column] = to_bool(out[column])
        elif dtype == "timestamp":
            out[column] = to_timestamp(out[column])
        else:
            out[column] = narrow_int(out[column], dtype)
    return out
