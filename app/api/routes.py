from fastapi import APIRouter, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import hashlib
import os
import time
from io import BytesIO
from typing import Dict, Any, List

from app.core.state import file_db, FileState, TARGET_FIELDS
from app.services.cleaner import (
    auto_map_headers,
    extract_records,
    find_duplicate_groups,
    resolve_duplicate_records,
    save_cleaned_records,
    load_tabular_rows,
    find_header_row_and_headers_from_rows,
    detect_distinct_branches,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

DUPLICATE_UPLOAD_WINDOW_SECONDS = 5


@router.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, "files": file_db.values()},
    )


@router.post("/api/upload", response_class=HTMLResponse)
async def upload_file(request: Request, file: List[UploadFile] = File(...)):
    os.makedirs("uploads", exist_ok=True)
    
    files_to_process = file if isinstance(file, list) else [file]
    processed_states = []
    now = time.time()
    
    for f in files_to_process:
        file_bytes = await f.read()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        file_size = len(file_bytes)
        
        is_duplicate = False
        for existing_state in file_db.values():
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

        temp_path = os.path.join("uploads", f.filename)

        with open(temp_path, "wb") as file_out:
            file_out.write(file_bytes)

        state = FileState()
        state.original_filename = f.filename
        state.saved_path = temp_path
        state.upload_hash = file_hash
        state.upload_size = file_size
        state.uploaded_at = now

        # Analyze headers
        try:
            _, sheet_names = load_tabular_rows(temp_path, "")
            state.sheet_names = sheet_names

            if len(sheet_names) > 1:
                state.status = "Needs Sheet"
            else:
                if sheet_names:
                    state.selected_sheet = sheet_names[0]
                rows, _ = load_tabular_rows(temp_path, state.selected_sheet)
                idx, headers = find_header_row_and_headers_from_rows(rows)
                state.headers = [h for h in headers if h]
                state.header_row_idx = idx

                mapped_fields, status = auto_map_headers(state.headers)
                state.mapped_fields = mapped_fields
                state.status = status
                state.available_branches = detect_distinct_branches(
                    state.headers,
                    rows,
                    idx,
                )

        except Exception as e:
            state.status = f"Error: {str(e)}"

        file_db[state.id] = state
        processed_states.append(state)

    return templates.TemplateResponse(
        request=request,
        name="partials/file_cards.html",
        context={"request": request, "files": processed_states, "targets": TARGET_FIELDS},
    )


