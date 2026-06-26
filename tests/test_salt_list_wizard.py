import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import saltListWizard as slw


def make_entry(detection_list_id=4, vra=9.5, sherlock_class='SN'):
    return {
        'object': {
            'id': '1234567890123456789',
            'detection_list_id': detection_list_id,
            'vra': vra,
            'sherlockClassification': sherlock_class,
        }
    }


class TestShouldAddToSalt:
    def test_passes_all_conditions(self):
        assert slw.should_add_to_salt(make_entry()) is True

    def test_fails_garbage(self):
        assert slw.should_add_to_salt(make_entry(detection_list_id=0)) is False

    def test_fails_vra_too_low(self):
        assert slw.should_add_to_salt(make_entry(vra=8.0)) is False

    def test_fails_vra_at_threshold(self):
        assert slw.should_add_to_salt(make_entry(vra=9.0)) is False

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


@patch("saltListWizard.ac.WriteToCustomList")
def test_add_targets_to_list_calls_write_once_with_array(mock_write):
    slw.add_targets_to_list(['1234567890123456789', '9876543210987654321'], 'salt')

    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert list(kwargs['array_ids']) == ['1234567890123456789', '9876543210987654321']
    assert isinstance(kwargs['array_ids'], np.ndarray)
    assert kwargs['list_name'] == 'salt'


@patch("saltListWizard.ac.WriteToCustomList")
def test_add_targets_to_list_noop_when_empty(mock_write):
    slw.add_targets_to_list([], 'salt')

    mock_write.assert_not_called()


@patch("saltListWizard.ac.RemoveFromCustomList")
def test_remove_targets_from_list_calls_remove_once_with_array_and_chunk_size(mock_remove):
    mock_remove.return_value = MagicMock()

    slw.remove_targets_from_list(['1234567890123456789'], 'salt')

    mock_remove.assert_called_once()
    _, kwargs = mock_remove.call_args
    assert list(kwargs['array_ids']) == ['1234567890123456789']
    assert isinstance(kwargs['array_ids'], np.ndarray)
    assert kwargs['list_name'] == 'salt'
    assert kwargs['chunk_size'] == 25
    mock_remove.return_value.get_response.assert_called_once()


@patch("saltListWizard.ac.RemoveFromCustomList")
def test_remove_targets_from_list_noop_when_empty(mock_remove):
    slw.remove_targets_from_list([], 'salt')

    mock_remove.assert_not_called()
