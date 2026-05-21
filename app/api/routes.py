from fastapi import APIRouter, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import hashlib
import os
import time
from io import BytesIO
from typing import Dict, Any, List

from app.core.state import file_db, FileState, TARGET_FIELDS, PRESETS
from app.services.cleaner import (
    auto_map_headers,
    extract_records,
    find_duplicate_groups,
    resolve_duplicate_records,
    save_cleaned_records,
    load_tabular_rows,
    find_header_row_and_headers_from_rows,
    detect_distinct_branches,
    pre_flight_validate,
)
from app.services.intelligence import check_file_records_against_db

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
            ):
                processed_states.append(existing_state)
                is_duplicate = True
                break
                
        if is_duplicate:
            continue

        temp_path = os.path.join("uploads", os.path.basename(f.filename))

        with open(temp_path, "wb") as file_out:
            file_out.write(file_bytes)

        state = FileState()
        state.original_filename = f.filename
        state.saved_path = temp_path
        state.upload_hash = file_hash
        state.upload_size = file_size
        state.uploaded_at = now

        # Run pre-flight health validator
        state.health_report = pre_flight_validate(temp_path)

        # Smart auto-detection of preset
        if "intel" in f.filename.lower():
            state.preset_name = "intelligence"
            state.duplicate_logic = "weirdly_similar"
            state.primary_key_field = ""
            state.output_pattern = "INTELIGENCE_GATHERING_{filename}"
        else:
            state.preset_name = "retail"
            state.duplicate_logic = "primary_key"
            state.primary_key_field = "NUBAN"
            state.output_pattern = "{filename}"

        # Analyze headers
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

                # Run pre-flight check again with sheets if needed
                state.health_report = pre_flight_validate(temp_path, state.selected_sheets[0])

                mapped_fields, status = auto_map_headers(state.headers, state.preset_name)
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

    # Determine display targets for cards
    card_targets = TARGET_FIELDS
    for s in processed_states:
        if s.preset_name == "custom":
            card_targets = s.custom_fields
        else:
            card_targets = PRESETS.get(s.preset_name, PRESETS["retail"])["fields"]

    return templates.TemplateResponse(
        request=request,
        name="partials/file_cards.html",
        context={"request": request, "files": processed_states, "targets": card_targets, "presets": PRESETS},
    )


@router.post("/api/components/mapping/{file_id}", response_class=HTMLResponse)
async def edit_mapping(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"

    preset_arg = request.query_params.get("preset")
    if preset_arg and preset_arg in ["retail", "intelligence", "custom"]:
        state.preset_name = preset_arg
        if preset_arg == "retail":
            state.duplicate_logic = "primary_key"
            state.primary_key_field = "NUBAN"
            state.output_pattern = "{filename}"
        elif preset_arg == "intelligence":
            state.duplicate_logic = "weirdly_similar"
            state.primary_key_field = ""
            state.output_pattern = "INTELIGENCE_GATHERING_{filename}"
        elif preset_arg == "custom":
            state.duplicate_logic = "primary_key"
            state.primary_key_field = ""
            state.output_pattern = "CUSTOM_{filename}"
            state.custom_fields = ["NAME", "PHONE", "IDENTITY"]

        # Run auto mapping for the newly selected preset
        mapped_fields, status = auto_map_headers(state.headers, state.preset_name, state.custom_fields)
        state.mapped_fields = mapped_fields
        state.status = status
    else:
        # Check if form data has updated custom fields
        try:
            form_data = await request.form()
            if form_data.get("custom_fields"):
                custom_raw = form_data.get("custom_fields")
                state.custom_fields = [f.strip().upper() for f in custom_raw.split(",") if f.strip()]
                mapped_fields, status = auto_map_headers(state.headers, state.preset_name, state.custom_fields)
                state.mapped_fields = mapped_fields
                state.status = status
        except Exception:
            pass

    preview_rows = []
    if state.status != "Needs Sheet" and getattr(state, "header_row_idx", None) is not None:
        try:
            rows, _ = load_tabular_rows(state.saved_path, state.selected_sheets[0] if state.selected_sheets else "")
            # Limit preview rows to 10 for performance
            preview_rows = rows[state.header_row_idx + 1 : state.header_row_idx + 11]
        except Exception:
            pass

    if state.preset_name == "custom":
        fields = state.custom_fields
    else:
        fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]

    return templates.TemplateResponse(
        request=request,
        name="partials/mapping_form.html",
        context={"request": request, "file": state, "targets": fields, "preview_rows": preview_rows, "presets": PRESETS},
    )


