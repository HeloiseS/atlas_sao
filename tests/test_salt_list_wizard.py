from unittest.mock import MagicMock, patch

import numpy as np

import atlas_sao.saltListWizard as slw


def make_entry(detection_list_id=4, sherlock_class='SN', dec=-30.0, observation_status=None,
                lc=None, lcnondets=None):
    if lc is None:
        lc = [{'filter': 'o', 'mjd': slw._current_mjd()}]
    if lcnondets is None:
        lcnondets = fresh_cluster()
    return {
        'object': {
            'id': '1234567890123456789',
            'detection_list_id': detection_list_id,
            'vra': 9.5,
            'sherlockClassification': sherlock_class,
            'dec': dec,
            'observation_status': observation_status,
        },
        'lc': lc,
        'lcnondets': lcnondets,
    }


def fresh_cluster(age_days=1.0, n=3, spread_hours=2.0):
    now = slw._current_mjd()
    return [{'mjd': now - age_days - i * (spread_hours / 24.0)} for i in range(n)]


def stale_cluster(age_days=10.0, n=3, spread_hours=2.0):
    return fresh_cluster(age_days=age_days, n=n, spread_hours=spread_hours)


class TestHasRecentNondetection:
    def test_fresh_cluster_of_three_passes(self):
        entry = make_entry(lcnondets=fresh_cluster())
        assert slw.has_recent_nondetection(entry) is True

    def test_stale_cluster_fails(self):
        entry = make_entry(lcnondets=stale_cluster())
        assert slw.has_recent_nondetection(entry) is False

    def test_scattered_singles_do_not_qualify(self):
        now = slw._current_mjd()
        entry = make_entry(lcnondets=[
            {'mjd': now - 1},
            {'mjd': now - 3},
            {'mjd': now - 5},
        ])
        assert slw.has_recent_nondetection(entry) is False

    def test_no_nondetections_fails(self):
        entry = make_entry(lcnondets=[])
        assert slw.has_recent_nondetection(entry) is False

    def test_uses_most_recent_qualifying_night(self):
        now = slw._current_mjd()
        old_night = [{'mjd': now - 20 - i * 0.05} for i in range(3)]
        recent_night = [{'mjd': now - 2 - i * 0.05} for i in range(3)]
        entry = make_entry(lcnondets=old_night + recent_night)
        assert slw.has_recent_nondetection(entry) is True


class TestHasNonWDetection:
    def test_passes_with_non_w_detection(self):
        entry = make_entry(lc=[{'filter': 'o'}, {'filter': 'w'}])
        assert slw.has_non_w_detection(entry) is True

    def test_fails_when_only_w(self):
        entry = make_entry(lc=[{'filter': 'w'}, {'filter': 'w'}])
        assert slw.has_non_w_detection(entry) is False

    def test_fails_when_no_detections(self):
        entry = make_entry(lc=[])
        assert slw.has_non_w_detection(entry) is False


class TestHasShortDetectionSpan:
    def test_passes_short_span(self):
        now = slw._current_mjd()
        entry = make_entry(lc=[{'mjd': now}, {'mjd': now - 2}])
        assert slw.is_not_too_old(entry) is True

    def test_fails_long_span(self):
        now = slw._current_mjd()
        entry = make_entry(lc=[{'mjd': now}, {'mjd': now - 10}])
        assert slw.is_not_too_old(entry) is False

    def test_single_detection_passes(self):
        entry = make_entry(lc=[{'mjd': slw._current_mjd()}])
        assert slw.is_not_too_old(entry) is True

    def test_fails_when_no_detections(self):
        entry = make_entry(lc=[])
        assert slw.is_not_too_old(entry) is False


