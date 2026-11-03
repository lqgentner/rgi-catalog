"""Tests for lossless typing."""

from __future__ import annotations

import pandas as pd
import pytest

from rgi_catalog.dtypes import LossyCastError, narrow_int, to_bool, to_timestamp


def test_narrow_int_rejects_overflow() -> None:
    with pytest.raises(LossyCastError):
        narrow_int(pd.Series([1, 300]), "uint8")


def test_narrow_int_rejects_fractions() -> None:
    with pytest.raises(LossyCastError):
        narrow_int(pd.Series([1.0, 2.5]), "uint8")


def test_narrow_int_keeps_values() -> None:
    out = narrow_int(pd.Series([0, 7, 255]), "uint8")
    assert str(out.dtype) == "uint8"
    assert out.tolist() == [0, 7, 255]


def test_narrow_int_accepts_integral_floats() -> None:
    out = narrow_int(pd.Series([1.0, 8.0]), "uint8")
    assert out.tolist() == [1, 8]


def test_narrow_int_keeps_nulls_in_nullable_dtype() -> None:
    out = narrow_int(pd.Series([1.0, None]), "UInt16")
    assert str(out.dtype) == "UInt16"
    assert out.iloc[0] == 1
    assert pd.isna(out.iloc[1])


def test_to_bool_requires_zero_or_one() -> None:
    assert to_bool(pd.Series([0, 1])).tolist() == [False, True]
    with pytest.raises(LossyCastError):
        to_bool(pd.Series([0, 2]))


def test_to_timestamp_microseconds() -> None:
    out = to_timestamp(pd.Series(["2003-08-13T00:00:00", None]))
    assert str(out.dtype) == "datetime64[us]"
    assert out.iloc[0] == pd.Timestamp("2003-08-13")
    assert pd.isna(out.iloc[1])
    with pytest.raises(LossyCastError):
        to_timestamp(pd.Series(["not a date"]))
