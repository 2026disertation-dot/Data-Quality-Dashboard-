"""
Download the Project Portfolio Dataset from Kaggle and extract its cost data.

The Kaggle dataset ``gacevedob/project-portfolio-dataset`` ships 16 workbooks in
two distinct families:

* ``EDM - <portfolio> - <code> - <name>.xlsx`` (8 files) are schedule-only
  Primavera P6 time-phased exports.  Their daily columns hold *duration*
  spreads (fractions of a day and day counts) and they contain no monetary
  values at all, so they cannot supply budget / actual cost figures.
* ``<portfolio> - <code> <name>.xlsx`` (8 files) are the financial models.  Each
  one carries a ``Portfolio WBS`` sheet holding a full earned value management
  (EVM) time-phase: the budget at completion (BAC) and, for every reporting
  month, the cumulative planned value (PV), actual cost (AC) and earned value
  (EV), alongside planned/actual quantities (PQ/AQ).  A companion
  ``Budget & Revenue`` sheet holds the tender budget and the revenue claimed
  against each claim.

This module resolves the dataset (downloading it with ``kagglehub`` when it is
not already cached, or accepting a local directory), selects the eight
financial workbooks and reads their EVM time-phase into a tidy long-format
DataFrame.  All business logic that turns those cumulative figures into the
dashboard's data contract lives in ``clean_kaggle_data.py``.

Output columns (one row per project x month x WBS code)::

    project_id, project_name, source_file, wbs_code, wbs_description,
    period_date, period_index, pv_cum, ac_cum, ev_cum

Usage::

    python download_kaggle_data.py
    python download_kaggle_data.py --output data/kaggle_original_data.csv
    python download_kaggle_data.py --local-dir C:/some/where/the/files/are
"""

import argparse
import glob
import os
import re
import warnings

import pandas as pd

# Kaggle dataset reference
DEFAULT_DATASET = "gacevedob/project-portfolio-dataset"

# Name of the sheet carrying the EVM time-phase inside the financial workbooks
FINANCE_SHEET = "Portfolio WBS"

# Filename prefix used by the schedule-only workbooks (no monetary values)
SCHEDULE_ONLY_PREFIX = "EDM - "

# Column labels that make up one monthly EVM block, in sheet order.
# The sheet repeats this block once per reporting month.
EVM_LABELS = ("PQ", "PV", "AQ", "AC", "EV")

# The same labels normalised to lower case, used as keys in a parsed block
EVM_KEYS = tuple(label.lower() for label in EVM_LABELS)

# Prefix marking the first column ("PQ") of a block
BLOCK_START_LABEL = "PQ"

# How many leading rows to scan when locating the EVM header row
HEADER_SCAN_ROWS = 8

# Default location for the extracted (still cumulative) source data
DEFAULT_OUTPUT = os.path.join("data", "kaggle_original_data.csv")

# Columns produced by this module
LONG_FORMAT_COLUMNS = [
    "project_id",
    "project_name",
    "source_file",
    "wbs_code",
    "wbs_description",
    "period_date",
    "period_index",
    "pv_cum",
    "ac_cum",
    "ev_cum",
]


# --------------------------------------------------------------------------- #
# Workbook / dataset resolution
# --------------------------------------------------------------------------- #
def project_code_from_filename(filename):
    """
    Extract the project code from a workbook filename.

    The financial workbooks are named ``<portfolio> - <code> <name>.xlsx``, for
    example ``P018 - P01 Airport Carpark.xlsx``.  The *second* code is the
    project itself (P01); the first one is the parent portfolio (P018).

    Args:
        filename: Workbook filename or full path.

    Returns:
        str | None: The project code (e.g. ``"P01"``) or None if not found.
    """
    stem = os.path.splitext(os.path.basename(str(filename)))[0]
    match = re.search(r"-\s*(P\d{1,3})\b", stem)
    if match:
        return match.group(1)
    fallback = re.search(r"\b(P\d{1,3})\b", stem)
    return fallback.group(1) if fallback else None


def project_name_from_filename(filename):
    """
    Derive a human readable project name from a workbook filename.

    ``P018 - P01 Airport Carpark.xlsx`` becomes ``Airport Carpark``.
    """
    stem = os.path.splitext(os.path.basename(str(filename)))[0]
    match = re.search(r"-\s*P\d{1,3}\s+(.*)", stem)
    if match:
        return match.group(1).strip()
    return re.sub(r"\bP\d{1,3}\b", "", stem).strip(" -_") or stem


