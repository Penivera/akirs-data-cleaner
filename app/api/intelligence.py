from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Request, Depends
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import os
import time
from typing import List, Dict, Any

from app.core import repository as repo
from app.core.deps import get_current_user
from app.core.executor import run_cpu
from app.core.models import User
from app.core.state import IntelSyncState, PRESETS, get_user_upload_dir, get_user_cleaned_dir
from app.services.audit import log_audit
from app.services.uploads import ANALYSING_STATUS, stream_upload_to_disk
from app.services.validators import validate_upload
from app.services.cleaner import load_tabular_rows, find_header_row_and_headers_from_rows, save_cleaned_records, auto_map_headers, extract_records
from app.services.intelligence import check_file_records_against_db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/api/intel/view", response_class=HTMLResponse)
async def get_intel_view(request: Request, current_user: User = Depends(get_current_user)):
    user_files = await repo.list_for_user(repo.KIND_INTEL, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="partials/intelligence_view.html",
        context={"request": request, "files": user_files},
    )

@router.post("/api/intel/upload", response_class=HTMLResponse)
async def intel_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
):
    user_upload_dir = get_user_upload_dir(current_user.id)

    files_to_process = file if isinstance(file, list) else [file]
    processed_states = []
    now = time.time()

    for f in files_to_process:
        validate_upload(f)

        safe_filename = os.path.basename(f.filename).replace("..", "").replace("/", "_").replace("\\", "_")
        temp_path = os.path.join(user_upload_dir, f"intel_{safe_filename}")

        file_hash, file_size = await stream_upload_to_disk(f, temp_path)

        is_duplicate = False
        for existing_state in await repo.list_for_user(repo.KIND_INTEL, current_user.id):
            if (
                existing_state.original_filename == f.filename
                and existing_state.upload_hash == file_hash
                and existing_state.upload_size == file_size
            ):
                processed_states.append(existing_state)
                is_duplicate = True
                break

        if is_duplicate:
            os.remove(temp_path)
            continue

        state = IntelSyncState()
        state.user_id = current_user.id
        state.original_filename = f.filename
        state.saved_path = temp_path
        state.upload_hash = file_hash
        state.upload_size = file_size
        state.uploaded_at = now
        state.status = ANALYSING_STATUS

        task_id = f"ana_{state.id}"
        await repo.put(repo.KIND_INTEL, state)
        await repo.set_task(
            task_id, state.id, current_user.id, "processing", "Queued for analysis…"
        )
        background_tasks.add_task(
            _analyse_intel_background,
            file_id=state.id,
            user_id=current_user.id,
            task_id=task_id,
        )
        processed_states.append(state)
        await log_audit(
            "intel_upload",
            user=current_user,
            filename=state.original_filename,
            status=state.status,
            request=request,
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/intelligence_file_cards.html",
        context={"request": request, "files": processed_states},
    )


async def _analyse_intel_background(file_id: str, user_id: int, task_id: str) -> None:
    """Detect worksheets for an accepted intelligence-sync upload."""
    state = await repo.get(repo.KIND_INTEL, file_id)
    if not state or state.user_id != user_id:
        await repo.set_task(task_id, file_id, user_id, "failed", "File not found")
        return

    try:
        await repo.update_task(task_id, message="Detecting worksheets…")
        _, sheet_names = await run_cpu(load_tabular_rows, state.saved_path, "")
        state.sheet_names = sheet_names

        if len(sheet_names) > 1:
            state.status = "Needs Sheet"
        else:
            state.selected_sheets = [sheet_names[0]] if sheet_names else [""]
            state.status = "Needs Config"
    except Exception as e:
        state.status = f"Error: {str(e)}"

    # Deleted mid-analysis? repo.put() recreates a missing row, so bail out
    # rather than resurrecting a file the user removed.
    if await repo.get(repo.KIND_INTEL, file_id) is None:
        await repo.set_task(
            task_id, file_id, user_id, "failed", "Cancelled — file removed"
        )
        return

    await repo.put(repo.KIND_INTEL, state)
    failed = state.status.startswith(("Error", "Failed"))
    await repo.set_task(
        task_id, file_id, user_id, "failed" if failed else "done", state.status
    )
    await log_audit(
        "intel_analysed",
        user=None,
        filename=state.original_filename,
        status=state.status,
        detail=f"user_id={user_id}",
    )


