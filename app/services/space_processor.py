"""Bulk processing of coworking space files (shared by Celery and the
in-process fallback)."""
import logging
import os
import shutil
from typing import List, Optional

from app.core import repository as repo
from app.core.config import settings
from app.core.executor import run_cpu
from app.core.state import PRESETS, get_user_cleaned_dir
from app.services.cleaner import (
    extract_records,
    find_duplicate_groups,
    resolve_duplicate_records,
    save_cleaned_records,
)
from app.services.mailer import notify_job_done

logger = logging.getLogger("app.cowork")


def _process_one_sync(state) -> int:
    """Process one space file in place; returns the number of output rows."""
    if state.preset_name == "custom":
        fields = state.custom_fields or []
    else:
        fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]

    records, skipped_records = extract_records(
        state.saved_path,
        state.mapped_fields,
        state.header_row_idx,
        state.selected_sheets,
        state.selected_branches,
        state.account_name_concat_order,
        state.account_name_concat_separator,
        state.preset_name,
        state.custom_fields,
        state.duplicate_logic,
        state.primary_key_field,
        getattr(state, "field_separators", None),
    )
    state.skipped_records = skipped_records

    duplicate_groups = find_duplicate_groups(
        records, state.duplicate_logic, state.primary_key_field, fields
    )
    if duplicate_groups:
        records = resolve_duplicate_records(records, duplicate_groups, "merge", [], fields)

    runner_id = state.processed_by or state.uploaded_by
    output_dir = get_user_cleaned_dir(runner_id)
    out_path = save_cleaned_records(
        state.saved_path, records, fields, state.output_pattern, output_dir=output_dir
    )

    state.cleaned_path = out_path
    state.result_filename = os.path.basename(out_path)
    return len(records)


async def process_space_files(
    task_id: str,
    space_id: str,
    file_ids: List[str],
    runner_user_id: int,
    owner_user_id: int,
    runner_email: Optional[str] = None,
    runner_name: Optional[str] = None,
    space_name: str = "",
    notify_email: bool = False,
) -> dict:
    """Process the given space files in bulk, updating the shared task state."""
    await repo.update_task(task_id, message="Starting...", status="processing")

    total = len(file_ids)
    done = 0
    failed = 0
    for index, file_id in enumerate(file_ids, start=1):
        state = await repo.get(repo.KIND_SPACE_FILE, file_id)
        if state is None or state.space_id != space_id:
            failed += 1
            continue

        await repo.update_task(
            task_id,
            message=f"Processing {index}/{total}: {state.original_filename}",
        )
        state.processed_by = runner_user_id
        try:
            row_count = await run_cpu(_process_one_sync, state)
            state.status = f"Processed ({row_count} rows)"
            state.processed_at = time_now()

            # Copy the result into the owner's cleaned directory too.
            if owner_user_id and owner_user_id != runner_user_id:
                await run_cpu(
                    _copy_result_to_owner,
                    state.cleaned_path,
                    get_user_cleaned_dir(owner_user_id),
                )
            done += 1
        except Exception as exc:  # pragma: no cover - defensive
            state.status = f"Failed ({exc})"
            failed += 1
        finally:
            await repo.put(repo.KIND_SPACE_FILE, state)

    summary = f"Bulk processing finished: {done}/{total} OK, {failed} failed"
    await repo.set_task(task_id, space_id, runner_user_id, "done", summary)

    if notify_email and runner_email:
        await run_cpu(
            notify_job_done,
            runner_email,
            runner_name or "there",
            space_name or "Coworking",
            total,
            settings.public_base_url,
            space_id,
        )
    return {"done": done, "failed": failed}


def time_now() -> float:
    import time

    return time.time()


def _copy_result_to_owner(result_path: Optional[str], owner_cleaned_dir: str) -> None:
    if not result_path or not os.path.exists(result_path):
        return
    os.makedirs(owner_cleaned_dir, exist_ok=True)
    target = os.path.join(owner_cleaned_dir, os.path.basename(result_path))
    if os.path.abspath(target) != os.path.abspath(result_path):
        shutil.copy2(result_path, target)
