"""
Pytest configuration for system testing
"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture(scope="session")
def test_data_dir():
    """Get the test data directory"""
    return os.path.join(os.path.dirname(__file__), 'data')


@pytest.fixture(scope="session")
def project_root():
    """Get the project root directory"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")