class TestShouldAddToSalt:
    def test_passes_all_conditions(self):
        assert slw.should_add_to_salt(make_entry()) is True

    def test_fails_classified(self):
        assert slw.should_add_to_salt(make_entry(observation_status='mover')) is False

    def test_empty_string_classification_treated_as_unclassified(self):
        assert slw.should_add_to_salt(make_entry(observation_status='')) is True

    def test_fails_too_far_north(self):
        assert slw.should_add_to_salt(make_entry(dec=10.0)) is False
        assert slw.should_add_to_salt(make_entry(dec=45.0)) is False

    def test_fails_stale(self):
        assert slw.should_add_to_salt(make_entry(lcnondets=stale_cluster())) is False

    def test_fails_long_detection_span(self):
        now = slw._current_mjd()
        entry = make_entry(lc=[{'filter': 'o', 'mjd': now}, {'filter': 'o', 'mjd': now - 10}])
        assert slw.should_add_to_salt(entry) is False

    def test_fails_only_w_detections(self):
        entry = make_entry(lc=[{'filter': 'w'}])
        assert slw.should_add_to_salt(entry) is False

    def test_ignores_garbage_and_hpm_detection_list_id(self):
        assert slw.should_add_to_salt(make_entry(detection_list_id=0)) is True
        assert slw.should_add_to_salt(make_entry(detection_list_id=11)) is True

    def test_ignores_sherlock_orphan(self):
        assert slw.should_add_to_salt(make_entry(sherlock_class='ORPHAN')) is True


@patch("atlas_sao.saltListWizard.ac.WriteToCustomList")
def test_add_targets_to_list_calls_write_once_with_array(mock_write):
    slw.add_targets_to_list(['1234567890123456789', '9876543210987654321'], 'salt')

    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert list(kwargs['array_ids']) == ['1234567890123456789', '9876543210987654321']
    assert isinstance(kwargs['array_ids'], np.ndarray)
    assert kwargs['list_name'] == 'salt'


@patch("atlas_sao.saltListWizard.ac.WriteToCustomList")
def test_add_targets_to_list_noop_when_empty(mock_write):
    slw.add_targets_to_list([], 'salt')

    mock_write.assert_not_called()


@patch("atlas_sao.saltListWizard.ac.RemoveFromCustomList")
def test_remove_targets_from_list_calls_remove_once_with_array_and_chunk_size(mock_remove):
    mock_remove.return_value = MagicMock()

    slw.remove_targets_from_list(['1234567890123456789'], 'salt')

    mock_remove.assert_called_once()
    _, kwargs = mock_remove.call_args
    assert list(kwargs['array_ids']) == ['1234567890123456789']
    assert isinstance(kwargs['array_ids'], np.ndarray)
    assert kwargs['list_name'] == 'salt'
    assert kwargs['chunk_size'] == 25


@patch("atlas_sao.saltListWizard.ac.RemoveFromCustomList")
def test_remove_targets_from_list_noop_when_empty(mock_remove):
    slw.remove_targets_from_list([], 'salt')

    mock_remove.assert_not_called()


@patch("atlas_sao.saltListWizard.ac.RequestMultipleSourceData")
@patch("atlas_sao.saltListWizard.ac.RequestCustomListsTable")
def test_clean_up_removes_attic_members(mock_table, mock_multi):
    mock_table.return_value.response_data = [
        {'transient_object_id': '1234567890123456789', 'object_group_id': 14}
    ]

    source_mock = MagicMock()
    source_mock.response_data = [make_entry(detection_list_id=5)]
    mock_multi.return_value = source_mock

    to_remove = slw.clean_up()

    assert to_remove == ['1234567890123456789']


@patch("atlas_sao.saltListWizard.ac.RequestMultipleSourceData")
@patch("atlas_sao.saltListWizard.ac.RequestCustomListsTable")
def test_clean_up_removes_hpm_members(mock_table, mock_multi):
    mock_table.return_value.response_data = [
        {'transient_object_id': '1234567890123456789', 'object_group_id': 14}
    ]

    source_mock = MagicMock()
    source_mock.response_data = [make_entry(detection_list_id=11)]
    mock_multi.return_value = source_mock

    to_remove = slw.clean_up()

    assert to_remove == ['1234567890123456789']


@patch("atlas_sao.saltListWizard.ac.RequestMultipleSourceData")
@patch("atlas_sao.saltListWizard.ac.RequestCustomListsTable")
def test_clean_up_removes_stale_members(mock_table, mock_multi):
    mock_table.return_value.response_data = [
        {'transient_object_id': '1234567890123456789', 'object_group_id': 14}
    ]

    source_mock = MagicMock()
    source_mock.response_data = [make_entry(lcnondets=stale_cluster())]
    mock_multi.return_value = source_mock

    to_remove = slw.clean_up()

    assert to_remove == ['1234567890123456789']