@router.post("/api/mapping/{file_id}", response_class=HTMLResponse)
async def save_mapping(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"

    form_data = await request.form()

    # Handle Sheet Selection
    if form_data.getlist("selected_sheets"):
        state.selected_sheets = form_data.getlist("selected_sheets")
        try:
            state.health_report = pre_flight_validate(state.saved_path, state.selected_sheets[0])
            rows, _ = load_tabular_rows(state.saved_path, state.selected_sheets[0])
            idx, headers = find_header_row_and_headers_from_rows(rows)
            state.headers = [h for h in headers if h]
            state.header_row_idx = idx

            mapped_fields, status = auto_map_headers(state.headers, state.preset_name)
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
        # Load preset preferences
        state.preset_name = form_data.get("preset_name", "retail")
        state.duplicate_logic = form_data.get("duplicate_logic", "primary_key")
        state.primary_key_field = form_data.get("primary_key_field") or ""
        state.output_pattern = form_data.get("output_pattern") or "{filename}"
        state.verify_db = form_data.get("verify_db") == "true"

        if state.preset_name == "custom":
            custom_raw = form_data.get("custom_fields", "")
            state.custom_fields = [f.strip().upper() for f in custom_raw.split(",") if f.strip()]
            fields = state.custom_fields
        else:
            fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]
            state.custom_fields = []

        # Read fields from mapping inputs
        state.mapped_fields = {}
        state.field_separators = {}
        for target in fields:
            val = form_data.getlist(target)
            val = [v for v in val if v]
            if not val:
                state.mapped_fields[target] = ""
            elif len(val) == 1:
                state.mapped_fields[target] = val[0]
            else:
                state.mapped_fields[target] = val
                
            sep = form_data.get(f"separator_{target}", " ")
            state.field_separators[target] = sep if sep else " "

        if form_data.getlist("selected_branches"):
            state.selected_branches = form_data.getlist("selected_branches")
        else:
            state.selected_branches = []

        # Save account name concatenation order configuration (backwards compatibility)
        state.account_name_concat_order = {}
        for header in state.headers:
            order_val = form_data.get(f"account_name_concat_order_{header}", "").strip()
            if order_val:
                state.account_name_concat_order[header] = order_val
        
        # Save account name concatenation separator
        sep = form_data.get("account_name_concat_separator", " ")
        state.account_name_concat_separator = sep if sep else " "

        # Check if all targets are mapped
        if all(state.mapped_fields.get(t) for t in fields):
            state.status = "Ready"
        else:
            state.status = "Needs Mapping"

    if state.preset_name == "custom":
        fields = state.custom_fields
    else:
        fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]

    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": fields},
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

    if state.preset_name == "custom":
        fields = state.custom_fields
    else:
        fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]

    try:
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
        duplicate_groups = find_duplicate_groups(records, state.duplicate_logic, state.primary_key_field, fields)

        if duplicate_groups:
            state.extracted_records = records
            state.duplicate_groups = duplicate_groups
            state.status = f"Needs Duplicate Review ({len(duplicate_groups)} groups)"
        else:
            # Check against live DB
            has_db_matches = False
            if getattr(state, "verify_db", False):
                matches_zipped = await check_file_records_against_db(records, fields)
                db_matches = []
                for uploaded_rec, db_rec in matches_zipped:
                    if db_rec:
                        db_matches.append({
                            "uploaded": uploaded_rec,
                            "existing": db_rec
                        })
                if db_matches:
                    state.extracted_records = records
                    state.db_matches = db_matches
                    state.status = f"Needs DB Review ({len(db_matches)} matches)"
                    has_db_matches = True
            
            if not has_db_matches:
                out_path = save_cleaned_records(state.saved_path, records, fields, state.output_pattern)
                state.status = f"Processed ({len(records)} rows)"
                setattr(state, "cleaned_path", out_path)
    except Exception as e:
        state.status = f"Failed ({str(e)})"

    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": fields},
    )


