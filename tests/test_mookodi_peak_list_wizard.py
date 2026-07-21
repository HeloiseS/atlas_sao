from unittest.mock import MagicMock, patch

import numpy as np

import atlas_sao.mookodiPeakListWizard as mpw


def make_entry(detection_list_id=4, observation_status=None, points=((15.5, 0.1),) * 3, vra=9.2,
               nondet_mjds=()):
    lc = [
        {'mag': mag, 'magerr': magerr, 'mjd': 60000 + i}
        for i, (mag, magerr) in enumerate(points)
    ] if points is not None else []
    lcnondets = [{'mjd': mjd, 'mag5sig': 19.5} for mjd in nondet_mjds]
    return {
        'object': {
            'id': '1234567890123456789',
            'detection_list_id': detection_list_id,
            'observation_status': observation_status,
            'vra': vra,
        },
        'lc': lc,
        'lcnondets': lcnondets,
    }


class TestIsAtPeak:
    def test_passes_all_conditions(self):
        assert mpw.is_at_peak(make_entry()) is True

    def test_fails_garbage(self):
        assert mpw.is_at_peak(make_entry(detection_list_id=0)) is False

    def test_fails_no_lightcurve(self):
        entry = make_entry()
        entry['lc'] = []
        assert mpw.is_at_peak(entry) is False

    def test_fails_no_lc_key(self):
        entry = make_entry()
        del entry['lc']
        assert mpw.is_at_peak(entry) is False

    def test_fails_fewer_than_three_points(self):
        assert mpw.is_at_peak(make_entry(points=((15.5, 0.1), (15.5, 0.1)))) is False

    def test_fails_no_mag_in_recent_point(self):
        assert mpw.is_at_peak(make_entry(points=((15.5, 0.1), (15.5, 0.1), (None, 0.1)))) is False

    def test_fails_non_detection_in_recent_points(self):
        assert mpw.is_at_peak(make_entry(points=((15.5, 0.1), (15.5, 0.1), (-18.8, 0.1)))) is False

    def test_fails_too_faint(self):
        assert mpw.is_at_peak(make_entry(points=((15.5, 0.1), (15.5, 0.1), (20.0, 0.1)))) is False

    def test_fails_exactly_at_threshold(self):
        assert mpw.is_at_peak(make_entry(points=((15.5, 0.1), (15.5, 0.1), (17.0, 0.1)))) is False

    def test_passes_just_brighter_than_threshold_with_error_margin(self):
        assert mpw.is_at_peak(make_entry(points=((15.5, 0.1), (15.5, 0.1), (17.5, 1.0)))) is True

    def test_fails_bogus_bright_single_point_flanked_by_faint(self):
        assert mpw.is_at_peak(make_entry(points=((15.0, 0.1), (17.5, 0.1), (15.0, 0.1)))) is False

    def test_only_last_three_points_considered_regardless_of_older_faint_history(self):
        assert mpw.is_at_peak(make_entry(points=((20.0, 0.1), (15.5, 0.1), (15.5, 0.1), (15.5, 0.1)))) is True

    def test_fails_when_most_recent_points_are_nondetections(self):
        entry = make_entry(points=((15.5, 0.1), (15.5, 0.1), (15.5, 0.1)), nondet_mjds=(60010, 60011, 60012))
        assert mpw.is_at_peak(entry) is False

    def test_passes_when_nondets_are_older_than_recent_detections(self):
        entry = make_entry(points=((15.5, 0.1), (15.5, 0.1), (15.5, 0.1)), nondet_mjds=(59990, 59991))
        assert mpw.is_at_peak(entry) is True

    def test_fails_when_single_recent_nondet_bumps_a_detection_out_of_last_three(self):
        entry = make_entry(points=((15.5, 0.1), (15.5, 0.1), (15.5, 0.1), (15.5, 0.1)), nondet_mjds=(60010,))
        assert mpw.is_at_peak(entry) is False

    def test_passes_when_no_lcnondets_key(self):
        entry = make_entry()
        del entry['lcnondets']
        assert mpw.is_at_peak(entry) is True



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
    mock_remove.return_value.get_response.assert_not_called()


@patch("atlas_sao.mookodiPeakListWizard.ac.RemoveFromCustomList")
def test_remove_targets_from_list_noop_when_empty(mock_remove):
    mpw.remove_targets_from_list([], 'mookodi_peak')

    mock_remove.assert_not_called()


@patch("atlas_sao.mookodiPeakListWizard.ac.RequestMultipleSourceData")
@patch("atlas_sao.mookodiPeakListWizard.db.get_active_xtgal_ids")
@patch("atlas_sao.mookodiPeakListWizard.ac.RequestCustomListsTable")
def test_fill_up_returns_ids_and_vra_scores(mock_table, mock_db, mock_multi):
    mock_table.return_value.response_data = []
    mock_db.return_value = ['1234567890123456789']

    source_mock = MagicMock()
    source_mock.response_data = [make_entry(vra=9.2)]
    mock_multi.return_value = source_mock

    ids, vra_scores = mpw.fill_up()

    assert ids == ['1234567890123456789']
    assert vra_scores == {'1234567890123456789': 9.2}
