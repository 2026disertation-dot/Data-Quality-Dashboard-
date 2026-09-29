"""
Data Processing Pipeline for Budget and Actual Cost Records
Supports both batch and incremental processing modes with integrated validation
"""

import pandas as pd
import numpy as np
from typing import Optional
from datetime import datetime
import json
import os

from data_contract import validate_data_contract, get_contract_specification
from validation_engine import ValidationEngine


class DataPipeline:
    """
    Data processing pipeline for multi-project cost records.
    Supports batch mode for historical data and incremental mode for real-time updates.
    """
    
    def __init__(self):
        """Initialize the data pipeline"""
        self.validation_engine = ValidationEngine()
        self.current_data = None
        self.validation_history = []
        self.pipeline_mode = "batch"  # Default mode
    
    def load_data(self, file_path: str, file_type: Optional[str] = None) -> pd.DataFrame:
        """
        Load data from various file formats.
        
        Args:
            file_path: Path to the data file
            file_type: File type ('csv', 'excel', 'json'). If None, inferred from extension
            
        Returns:
            pd.DataFrame: Loaded data
        """
        if file_type is None:
            file_type = file_path.split('.')[-1].lower()
        
        try:
            if file_type in ['csv']:
                df = pd.read_csv(file_path)
            elif file_type in ['xlsx', 'xls']:
                df = pd.read_excel(file_path)
            elif file_type in ['json']:
                df = pd.read_json(file_path)
            else:
                raise ValueError(f"Unsupported file type: {file_type}")
            
            # Standardize column names
            df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
            
            return df
        except Exception as e:
            raise ValueError(f"Error loading data: {str(e)}")
    
    def process_batch(self, df: pd.DataFrame) -> dict:
        """
        Process data in batch mode for historical analysis.
        
        Args:
            df: Input DataFrame
            
        Returns:
            dict: Processing results with validation and quality metrics
        """
        self.pipeline_mode = "batch"
        
        results = {
            "mode": "batch",
            "input_records": len(df),
            "timestamp": datetime.now().isoformat(),
            "data_contract_valid": False,
            "validation_results": None,
            "quality_metrics": None,
            "processed_data": None
        }
        
        # Step 1: Validate against data contract
        try:
            is_valid, validated_df, contract_errors = validate_data_contract(df)
            results["data_contract_valid"] = is_valid
            results["contract_errors"] = contract_errors
            
            if not is_valid:
                # Try to fix common issues
                validated_df = self._fix_common_issues(df)
                is_valid, validated_df, contract_errors = validate_data_contract(validated_df)
                results["data_contract_valid"] = is_valid
                results["contract_errors"] = contract_errors
            
            if is_valid:
                df = validated_df
        except Exception as e:
            results["contract_errors"] = [f"Data contract validation failed: {str(e)}"]
            # Continue with original data for validation engine
        
        # Step 2: Run validation engine
        validation_results = self.validation_engine.validate_batch(df)
        results["validation_results"] = validation_results
        
        # Step 3: Calculate quality metrics
        quality_metrics = self._calculate_quality_metrics(df, validation_results)
        results["quality_metrics"] = quality_metrics
        
        # Step 4: Store processed data
        self.current_data = df
        results["processed_data"] = df
        
        # Step 5: Store validation history
        self.validation_history.append({
            "timestamp": results["timestamp"],
            "mode": "batch",
            "records_processed": len(df),
            "quality_score": quality_metrics["overall_score"]
        })
        
        return results
    
    def process_incremental(self, new_records: pd.DataFrame) -> dict:
        """
        Process new records in incremental mode for real-time updates.
        
        Args:
            new_records: New records to process
            
        Returns:
            dict: Processing results with validation and quality metrics
        """
        self.pipeline_mode = "incremental"
        
        # ``input_records`` is the key batch mode uses; ``new_records`` is kept
        # as an alias so both modes expose a consistent set of names.
        results = {
            "mode": "incremental",
            "input_records": len(new_records),
            "new_records": len(new_records),
            "timestamp": datetime.now().isoformat(),
            "data_contract_valid": False,
            "validation_results": None,
            "quality_metrics": None,
            "processed_data": None
        }
        
        # Step 1: Validate against data contract
        try:
            is_valid, validated_df, contract_errors = validate_data_contract(new_records)
            results["data_contract_valid"] = is_valid
            results["contract_errors"] = contract_errors
            
            if not is_valid:
                # Try to fix common issues
                validated_df = self._fix_common_issues(new_records)
                is_valid, validated_df, contract_errors = validate_data_contract(validated_df)
                results["data_contract_valid"] = is_valid
                results["contract_errors"] = contract_errors
            
            if is_valid:
                new_records = validated_df
        except Exception as e:
            results["contract_errors"] = [f"Data contract validation failed: {str(e)}"]
        
        # Step 2: Run validation engine (against existing data if available)
        existing_data = self.current_data if self.current_data is not None else None
        validation_results = self.validation_engine.validate_incremental(new_records, existing_data)
        results["validation_results"] = validation_results
        
        # Step 3: Calculate quality metrics for new records
        quality_metrics = self._calculate_quality_metrics(new_records, validation_results)
        results["quality_metrics"] = quality_metrics
        
        # Step 4: Append to existing data if valid
        if self.current_data is not None and results["data_contract_valid"]:
            self.current_data = pd.concat([self.current_data, new_records], ignore_index=True)
            results["processed_data"] = self.current_data
        else:
            results["processed_data"] = new_records
            if self.current_data is None:
                self.current_data = new_records
        
        # Step 5: Store validation history
        self.validation_history.append({
            "timestamp": results["timestamp"],
            "mode": "incremental",
            "records_processed": len(new_records),
            "quality_score": quality_metrics["overall_score"]
        })
        
        return results
    
    def _fix_common_issues(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Attempt to fix common data quality issues automatically.
        
        Args:
            df: Input DataFrame
            
        Returns:
            pd.DataFrame: Fixed DataFrame
        """
        df = df.copy()
        
        # Standardize column names
        df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
        
        # Convert date columns
        date_columns = ['actual_date', 'baseline_start_date', 'date']
        for col in date_columns:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
        
        # Convert numeric columns
        numeric_columns = ['pmb_budget', 'actual_cost', 'progress_pct', 'revenue_claimed',
                          'budget', 'cost', 'progress', 'revenue']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Fill missing values with defaults where appropriate
        if 'progress_pct' in df.columns:
            df['progress_pct'] = df['progress_pct'].fillna(0)
        
        return df
    
    def _calculate_quality_metrics(self, df: pd.DataFrame, 
                                   validation_results: dict) -> dict:
        """
        Calculate comprehensive data quality metrics.
        
        Args:
            df: Input DataFrame
            validation_results: Results from validation engine
            
        Returns:
            dict: Quality metrics for each dimension
        """
        metrics = {
            "accuracy": self._calculate_accuracy(df),
            "completeness": self._calculate_completeness(df),
            "consistency": self._calculate_consistency(df),
            "integrity": self._calculate_integrity(df, validation_results),
            "overall_score": 0.0
        }
        
        # Calculate overall score as weighted average
        weights = {
            "accuracy": 0.25,
            "completeness": 0.30,
            "consistency": 0.25,
            "integrity": 0.20
        }
        
        overall_score = sum(metrics[dim] * weights[dim] for dim in metrics if dim != "overall_score")
        metrics["overall_score"] = round(overall_score, 2)
        
        return metrics
    
    def _calculate_accuracy(self, df: pd.DataFrame) -> float:
        """
        Calculate accuracy score based on valid ranges and types.
        
        Args:
            df: Input DataFrame
            
        Returns:
            float: Accuracy score (0-100)
        """
        if len(df) == 0:
            return 100.0
        
        total_cells = 0
        valid_cells = 0
        
        # Check numeric columns for valid ranges
        numeric_checks = {
            'pmb_budget': lambda x: x >= 0,
            'actual_cost': lambda x: x >= 0,
            'progress_pct': lambda x: 0 <= x <= 100,
            'revenue_claimed': lambda x: x >= 0
        }
        
        for col, check_func in numeric_checks.items():
            if col in df.columns:
                total_cells += len(df)
                valid_cells += df[col].apply(check_func).sum()
        
        # Check other columns for non-null
        other_columns = ['project_id', 'time_period']
        for col in other_columns:
            if col in df.columns:
                total_cells += len(df)
                valid_cells += df[col].notna().sum()
        
        if total_cells == 0:
            return 100.0
        
        accuracy = (valid_cells / total_cells) * 100
        return round(accuracy, 2)
    
    def _calculate_completeness(self, df: pd.DataFrame) -> float:
        """
        Calculate completeness score based on missing values.
        
        Args:
            df: Input DataFrame
            
        Returns:
            float: Completeness score (0-100)
        """
        if len(df) == 0:
            return 100.0
        
        required_columns = ['project_id', 'time_period', 'pmb_budget', 'actual_cost',
                           'progress_pct', 'revenue_claimed', 'actual_date', 'baseline_start_date']
        
        available_columns = [col for col in required_columns if col in df.columns]
        
        if not available_columns:
            return 100.0
        
        total_cells = len(df) * len(available_columns)
        non_null_cells = df[available_columns].notna().sum().sum()
        
        completeness = (non_null_cells / total_cells) * 100
        return round(completeness, 2)
    
    def _calculate_consistency(self, df: pd.DataFrame) -> float:
        """
        Calculate consistency score based on duplicates and format conflicts.
        
        Args:
            df: Input DataFrame
            
        Returns:
            float: Consistency score (0-100)
        """
        if len(df) == 0:
            return 100.0
        
        # Check for duplicates
        key_columns = ['project_id', 'time_period']
        available_keys = [col for col in key_columns if col in df.columns]
        
        if not available_keys:
            return 100.0
        
        total_records = len(df)
        duplicate_count = df.duplicated(subset=available_keys, keep=False).sum()
        
        # Consistency score decreases with duplicates
        if total_records == 0:
            return 100.0
        
        consistency = ((total_records - duplicate_count) / total_records) * 100
        return round(consistency, 2)
    
    def _calculate_integrity(self, df: pd.DataFrame, validation_results: dict) -> float:
        """
        Calculate integrity score based on logical constraints.
        
        Args:
            df: Input DataFrame
            validation_results: Results from validation engine
            
        Returns:
            float: Integrity score (0-100)
        """
        if len(df) == 0:
            return 100.0
        
        # Use logical anomalies from validation results
        logical_anomalies = validation_results.get("anomalies", {}).get("logical_anomalies", [])
        total_records = validation_results.get("total_records", len(df))
        
        if total_records == 0:
            return 100.0
        
        # Integrity score based on logical constraint violations
        integrity = ((total_records - len(logical_anomalies)) / total_records) * 100
        return round(integrity, 2)
    
    def get_data_summary(self) -> dict:
        """
        Get summary statistics of the current dataset.
        
        Returns:
            dict: Summary statistics
        """
        if self.current_data is None:
            return {"error": "No data loaded"}
        
        df = self.current_data
        
        summary = {
            "total_records": len(df),
            "columns": list(df.columns),
            "memory_usage": df.memory_usage(deep=True).sum(),
            "date_range": {},
            "numeric_summary": {},
            "categorical_summary": {}
        }
        
        # Date range
        date_columns = df.select_dtypes(include=['datetime64']).columns
        for col in date_columns:
            summary["date_range"][col] = {
                "min": df[col].min().isoformat() if pd.notna(df[col].min()) else None,
                "max": df[col].max().isoformat() if pd.notna(df[col].max()) else None
            }
        
        # Numeric summary
        numeric_columns = df.select_dtypes(include=[np.number]).columns
        for col in numeric_columns:
            summary["numeric_summary"][col] = {
                "mean": float(df[col].mean()) if pd.notna(df[col].mean()) else None,
                "median": float(df[col].median()) if pd.notna(df[col].median()) else None,
                "std": float(df[col].std()) if pd.notna(df[col].std()) else None,
                "min": float(df[col].min()) if pd.notna(df[col].min()) else None,
                "max": float(df[col].max()) if pd.notna(df[col].max()) else None
            }
        
        # Categorical summary
        categorical_columns = df.select_dtypes(include=['object', 'string']).columns
        for col in categorical_columns:
            summary["categorical_summary"][col] = {
                "unique_count": df[col].nunique(),
                "most_common": df[col].mode().iloc[0] if not df[col].mode().empty else None
            }
        
        return summary
    
    def get_validation_history(self) -> list:
        """
        Get history of validation runs.
        
        Returns:
            list: Validation history
        """
        return self.validation_history
    
    def export_processed_data(self, file_path: str, file_type: str = 'csv') -> bool:
        """
        Export processed data to file.
        
        Args:
            file_path: Output file path
            file_type: File type ('csv', 'excel', 'json')
            
        Returns:
            bool: Success status
        """
        if self.current_data is None:
            return False
        
        try:
            if file_type == 'csv':
                self.current_data.to_csv(file_path, index=False)
            elif file_type in ['xlsx', 'xls']:
                self.current_data.to_excel(file_path, index=False)
            elif file_type == 'json':
                self.current_data.to_json(file_path, orient='records')
            else:
                raise ValueError(f"Unsupported file type: {file_type}")
            
            return True
        except Exception as e:
            print(f"Error exporting data: {str(e)}")
            return False


if __name__ == "__main__":
    # Test the data pipeline
    import pandas as pd
    
    # Create sample data
    sample_data = pd.DataFrame({
        "project_id": ["PROJ001", "PROJ002", "PROJ003"] * 5,
        "time_period": ["Week-1", "Week-2", "Week-3"] * 5,
        "pmb_budget": [100000.0, 150000.0, 200000.0] * 5,
        "actual_cost": [95000.0, 145000.0, 180000.0] * 5,
        "progress_pct": [45.0, 50.0, 55.0] * 5,
        "revenue_claimed": [90000.0, 140000.0, 170000.0] * 5,
        "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29"] * 5),
        "baseline_start_date": pd.to_datetime(["2024-01-01"] * 15)
    })
    
    # Initialize pipeline
    pipeline = DataPipeline()
    
    # Process in batch mode
    print("Processing in BATCH mode...")
    batch_results = pipeline.process_batch(sample_data)
    
    print(f"Data Contract Valid: {batch_results['data_contract_valid']}")
    print(f"Quality Score: {batch_results['quality_metrics']['overall_score']}")
    print(f"Validation Summary: {pipeline.validation_engine.get_validation_summary(batch_results['validation_results'])}")
    
    # Process incremental data
    print("\nProcessing in INCREMENTAL mode...")
    new_data = pd.DataFrame({
        "project_id": ["PROJ004"],
        "time_period": ["Week-4"],
        "pmb_budget": [250000.0],
        "actual_cost": [240000.0],
        "progress_pct": [60.0],
        "revenue_claimed": [230000.0],
        "actual_date": pd.to_datetime(["2024-02-05"]),
        "baseline_start_date": pd.to_datetime(["2024-01-15"])
    })
    
    incremental_results = pipeline.process_incremental(new_data)
    print(f"Quality Score: {incremental_results['quality_metrics']['overall_score']}")
    
    # Get data summary
    print("\nData Summary:")
    summary = pipeline.get_data_summary()
    print(f"Total Records: {summary['total_records']}")
    print(f"Projects: {summary['categorical_summary'].get('project_id', {}).get('unique_count', 'N/A')}")