from fastapi import APIRouter, UploadFile, File, Request, Form, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import hashlib
import os
import time
from io import BytesIO
from typing import Dict, Any, List

from app.core import repository as repo
from app.core.config import settings
from app.core.deps import get_current_user
from app.core.executor import run_cpu
from app.core.models import User
from app.core.state import (
    FileState,
    TARGET_FIELDS,
    PRESETS,
    get_user_upload_dir,
    get_user_cleaned_dir,
    get_user_reports_dir,
)
from app.services.audit import log_audit
from app.services.cleanup import remove_uploaded_file
from app.services.validators import validate_upload
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
async def read_index(request: Request, current_user: User = Depends(get_current_user)):
    user_files = await repo.list_for_user(repo.KIND_FILE, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, "files": user_files},
    )


@router.post("/api/upload", response_class=HTMLResponse)
async def upload_file(
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

        # Stream file to disk in chunks to avoid loading entire file into memory
        safe_filename = os.path.basename(f.filename).replace("..", "").replace("/", "_").replace("\\", "_")
        temp_path = os.path.join(user_upload_dir, safe_filename)

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
        for existing_state in await repo.list_for_user(repo.KIND_FILE, current_user.id):
            if (
                existing_state.original_filename == f.filename
                and getattr(existing_state, "upload_hash", "") == file_hash
                and getattr(existing_state, "upload_size", 0) == file_size
            ):
                processed_states.append(existing_state)
                is_duplicate = True
                break

        if is_duplicate:
            os.remove(temp_path)  # Clean up the duplicate file
            continue

        state = FileState()
        state.user_id = current_user.id
        state.original_filename = f.filename
        state.saved_path = temp_path
        state.upload_hash = file_hash
        state.upload_size = file_size
        state.uploaded_at = now

        # Run pre-flight health validator (CPU-bound: off the event loop)
        state.health_report = await run_cpu(pre_flight_validate, temp_path)

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

        # Analyze headers (CPU-bound: off the event loop)
        try:
            _, sheet_names = await run_cpu(load_tabular_rows, temp_path, "")
            state.sheet_names = sheet_names

            if len(sheet_names) > 1:
                state.status = "Needs Sheet"
            else:
                state.selected_sheets = [sheet_names[0]] if sheet_names else [""]
                rows, _ = await run_cpu(load_tabular_rows, temp_path, state.selected_sheets[0])
                idx, headers = await run_cpu(find_header_row_and_headers_from_rows, rows)
                state.headers = [h for h in headers if h]
                state.header_row_idx = idx

                # Run pre-flight check again with sheets if needed
                state.health_report = await run_cpu(
                    pre_flight_validate, temp_path, state.selected_sheets[0]
                )

                mapped_fields, status = auto_map_headers(state.headers, state.preset_name)
                state.mapped_fields = mapped_fields
                state.status = status
                state.available_branches = await run_cpu(
                    detect_distinct_branches,
                    state.headers,
                    rows,
                    idx,
                )

        except Exception as e:
            state.status = f"Error: {str(e)}"

        await repo.put(repo.KIND_FILE, state)
        processed_states.append(state)
        await log_audit(
            "upload",
            user=current_user,
            filename=state.original_filename,
            status=state.status,
            request=request,
        )

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
async def edit_mapping(request: Request, file_id: str, current_user: User = Depends(get_current_user)):
    state = await repo.get(repo.KIND_FILE, file_id)
    if not state or state.user_id != current_user.id:
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
            rows, _ = await run_cpu(
                load_tabular_rows,
                state.saved_path,
                state.selected_sheets[0] if state.selected_sheets else "",
            )
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
async def save_mapping(request: Request, file_id: str, current_user: User = Depends(get_current_user)):
    state = await repo.get(repo.KIND_FILE, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"

    form_data = await request.form()

    # Handle Sheet Selection
    if form_data.getlist("selected_sheets"):
        state.selected_sheets = form_data.getlist("selected_sheets")
        try:
            state.health_report = await run_cpu(
                pre_flight_validate, state.saved_path, state.selected_sheets[0]
            )
            rows, _ = await run_cpu(
                load_tabular_rows, state.saved_path, state.selected_sheets[0]
            )
            idx, headers = await run_cpu(find_header_row_and_headers_from_rows, rows)
            state.headers = [h for h in headers if h]
            state.header_row_idx = idx

            mapped_fields, status = auto_map_headers(state.headers, state.preset_name)
            state.mapped_fields = mapped_fields
            state.status = status
            state.available_branches = await run_cpu(
                detect_distinct_branches,
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
        state.verify_db_query_field = form_data.get("verify_db_query_field") or ""
        state.verify_db_target_column = form_data.get("verify_db_target_column") or "ANY"
        state.verify_db_fuzzy = form_data.get("verify_db_fuzzy") == "true"

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

    await repo.put(repo.KIND_FILE, state)
    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": fields},
    )


@router.delete("/api/delete/{file_id}")
async def delete_file(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    state = await repo.get(repo.KIND_FILE, file_id)
    if state is not None and state.user_id == current_user.id:
        # Delete the physical file
        if state.saved_path and os.path.exists(state.saved_path):
            try:
                os.remove(state.saved_path)
            except OSError:
                pass
        # Delete the cleaned output if it exists
        if state.cleaned_path and os.path.exists(state.cleaned_path):
            try:
                os.remove(state.cleaned_path)
            except OSError:
                pass
        await repo.delete(repo.KIND_FILE, file_id)
        await log_audit(
            "delete",
            user=current_user,
            filename=state.original_filename,
            request=request,
        )
    return Response(status_code=204)


@router.post("/api/process/{file_id}", response_class=HTMLResponse)
async def process_file(
    request: Request,
    file_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    state = await repo.get(repo.KIND_FILE, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"

    if state.preset_name == "custom":
        fields = state.custom_fields
    else:
        fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]

    # Mark as processing and queue background task
    state.status = "Processing..."
    task_id = f"proc_{state.id}"
    await repo.set_task(task_id, file_id, current_user.id, "processing", "Starting...")

    background_tasks.add_task(
        _process_file_background,
        file_id=file_id,
        user_id=current_user.id,
        task_id=task_id,
    )

    await repo.put(repo.KIND_FILE, state)
    await log_audit(
        "process_started",
        user=current_user,
        filename=state.original_filename,
        status="Processing...",
        request=request,
    )

    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": fields},
    )


async def _process_file_background(file_id: str, user_id: int, task_id: str):
    """Run the actual file processing in the background."""
    state = await repo.get(repo.KIND_FILE, file_id)
    if not state or state.user_id != user_id:
        await repo.set_task(task_id, file_id, user_id, "failed", "File not found")
        return

    if state.preset_name == "custom":
        fields = state.custom_fields
    else:
        fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]

    try:
        await repo.update_task(task_id, message="Extracting records...")
        records, skipped_records = await run_cpu(
            extract_records,
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

        await repo.update_task(task_id, message="Checking for duplicates...")
        duplicate_groups = await run_cpu(
            find_duplicate_groups, records, state.duplicate_logic, state.primary_key_field, fields
        )

        if duplicate_groups:
            state.extracted_records = records
            state.duplicate_groups = duplicate_groups
            state.status = f"Needs Duplicate Review ({len(duplicate_groups)} groups)"
            await repo.set_task(task_id, file_id, user_id, "done", state.status)
        else:
            # Check against live DB
            has_db_matches = False
            if getattr(state, "verify_db", False):
                await repo.update_task(task_id, message="Checking against live DB...")
                matches_zipped = await check_file_records_against_db(
                    records,
                    fields,
                    query_field=getattr(state, "verify_db_query_field", ""),
                    db_target_column=getattr(state, "verify_db_target_column", "ANY"),
                    fuzzy_match=getattr(state, "verify_db_fuzzy", False)
                )
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
                await repo.update_task(task_id, message="Writing cleaned file...")
                cleaned_dir = get_user_cleaned_dir(user_id)
                out_path = await run_cpu(
                    save_cleaned_records,
                    state.saved_path,
                    records,
                    fields,
                    state.output_pattern,
                    output_dir=cleaned_dir,
                )
                state.status = f"Processed ({len(records)} rows)"
                state.cleaned_path = out_path
                await repo.set_task(task_id, file_id, user_id, "done", state.status)
                await remove_uploaded_file(state.saved_path)

    except Exception as e:
        state.status = f"Failed ({str(e)})"
        await repo.set_task(task_id, file_id, user_id, "failed", str(e))

    await repo.put(repo.KIND_FILE, state)


@router.get("/api/task-status/{task_id}")
async def get_task_status(task_id: str, current_user: User = Depends(get_current_user)):
    """Poll the status of a background processing task."""
    task = await repo.get_task(task_id)
    if not task or task.get("user_id") != current_user.id:
        return {"status": "unknown", "message": "Task not found"}

    return {
        "status": task["status"],
        "file_id": task["file_id"],
        "message": task["message"],
    }


@router.post("/api/duplicates/{file_id}", response_class=HTMLResponse)
async def resolve_duplicates(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    state = await repo.get(repo.KIND_FILE, file_id)
    if not state or state.user_id != current_user.id:
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
        resolved_records = await run_cpu(
            resolve_duplicate_records,
            records,
            duplicate_groups,
            decision,
            accepted_record_ids,
            fields,
        )
        
        # Check resolved records against live DB
        has_db_matches = False
        if getattr(state, "verify_db", False):
            matches_zipped = await check_file_records_against_db(
                resolved_records,
                fields,
                query_field=getattr(state, "verify_db_query_field", ""),
                db_target_column=getattr(state, "verify_db_target_column", "ANY"),
                fuzzy_match=getattr(state, "verify_db_fuzzy", False)
            )
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
            cleaned_dir = get_user_cleaned_dir(current_user.id)
            out_path = await run_cpu(
                save_cleaned_records,
                state.saved_path,
                resolved_records,
                fields,
                state.output_pattern,
                output_dir=cleaned_dir,
            )
            state.status = f"Processed ({len(resolved_records)} rows)"
            state.cleaned_path = out_path
            state.duplicate_groups = []
            state.extracted_records = []
            await remove_uploaded_file(state.saved_path)
    except Exception as e:
        state.status = f"Failed ({str(e)})"

    await repo.put(repo.KIND_FILE, state)
    await log_audit(
        "resolve_duplicates",
        user=current_user,
        filename=state.original_filename,
        status=state.status,
        detail=decision,
        request=request,
    )
    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": fields},
    )


@router.post("/api/db-resolve/{file_id}", response_class=HTMLResponse)
async def resolve_db(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    state = await repo.get(repo.KIND_FILE, file_id)
    if not state or state.user_id != current_user.id:
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
        cleaned_dir = get_user_cleaned_dir(current_user.id)
        out_path = await run_cpu(
            save_cleaned_records,
            state.saved_path,
            final_records,
            fields,
            state.output_pattern,
            output_dir=cleaned_dir,
        )
        state.status = f"Processed ({len(final_records)} rows, {skipped_count} skipped)"
        state.cleaned_path = out_path
        state.db_matches = []
        state.extracted_records = []
        await remove_uploaded_file(state.saved_path)
    except Exception as e:
        state.status = f"Failed ({str(e)})"

    await repo.put(repo.KIND_FILE, state)
    await log_audit(
        "resolve_db",
        user=current_user,
        filename=state.original_filename,
        status=state.status,
        request=request,
    )
    return templates.TemplateResponse(
        request=request,
        name="partials/file_card.html",
        context={"request": request, "file": state, "targets": fields},
    )


@router.get("/api/view/process", response_class=HTMLResponse)
async def get_process_view(request: Request, current_user: User = Depends(get_current_user)):
    user_files = await repo.list_for_user(repo.KIND_FILE, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="partials/process_view.html",
        context={"request": request, "files": user_files},
    )


@router.get("/api/view/cleaned", response_class=HTMLResponse)
async def get_cleaned_view(request: Request, current_user: User = Depends(get_current_user)):
    files_info = []
    user_cleaned_dir = get_user_cleaned_dir(current_user.id)
    user_reports_dir = get_user_reports_dir(current_user.id)

    output_dirs = [
        {
            "path": user_cleaned_dir,
            "extensions": (".csv", ".xlsx"),
            "source": "Batch Cleaner",
            "download_prefix": "/api/download",
        },
        {
            "path": user_reports_dir,
            "extensions": (".md",),
            "source": "Analysis & Report",
            "download_prefix": "/api/analyse/download",
        },
    ]

    for output_dir in output_dirs:
        os.makedirs(output_dir["path"], exist_ok=True)
        for fname in os.listdir(output_dir["path"]):
            if not fname.endswith(output_dir["extensions"]):
                continue

            source = output_dir["source"]
            if "cleaned" in output_dir["path"] and fname.startswith("resolved_"):
                source = "NUBAN Resolver"

            fpath = os.path.join(output_dir["path"], fname)
            size_bytes = os.path.getsize(fpath)
            size_mb = round(size_bytes / (1024 * 1024), 2) if size_bytes > 0 else 0
            files_info.append(
                {
                    "name": fname,
                    "source": source,
                    "size": size_mb,
                    "download_url": f"{output_dir['download_prefix']}/{fname}",
                    "download_key": f"{output_dir['path']}/{fname}",
                }
            )

    files_info.sort(key=lambda x: (x["source"], x["name"]))

    return templates.TemplateResponse(
        request=request,
        name="partials/cleaned_view.html",
        context={"request": request, "cleaned_files": files_info},
    )


@router.get("/api/view/{file_id}", response_class=HTMLResponse)
async def view_data(request: Request, file_id: str, current_user: User = Depends(get_current_user)):
    import csv

    state = await repo.get(repo.KIND_FILE, file_id)
    if not state or state.user_id != current_user.id or not state.cleaned_path:
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
async def view_skipped(request: Request, file_id: str, current_user: User = Depends(get_current_user)):
    state = await repo.get(repo.KIND_FILE, file_id)
    if not state or state.user_id != current_user.id or getattr(state, "skipped_records", None) is None:
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
async def download_single(
    request: Request,
    filename: str,
    current_user: User = Depends(get_current_user),
):
    from fastapi.responses import FileResponse

    # Sanitize filename to prevent path traversal
    safe_filename = os.path.basename(filename).replace("..", "").replace("/", "_").replace("\\", "_")
    user_cleaned_dir = get_user_cleaned_dir(current_user.id)
    file_path = os.path.join(user_cleaned_dir, safe_filename)

    if os.path.exists(file_path):
        await log_audit("download", user=current_user, filename=safe_filename, request=request)
        return FileResponse(path=file_path, filename=safe_filename, media_type="text/csv")
    return HTMLResponse("File not found", status_code=404)


@router.post("/api/download-batch")
async def download_batch(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    from fastapi.responses import StreamingResponse
    import zipfile

    form_data = await request.form()
    selected_files = form_data.getlist("files")

    if not selected_files:
        return HTMLResponse("No files selected.", status_code=400)

    await log_audit(
        "download_batch",
        user=current_user,
        detail=", ".join(selected_files),
        request=request,
    )

    user_cleaned_dir = get_user_cleaned_dir(current_user.id)
    user_reports_dir = get_user_reports_dir(current_user.id)

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for selected_file in selected_files:
            folder, fname = os.path.split(selected_file)
            # Sanitize
            safe_fname = os.path.basename(fname).replace("..", "").replace("/", "_").replace("\\", "_")
            safe_folder = os.path.basename(folder)

            if safe_folder == "cleaned":
                file_path = os.path.join(user_cleaned_dir, safe_fname)
            elif safe_folder == "reports":
                file_path = os.path.join(user_reports_dir, safe_fname)
            else:
                continue

            if os.path.exists(file_path):
                zf.write(file_path, arcname=os.path.join(safe_folder, safe_fname))

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": "attachment; filename=AKIRS_Cleaned_Batch.zip"},
    )