@router.post("/api/components/mapping/{file_id}", response_class=HTMLResponse)
async def edit_mapping(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"

    preview_rows = []
    if state.status != "Needs Sheet" and getattr(state, "header_row_idx", None) is not None:
        try:
            from app.services.cleaner import load_tabular_rows
            rows, _ = load_tabular_rows(state.saved_path, state.selected_sheet)
            preview_rows = rows[state.header_row_idx + 1 : state.header_row_idx + 4]
        except Exception:
            pass

    return templates.TemplateResponse(
        request=request,
        name="partials/mapping_form.html",
        context={"request": request, "file": state, "targets": TARGET_FIELDS, "preview_rows": preview_rows},
    )


@router.post("/api/mapping/{file_id}", response_class=HTMLResponse)
async def save_mapping(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"

    form_data = await request.form()

    # Handle Sheet Selection
    if (
        form_data.get("selected_sheet")
        and form_data.get("selected_sheet") in state.sheet_names
    ):
        state.selected_sheet = form_data.get("selected_sheet")
        # Proceed with parsing this sheet
        try:
            rows, _ = load_tabular_rows(state.saved_path, state.selected_sheet)
            idx, headers = find_header_row_and_headers_from_rows(rows)
            state.headers = [h for h in headers if h]
            state.header_row_idx = idx

            mapped_fields, status = auto_map_headers(state.headers)
            state.mapped_fields = mapped_fields
            state.status = status
            state.available_branches = detect_distinct_branches(
                state.headers,
                rows,
                idx,
            )
        except Exception as e:
            state.status = f"Error: {str(e)}"
    else:
        for target in TARGET_FIELDS:
            val = form_data.get(target)
            if val is not None:
                state.mapped_fields[target] = val

        if form_data.getlist("selected_branches"):
            state.selected_branches = form_data.getlist("selected_branches")

        # Check if all targets are mapped
        if all(state.mapped_fields.get(t) for t in TARGET_FIELDS):
            state.status = "Ready"
        else:
            state.status = "Needs Mapping"

    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": TARGET_FIELDS},
    )


@router.delete("/api/delete/{file_id}")
async def delete_file(file_id: str):
    if file_id in file_db:
        del file_db[file_id]
    return Response(status_code=204)


@router.post("/api/process/{file_id}", response_class=HTMLResponse)
async def process_file(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"

    try:
        records, skipped_records = extract_records(
            state.saved_path,
            state.mapped_fields,
            getattr(state, "header_row_idx", 3),
            state.selected_sheet,
            state.selected_branches,
        )
        state.skipped_records = skipped_records
        duplicate_groups = find_duplicate_groups(records)

        if duplicate_groups:
            state.extracted_records = records
            state.duplicate_groups = duplicate_groups
            state.status = f"Needs Duplicate Review ({len(duplicate_groups)} groups)"
        else:
            out_path = save_cleaned_records(state.saved_path, records)
            state.status = f"Processed ({len(records)} rows)"
            setattr(state, "cleaned_path", out_path)
    except Exception as e:
        state.status = f"Failed ({str(e)})"

    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": TARGET_FIELDS},
    )


@router.post("/api/duplicates/{file_id}", response_class=HTMLResponse)
async def resolve_duplicates(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"

    form_data = await request.form()
    decision = form_data.get("decision", "merge")
    accepted_record_ids = form_data.getlist("accepted_records")

    if decision not in {"merge", "pick"}:
        state.status = "Failed (Invalid duplicate handling option)"
        return templates.TemplateResponse(
            request=request,
            name="partials/file_card.html",
            context={"request": request, "file": state, "targets": TARGET_FIELDS},
        )

    if decision == "pick" and not accepted_record_ids:
        state.status = "Needs Duplicate Review (Pick at least one row)"
        return templates.TemplateResponse(
            request=request,
            name="partials/file_card.html",
            context={"request": request, "file": state, "targets": TARGET_FIELDS},
        )

    try:
        records = state.extracted_records or []
        duplicate_groups = state.duplicate_groups or []
        resolved_records = resolve_duplicate_records(
            records,
            duplicate_groups,
            decision,
            accepted_record_ids,
        )
        out_path = save_cleaned_records(state.saved_path, resolved_records)
        state.status = f"Processed ({len(resolved_records)} rows)"
        state.cleaned_path = out_path
        state.duplicate_groups = []
        state.extracted_records = []
    except Exception as e:
        state.status = f"Failed ({str(e)})"

    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": TARGET_FIELDS},
    )


@router.get("/api/view/process", response_class=HTMLResponse)
async def get_process_view(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="partials/process_view.html",
        context={"request": request, "files": file_db.values()},
    )


@router.get("/api/view/cleaned", response_class=HTMLResponse)
async def get_cleaned_view(request: Request):
    import math

    cleaned_dir = "cleaned"
    os.makedirs(cleaned_dir, exist_ok=True)
    files_info = []

    for fname in os.listdir(cleaned_dir):
        if fname.endswith(".csv") or fname.endswith(".xlsx"):
            fpath = os.path.join(cleaned_dir, fname)
            size_bytes = os.path.getsize(fpath)
            size_mb = round(size_bytes / (1024 * 1024), 2) if size_bytes > 0 else 0
            files_info.append({"name": fname, "size": size_mb})

    # Sort files by name or modified time if needed
    files_info.sort(key=lambda x: x["name"])

    return templates.TemplateResponse(
        request=request,
        name="partials/cleaned_view.html",
        context={"request": request, "cleaned_files": files_info},
    )


@router.get("/api/view/{file_id}", response_class=HTMLResponse)
async def view_data(request: Request, file_id: str):
    import csv

    state = file_db.get(file_id)
    if not state or not getattr(state, "cleaned_path", None):
        return "Not available"

    rows = []
    try:
        with open(state.cleaned_path, mode="r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i > 50:
                    break
                rows.append(row)
    except Exception:
        return "Error reading file"

    return templates.TemplateResponse(
        request=request,
        name="partials/data_view.html",
        context={"request": request, "file": state, "rows": rows},
    )


@router.get("/api/view-skipped/{file_id}", response_class=HTMLResponse)
async def view_skipped(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state or getattr(state, "skipped_records", None) is None:
        return "Not available"

    return templates.TemplateResponse(
        request=request,
        name="partials/skip_report.html",
        context={"request": request, "file": state, "targets": TARGET_FIELDS},
    )


@router.get("/api/download/{filename}")
async def download_single(filename: str):
    from fastapi.responses import FileResponse

    file_path = os.path.join("cleaned", filename)
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename, media_type="text/csv")
    return HTMLResponse("File not found", status_code=404)


@router.post("/api/download-batch")
async def download_batch(request: Request):
    from fastapi.responses import StreamingResponse
    import zipfile

    form_data = await request.form()
    selected_files = form_data.getlist("files")

    if not selected_files:
        return HTMLResponse("No files selected.", status_code=400)

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in selected_files:
            file_path = os.path.join("cleaned", fname)
            if os.path.exists(file_path):
                zf.write(file_path, arcname=fname)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": "attachment; filename=AKIRS_Cleaned_Batch.zip"},
    )
