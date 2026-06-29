from unittest.mock import MagicMock, patch

import numpy as np

import atlas_sao.mookodiListWizard as mlw


def make_entry(detection_list_id=4, observation_status=None, last_mag: float | None = 15.5):
    lc = [{'mag': last_mag}] if last_mag is not None else []
    return {
        'object': {
            'id': '1234567890123456789',
            'detection_list_id': detection_list_id,
            'observation_status': observation_status,
        },
        'lc': lc,
    }


class TestShouldAddToMookodiLive:
    def test_passes_all_conditions(self):
        assert mlw.should_add_to_mookodi_live(make_entry()) is True

    def test_fails_garbage(self):
        assert mlw.should_add_to_mookodi_live(make_entry(detection_list_id=0)) is False

    def test_fails_classified(self):
        assert mlw.should_add_to_mookodi_live(make_entry(observation_status='SN Ia')) is False

    def test_empty_string_classification_treated_as_unclassified(self):
        assert mlw.should_add_to_mookodi_live(make_entry(observation_status='')) is True

    def test_fails_no_lightcurve(self):
        entry = make_entry()
        entry['lc'] = []
        assert mlw.should_add_to_mookodi_live(entry) is False

    def test_fails_no_lc_key(self):
        entry = make_entry()
        del entry['lc']
        assert mlw.should_add_to_mookodi_live(entry) is False

    def test_fails_no_mag_in_last_point(self):
        assert mlw.should_add_to_mookodi_live(make_entry(last_mag=None)) is False

    def test_fails_too_faint(self):
        assert mlw.should_add_to_mookodi_live(make_entry(last_mag=17.5)) is False

    def test_fails_exactly_at_threshold(self):
        assert mlw.should_add_to_mookodi_live(make_entry(last_mag=17.0)) is False

    def test_passes_just_brighter_than_threshold(self):
        assert mlw.should_add_to_mookodi_live(make_entry(last_mag=16.99)) is True

    def test_custom_mag_threshold(self):
        assert mlw.should_add_to_mookodi_live(make_entry(last_mag=15.5), mag_threshold=15.0) is False
        assert mlw.should_add_to_mookodi_live(make_entry(last_mag=14.9), mag_threshold=15.0) is True


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
