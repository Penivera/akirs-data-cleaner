"""Run with an isolated DATABASE_URL; never touches the application database."""
import asyncio
import csv
import os
import tempfile
import types
from pathlib import Path

_test_dir = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_test_dir.name) / 'test.db')
os.environ['APP_ENV'] = 'development'
os.environ['SECRET_KEY'] = 'test-only-secret-key-at-least-32-characters'
os.environ['CLEANUP_ENABLED'] = 'false'

from app.core import state as state_mod  # noqa: E402
from app.core.state import NubanState  # noqa: E402
from app.services import nuban as nuban_svc  # noqa: E402


def _make_state(path):
    s = NubanState()
    s.saved_path = path
    # A truthy user_id makes the resolver route through get_user_cleaned_dir,
    # which is stubbed above; None would write into the real ./cleaned folder.
    s.user_id = 1
    s.selected_bank_code = '058'
    s.mapped_nuban_col = 'NUBAN'
    s.mapped_target_col = 'RESOLVED_NAME'
    s.selected_sheets = ['']
    s.header_row_idx = 0
    return s


async def _resolve(rows, seen):
    """Run the resolver with the payment keys and output dir stubbed out."""

    async def fake_resolve(account_number, bank_code):
        seen.append(account_number)
        return 'ACME HOLDINGS' if account_number == '0123456789' else None

    out_dir = tempfile.mkdtemp()
    orig_settings = nuban_svc.settings
    orig_resolve = nuban_svc.resolve_account
    orig_dir = state_mod.get_user_cleaned_dir
    nuban_svc.settings = types.SimpleNamespace(
        paystack_secret_key='test-key', flutterwave_secret_key=None,
    )
    nuban_svc.resolve_account = fake_resolve
    state_mod.get_user_cleaned_dir = lambda *a, **k: out_dir
    try:
        path = Path(_test_dir.name) / 'accounts.csv'
        with open(path, 'w', newline='', encoding='utf-8') as fh:
            csv.writer(fh).writerows(rows)
        await nuban_svc.process_nuban_resolution(_make_state(str(path)))
        produced = Path(out_dir) / f'resolved_{path.name}'
        with open(produced, newline='', encoding='utf-8') as fh:
            return list(csv.reader(fh))
    finally:
        nuban_svc.settings = orig_settings
        nuban_svc.resolve_account = orig_resolve
        state_mod.get_user_cleaned_dir = orig_dir


def _run(rows):
    seen = []
    produced = asyncio.run(_resolve(rows, seen))
    return seen, produced


def test_nine_digit_nuban_is_padded_and_resolved():
    seen, rows = _run([['NUBAN', 'RESOLVED_NAME'], ['123456789', '']])
    assert seen == ['0123456789'], 'the padded number must be the one resolved'
    assert rows[1][0] == '0123456789', 'output must show the corrected NUBAN'
    assert rows[1][1] == 'ACME HOLDINGS'


def test_ten_digit_nuban_still_resolves():
    seen, rows = _run([['NUBAN', 'RESOLVED_NAME'], ['0123456789', '']])
    assert seen == ['0123456789']
    assert rows[1][1] == 'ACME HOLDINGS'


def test_eight_digit_nuban_is_still_invalid():
    seen, rows = _run([['NUBAN', 'RESOLVED_NAME'], ['12345678', '']])
    assert seen == [], 'an 8-digit value must not be padded'
    assert rows[1][1] == 'Invalid NUBAN'


def test_row_with_other_data_but_no_nuban_is_invalid():
    seen, rows = _run([['NUBAN', 'NAME', 'RESOLVED_NAME'], ['', 'ALICE', '']])
    assert seen == []
    assert rows[1][2] == 'Invalid NUBAN'


def test_fully_blank_row_is_skipped_entirely():
    """A wholly empty row is dropped before it is ever classified."""
    seen, rows = _run([['NUBAN', 'NAME', 'RESOLVED_NAME'], ['', '', '']])
    assert seen == []
    assert len(rows) == 1, 'a blank row must not be written to the output'


def test_padded_value_that_fails_to_resolve_reports_failure_not_invalid():
    """Padding must not turn a genuinely unknown account into 'Invalid NUBAN'."""
    seen, rows = _run([['NUBAN', 'RESOLVED_NAME'], ['987654321', '']])
    assert seen == ['0987654321']
    assert rows[1][1] == 'Resolution Failed'
