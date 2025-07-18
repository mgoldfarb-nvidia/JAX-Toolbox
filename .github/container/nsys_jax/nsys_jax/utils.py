from dataclasses import dataclass
import os
import pandas as pd  # type: ignore
import pathlib
from typing import Optional

pd.options.mode.copy_on_write = True


def default_data_prefix() -> pathlib.Path:
    """
    Default path for profiler data. This is particularly useful for Jupyter notebooks,
    which make it awkward to arrange for a sensible default working directory.
    """
    return pathlib.Path(os.environ.get("NSYS_JAX_DEFAULT_PREFIX", "."))


@dataclass
class ProfilerData:
    """
    Collection of profile data frames, as returned by load_profiler_data.
    """

    communication: Optional[pd.DataFrame] = None
    compile: Optional[pd.DataFrame] = None
    module: Optional[pd.DataFrame] = None
    thunk: Optional[pd.DataFrame] = None


def make_child_mask(df: pd.DataFrame, parent_row: int) -> pd.Series:
    """
    Return a mask of descendants of the given range.
    """
    return df["RangeStack"].str.startswith(df.loc[parent_row, "RangeStack"] + ":")


def remove_child_ranges(df: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    """
    Return a new data frame with the children of ``df[mask]`` removed.

    This can be useful to erase excessive detail from a compilation trace, or make sure
    that a certain class of operation is accounted for as a higher-level concept (e.g.
    autotuning compilation) instead of as lower-level operations (emitting IR,
    optimizing IR, ...).
    """
    to_remove: Optional[pd.Series] = None
    mask &= df["NumChild"] != 0
    for row in df[mask].itertuples():
        child_mask = make_child_mask(df, row.Index)
        to_remove = child_mask if to_remove is None else child_mask | to_remove
        df.loc[row.Index, ["NumChild", "DurChildMs"]] = 0
        df.loc[row.Index, "DurNonChildMs"] = row.DurMs
    return df if to_remove is None else df[~to_remove]


def remove_autotuning_detail(
    data: ProfilerData,
    *,
    compilation: bool = True,
    measurement: bool = True,
    module_frame: bool = True,
    thunk_frame: bool = True,
) -> ProfilerData:
    """
    Remove excessive detail originating from the autotuner, returning a cleaner
    ProfilerData dataclass:
    - module and thunk frames lose ProgramId == "unknown" executions
    - compile frame loses granular detail within autotuner compilation and measurement
    """
    # Ignore autotuning executions with ProgramId == "unknown"
    if module_frame and data.module is not None and len(data.module):
        data.module = data.module[
            data.module.index.get_level_values("ProgramId") != "unknown"
        ]
    if thunk_frame and data.thunk is not None and len(data.thunk):
        data.thunk = data.thunk[
            data.thunk.index.get_level_values("ProgramId") != "unknown"
        ]
    if measurement and data.compile is not None and len(data.compile):
        # Removing child ranges of XlaAutotunerMeasurement ranges. The GEMM fusion
        # autotuner creates small modules/thunks when measuring, which emit XlaModule
        # and XlaThunk ranges
        mask = data.compile["Name"].str.startswith("XlaAutotunerMeasurement")
        # Erase the name of the op being autotuned
        data.compile.loc[mask, "Name"] = "XlaAutotunerMeasurement"
        data.compile = remove_child_ranges(data.compile, mask)
    if compilation and data.compile is not None and len(data.compile):
        # Remove the detail of the constituent parts (EmitLlvmIr etc.) of autotuner
        # compilation
        data.compile = remove_child_ranges(
            data.compile, data.compile["Name"] == "XlaAutotunerCompilation"
        )
    return data
