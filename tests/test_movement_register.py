"""Movement register: legs recorded individually, never netted."""
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, '.')
from app.services.analyser import generate_markdown_report  # noqa: E402

HEADERS = ['Account', 'Nuban', 'Name', 'Credit', 'Debit']

# Two accounts under one name, plus a perfectly offsetting single account.
ROWS = [
    HEADERS,
    ['A', '001', 'JASHUB VENTURES', 140_000_000, 136_120_303.25],
    ['A', '002', 'JASHUB VENTURES', 100_000_000, 100_107_675.50],
    ['B', '003', 'FLAT CO', 400_000_000, 400_000_000],
    ['C', '004', 'BIG SPENDER', 0, 900_000_000],
]


def _report(config, rows=None):
    state = SimpleNamespace(
        config=config, original_filename='statement.csv', selected_sheets=[]
    )
    return generate_markdown_report(state, rows if rows is not None else ROWS, 0)


BASE = {
    'identity_col': 'Name',
    'credit_col': 'Credit',
    'debit_col': 'Debit',
    'amount_mode': 'split',
}


def _register(report):
    """The movement register section, up to the ranked list."""
    start = report.index('MOVEMENT REGISTER')
    end = report.index('TOP ', start) if 'TOP ' in report[start:] else len(report)
    return report[start:end]


#: rank, account, then four right-aligned figures, then the name.
_ROW = re.compile(
    r'^\s*(\d+)\s+(\S+)\s+'
    r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+(.*)$'
)


def _account_table(report):
    """Just the numbered per-account rows of the register."""
    rows = []
    for line in _register(report).splitlines():
        match = _ROW.match(line)
        if match:
            rows.append(
                {
                    'rank': match.group(1),
                    'account': match.group(2),
                    'credit': match.group(3),
                    'debit': match.group(4),
                    'gross': match.group(5),
                    'largest': match.group(6),
                    'name': match.group(7),
                }
            )
    return rows


def test_offsetting_activity_is_still_recorded():
    """A 400M-in/400M-out account nets to zero. Netting it away would hide it."""
    report = _register(_report({**BASE, 'movement_identity_col': 'Nuban'}))
    assert 'Accounts recorded: 4' in report
    # Both legs of the offsetting account appear, at full value.
    assert '400,000,000.00' in report
    assert 'OFFSETTING ACTIVITY' in report
    assert 'FLAT CO' in report


def test_each_leg_is_recorded_as_its_own_entry():
    register = _register(_report({**BASE, 'movement_identity_col': 'Nuban'}))
    # 4 rows x 2 sides, minus the one row with no credit: 7 legs.
    assert 'Individual legs recorded: 7' in register
    # The 900M debit is a movement in its own right, on an account with no credit.
    assert 'Debit    NGN 900,000,000.00' in register
    # Both legs of the offsetting account are kept, not collapsed to its net.
    assert 'Credit   NGN 400,000,000.00' in register
    assert 'Debit    NGN 400,000,000.00' in register


def test_accounts_keyed_by_account_are_not_pooled_by_name():
    """Two NUBANs under one name must stay separate so they are not summed."""
    table = _account_table(_report({**BASE, 'movement_identity_col': 'Nuban'}))
    jashub = [row for row in table if 'JASHUB' in row['name']]
    # Two separate register rows, one per account, not one pooled row.
    assert len(jashub) == 2
    assert {row['account'] for row in jashub} == {'001', '002'}


def test_threshold_is_applied_per_leg_not_to_the_net():
    """The 900M debit must be caught even though that account nets to -900M."""
    report = _register(
        _report(
            {
                **BASE,
                'movement_identity_col': 'Nuban',
                'movement_threshold': 500_000_000,
            }
        )
    )
    assert 'Movement threshold: NGN 500,000,000.00' in report
    # Only the single 900M leg is at or above 500M. The 400M pair drops out,
    # which is the point: the threshold judges each leg, not the net.
    assert 'Individual legs recorded: 1' in report
    assert '900,000,000.00' in report
    assert 'FLAT CO' not in report


def test_ordering_modes_answer_different_questions():
    """Each mode surfaces a different account, because they measure different
    things. Credit turnover is the assessable base; the largest single leg and
    gross both surface the account that only pays out."""
    firsts = {}
    for mode in ('credit', 'largest', 'gross'):
        table = _account_table(
            _report(
                {
                    **BASE,
                    'movement_identity_col': 'Nuban',
                    'movement_sort': mode,
                }
            )
        )
        firsts[mode] = table[0]['account']

    # FLAT CO has the most credit (400M), so credit turnover ranks it first.
    assert firsts['credit'] == '003'
    # BIG SPENDER only ever pays out, so it leads on gross and on largest leg.
    assert firsts['largest'] == '004'
    assert firsts['gross'] == '004'


def test_all_three_measures_are_shown_for_every_account():
    """Credit, gross and largest are columns, so no ordering hides a figure."""
    register = _register(_report({**BASE, 'movement_identity_col': 'Nuban'}))
    assert 'Credit' in register and 'Debit' in register
    assert 'Gross' in register and 'Largest' in register
    assert 'Ordered by: credit turnover (the assessable base)' in register


def test_legs_carry_their_source_row_for_traceability():
    report = _report({**BASE, 'movement_identity_col': 'Nuban'})
    assert 'Row    2' in report
    assert 'Row    3' in report


def test_register_falls_back_to_grouping_by_name():
    report = _register(_report(BASE))
    assert 'Accounts keyed by:' not in report
    # Pooled by name: three distinct names, not four accounts.
    assert 'Accounts recorded: 3' in report


def test_no_movement_config_still_produces_a_register():
    """Older configs must not crash or silently lose the section."""
    report = _register(_report(BASE))
    assert 'Accounts recorded: 3' in report
    assert 'Individual legs recorded: 7' in report


def test_negative_limit_is_clamped_not_sliced_from_the_end():
    """TOP -35 came from [:limit] with limit=-35, which drops the wrong rows."""
    from app.services.analyser import generate_markdown_report as gen

    state = SimpleNamespace(
        config={**BASE, 'identity_col': 'Name', 'limit': -35},
        original_filename='s.csv',
    )
    report = gen(state, ROWS, 0)
    assert 'TOP -35' not in report
    # A negative limit is treated as "no limit" rather than a reversed slice.
    assert 'ALL RECORDS BY' in report
    assert 'FLAT CO' in report
