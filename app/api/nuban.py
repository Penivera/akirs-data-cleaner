from fastapi import APIRouter, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import hashlib
import os
import time
from typing import List

from app.core.state import nuban_db, NubanState
from app.services.cleaner import load_tabular_rows, find_header_row_and_headers_from_rows
from app.services.nuban import get_bank_list, process_nuban_resolution

router = APIRouter()
templates = Jinja2Templates(directory="templates")

DUPLICATE_UPLOAD_WINDOW_SECONDS = 5

@router.get("/api/nuban/view", response_class=HTMLResponse)
async def get_nuban_view(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="partials/nuban_view.html",
        context={"request": request, "files": nuban_db.values()},
    )

@router.post("/api/nuban/upload", response_class=HTMLResponse)
async def nuban_upload(request: Request, file: List[UploadFile] = File(...)):
    os.makedirs("uploads", exist_ok=True)
    
    files_to_process = file if isinstance(file, list) else [file]
    processed_states = []
    now = time.time()
    
    for f in files_to_process:
        file_bytes = await f.read()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        file_size = len(file_bytes)
        
        is_duplicate = False
        for existing_state in nuban_db.values():
            if (
                existing_state.original_filename == f.filename
                and getattr(existing_state, "upload_hash", "") == file_hash
                and getattr(existing_state, "upload_size", 0) == file_size
                and (now - getattr(existing_state, "uploaded_at", 0.0))
                <= DUPLICATE_UPLOAD_WINDOW_SECONDS
            ):
                processed_states.append(existing_state)
                is_duplicate = True
                break
                
        if is_duplicate:
            continue

        temp_path = os.path.join("uploads", f"nuban_{f.filename}")

        with open(temp_path, "wb") as file_out:
            file_out.write(file_bytes)

        state = NubanState()
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
                rows, _ = load_tabular_rows(temp_path, state.selected_sheets[0])
                idx, headers = find_header_row_and_headers_from_rows(rows)
                state.headers = [h for h in headers if h]
                state.header_row_idx = idx
                state.status = "Ready"

        except Exception as e:
            state.status = f"Error: {str(e)}"

        nuban_db[state.id] = state
        processed_states.append(state)

    return templates.TemplateResponse(
        request=request,
        name="partials/nuban_file_cards.html",
        context={"request": request, "files": processed_states},
    )

@router.post("/api/nuban/config-form/{file_id}", response_class=HTMLResponse)
async def get_nuban_config_form(request: Request, file_id: str):
    state = nuban_db.get(file_id)
    if not state:
        return "File not found"
        
    banks = await get_bank_list()
    
    preview_rows = []
    if state.status != "Needs Sheet" and getattr(state, "header_row_idx", None) is not None:
        try:
            rows, _ = load_tabular_rows(state.saved_path, state.selected_sheets[0] if state.selected_sheets else "")
            preview_rows = rows[state.header_row_idx + 1 : state.header_row_idx + 4]
        except Exception:
            pass

    return templates.TemplateResponse(
        request=request,
        name="partials/nuban_config_form.html",
        context={"request": request, "file": state, "banks": banks, "preview_rows": preview_rows},
    )

@router.post("/api/nuban/save-config/{file_id}", response_class=HTMLResponse)
async def save_nuban_config(request: Request, file_id: str):
    state = nuban_db.get(file_id)
    if not state:
        return "File not found"
        
    form_data = await request.form()
    
    if form_data.getlist("selected_sheets"):
        state.selected_sheets = form_data.getlist("selected_sheets")
        rows, _ = load_tabular_rows(state.saved_path, state.selected_sheets[0])
        idx, headers = find_header_row_and_headers_from_rows(rows)
        state.headers = [h for h in headers if h]
        state.header_row_idx = idx
        state.status = "Ready"
    else:
        state.mapped_nuban_col = form_data.get("nuban_col", "")
        state.mapped_target_col = form_data.get("target_col", "")
        state.selected_bank_code = form_data.get("bank_code", "")
        
        if state.mapped_nuban_col and state.mapped_target_col and state.selected_bank_code:
            state.status = "Configured"

    return templates.TemplateResponse(
        request=request,
        name="partials/nuban_file_card.html",
        context={"request": request, "file": state},
    )

@router.post("/api/nuban/resolve/{file_id}", response_class=HTMLResponse)
async def resolve_nuban_action(request: Request, file_id: str):
    state = nuban_db.get(file_id)
    if not state:
        return "File not found"

    state.status = "Resolving..."
    # Note: For production, this should be a background task
    try:
        await process_nuban_resolution(state)
        state.status = "Resolved"
    except Exception as e:
        state.status = f"Failed ({str(e)})"
        
    return templates.TemplateResponse(
        request=request,
        name="partials/nuban_file_card.html",
        context={"request": request, "file": state},
    )

@router.delete("/api/nuban/delete/{file_id}")
async def delete_nuban_file(file_id: str):
    if file_id in nuban_db:
        del nuban_db[file_id]
    return Response(status_code=204)