@router.get("/api/intel/card/{file_id}", response_class=HTMLResponse)
async def get_intel_card(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    """Re-render one intelligence card (used to poll an in-progress analysis)."""
    state = await repo.get(repo.KIND_INTEL, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"
    return templates.TemplateResponse(
        request=request,
        name="partials/intelligence_file_card.html",
        context={"request": request, "file": state},
    )


@router.post("/api/intel/config-form/{file_id}", response_class=HTMLResponse)
async def get_intel_config_form(request: Request, file_id: str, current_user: User = Depends(get_current_user)):
    state = await repo.get(repo.KIND_INTEL, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"
        
    preview_rows = []
    if state.status != "Needs Sheet" and getattr(state, "header_row_idx", None) is not None:
        try:
            rows, _ = await run_cpu(
                load_tabular_rows,
                state.saved_path,
                state.selected_sheets[0] if state.selected_sheets else "",
            )
            preview_rows = rows[state.header_row_idx + 1 : state.header_row_idx + 4]
        except Exception:
            pass

    return templates.TemplateResponse(
        request=request,
        name="partials/intelligence_config_form.html",
        context={"request": request, "file": state, "preview_rows": preview_rows, "targets": PRESETS["intelligence"]["fields"]},
    )

@router.post("/api/intel/save-config/{file_id}", response_class=HTMLResponse)
async def save_intel_config(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    state = await repo.get(repo.KIND_INTEL, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"

    form_data = await request.form()

    state.verify_db_query_field = form_data.get("verify_db_query_field") or ""
    state.verify_db_target_column = form_data.get("verify_db_target_column") or "ANY"
    state.verify_db_fuzzy = form_data.get("verify_db_fuzzy") == "true"

    if form_data.getlist("selected_sheets"):
        state.selected_sheets = form_data.getlist("selected_sheets")
        await process_intel_sync(state, user_id=current_user.id)
        await repo.put(repo.KIND_INTEL, state)
        await log_audit(
            "intel_sync",
            user=current_user,
            filename=state.original_filename,
            status=state.status,
            request=request,
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/intelligence_file_card.html",
        context={"request": request, "file": state},
    )

@router.delete("/api/intel/delete/{file_id}")
async def delete_intel_file(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    state = await repo.get(repo.KIND_INTEL, file_id)
    if state is not None and state.user_id == current_user.id:
        # Delete physical files
        if state.saved_path and os.path.exists(state.saved_path):
            try:
                os.remove(state.saved_path)
            except OSError:
                pass
        if state.unique_path and os.path.exists(state.unique_path):
            try:
                os.remove(state.unique_path)
            except OSError:
                pass
        await repo.delete(repo.KIND_INTEL, file_id)
        await log_audit(
            "intel_delete",
            user=current_user,
            filename=state.original_filename,
            request=request,
        )
    return Response(status_code=200)

async def process_intel_sync(state: IntelSyncState, user_id: int = None):
    """
    Extracts records, auto-maps columns to the intelligence preset, checks them against the live DB,
    stores duplicates, and writes out a unique-only CSV.
    """
    rows, _ = await run_cpu(load_tabular_rows, state.saved_path, state.selected_sheets[0])
    idx, headers = await run_cpu(find_header_row_and_headers_from_rows, rows)
    state.headers = [h for h in headers if h]
    state.header_row_idx = idx

    fields = PRESETS["intelligence"]["fields"]
    mapped_fields, _ = auto_map_headers(state.headers, "intelligence")

    records, _ = await run_cpu(
        extract_records,
        state.saved_path,
        mapped_fields,
        state.header_row_idx,
        state.selected_sheets,
        selected_branches=[],
        account_name_concat_order={},
        account_name_concat_separator=" ",
        preset_name="intelligence",
        duplicate_logic="primary_key",
        primary_key_field="NAME",
    )

    # Parallel live database checking
    matches_zipped = await check_file_records_against_db(
        records,
        fields,
        query_field=getattr(state, "verify_db_query_field", ""),
        db_target_column=getattr(state, "verify_db_target_column", "ANY"),
        fuzzy_match=getattr(state, "verify_db_fuzzy", False)
    )

    matched_records = []
    unique_records = []

    for uploaded_rec, db_rec in matches_zipped:
        if db_rec:
            matched_records.append(db_rec)
        else:
            unique_records.append(uploaded_rec)

    state.matched_records = matched_records
    state.unique_records_count = len(unique_records)

    out_pattern = "CLEANED_UNIQUE_{filename}"
    output_dir = get_user_cleaned_dir(user_id) if user_id else "cleaned"
    out_path = await run_cpu(
        save_cleaned_records,
        state.saved_path,
        unique_records,
        fields,
        out_pattern,
        output_dir=output_dir,
    )

    state.unique_path = out_path
    state.unique_filename = os.path.basename(out_path)
    state.status = f"Synced ({len(unique_records)} unique, {len(matched_records)} existing)"
