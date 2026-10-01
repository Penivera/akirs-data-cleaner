from fastapi import APIRouter, UploadFile, File, Request, Depends
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import hashlib
import os
import time
from typing import List, Dict, Any

from app.core import repository as repo
from app.core.config import settings
from app.core.deps import get_current_user
from app.core.executor import run_cpu
from app.core.models import User
from app.core.state import IntelSyncState, PRESETS, get_user_upload_dir, get_user_cleaned_dir
from app.services.audit import log_audit
from app.services.validators import validate_upload
from app.services.cleaner import load_tabular_rows, find_header_row_and_headers_from_rows, save_cleaned_records, auto_map_headers, extract_records
from app.services.intelligence import check_file_records_against_db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/api/intel/view", response_class=HTMLResponse)
async def get_intel_view(request: Request, current_user: User = Depends(get_current_user)):
    user_files = repo.list_for_user(repo.KIND_INTEL, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="partials/intelligence_view.html",
        context={"request": request, "files": user_files},
    )

@router.post("/api/intel/upload", response_class=HTMLResponse)
async def intel_upload(
    request: Request,
    file: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
):
    user_upload_dir = get_user_upload_dir(current_user.id)

    files_to_process = file if isinstance(file, list) else [file]
    processed_states = []
    now = time.time()

    for f in files_to_process:
        validate_upload(f)

        # Stream file to disk in chunks
        safe_filename = os.path.basename(f.filename).replace("..", "").replace("/", "_").replace("\\", "_")
        temp_path = os.path.join(user_upload_dir, f"intel_{safe_filename}")

        hasher = hashlib.sha256()
        file_size = 0
        max_size_bytes = settings.max_upload_size_mb * 1024 * 1024

        with open(temp_path, "wb") as file_out:
            while chunk := await f.read(1024 * 1024):  # 1MB chunks
                file_size += len(chunk)
                if file_size > max_size_bytes:
                    file_out.close()
                    os.remove(temp_path)
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=413,
                        detail=f"File size exceeds the maximum allowed size of {settings.max_upload_size_mb}MB",
                    )
                hasher.update(chunk)
                file_out.write(chunk)

        file_hash = hasher.hexdigest()

        is_duplicate = False
        for existing_state in repo.list_for_user(repo.KIND_INTEL, current_user.id):
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

        try:
            _, sheet_names = await run_cpu(load_tabular_rows, temp_path, "")
            state.sheet_names = sheet_names

            if len(sheet_names) > 1:
                state.status = "Needs Sheet"
            else:
                state.selected_sheets = [sheet_names[0]] if sheet_names else [""]
                state.status = "Needs Config"

        except Exception as e:
            state.status = f"Error: {str(e)}"

        repo.put(repo.KIND_INTEL, state)
        processed_states.append(state)
        log_audit(
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

@router.post("/api/intel/config-form/{file_id}", response_class=HTMLResponse)
async def get_intel_config_form(request: Request, file_id: str, current_user: User = Depends(get_current_user)):
    state = repo.get(repo.KIND_INTEL, file_id)
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
    state = repo.get(repo.KIND_INTEL, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"

    form_data = await request.form()

    state.verify_db_query_field = form_data.get("verify_db_query_field") or ""
    state.verify_db_target_column = form_data.get("verify_db_target_column") or "ANY"
    state.verify_db_fuzzy = form_data.get("verify_db_fuzzy") == "true"

    if form_data.getlist("selected_sheets"):
        state.selected_sheets = form_data.getlist("selected_sheets")
        await process_intel_sync(state, user_id=current_user.id)
        repo.put(repo.KIND_INTEL, state)
        log_audit(
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
    state = repo.get(repo.KIND_INTEL, file_id)
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
        repo.delete(repo.KIND_INTEL, file_id)
        log_audit(
            "intel_delete",
            user=current_user,
            filename=state.original_filename,
            request=request,
        )
    return Response(status_code=204)

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
