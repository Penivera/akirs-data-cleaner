"""Run with an isolated DATABASE_URL; never touches the application database."""
import os
import tempfile
from pathlib import Path

_test_dir = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_test_dir.name) / 'test.db')
os.environ['APP_ENV'] = 'development'
os.environ['SECRET_KEY'] = 'test-only-secret-key-at-least-32-characters'
os.environ['CLEANUP_ENABLED'] = 'false'

import pytest  # noqa: E402

from app.core.state import PRESETS  # noqa: E402
from app.services.cleaner import extract_records  # noqa: E402

FIELDS = PRESETS['retail']['fields']  # TAXPAYER_ID..DATE, includes NUBAN


def _write(rows):
    path = Path(_test_dir.name) / 'rows.csv'
    header = 'TIN,NAME,NUBAN,BVN,PHONE,ADDRESS,DATE'
    body = '\n'.join(','.join(str(c) for c in r) for r in rows)
    path.write_text(f'{header}\n{body}\n', encoding='utf-8')
    return str(path)


def _extract(path, **kwargs):
    mapped = {
        'TAXPAYER_ID': 'TIN', 'ACCOUNT_NAME': 'NAME', 'NUBAN': 'NUBAN',
        'BVN': 'BVN', 'PHONE': 'PHONE', 'ADDRESS': 'ADDRESS', 'DATE': 'DATE',
    }
    params = dict(
        mapped_fields=mapped, header_row_idx=0, selected_sheets=[''],
        selected_branches=[], account_name_concat_order={},
        account_name_concat_separator=' ', preset_name='retail',
        custom_fields=None, duplicate_logic='primary_key',
        primary_key_field='NUBAN', field_separators={},
    )
    params.update(kwargs)
    return extract_records(path, **params)


def _nuban_of(record):
    return record['values'][FIELDS.index('NUBAN')]


def _valid_row(nuban, tin='TIN0001', bvn='11111111111'):
    return [tin, 'Alice', nuban, bvn, '08030000001', '1 Example St', '2026-01-01']


def test_nine_digit_nuban_is_padded_and_kept():
    records, skipped = _extract(_write([_valid_row(123456789)]))
    assert len(records) == 1, 'a 9-digit NUBAN must not be dropped'
    assert skipped == []
    assert _nuban_of(records[0]) == '0123456789'


def test_padded_value_is_used_as_the_duplicate_key():
    """The padded value must reach the grouping key, so both spellings of the
    same account collapse into one cluster instead of two accounts."""
    records, _ = _extract(_write([_valid_row(123456789, 'TIN0001'),
                                  _valid_row('0123456789', 'TIN0002')]))
    assert len(records) == 2
    assert records[0]['nuban'] == '0123456789'
    assert records[1]['nuban'] == '0123456789'
    assert len({r['nuban'] for r in records}) == 1


def test_nine_digit_nuban_is_padded_in_a_custom_preset_too():
    """A custom preset that maps its own NUBAN target gets the same repair."""
    path = _write([_valid_row(123456789)])
    custom = ['NAME', 'NUBAN']
    records, skipped = extract_records(
        path,
        mapped_fields={'NAME': 'NAME', 'NUBAN': 'NUBAN'},
        header_row_idx=0, selected_sheets=[''], selected_branches=[],
        account_name_concat_order={}, account_name_concat_separator=' ',
        preset_name='custom', custom_fields=custom,
        duplicate_logic='primary_key', primary_key_field='NUBAN',
        field_separators={},
    )
    assert len(records) == 1
    assert records[0]['values'][custom.index('NUBAN')] == '0123456789'


@pytest.mark.parametrize('bad', ['12345678', '1234567', '123456789012', 'N/A', ''])
def test_other_lengths_are_still_rejected(bad):
    records, skipped = _extract(_write([_valid_row(bad)]))
    assert len(records) == 0, f'{bad!r} must not be accepted as a NUBAN'


def test_ten_digit_nubans_are_untouched():
    records, _ = _extract(_write([_valid_row('0123456789')]))
    assert _nuban_of(records[0]) == '0123456789'


def test_nine_digit_with_surrounding_whitespace_is_padded():
    records, _ = _extract(_write([['TIN0001', 'Alice', ' 123456789 ', '11111111111',
                                   '08030000001', '1 Example St', '2026-01-01']]))
    assert len(records) == 1
    assert _nuban_of(records[0]) == '0123456789'


def test_zero_prefixed_value_equals_the_padded_form():
    """'0123456789' and the padded '123456789' are the same account number."""
    rows = [_valid_row('0123456789', 'TIN0001'), _valid_row(123456789, 'TIN0002')]
    records, _ = _extract(_write(rows))
    assert {r['nuban'] for r in records} == {'0123456789'}
