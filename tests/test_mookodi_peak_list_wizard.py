from unittest.mock import MagicMock, patch

import numpy as np

import atlas_sao.mookodiPeakListWizard as mpw


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


class TestIsAtPeak:
    def test_passes_all_conditions(self):
        assert mpw.is_at_peak(make_entry()) is True

    def test_fails_garbage(self):
        assert mpw.is_at_peak(make_entry(detection_list_id=0)) is False

    def test_fails_empty_string_classification_treated_as_none(self):
        assert mpw.is_at_peak(make_entry(observation_status='')) is True

    def test_fails_no_lightcurve(self):
        entry = make_entry()
        entry['lc'] = []
        assert mpw.is_at_peak(entry) is False

    def test_fails_no_lc_key(self):
        entry = make_entry()
        del entry['lc']
        assert mpw.is_at_peak(entry) is False

    def test_fails_no_mag_in_last_point(self):
        assert mpw.is_at_peak(make_entry(last_mag=None)) is False

    def test_fails_too_faint(self):
        assert mpw.is_at_peak(make_entry(last_mag=16.5)) is False

    def test_fails_exactly_at_threshold(self):
        assert mpw.is_at_peak(make_entry(last_mag=16.0)) is False

    def test_passes_just_brighter_than_threshold(self):
        assert mpw.is_at_peak(make_entry(last_mag=15.99)) is True



@patch("atlas_sao.mookodiPeakListWizard.ac.WriteToCustomList")
def test_add_targets_to_list_calls_write_once_with_array(mock_write):
    mpw.add_targets_to_list(['1234567890123456789', '9876543210987654321'], 'mookodi_peak')

    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert list(kwargs['array_ids']) == ['1234567890123456789', '9876543210987654321']
    assert isinstance(kwargs['array_ids'], np.ndarray)
    assert kwargs['list_name'] == 'mookodi_peak'


@patch("atlas_sao.mookodiPeakListWizard.ac.WriteToCustomList")
def test_add_targets_to_list_noop_when_empty(mock_write):
    mpw.add_targets_to_list([], 'mookodi_peak')

    mock_write.assert_not_called()


@patch("atlas_sao.mookodiPeakListWizard.ac.RemoveFromCustomList")
def test_remove_targets_from_list_calls_remove_once_with_array_and_chunk_size(mock_remove):
    mock_remove.return_value = MagicMock()

    mpw.remove_targets_from_list(['1234567890123456789'], 'mookodi_peak')

    mock_remove.assert_called_once()
    _, kwargs = mock_remove.call_args
    assert list(kwargs['array_ids']) == ['1234567890123456789']
    assert isinstance(kwargs['array_ids'], np.ndarray)
    assert kwargs['list_name'] == 'mookodi_peak'
    assert kwargs['chunk_size'] == 25
    mock_remove.return_value.get_response.assert_called_once()


@patch("atlas_sao.mookodiPeakListWizard.ac.RemoveFromCustomList")
def test_remove_targets_from_list_noop_when_empty(mock_remove):
    mpw.remove_targets_from_list([], 'mookodi_peak')

    mock_remove.assert_not_called()
