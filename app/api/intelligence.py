from fastapi import APIRouter, UploadFile, File, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import hashlib
import os
import time
from typing import List, Dict, Any

from app.core.state import intelsync_db, IntelSyncState, PRESETS, save_all_states
from app.services.cleaner import load_tabular_rows, find_header_row_and_headers_from_rows, save_cleaned_records, auto_map_headers, extract_records
from app.services.intelligence import check_file_records_against_db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/api/intel/view", response_class=HTMLResponse)
async def get_intel_view(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="partials/intelligence_view.html",
        context={"request": request, "files": intelsync_db.values()},
    )

@router.post("/api/intel/upload", response_class=HTMLResponse)
async def intel_upload(request: Request, file: List[UploadFile] = File(...)):
    os.makedirs("uploads", exist_ok=True)
    
    files_to_process = file if isinstance(file, list) else [file]
    processed_states = []
    now = time.time()
    
    for f in files_to_process:
        file_bytes = await f.read()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        file_size = len(file_bytes)
        
        is_duplicate = False
        for existing_state in intelsync_db.values():
            if (
                existing_state.original_filename == f.filename
                and existing_state.upload_hash == file_hash
                and existing_state.upload_size == file_size
            ):
                processed_states.append(existing_state)
                is_duplicate = True
                break
                
        if is_duplicate:
            continue

        temp_path = os.path.join("uploads", f"intel_{os.path.basename(f.filename)}")

        with open(temp_path, "wb") as file_out:
            file_out.write(file_bytes)

        state = IntelSyncState()
        state.original_filename = f.filename
        state.saved_path = temp_path
        state.upload_hash = file_hash
        state.upload_size = file_size
        state.uploaded_at = now

        try:
            _, sheet_names = load_tabular_rows(temp_path, "")
            state.sheet_names = sheet_names

            if len(sheet_names) > 1:
                state.status = "Needs Sheet"
            else:
                state.selected_sheets = [sheet_names[0]] if sheet_names else [""]
                state.status = "Needs Config"

        except Exception as e:
            state.status = f"Error: {str(e)}"

        intelsync_db[state.id] = state
        save_all_states()
        processed_states.append(state)

    return templates.TemplateResponse(
        request=request,
        name="partials/intelligence_file_cards.html",
        context={"request": request, "files": processed_states},
    )

@router.post("/api/intel/config-form/{file_id}", response_class=HTMLResponse)
async def get_intel_config_form(request: Request, file_id: str):
    state = intelsync_db.get(file_id)
    if not state:
        return "File not found"
        
    preview_rows = []
    if state.status != "Needs Sheet" and getattr(state, "header_row_idx", None) is not None:
        try:
            rows, _ = load_tabular_rows(state.saved_path, state.selected_sheets[0] if state.selected_sheets else "")
            preview_rows = rows[state.header_row_idx + 1 : state.header_row_idx + 4]
        except Exception:
            pass

    return templates.TemplateResponse(
        request=request,
        name="partials/intelligence_config_form.html",
        context={"request": request, "file": state, "preview_rows": preview_rows, "targets": PRESETS["intelligence"]["fields"]},
    )

@router.post("/api/intel/save-config/{file_id}", response_class=HTMLResponse)
async def save_intel_config(request: Request, file_id: str):
    state = intelsync_db.get(file_id)
    if not state:
        return "File not found"
        
    form_data = await request.form()
    
    state.verify_db_query_field = form_data.get("verify_db_query_field") or ""
    state.verify_db_target_column = form_data.get("verify_db_target_column") or "ANY"
    state.verify_db_fuzzy = form_data.get("verify_db_fuzzy") == "true"
    
    if form_data.getlist("selected_sheets"):
        state.selected_sheets = form_data.getlist("selected_sheets")
        await process_intel_sync(state)
        save_all_states()

    return templates.TemplateResponse(
        request=request,
        name="partials/intelligence_file_card.html",
        context={"request": request, "file": state},
    )

@router.delete("/api/intel/delete/{file_id}")
async def delete_intel_file(file_id: str):
    if file_id in intelsync_db:
        del intelsync_db[file_id]
        save_all_states()
    return Response(status_code=204)

async def process_intel_sync(state: IntelSyncState):
    """
    Extracts records, auto-maps columns to the intelligence preset, checks them against the live DB,
    stores duplicates, and writes out a unique-only CSV.
    """
    rows, _ = load_tabular_rows(state.saved_path, state.selected_sheets[0])
    idx, headers = find_header_row_and_headers_from_rows(rows)
    state.headers = [h for h in headers if h]
    state.header_row_idx = idx

    fields = PRESETS["intelligence"]["fields"]
    mapped_fields, _ = auto_map_headers(state.headers, "intelligence")
    
    records, _ = extract_records(
        state.saved_path,
        mapped_fields,
        state.header_row_idx,
        state.selected_sheets,
        selected_branches=[],
        account_name_concat_order={},
        account_name_concat_separator=" ",
        preset_name="intelligence",
        duplicate_logic="primary_key",
        primary_key_field="NAME"
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
    out_path = save_cleaned_records(state.saved_path, unique_records, fields, out_pattern)
    
    state.unique_path = out_path
    state.unique_filename = os.path.basename(out_path)
    state.status = f"Synced ({len(unique_records)} unique, {len(matched_records)} existing)"
