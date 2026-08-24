from unittest.mock import patch

import numpy as np

import atlas_sao.observedListCleanup as olc


@patch("atlas_sao.observedListCleanup.ac.RemoveFromCustomList")
def test_remove_targets_from_list_calls_remove_once_with_array(mock_remove):
    olc.remove_targets_from_list(['1234567890123456789'], 'salt')

    mock_remove.assert_called_once()
    _, kwargs = mock_remove.call_args
    assert list(kwargs['array_ids']) == ['1234567890123456789']
    assert isinstance(kwargs['array_ids'], np.ndarray)
    assert kwargs['list_name'] == 'salt'
    assert kwargs['chunk_size'] == 25


@patch("atlas_sao.observedListCleanup.ac.RemoveFromCustomList")
def test_remove_targets_from_list_noop_when_empty(mock_remove):
    olc.remove_targets_from_list([], 'salt')

    mock_remove.assert_not_called()


@patch("atlas_sao.observedListCleanup.db.mark_list_removed")
@patch("atlas_sao.observedListCleanup.db.log_removed")
@patch("atlas_sao.observedListCleanup.ac.RemoveFromCustomList")
@patch("atlas_sao.observedListCleanup.db.get_unprocessed_observed_reports")
def test_process_observed_reports_removes_and_marks(mock_get, mock_remove, mock_log_removed, mock_mark):
    mock_get.return_value = [
        {'id': 1, 'atlas_id': 1111111111111111111, 'telescope': 'Mookodi',
         'related_list': 'Bright 100Mpc Southern Transients'},
    ]

    olc.process_observed_reports(db_path='fake.db')

    mock_remove.assert_called_once()
    _, kwargs = mock_remove.call_args
    assert list(kwargs['array_ids']) == [1111111111111111111]
    assert kwargs['list_name'] == 'bright_south_transients_100mpc'

    mock_log_removed.assert_called_once_with([1111111111111111111], 'bk_young_fast_track', db_path='fake.db')
    mock_mark.assert_called_once_with(1, db_path='fake.db')


@patch("atlas_sao.observedListCleanup.db.mark_list_removed")
@patch("atlas_sao.observedListCleanup.db.log_removed")
@patch("atlas_sao.observedListCleanup.ac.RemoveFromCustomList")
@patch("atlas_sao.observedListCleanup.db.get_unprocessed_observed_reports")
def test_process_observed_reports_staging_list_has_no_bk_table(mock_get, mock_remove, mock_log_removed, mock_mark):
    mock_get.return_value = [
        {'id': 1, 'atlas_id': 1111111111111111111, 'telescope': 'Mookodi',
         'related_list': '100Mpc Southern Transients'},
    ]

    olc.process_observed_reports(db_path='fake.db')

    mock_remove.assert_called_once()
    _, kwargs = mock_remove.call_args
    assert kwargs['list_name'] == 'south_transients_100mpc'

    mock_log_removed.assert_not_called()
    mock_mark.assert_called_once_with(1, db_path='fake.db')


@patch("atlas_sao.observedListCleanup.db.mark_list_removed")
@patch("atlas_sao.observedListCleanup.db.log_removed")
@patch("atlas_sao.observedListCleanup.ac.RemoveFromCustomList")
@patch("atlas_sao.observedListCleanup.db.get_unprocessed_observed_reports")
def test_process_observed_reports_skips_unresolved_list(mock_get, mock_remove, mock_log_removed, mock_mark):
    mock_get.return_value = [
        {'id': 1, 'atlas_id': 1111111111111111111, 'telescope': 'Mookodi', 'related_list': None},
    ]

    olc.process_observed_reports(db_path='fake.db')

    mock_remove.assert_not_called()
    mock_log_removed.assert_not_called()
    mock_mark.assert_not_called()


