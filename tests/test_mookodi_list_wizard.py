from unittest.mock import MagicMock, patch

import numpy as np

import atlas_sao.mookodiListWizard as mlw


@patch("atlas_sao.mookodiListWizard.ac.WriteToCustomList")
def test_add_targets_to_list_calls_write_once_with_array(mock_write):
    mlw.add_targets_to_list([111, 222], "mookodi_live")

    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert list(kwargs["array_ids"]) == [111, 222]
    assert isinstance(kwargs["array_ids"], np.ndarray)
    assert kwargs["list_name"] == "mookodi_live"


@patch("atlas_sao.mookodiListWizard.ac.WriteToCustomList")
def test_add_targets_to_list_noop_when_empty(mock_write):
    mlw.add_targets_to_list([], "mookodi_live")

    mock_write.assert_not_called()


@patch("atlas_sao.mookodiListWizard.ac.RemoveFromCustomList")
def test_remove_targets_from_list_calls_remove_once_with_array_and_chunk_size(mock_remove):
    mock_remove.return_value = MagicMock()

    mlw.remove_targets_from_list([333, 444], "mookodi")

    mock_remove.assert_called_once()
    _, kwargs = mock_remove.call_args
    assert list(kwargs["array_ids"]) == [333, 444]
    assert isinstance(kwargs["array_ids"], np.ndarray)
    assert kwargs["list_name"] == "mookodi"
    assert kwargs["chunk_size"] == 25
    mock_remove.return_value.get_response.assert_called_once()


@patch("atlas_sao.mookodiListWizard.ac.RemoveFromCustomList")
def test_remove_targets_from_list_noop_when_empty(mock_remove):
    mlw.remove_targets_from_list([], "mookodi")

    mock_remove.assert_not_called()