@router.post("/api/duplicates/{file_id}", response_class=HTMLResponse)
async def resolve_duplicates(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"

    if state.preset_name == "custom":
        fields = state.custom_fields
    else:
        fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]

    form_data = await request.form()
    decision = form_data.get("decision", "merge")
    accepted_record_ids = form_data.getlist("accepted_records")

    if decision not in {"merge", "pick"}:
        state.status = "Failed (Invalid duplicate handling option)"
        return templates.TemplateResponse(
            request=request,
            name="partials/file_card.html",
            context={"request": request, "file": state, "targets": fields},
        )

    if decision == "pick" and not accepted_record_ids:
        state.status = "Needs Duplicate Review (Pick at least one row)"
        return templates.TemplateResponse(
            request=request,
            name="partials/file_card.html",
            context={"request": request, "file": state, "targets": fields},
        )

    try:
        records = state.extracted_records or []
        duplicate_groups = state.duplicate_groups or []
        resolved_records = resolve_duplicate_records(
            records,
            duplicate_groups,
            decision,
            accepted_record_ids,
            fields,
        )
        
        # Check resolved records against live DB
        has_db_matches = False
        if getattr(state, "verify_db", False):
            matches_zipped = await check_file_records_against_db(resolved_records, fields)
            db_matches = []
            for uploaded_rec, db_rec in matches_zipped:
                if db_rec:
                    db_matches.append({
                        "uploaded": uploaded_rec,
                        "existing": db_rec
                    })
            if db_matches:
                state.extracted_records = resolved_records
                state.db_matches = db_matches
                state.status = f"Needs DB Review ({len(db_matches)} matches)"
                has_db_matches = True
                
        if not has_db_matches:
            out_path = save_cleaned_records(state.saved_path, resolved_records, fields, state.output_pattern)
            state.status = f"Processed ({len(resolved_records)} rows)"
            state.cleaned_path = out_path
            state.duplicate_groups = []
            state.extracted_records = []
    except Exception as e:
        state.status = f"Failed ({str(e)})"

    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": fields},
    )


@router.post("/api/db-resolve/{file_id}", response_class=HTMLResponse)
async def resolve_db(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"

    if state.preset_name == "custom":
        fields = state.custom_fields
    else:
        fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]

    form_data = await request.form()
    
    # Filter out skipped records
    final_records = []
    skipped_count = 0
    
    # Store decisions
    state.db_decisions = {}
    for match in getattr(state, "db_matches", []):
        uploaded_id = match["uploaded"]["id"]
        dec = form_data.get(f"decision_{uploaded_id}", "skip")
        state.db_decisions[uploaded_id] = dec
        
    for rec in getattr(state, "extracted_records", []):
        rec_id = rec["id"]
        if rec_id in state.db_decisions:
            if state.db_decisions[rec_id] == "skip":
                skipped_count += 1
                continue
        final_records.append(rec)
        
    try:
        out_path = save_cleaned_records(state.saved_path, final_records, fields, state.output_pattern)
        state.status = f"Processed ({len(final_records)} rows, {skipped_count} skipped)"
        state.cleaned_path = out_path
        state.db_matches = []
        state.extracted_records = []
    except Exception as e:
        state.status = f"Failed ({str(e)})"
        
    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": fields},
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

    if state.preset_name == "custom":
        fields = state.custom_fields
    else:
        fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]

    return templates.TemplateResponse(
        request=request,
        name="partials/skip_report.html",
        context={"request": request, "file": state, "targets": fields},
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