@patch("atlas_sao.observedListCleanup.db.deactivate_xtgal_ids")
@patch("atlas_sao.observedListCleanup.db.mark_list_removed")
@patch("atlas_sao.observedListCleanup.db.log_removed")
@patch("atlas_sao.observedListCleanup.ac.RemoveFromCustomList")
@patch("atlas_sao.observedListCleanup.db.get_unprocessed_observed_reports")
def test_process_observed_reports_dedupes_atlas_ids_within_a_list(mock_get, mock_remove, mock_log_removed, mock_mark, mock_deactivate):
    mock_get.return_value = [
        {'id': 1, 'atlas_id': 1111111111111111111, 'telescope': 'Mookodi', 'related_list': 'Southern Transients at Peak'},
        {'id': 2, 'atlas_id': 1111111111111111111, 'telescope': 'Mookodi', 'related_list': 'Southern Transients at Peak'},
    ]

    olc.process_observed_reports(db_path='fake.db')

    mock_remove.assert_called_once()
    _, kwargs = mock_remove.call_args
    assert list(kwargs['array_ids']) == [1111111111111111111]
    assert kwargs['list_name'] == 'south_transients_peak'

    mock_log_removed.assert_called_once_with([1111111111111111111], 'bk_peak', db_path='fake.db')
    assert mock_mark.call_count == 2


@patch("atlas_sao.observedListCleanup.db.deactivate_xtgal_ids")
@patch("atlas_sao.observedListCleanup.db.mark_list_removed")
@patch("atlas_sao.observedListCleanup.db.log_removed")
@patch("atlas_sao.observedListCleanup.ac.RemoveFromCustomList")
@patch("atlas_sao.observedListCleanup.db.get_unprocessed_observed_reports")
def test_process_observed_reports_deactivates_xtgal_watchlist_for_peak_list(mock_get, mock_remove, mock_log_removed, mock_mark, mock_deactivate):
    mock_get.return_value = [
        {'id': 1, 'atlas_id': 1111111111111111111, 'telescope': 'Mookodi',
         'related_list': 'Southern Transients at Peak'},
    ]

    olc.process_observed_reports(db_path='fake.db')

    mock_deactivate.assert_called_once_with([1111111111111111111], db_path='fake.db')


@patch("atlas_sao.observedListCleanup.db.deactivate_xtgal_ids")
@patch("atlas_sao.observedListCleanup.db.mark_list_removed")
@patch("atlas_sao.observedListCleanup.db.log_removed")
@patch("atlas_sao.observedListCleanup.ac.RemoveFromCustomList")
@patch("atlas_sao.observedListCleanup.db.get_unprocessed_observed_reports")
def test_process_observed_reports_does_not_deactivate_xtgal_for_non_peak_list(mock_get, mock_remove, mock_log_removed, mock_mark, mock_deactivate):
    mock_get.return_value = [
        {'id': 1, 'atlas_id': 1111111111111111111, 'telescope': 'Mookodi',
         'related_list': 'Bright 100Mpc Southern Transients'},
    ]

    olc.process_observed_reports(db_path='fake.db')

    mock_deactivate.assert_not_called()


@patch("atlas_sao.observedListCleanup.db.mark_list_removed")
@patch("atlas_sao.observedListCleanup.db.log_removed")
@patch("atlas_sao.observedListCleanup.ac.RemoveFromCustomList")
@patch("atlas_sao.observedListCleanup.db.get_unprocessed_observed_reports")
def test_process_observed_reports_leaves_rows_unprocessed_on_removal_failure(mock_get, mock_remove, mock_log_removed, mock_mark):
    mock_get.return_value = [
        {'id': 1, 'atlas_id': 1111111111111111111, 'telescope': 'Mookodi',
         'related_list': 'Southern Transients at Peak'},
    ]
    mock_remove.side_effect = Exception("boom")

    olc.process_observed_reports(db_path='fake.db')

    mock_remove.assert_called_once()
    mock_log_removed.assert_not_called()
    mock_mark.assert_not_called()


@patch("atlas_sao.observedListCleanup.db.get_unprocessed_observed_reports")
def test_process_observed_reports_noop_when_nothing_unprocessed(mock_get):
    mock_get.return_value = []
    # Should just return without raising, no need to mock anything else.
    olc.process_observed_reports(db_path='fake.db')
