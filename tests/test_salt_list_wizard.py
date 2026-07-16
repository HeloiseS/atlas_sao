from unittest.mock import MagicMock, patch

import numpy as np

import atlas_sao.saltListWizard as slw


def make_entry(detection_list_id=4, vra=9.5, sherlock_class='SN', dec=-30.0):
    return {
        'object': {
            'id': '1234567890123456789',
            'detection_list_id': detection_list_id,
            'vra': vra,
            'sherlockClassification': sherlock_class,
            'dec': dec,
        }
    }


class TestShouldAddToSalt:
    def test_passes_all_conditions(self):
        assert slw.should_add_to_salt(make_entry()) is True

    def test_fails_garbage(self):
        assert slw.should_add_to_salt(make_entry(detection_list_id=0)) is False

    def test_fails_vra_none(self):
        entry = make_entry()
        entry['object']['vra'] = None
        assert slw.should_add_to_salt(entry) is False

    def test_fails_vra_too_low(self):
        assert slw.should_add_to_salt(make_entry(vra=8.0)) is False

    def test_fails_vra_at_threshold(self):
        assert slw.should_add_to_salt(make_entry(vra=9.0)) is False

    def test_fails_too_far_north(self):
        assert slw.should_add_to_salt(make_entry(dec=10.0)) is False
        assert slw.should_add_to_salt(make_entry(dec=45.0)) is False

    def test_fails_orphan(self):
        assert slw.should_add_to_salt(make_entry(sherlock_class='ORPHAN')) is False

    def test_passes_missing_sherlock(self):
        entry = make_entry()
        del entry['object']['sherlockClassification']
        assert slw.should_add_to_salt(entry) is True

    def test_custom_vra_threshold(self):
        assert slw.should_add_to_salt(make_entry(vra=9.5), vra_threshold=9.5) is False
        assert slw.should_add_to_salt(make_entry(vra=9.6), vra_threshold=9.5) is True

    def test_custom_sherlock_exclude(self):
        assert slw.should_add_to_salt(make_entry(sherlock_class='SN'), sherlock_exclude='SN') is False


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
@patch("atlas_sao.saltListWizard.ac.RequestATLASIDsFromWebServerList")
@patch("atlas_sao.saltListWizard.ac.RequestCustomListsTable")
def test_fill_up_returns_ids_and_vra_scores(mock_table, mock_eyeball, mock_multi):
    mock_table.return_value.response_data = []

    eyeball_mock = MagicMock()
    eyeball_mock.atlas_id_list_str = ['1234567890123456789']
    mock_eyeball.return_value = eyeball_mock

    source_mock = MagicMock()
    source_mock.response_data = [make_entry(vra=9.5)]
    mock_multi.return_value = source_mock

    ids, vra_scores = slw.fill_up()

    assert ids == ['1234567890123456789']
    assert vra_scores == {'1234567890123456789': 9.5}

    _, kwargs = mock_eyeball.call_args
    assert kwargs['list_name'] == 'eyeball'
    assert kwargs['vra_gte'] == slw.SALT_VRA_THRESHOLD
    assert kwargs['dec_lte'] == slw.SALT_DEC_MAX
