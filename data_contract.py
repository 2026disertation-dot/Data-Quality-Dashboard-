"""
Data Contract Schema for Budget and Actual Cost Records
Defines formal validation rules using pandera for multi-project cost data
"""

import pandera as pa
from pandera import Column, DataFrameSchema, Check
from datetime import datetime
import pandas as pd
from pandera.typing import Series
import pandera.pandas as ppa


class CostRecordSchema(ppa.DataFrameModel):
    """
    Data contract schema for budget (PMB) and actual cost records.
    Enforces data quality dimensions: accuracy, completeness, consistency, integrity
    """
    
    # Project identifier - must be non-null string
    project_id: Series[str] = pa.Field(
        nullable=False,
        coerce=True,
        description="Unique identifier for the project"
    )
    
    # Time period - must be non-null string (e.g., "Week-1", "Week-2")
    time_period: Series[str] = pa.Field(
        nullable=False,
        coerce=True,
        description="Reporting period identifier"
    )
    
    # Performance Measurement Baseline (PMB) budget
    pmb_budget: Series[float] = pa.Field(
        nullable=False,
        coerce=True,
        ge=0,  # Must be non-negative
        description="Planned budget value for the period"
    )
    
    # Actual cost incurred
    actual_cost: Series[float] = pa.Field(
        nullable=False,
        coerce=True,
        ge=0,  # Must be non-negative
        description="Actual cost incurred for the period"
    )
    
    # Progress percentage
    progress_pct: Series[float] = pa.Field(
        nullable=False,
        coerce=True,
        ge=0,  # Minimum 0%
        le=100,  # Maximum 100%
        description="Physical progress percentage"
    )
    
    # Revenue claimed
    revenue_claimed: Series[float] = pa.Field(
        nullable=False,
        coerce=True,
        ge=0,  # Must be non-negative
        description="Revenue claimed for the period"
    )
    
    # Actual cost date
    actual_date: Series = pa.Field(
        nullable=False,
        coerce=True,
        description="Date when actual cost was recorded"
    )
    
    # Baseline start date
    baseline_start_date: Series = pa.Field(
        nullable=False,
        coerce=True,
        description="Project baseline start date"
    )
    
    class Config:
        """Configuration for the schema"""
        strict = True  # Enforce that no extra columns are present
        coerce = True  # Automatically coerce types
        drop_invalid_rows = False  # Keep invalid rows for reporting


# Legacy DataFrameSchema for backward compatibility
data_contract = DataFrameSchema({
    "project_id": Column(str, required=True, coerce=True, nullable=False),
    "time_period": Column(str, required=True, coerce=True, nullable=False),
    "pmb_budget": Column(float, Check.ge(0), required=True, coerce=True, nullable=False),
    "actual_cost": Column(float, Check.ge(0), required=True, coerce=True, nullable=False),
    "progress_pct": Column(float, [Check.ge(0), Check.le(100)], required=True, coerce=True, nullable=False),
    "revenue_claimed": Column(float, Check.ge(0), required=True, coerce=True, nullable=False),
    "actual_date": Column("datetime64[ns]", required=True, coerce=True, nullable=False),
    "baseline_start_date": Column("datetime64[ns]", required=True, coerce=True, nullable=False),
})


def _describe_schema_failure(error) -> list:
    """
    Turn a pandera validation failure into readable messages.

    Args:
        error: A ``SchemaError`` (single failure) or ``SchemaErrors`` (several).

    Returns:
        list[str]: One message per failing record/column.
    """
    failure_cases = getattr(error, "failure_cases", None)
    if failure_cases is None:
        return [str(error)]

    try:
        cases = list(failure_cases.itertuples())
    except AttributeError:
        return [str(error)]

    messages = []
    for case in cases:
        column = getattr(case, "column", None)
        check = getattr(case, "check", None)
        value = getattr(case, "failure_case", None)
        if column is None:
            continue
        messages.append(f"{column}: failed '{check}' (value: {value!r})")
    return messages or [str(error)]


def validate_data_contract(df: pd.DataFrame) -> tuple:
    """
    Validate a DataFrame against the data contract schema.
    
    Args:
        df: Input DataFrame to validate
        
    Returns:
        tuple: (is_valid, validated_df, error_messages)
    """
    try:
        validated_df = CostRecordSchema.validate(df)
        return True, validated_df, []
    except (pa.errors.SchemaError, pa.errors.SchemaErrors) as e:
        # pandera raises SchemaError for a single failure but SchemaErrors
        # (which is *not* a subclass of it) when several columns fail at once.
        # Both have to be handled, otherwise malformed data raises out of this
        # function instead of being reported.
        error_messages = _describe_schema_failure(e)
        return False, df, error_messages


def get_contract_specification():
    """
    Get the data contract specification as a dictionary.
    Useful for documentation and UI display.
    
    Returns:
        dict: Contract specification with field details
    """
    return {
        "required_fields": [
            "project_id",
            "time_period", 
            "pmb_budget",
            "actual_cost",
            "progress_pct",
            "revenue_claimed",
            "actual_date",
            "baseline_start_date"
        ],
        "field_types": {
            "project_id": "string",
            "time_period": "string",
            "pmb_budget": "float",
            "actual_cost": "float",
            "progress_pct": "float",
            "revenue_claimed": "float",
            "actual_date": "datetime",
            "baseline_start_date": "datetime"
        },
        "field_constraints": {
            "pmb_budget": ">= 0",
            "actual_cost": ">= 0",
            "progress_pct": "0-100",
            "revenue_claimed": ">= 0"
        },
        "logical_constraints": [
            "actual_date must not precede baseline_start_date",
            "All required fields must be non-null",
            "Progress percentage must be between 0 and 100"
        ]
    }


if __name__ == "__main__":
    # Test the schema with sample data
    import pandas as pd
    
    # Valid sample data
    valid_data = pd.DataFrame({
        "project_id": ["PROJ001", "PROJ002"],
        "time_period": ["Week-1", "Week-2"],
        "pmb_budget": [100000.0, 150000.0],
        "actual_cost": [95000.0, 145000.0],
        "progress_pct": [45.0, 50.0],
        "revenue_claimed": [90000.0, 140000.0],
        "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22"]),
        "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01"])
    })
    
    # Test validation
    is_valid, validated_df, errors = validate_data_contract(valid_data)
    print(f"Validation result: {is_valid}")
    if errors:
        print(f"Errors: {errors}")
    else:
        print("Data contract validation passed!")
        print(validated_df)