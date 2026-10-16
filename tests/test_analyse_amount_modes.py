"""Run with an isolated DATABASE_URL; never touches the application database."""
import os
import tempfile
from pathlib import Path

_test_dir = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_test_dir.name) / 'test.db')
os.environ['APP_ENV'] = 'development'
os.environ['ADMIN_PASSWORD'] = 'test-only-password-123'
os.environ['SECRET_KEY'] = 'test-only-secret-key-at-least-32-characters'
os.environ['DEBUG'] = 'false'
os.environ['ADMIN_EMAIL'] = 'admin@akirs.local'
# Disable the startup cleanup job so tests never touch the working directory's
# uploads/cleaned/cleaned/reports folders.
os.environ['CLEANUP_ENABLED'] = 'false'

import pytest  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.services.analyser import generate_markdown_report  # noqa: E402

HEADERS = ['Account', 'Amount', 'Direction', 'Credit', 'Debit']

# ACME uses the flow-column shape, BETA/GAMMA/DELTA use the credit/debit shape.
ROWS = [
    HEADERS,
    ['ACME', 100, 'CR', None, None],
    ['ACME', 40, 'DR', None, None],
    ['BETA', 0, '', 500, None],
    ['GAMMA', 0, '', None, 250],
    ['DELTA', 0, '', 300, 100],
]


def _report(config, rows=None):
    """Render a report from a config dict against the shared fixture rows."""
    state = SimpleNamespace(
        config=config, original_filename='statement.csv', selected_sheets=[]
    )
    return generate_markdown_report(state, rows if rows is not None else ROWS, 0)


def _net_total(report):
    for line in report.splitlines():
        if line.startswith('Net Total'):
            return float(line.rsplit(' ', 1)[1].replace('NGN', '').replace(',', ''))
    raise AssertionError('report has no net total line')


def _breakdown(report):
    """Return {account: (inflows, outflows)} from the ranked section."""
    found = {}
    account = None
    for line in report.splitlines():
        if ' - Net: ' in line:
            account = line.split(' - Net: ')[0].split('. ', 1)[-1]
        elif 'Inflows: ' in line and 'Outflows: ' in line and account:
            body = line.split('Inflows: ')[1]
            inflow = float(body.split(' | Outflows: ')[0].replace('NGN', '').replace(',', ''))
            outflow = float(body.split(' | Outflows: ')[1].replace('NGN', '').replace(',', ''))
            found[account] = (inflow, outflow)
    return found


def test_single_mode_sums_the_metric_column():
    report = _report(
        {'identity_col': 'Account', 'metric_col': 'Amount', 'amount_mode': 'single'}
    )
    # 100 + 40 + 0 + 0 + 0. The metric is summed raw; direction only decides
    # which way a row is booked, not the sign of its contribution.
    assert _net_total(report) == pytest.approx(140.0)
    assert 'Metric Analyzed: Amount' in report


def test_split_mode_nets_credit_against_debit():
    report = _report(
        {
            'identity_col': 'Account',
            'credit_col': 'Credit',
            'debit_col': 'Debit',
            'amount_mode': 'split',
        }
    )
    # 500 - 250 + (300 - 100) = 450
    assert _net_total(report) == pytest.approx(450.0)
    assert 'Metric Analyzed: Credit - Debit' in report


def test_split_mode_counts_both_sides_of_one_row():
    """A row with credit 300 and debit 100 is an inflow AND an outflow."""
    report = _report(
        {
            'identity_col': 'Account',
            'credit_col': 'Credit',
            'debit_col': 'Debit',
            'amount_mode': 'split',
        }
    )
    inflows, outflows = _breakdown(report)['DELTA']
    assert inflows == pytest.approx(300.0)
    assert outflows == pytest.approx(100.0)


def test_split_mode_does_not_book_an_empty_row_as_an_inflow():
    """A row with neither side populated moved no money. It previously fell into
    the sign-of-metric branch, was marked an inflow, and therefore slipped past
    the "Inflows only" filter while adding a 0.00 to the inflow total."""
    rows = [HEADERS, ['QUIET', 0, '', None, None], ['LOUD', 0, '', 700, None]]
    base = {
        'identity_col': 'Account',
        'credit_col': 'Credit',
        'debit_col': 'Debit',
        'amount_mode': 'split',
    }

    unfiltered = _report(base, rows)
    assert 'Total Inflows: NGN 700.00' in unfiltered
    assert _breakdown(unfiltered)['QUIET'] == (0.0, 0.0)

    inflows_only = _report({**base, 'flow_filter': 'Inflows Only'}, rows)
    # The flow filter drops rows that belong to neither direction, so only the
    # row that actually received money survives.
    assert 'Total Transactions Parsed: 1' in inflows_only
    assert 'LOUD' in inflows_only
    assert 'QUIET' not in _breakdown(inflows_only)


