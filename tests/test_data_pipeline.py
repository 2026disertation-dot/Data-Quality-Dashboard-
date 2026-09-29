"""
System tests for data pipeline
Tests the batch and incremental processing functionality
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data_pipeline import DataPipeline


class TestDataPipeline:
    """Test suite for data pipeline"""
    
    @pytest.fixture
    def pipeline(self):
        """Create data pipeline instance"""
        return DataPipeline()
    
    @pytest.fixture
    def sample_data(self):
        """Create sample test data"""
        return pd.DataFrame({
            "project_id": ["PROJ001", "PROJ002", "PROJ003"] * 5,
            "time_period": ["Week-1", "Week-2", "Week-3"] * 5,
            "pmb_budget": [100000.0, 150000.0, 200000.0] * 5,
            "actual_cost": [95000.0, 145000.0, 180000.0] * 5,
            "progress_pct": [45.0, 50.0, 55.0] * 5,
            "revenue_claimed": [90000.0, 140000.0, 170000.0] * 5,
            "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29"] * 5),
            "baseline_start_date": pd.to_datetime(["2024-01-01"] * 15)
        })
    
    @pytest.fixture
    def new_incremental_data(self):
        """Create new data for incremental processing"""
        return pd.DataFrame({
            "project_id": ["PROJ004", "PROJ005"],
            "time_period": ["Week-4", "Week-5"],
            "pmb_budget": [250000.0, 300000.0],
            "actual_cost": [240000.0, 290000.0],
            "progress_pct": [60.0, 65.0],
            "revenue_claimed": [230000.0, 280000.0],
            "actual_date": pd.to_datetime(["2024-02-05", "2024-02-12"]),
            "baseline_start_date": pd.to_datetime(["2024-01-15", "2024-01-20"])
        })
    
    def test_pipeline_initialization(self, pipeline):
        """Test pipeline initializes correctly"""
        assert pipeline is not None
        assert pipeline.validation_engine is not None
        assert pipeline.current_data is None
        assert pipeline.pipeline_mode == "batch"
    
    def test_batch_processing(self, pipeline, sample_data):
        """Test batch mode processing"""
        results = pipeline.process_batch(sample_data)
        
        assert results["mode"] == "batch"
        assert results["input_records"] == 15
        assert "validation_results" in results
        assert "quality_metrics" in results
        assert "processed_data" in results
        assert len(results["processed_data"]) == 15
    
    def test_incremental_processing(self, pipeline, new_incremental_data):
        """Test incremental mode processing"""
        results = pipeline.process_incremental(new_incremental_data)
        
        assert results["mode"] == "incremental"
        assert results["new_records"] == 2
        assert "validation_results" in results
        assert "quality_metrics" in results
        assert len(results["processed_data"]) == 2

    def test_incremental_matches_the_batch_result_schema(self, pipeline, sample_data,
                                                        new_incremental_data):
        """Both modes must expose the same keys to the dashboard."""
        batch = pipeline.process_batch(sample_data)
        incremental = pipeline.process_incremental(new_incremental_data)

        for key in ("mode", "input_records", "validation_results", "quality_metrics"):
            assert key in batch, f"batch results missing {key}"
            assert key in incremental, f"incremental results missing {key}"

        # The record count the UI reads is present and consistent in both modes.
        assert incremental["input_records"] == incremental["new_records"]
        assert (incremental["validation_results"]["total_records"]
                == len(new_incremental_data))

    def test_incremental_append_to_existing(self, pipeline, sample_data, new_incremental_data):
        """Test incremental processing appends to existing data"""
        # First process batch data
        pipeline.process_batch(sample_data)
        initial_count = len(pipeline.current_data)
        
        # Then process incremental data
        pipeline.process_incremental(new_incremental_data)
        final_count = len(pipeline.current_data)
        
        assert final_count == initial_count + 2
    
    def test_quality_metrics_calculation(self, pipeline, sample_data):
        """Test quality metrics are calculated correctly"""
        results = pipeline.process_batch(sample_data)
        metrics = results["quality_metrics"]
        
        assert "accuracy" in metrics
        assert "completeness" in metrics
        assert "consistency" in metrics
        assert "integrity" in metrics
        assert "overall_score" in metrics
        
        # All scores should be between 0 and 100
        for metric_name, score in metrics.items():
            if metric_name != "overall_score":
                assert 0 <= score <= 100
    
    def test_data_summary_generation(self, pipeline, sample_data):
        """Test data summary generation"""
        pipeline.process_batch(sample_data)
        summary = pipeline.get_data_summary()
        
        assert "total_records" in summary
        assert "columns" in summary
        assert "numeric_summary" in summary
        assert "categorical_summary" in summary
        
        assert summary["total_records"] == 15
        assert len(summary["columns"]) == 8
    
    def test_validation_history_tracking(self, pipeline, sample_data, new_incremental_data):
        """Test validation history is tracked"""
        pipeline.process_batch(sample_data)
        pipeline.process_incremental(new_incremental_data)
        
        history = pipeline.get_validation_history()
        
        assert len(history) == 2
        assert history[0]["mode"] == "batch"
        assert history[1]["mode"] == "incremental"
    
    def test_load_csv_data(self, pipeline, sample_data):
        """Test loading CSV data"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            sample_data.to_csv(f.name, index=False)
            temp_path = f.name
        
        try:
            loaded_data = pipeline.load_data(temp_path, 'csv')
            assert len(loaded_data) == 15
            assert list(loaded_data.columns) == list(sample_data.columns)
        finally:
            os.unlink(temp_path)
    
    def test_load_excel_data(self, pipeline, sample_data):
        """Test loading Excel data"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xlsx', delete=False) as f:
            sample_data.to_excel(f.name, index=False)
            temp_path = f.name
        
        try:
            loaded_data = pipeline.load_data(temp_path, 'xlsx')
            assert len(loaded_data) == 15
        finally:
            os.unlink(temp_path)
    
    def test_export_processed_data(self, pipeline, sample_data):
        """Test exporting processed data"""
        pipeline.process_batch(sample_data)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            temp_path = f.name
        
        try:
            success = pipeline.export_processed_data(temp_path, 'csv')
            assert success is True
            assert os.path.exists(temp_path)
            
            # Verify exported data
            exported_data = pd.read_csv(temp_path)
            assert len(exported_data) == 15
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_mode_switching(self, pipeline, sample_data):
        """Test switching between batch and incremental modes"""
        # Start with batch
        pipeline.process_batch(sample_data)
        assert pipeline.pipeline_mode == "batch"
        
        # Switch to incremental
        new_data = sample_data.head(1)
        pipeline.process_incremental(new_data)
        assert pipeline.pipeline_mode == "incremental"
    
    def test_accuracy_metric_calculation(self, pipeline, sample_data):
        """Test accuracy metric calculation"""
        results = pipeline.process_batch(sample_data)
        accuracy = results["quality_metrics"]["accuracy"]
        
        assert isinstance(accuracy, (int, float))
        assert 0 <= accuracy <= 100
        # Clean data should have high accuracy
        assert accuracy >= 90.0
    
    def test_completeness_metric_calculation(self, pipeline, sample_data):
        """Test completeness metric calculation"""
        results = pipeline.process_batch(sample_data)
        completeness = results["quality_metrics"]["completeness"]
        
        assert isinstance(completeness, (int, float))
        assert 0 <= completeness <= 100
        # Clean data should have 100% completeness
        assert completeness == 100.0
    
    def test_consistency_metric_calculation(self, pipeline, sample_data):
        """Test consistency metric calculation"""
        results = pipeline.process_batch(sample_data)
        consistency = results["quality_metrics"]["consistency"]
        
        assert isinstance(consistency, (int, float))
        assert 0 <= consistency <= 100
        # Sample data has some duplicates, so consistency might be < 100
        assert consistency >= 0.0
    
    def test_integrity_metric_calculation(self, pipeline, sample_data):
        """Test integrity metric calculation"""
        results = pipeline.process_batch(sample_data)
        integrity = results["quality_metrics"]["integrity"]
        
        assert isinstance(integrity, (int, float))
        assert 0 <= integrity <= 100
        # Clean data should have high integrity
        assert integrity >= 90.0
    
    def test_regression_consistency(self, pipeline, sample_data):
        """Test that batch and incremental modes produce consistent results for same data"""
        # Process in batch mode
        batch_results = pipeline.process_batch(sample_data)
        batch_score = batch_results["quality_metrics"]["overall_score"]
        
        # Reset pipeline
        pipeline.current_data = None
        pipeline.validation_history = []
        
        # Process same data in incremental mode
        incremental_results = pipeline.process_incremental(sample_data)
        incremental_score = incremental_results["quality_metrics"]["overall_score"]
        
        # Scores should be similar (allowing for small differences due to mode)
        assert abs(batch_score - incremental_score) < 5.0
    
    def test_performance_large_dataset(self, pipeline):
        """Test performance with larger dataset"""
        # Create larger dataset
        large_data = pd.DataFrame({
            "project_id": [f"PROJ{i:03d}" for i in range(100)] * 50,
            "time_period": [f"Week-{i}" for i in range(1, 51)] * 100,
            "pmb_budget": [100000.0 + i * 1000 for i in range(5000)],
            "actual_cost": [95000.0 + i * 950 for i in range(5000)],
            "progress_pct": [45.0 + (i % 10) * 5 for i in range(5000)],
            "revenue_claimed": [90000.0 + i * 900 for i in range(5000)],
            "actual_date": pd.to_datetime([pd.Timestamp("2024-01-01") + pd.Timedelta(days=i*7) for i in range(5000)]),
            "baseline_start_date": pd.to_datetime(["2024-01-01"] * 5000)
        })
        
        import time
        start_time = time.time()
        results = pipeline.process_batch(large_data)
        end_time = time.time()
        
        processing_time = end_time - start_time
        
        # Should process 5000 records in reasonable time (< 10 seconds)
        assert processing_time < 10.0
        assert results["input_records"] == 5000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])