@patch("atlas_sao.saltListWizard.ac.RequestMultipleSourceData")
@patch("atlas_sao.saltListWizard.ac.RequestCustomListsTable")
def test_clean_up_removes_long_span_members(mock_table, mock_multi):
    mock_table.return_value.response_data = [
        {'transient_object_id': '1234567890123456789', 'object_group_id': 14}
    ]

    now = slw._current_mjd()
    source_mock = MagicMock()
    source_mock.response_data = [
        make_entry(lc=[{'filter': 'o', 'mjd': now}, {'filter': 'o', 'mjd': now - 10}])
    ]
    mock_multi.return_value = source_mock

    to_remove = slw.clean_up()

    assert to_remove == ['1234567890123456789']


@patch("atlas_sao.saltListWizard.ac.RequestMultipleSourceData")
@patch("atlas_sao.saltListWizard.ac.RequestCustomListsTable")
def test_clean_up_keeps_fresh_unclassified_members(mock_table, mock_multi):
    mock_table.return_value.response_data = [
        {'transient_object_id': '1234567890123456789', 'object_group_id': 14}
    ]

    source_mock = MagicMock()
    source_mock.response_data = [make_entry()]
    mock_multi.return_value = source_mock

    to_remove = slw.clean_up()

    assert to_remove == []


@patch("atlas_sao.saltListWizard.db.get_removed_atlas_ids_for_list")
@patch("atlas_sao.saltListWizard.ac.RequestMultipleSourceData")
@patch("atlas_sao.saltListWizard.ac.RequestATLASIDsFromWebServerList")
@patch("atlas_sao.saltListWizard.ac.RequestCustomListsTable")
def test_fill_up_unions_two_sources_and_returns_vra_scores(mock_table, mock_web_list, mock_multi, mock_removed):
    def table_side_effect(params, get_response=True):
        result = MagicMock()
        if params['objectgroupid'] == 14:
            result.response_data = []
        elif params['objectgroupid'] == 2:
            result.response_data = [{'transient_object_id': '2222222222222222222', 'object_group_id': 2}]
        return result
    mock_table.side_effect = table_side_effect

    def web_list_side_effect(list_name, dec_lte=None, **kwargs):
        result = MagicMock()
        if list_name == 'follow_up':
            result.atlas_id_list_str = ['1111111111111111111']
        return result
    mock_web_list.side_effect = web_list_side_effect

    mock_removed.return_value = []

    source_mock = MagicMock()
    source_mock.response_data = [
        make_entry(),
        {**make_entry(), 'object': {**make_entry()['object'], 'id': '2222222222222222222'}},
    ]
    mock_multi.return_value = source_mock

    ids, vra_scores = slw.fill_up()

    assert set(ids) == {'1234567890123456789', '2222222222222222222'}
    assert vra_scores == {'1234567890123456789': 9.5, '2222222222222222222': 9.5}

    _, kwargs = mock_multi.call_args
    assert set(kwargs['array_ids']) == {'1111111111111111111', '2222222222222222222'}


@patch("atlas_sao.saltListWizard.db.get_removed_atlas_ids_for_list")
@patch("atlas_sao.saltListWizard.ac.RequestMultipleSourceData")
@patch("atlas_sao.saltListWizard.ac.RequestATLASIDsFromWebServerList")
@patch("atlas_sao.saltListWizard.ac.RequestCustomListsTable")
def test_fill_up_excludes_already_in_salt_and_previously_removed(mock_table, mock_web_list, mock_multi, mock_removed):
    def table_side_effect(params, get_response=True):
        result = MagicMock()
        if params['objectgroupid'] == 14:
            result.response_data = [{'transient_object_id': '1111111111111111111', 'object_group_id': 14}]
        elif params['objectgroupid'] == 2:
            result.response_data = []
        return result
    mock_table.side_effect = table_side_effect

    def web_list_side_effect(list_name, dec_lte=None, **kwargs):
        result = MagicMock()
        if list_name == 'follow_up':
            result.atlas_id_list_str = ['1111111111111111111', '3333333333333333333']
        return result
    mock_web_list.side_effect = web_list_side_effect

    mock_removed.return_value = ['3333333333333333333']

    ids, vra_scores = slw.fill_up()

    assert ids == []
    mock_multi.assert_not_called()