def resolve_finance_sheet(sheet_names):
    """
    Find the EVM sheet name, tolerating small naming differences.

    Args:
        sheet_names: Sheet names available in the workbook.

    Returns:
        str | None: The matched sheet name, or None when absent.
    """
    for name in sheet_names:
        if str(name).strip().lower() == FINANCE_SHEET.lower():
            return name
    for name in sheet_names:
        if "wbs" in str(name).strip().lower():
            return name
    return None


def is_finance_workbook(path):
    """
    Report whether a workbook contains the financial (EVM) sheets.

    Schedule-only workbooks are rejected, as they hold duration data with no
    monetary values.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            workbook = pd.ExcelFile(path)
            try:
                sheet_names = workbook.sheet_names
            finally:
                workbook.close()
    except Exception:
        return False
    return resolve_finance_sheet(sheet_names) is not None


def discover_workbooks(directory):
    """
    Split the workbooks in a dataset directory into financial and schedule-only.

    Args:
        directory: Directory holding the downloaded Kaggle dataset.

    Returns:
        tuple: ``(finance_paths, skipped)`` where ``finance_paths`` is a sorted
        list of workbooks carrying EVM data and ``skipped`` is a list of
        ``(filename, reason)`` tuples for the ones that were ignored.
    """
    finance_paths, skipped = [], []
    for path in sorted(glob.glob(os.path.join(directory, "*.xlsx"))):
        filename = os.path.basename(path)
        if filename.startswith(SCHEDULE_ONLY_PREFIX) and not is_finance_workbook(path):
            skipped.append((filename, "schedule-only export (no monetary values)"))
        elif is_finance_workbook(path):
            finance_paths.append(path)
        else:
            skipped.append((filename, "no EVM sheet found"))
    return finance_paths, skipped


def resolve_dataset_directory(dataset=DEFAULT_DATASET, local_dir=None):
    """
    Resolve the directory that contains the downloaded dataset.

    Resolution order:

    1. An explicitly supplied ``local_dir``.
    2. The ``KAGGLE_DATA_DIR`` environment variable.
    3. A fresh/cached download performed with ``kagglehub``.

    Args:
        dataset: Kaggle dataset reference, e.g. ``owner/name``.
        local_dir: Optional local directory to read from instead of downloading.

    Returns:
        str | None: The dataset directory, or None when it cannot be resolved.
    """
    candidates = []
    if local_dir:
        candidates.append(local_dir)
    env_dir = os.environ.get("KAGGLE_DATA_DIR")
    if env_dir:
        candidates.append(env_dir)

    for candidate in candidates:
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)

    try:
        import kagglehub
    except ImportError:
        print("ERROR: kagglehub is not installed - run: pip install kagglehub")
        return None

    try:
        print(f"Downloading {dataset} from Kaggle...")
        path = kagglehub.dataset_download(dataset)
        print(f"Dataset available at: {path}")
        return os.path.abspath(path)
    except Exception as exc:  # pragma: no cover - network / auth failure
        print(f"ERROR: could not download the dataset: {exc}")
        print("  Set KAGGLE_DATA_DIR or pass --local-dir to use an existing copy.")
        return None


# --------------------------------------------------------------------------- #
# EVM sheet parsing
# --------------------------------------------------------------------------- #
def find_label_row(df, max_scan=HEADER_SCAN_ROWS):
    """
    Locate the row holding the EVM column labels (PQ/PV/AQ/AC/EV).

    Args:
        df: Raw sheet read with ``header=None``.
        max_scan: How many leading rows to inspect.

    Returns:
        int | None: Index of the label row, or None when it cannot be found.
    """
    for row in range(min(max_scan, len(df))):
        labels = {
            str(df.iat[row, col]).strip().upper()
            for col in range(df.shape[1])
            if pd.notna(df.iat[row, col])
        }
        if BLOCK_START_LABEL in labels and "PV" in labels:
            return row
    return None


def find_evm_blocks(df, label_row):
    """
    Group the EVM columns into one block per reporting month.

    Each block maps a label (``pq``/``pv``/``aq``/``ac``/``ev``) to its column
    index and starts at every ``PQ`` column.  Blocks with a partial label set
    are still returned so that the available measures can be used.

    Args:
        df: Raw sheet read with ``header=None``.
        label_row: Row index returned by :func:`find_label_row`.

    Returns:
        list[dict]: One mapping of label -> column index per month.
    """
    blocks = []
    current = None
    for col in range(df.shape[1]):
        value = df.iat[label_row, col]
        label = str(value).strip().upper() if pd.notna(value) else ""
        if label == BLOCK_START_LABEL:
            if current:
                blocks.append(current)
            current = {"pq": col}
        elif current is not None and label in EVM_LABELS:
            current[label.lower()] = col
    if current:
        blocks.append(current)
    return blocks


def find_wbs_rows(df, label_row):
    """
    Identify the rows that hold one Portfolio WBS line each.

    A data row has a numeric WBS code in the first column and a non-empty
    description that is not a totals line.

    Args:
        df: Raw sheet read with ``header=None``.
        label_row: Index of the EVM label row; header rows are skipped.

    Returns:
        list[int]: Row indices of the WBS data rows.
    """
    rows = []
    for row in range(label_row + 1, len(df)):
        code = df.iat[row, 0]
        description = df.iat[row, 1]
        code_ok = isinstance(code, (int, float)) or (
            isinstance(code, str) and code.strip().isdigit()
        )
        description_ok = (
            isinstance(description, str)
            and description.strip() != ""
            and "total" not in description.lower()
        )
        if code_ok and description_ok:
            rows.append(row)
    return rows


def coerce_date(value):
    """
    Coerce a cell into a Timestamp.

    Handles real datetimes and Excel serial numbers (some workbooks store the
    month headers as bare serials).  Returns None when the value is not a date.
    """
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        serial = float(value)
        if 20000 < serial < 60000:  # 1954-01-01 .. 2064-04-08
            return pd.Timestamp("1899-12-30") + pd.Timedelta(days=serial)
        return None
    if hasattr(value, "year") and hasattr(value, "month"):
        return pd.Timestamp(value)
    try:
        return pd.to_datetime(value)
    except Exception:
        return None


def coerce_number(value):
    """
    Coerce a cell into a float, returning None for blanks / non-numeric text.
    """
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def find_block_period(df, block, label_row):
    """
    Find the reporting month a block belongs to.

    The month header sits in one of the rows above the label row, inside the
    block's own columns.

    Args:
        df: Raw sheet read with ``header=None``.
        block: Block mapping returned by :func:`find_evm_blocks`.
        label_row: Index of the EVM label row.

    Returns:
        pd.Timestamp | None: The month start date, or None when absent.
    """
    columns = [block[key] for key in EVM_KEYS if key in block]
    for row in range(0, label_row + 1):
        for col in columns:
            date = coerce_date(df.iat[row, col])
            if date is not None:
                return date
    return None


def read_evm_workbook(path):
    """
    Read one financial workbook into a tidy long-format EVM DataFrame.

    Args:
        path: Path to the workbook.

    Returns:
        pd.DataFrame: Long-format frame using :data:`LONG_FORMAT_COLUMNS`.

    Raises:
        ValueError: If the workbook has no EVM sheet, no EVM header row or no
            usable reporting months.
    """
    filename = os.path.basename(path)
    project_id = project_code_from_filename(path)
    if project_id is None:
        raise ValueError(f"{filename}: no project code could be parsed from the filename")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workbook = pd.ExcelFile(path)
        try:
            sheet = resolve_finance_sheet(workbook.sheet_names)
            if sheet is None:
                raise ValueError(f"{filename}: no '{FINANCE_SHEET}' sheet found")
            df = pd.read_excel(workbook, sheet_name=sheet, header=None)
        finally:
            workbook.close()

    label_row = find_label_row(df)
    if label_row is None:
        raise ValueError(f"{filename}: no EVM header row (PQ/PV/AQ/AC/EV) found")

    blocks = find_evm_blocks(df, label_row)
    wbs_rows = find_wbs_rows(df, label_row)
    if not blocks:
        raise ValueError(f"{filename}: no monthly EVM blocks found")
    if not wbs_rows:
        raise ValueError(f"{filename}: no Portfolio WBS data rows found")

    project_name = project_name_from_filename(path)
    records = []
    previous_date = None

    for index, block in enumerate(blocks, start=1):
        period_date = find_block_period(df, block, label_row)
        if period_date is None:
            # The month header is missing for this block: keep the series
            # continuous by advancing one month from the previous period.
            period_date = (
                previous_date + pd.offsets.MonthBegin(1)
                if previous_date is not None
                else pd.Timestamp("2011-01-01")
            )
        previous_date = period_date

        for row in wbs_rows:
            pv = coerce_number(df.iat[row, block["pv"]]) if "pv" in block else None
            ac = coerce_number(df.iat[row, block["ac"]]) if "ac" in block else None
            ev = coerce_number(df.iat[row, block["ev"]]) if "ev" in block else None

            # A line with no monetary value at all is not a cost record.
            if pv is None and ac is None and ev is None:
                continue

            records.append(
                {
                    "project_id": project_id,
                    "project_name": project_name,
                    "source_file": filename,
                    "wbs_code": str(df.iat[row, 0]).strip(),
                    "wbs_description": str(df.iat[row, 1]).strip(),
                    "period_date": period_date,
                    "period_index": index,
                    "pv_cum": pv if pv is not None else 0.0,
                    "ac_cum": ac if ac is not None else 0.0,
                    "ev_cum": ev if ev is not None else 0.0,
                }
            )

    if not records:
        raise ValueError(f"{filename}: the EVM blocks contained no monetary records")

    return pd.DataFrame.from_records(records, columns=LONG_FORMAT_COLUMNS)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def download_and_format_dataset(dataset=DEFAULT_DATASET, local_dir=None, output=DEFAULT_OUTPUT):
    """
    Resolve the Kaggle dataset and extract its EVM cost data.

    Args:
        dataset: Kaggle dataset reference.
        local_dir: Optional local copy of the dataset to use instead of downloading.
        output: CSV path for the extracted long-format data. Pass None to skip writing.

    Returns:
        pd.DataFrame | None: Long-format EVM frame, or None on failure.
    """
    directory = resolve_dataset_directory(dataset, local_dir)
    if directory is None:
        return None

    print(f"Dataset directory: {directory}")

    finance_paths, skipped = discover_workbooks(directory)
    print(f"\nFinancial workbooks with EVM data: {len(finance_paths)}")
    for path in finance_paths:
        print(f"  [use] {os.path.basename(path)}")
    if skipped:
        print(f"\nSkipped {len(skipped)} workbook(s):")
        for filename, reason in skipped:
            print(f"  [skip] {filename} - {reason}")

    if not finance_paths:
        print("ERROR: no financial workbooks found - cannot build cost data.")
        return None

    frames = []
    for path in finance_paths:
        try:
            frame = read_evm_workbook(path)
        except Exception as exc:
            print(f"  [fail] {os.path.basename(path)}: {exc}")
            continue
        print(
            f"  [ok]   {os.path.basename(path)}: "
            f"{frame['period_index'].nunique()} month(s), {frame['wbs_code'].nunique()} WBS line(s)"
        )
        frames.append(frame)

    if not frames:
        print("ERROR: no EVM data could be read from any workbook.")
        return None

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(
        ["project_id", "period_index", "wbs_code"]
    ).reset_index(drop=True)

    print(
        f"\nExtracted {len(combined)} cumulative EVM records "
        f"across {combined['project_id'].nunique()} project(s)."
    )

    if output:
        output_dir = os.path.dirname(output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        combined.to_csv(output, index=False)
        print(f"Saved cumulative source data to {output}")
        print("Next: python clean_kaggle_data.py")

    return combined


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(
        description="Download the Kaggle Project Portfolio Dataset and extract its EVM cost data."
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Kaggle dataset reference")
    parser.add_argument(
        "--local-dir",
        default=None,
        help="Read the dataset from this local directory instead of downloading it",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output CSV path ('' to skip)")
    args = parser.parse_args()

    df = download_and_format_dataset(
        dataset=args.dataset,
        local_dir=args.local_dir,
        output=args.output or None,
    )

    if df is None:
        print("\nExtraction failed. Fix the problem above and run the script again.")
        return 1

    print("\nPreview:")
    print(df.head())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
