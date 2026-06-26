"""
Integration tests for saltListWizard — require a valid ATLAS API config.
These tests READ from the real API but do NOT write to any list.
Run with: pytest -m integration
"""
import pytest

import atlas_sao.saltListWizard as slw


@pytest.mark.integration
class TestCleanUp:
    def test_returns_list(self):
        result = slw.clean_up()
        assert isinstance(result, list)



@pytest.mark.integration
class TestFillUp:
    def test_returns_list(self):
        result = slw.fill_up()
        assert isinstance(result, list)


