"""
System tests for data contract validation
Tests the pandera schema enforcement for budget and actual cost records
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dqd.legacy.contract import validate_data_contract, get_contract_specification, CostRecordSchema


class TestDataContract:
    """Test suite for data contract validation"""
    
    @pytest.fixture
    def valid_data(self):
        """Create valid test data"""
        return pd.DataFrame({
            "project_id": ["PROJ001", "PROJ002", "PROJ003"],
            "time_period": ["Week-1", "Week-2", "Week-3"],
            "pmb_budget": [100000.0, 150000.0, 200000.0],
            "actual_cost": [95000.0, 145000.0, 180000.0],
            "progress_pct": [45.0, 50.0, 55.0],
            "revenue_claimed": [90000.0, 140000.0, 170000.0],
            "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01"])
        })
    
    @pytest.fixture
    def invalid_data_missing_fields(self):
        """Create data with missing required fields"""
        return pd.DataFrame({
            "project_id": ["PROJ001", None, "PROJ003"],
            "time_period": ["Week-1", "Week-2", "Week-3"],
            "pmb_budget": [100000.0, 150000.0, 200000.0],
            "actual_cost": [95000.0, 145000.0, 180000.0],
            "progress_pct": [45.0, 50.0, 55.0],
            "revenue_claimed": [90000.0, 140000.0, 170000.0],
            "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01"])
        })
    
    @pytest.fixture
    def invalid_data_negative_values(self):
        """Create data with negative budget values"""
        return pd.DataFrame({
            "project_id": ["PROJ001", "PROJ002", "PROJ003"],
            "time_period": ["Week-1", "Week-2", "Week-3"],
            "pmb_budget": [100000.0, -50000.0, 200000.0],
            "actual_cost": [95000.0, 145000.0, 180000.0],
            "progress_pct": [45.0, 50.0, 55.0],
            "revenue_claimed": [90000.0, 140000.0, 170000.0],
            "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01"])
        })
    
    @pytest.fixture
    def invalid_data_progress_out_of_range(self):
        """Create data with progress percentage out of valid range"""
        return pd.DataFrame({
            "project_id": ["PROJ001", "PROJ002", "PROJ003"],
            "time_period": ["Week-1", "Week-2", "Week-3"],
            "pmb_budget": [100000.0, 150000.0, 200000.0],
            "actual_cost": [95000.0, 145000.0, 180000.0],
            "progress_pct": [45.0, 150.0, 55.0],  # 150% is invalid
            "revenue_claimed": [90000.0, 140000.0, 170000.0],
            "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01"])
        })
    
    def test_valid_data_passes_contract(self, valid_data):
        """Test that valid data passes data contract validation"""
        is_valid, validated_df, errors = validate_data_contract(valid_data)
        assert is_valid is True
        assert len(errors) == 0
        assert len(validated_df) == len(valid_data)
    
    def test_missing_fields_fails_contract(self, invalid_data_missing_fields):
        """Test that data with missing fields fails data contract validation"""
        is_valid, validated_df, errors = validate_data_contract(invalid_data_missing_fields)
        assert is_valid is False
        assert len(errors) > 0
    
    def test_negative_values_fails_contract(self, invalid_data_negative_values):
        """Test that data with negative values fails data contract validation"""
        is_valid, validated_df, errors = validate_data_contract(invalid_data_negative_values)
        assert is_valid is False
        assert len(errors) > 0
    
    def test_progress_out_of_range_fails_contract(self, invalid_data_progress_out_of_range):
        """Test that progress percentage out of range fails validation"""
        is_valid, validated_df, errors = validate_data_contract(invalid_data_progress_out_of_range)
        assert is_valid is False
        assert len(errors) > 0
    
    def test_contract_specification_structure(self):
        """Test that contract specification has correct structure"""
        spec = get_contract_specification()
        
        assert "required_fields" in spec
        assert "field_types" in spec
        assert "field_constraints" in spec
        assert "logical_constraints" in spec
        
        assert len(spec["required_fields"]) == 8
        assert "project_id" in spec["required_fields"]
        assert "pmb_budget" in spec["required_fields"]
    
    def test_boundary_zero_values(self):
        """Test boundary case: zero values should be valid for budget/cost"""
        boundary_data = pd.DataFrame({
            "project_id": ["PROJ001"],
            "time_period": ["Week-1"],
            "pmb_budget": [0.0],  # Zero should be valid
            "actual_cost": [0.0],  # Zero should be valid
            "progress_pct": [0.0],  # Zero should be valid
            "revenue_claimed": [0.0],  # Zero should be valid
            "actual_date": pd.to_datetime(["2024-01-15"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01"])
        })
        
        is_valid, validated_df, errors = validate_data_contract(boundary_data)
        assert is_valid is True
    
    def test_boundary_max_progress(self):
        """Test boundary case: 100% progress should be valid"""
        boundary_data = pd.DataFrame({
            "project_id": ["PROJ001"],
            "time_period": ["Week-1"],
            "pmb_budget": [100000.0],
            "actual_cost": [100000.0],
            "progress_pct": [100.0],  # 100% should be valid
            "revenue_claimed": [100000.0],
            "actual_date": pd.to_datetime(["2024-01-15"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01"])
        })
        
        is_valid, validated_df, errors = validate_data_contract(boundary_data)
        assert is_valid is True
    
    def test_empty_dataframe(self):
        """Test handling of empty dataframe"""
        empty_data = pd.DataFrame(columns=[
            "project_id", "time_period", "pmb_budget", "actual_cost",
            "progress_pct", "revenue_claimed", "actual_date", "baseline_start_date"
        ])
        
        is_valid, validated_df, errors = validate_data_contract(empty_data)
        # Empty dataframe should pass structural validation
        assert len(validated_df) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])