def test_chosen_mode_wins_over_a_stale_selection_in_the_other():
    """Editing a split config back to single must not keep summing the old pair."""
    stale = {
        'identity_col': 'Account',
        'metric_col': 'Amount',
        'credit_col': 'Credit',
        'debit_col': 'Debit',
        'flow_type_col': 'Direction',
        'amount_mode': 'single',
    }
    # Single mode must read Amount (140), ignoring the leftover credit/debit pair.
    assert _net_total(_report(stale)) == pytest.approx(140.0)

    # Switching to split must read the pair (450), ignoring the leftover metric.
    stale['amount_mode'] = 'split'
    assert _net_total(_report(stale)) == pytest.approx(450.0)


def test_legacy_config_without_a_mode_infers_split_from_its_columns():
    """Configs saved before the mode existed must still produce the same report."""
    legacy = {
        'identity_col': 'Account',
        'credit_col': 'Credit',
        'debit_col': 'Debit',
    }
    assert _net_total(_report(legacy)) == pytest.approx(450.0)
    assert 'Metric Analyzed: Credit - Debit' in _report(legacy)


def test_split_mode_requires_both_columns():
    with pytest.raises(ValueError, match='Credit column and a Debit column'):
        _report(
            {
                'identity_col': 'Account',
                'credit_col': 'Credit',
                'amount_mode': 'split',
            }
        )


def test_single_mode_requires_a_metric_column():
    with pytest.raises(ValueError, match='metric column'):
        _report({'identity_col': 'Account', 'amount_mode': 'single'})


def _ranked_names(report):
    """Names in the net-ranked list, i.e. the numbered '1. NAME - Net:' lines."""
    names = []
    for line in report.splitlines():
        stripped = line.strip()
        # Skip the movement register's own rows, which are formatted differently.
        if ' - Net: ' in stripped and stripped[0].isdigit():
            names.append(stripped.split(' - Net: ')[0].split('. ', 1)[1])
    return names


def test_minimum_filter_keeps_accounts_whose_net_is_exactly_zero():
    """A truthiness test on the total silently dropped zero-net accounts."""
    rows = [HEADERS, ['FLAT', 0, '', 400, 400]]
    base = {
        'identity_col': 'Account',
        'credit_col': 'Credit',
        'debit_col': 'Debit',
        'amount_mode': 'split',
    }
    # FLAT nets to exactly 0, so the net-ranked list drops it at a 0.01 floor...
    assert _ranked_names(_report({**base, 'min_amount_filter': 0.01}, rows)) == []
    # ...but it is present when no floor is set.
    assert _ranked_names(_report(base, rows)) == ['FLAT']


def test_cumulative_report_supports_split_mode():
    """NUBAN cumulative used to demand a metric column, so pairing it with
    credit/debit columns failed at generate time with no way to recover."""
    from app.services.analyser import generate_cumulative_report

    headers = ['Nuban', 'Amount', 'Credit', 'Debit']
    rows = [
        headers,
        ['0123', 0, 500, None],
        ['0123', 0, None, 200],
        ['0456', 0, None, None],
    ]
    state = SimpleNamespace(
        config={
            'nuban_col': 'Nuban',
            'credit_col': 'Credit',
            'debit_col': 'Debit',
            'amount_mode': 'split',
        },
        original_filename='statement.csv',
    )
    report = generate_cumulative_report(state, rows, 0)
    # 500 - 200 = 300 for 0123, and nothing for the row with neither side set.
    assert 'ACCOUNTS BY Credit - Debit' in report
    assert '0123 - Total: NGN 300.00' in report
    assert '0456 - Total: NGN 0.00' in report


def test_cumulative_report_still_requires_its_columns():
    from app.services.analyser import generate_cumulative_report

    headers = ['Nuban', 'Amount', 'Credit', 'Debit']
    rows = [headers, ['0123', 10, None, None]]
    with pytest.raises(ValueError, match='metric column'):
        generate_cumulative_report(
            SimpleNamespace(
                config={'nuban_col': 'Nuban', 'amount_mode': 'single'},
                original_filename='statement.csv',
            ),
            rows,
            0,
        )


def test_flow_column_markers_drive_direction_in_single_mode():
    rows = [
        HEADERS,
        ['ACME', 500, 'CR', None, None],
        ['ACME', 200, 'DR', None, None],
    ]
    report = _report(
        {
            'identity_col': 'Account',
            'metric_col': 'Amount',
            'flow_type_col': 'Direction',
            'amount_mode': 'single',
        },
        rows,
    )
    inflows, outflows = _breakdown(report)['ACME']
    assert inflows == pytest.approx(500.0)
    assert outflows == pytest.approx(200.0)


def test_custom_flow_markers_are_honoured():
    rows = [HEADERS, ['ACME', 750, 'MONEY IN', None, None]]
    report = _report(
        {
            'identity_col': 'Account',
            'metric_col': 'Amount',
            'flow_type_col': 'Direction',
            'inflow_indicator': 'MONEY IN',
            'amount_mode': 'single',
        },
        rows,
    )
    assert 'Inflows: NGN 750.00' in report
