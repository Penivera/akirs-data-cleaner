from fastapi import APIRouter, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.templating import Jinja2Templates
import hashlib
import os
import time
from typing import List

from app.core.state import analysis_db, AnalysisState
from app.services.cleaner import load_tabular_rows, find_header_row_and_headers_from_rows
from app.services.analyser import process_analytics

router = APIRouter()
templates = Jinja2Templates(directory="templates")

DUPLICATE_UPLOAD_WINDOW_SECONDS = 5

@router.get("/api/analyse/view", response_class=HTMLResponse)
async def get_analyse_view(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="partials/analyse_view.html",
        context={"request": request, "files": analysis_db.values()},
    )

@router.post("/api/analyse/upload", response_class=HTMLResponse)
async def analyse_upload(request: Request, file: List[UploadFile] = File(...)):
    os.makedirs("uploads", exist_ok=True)
    
    files_to_process = file if isinstance(file, list) else [file]
    processed_states = []
    now = time.time()
    
    for f in files_to_process:
        file_bytes = await f.read()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        file_size = len(file_bytes)
        
        is_duplicate = False
        for existing_state in analysis_db.values():
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

        temp_path = os.path.join("uploads", f"analytics_{f.filename}")

        with open(temp_path, "wb") as file_out:
            file_out.write(file_bytes)

        state = AnalysisState()
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
                if sheet_names:
                    state.selected_sheets = [sheet_names[0]]
                rows, _ = load_tabular_rows(temp_path, state.selected_sheets[0] if state.selected_sheets else "")
                idx, headers = find_header_row_and_headers_from_rows(rows)
                state.headers = [h for h in headers if h]
                state.header_row_idx = idx
                state.status = "Ready"

        except Exception as e:
            state.status = f"Error: {str(e)}"

        analysis_db[state.id] = state
        processed_states.append(state)

    return templates.TemplateResponse(
        request=request,
        name="partials/analyse_file_cards.html",
        context={"request": request, "files": processed_states},
    )

@router.post("/api/analyse/config/{file_id}", response_class=HTMLResponse)
async def analyse_config(request: Request, file_id: str):
    state = analysis_db.get(file_id)
    if not state:
        return "File not found"
        
    form_data = await request.form()
    
    # Check if this is a sheet selection submit
    if form_data.getlist("selected_sheets"):
        state.selected_sheets = form_data.getlist("selected_sheets")
        rows, _ = load_tabular_rows(state.saved_path, state.selected_sheets[0])
        idx, headers = find_header_row_and_headers_from_rows(rows)
        state.headers = [h for h in headers if h]
        state.header_row_idx = idx
        state.status = "Ready"
    else:
        # Save actual configuration
        state.config["identity_col"] = form_data.get("identity_col", "")
        state.config["metric_col"] = form_data.get("metric_col", "")
        state.config["currency_col"] = form_data.get("currency_col", "")
        state.config["flow_type_col"] = form_data.get("flow_type_col", "")
        state.config["inflow_indicator"] = form_data.get("inflow_indicator", "INFLOW")
        state.config["outflow_indicator"] = form_data.get("outflow_indicator", "OUTFLOW")
        state.config["flow_filter"] = form_data.get("flow_filter", "All")
        state.config["limit"] = int(form_data.get("limit", 50))
        state.config["title"] = form_data.get("title", "DATA ANALYSIS REPORT")
        state.config["keep_columns"] = form_data.getlist("keep_columns")
        
        if state.config["identity_col"] and state.config["metric_col"]:
            state.status = "Configured"

    return templates.TemplateResponse(
        request=request,
        name="partials/analyse_file_card.html",
        context={"request": request, "file": state},
    )
    
@router.post("/api/analyse/components/config-form/{file_id}", response_class=HTMLResponse)
async def get_config_form(request: Request, file_id: str):
    state = analysis_db.get(file_id)
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
        name="partials/analyse_config_form.html",
        context={"request": request, "file": state, "preview_rows": preview_rows},
    )

@router.post("/api/analyse/generate/{file_id}", response_class=HTMLResponse)
async def analyse_generate(request: Request, file_id: str):
    state = analysis_db.get(file_id)
    if not state:
        return "File not found"

    try:
        report_path = process_analytics(state)
        state.report_path = report_path
        state.status = "Generated"
    except Exception as e:
        state.status = f"Failed ({str(e)})"
        
    return templates.TemplateResponse(
        request=request,
        name="partials/analyse_file_card.html",
        context={"request": request, "file": state},
    )

@router.delete("/api/analyse/delete/{file_id}")
async def delete_analyse_file(file_id: str):
    if file_id in analysis_db:
        del analysis_db[file_id]
    return Response(status_code=204)

@router.get("/api/analyse/download/{filename}")
async def download_analysis(filename: str):
    file_path = os.path.join("reports", filename)
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path, 
            filename=filename, 
            media_type="text/markdown",
            content_disposition_type="attachment"
        )
    return HTMLResponse(f"File not found on disk at {file_path}", status_code=404)
