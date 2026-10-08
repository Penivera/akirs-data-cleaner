import hashlib
import os
import time
from typing import List

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.core import repository as repo
from app.core.config import settings
from app.core.deps import get_current_user
from app.core.executor import run_cpu
from app.core.models import User
from app.core.state import AnalysisState, get_user_upload_dir, get_user_reports_dir
from app.services.analyser import process_analytics, process_cumulative_transactions
from app.services.audit import log_audit
from app.services.validators import validate_upload
from app.services.cleaner import (
    find_header_row_and_headers_from_rows,
    load_tabular_rows,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

DUPLICATE_UPLOAD_WINDOW_SECONDS = 5


@router.get("/api/analyse/view", response_class=HTMLResponse)
async def get_analyse_view(request: Request, current_user: User = Depends(get_current_user)):
    user_files = await repo.list_for_user(repo.KIND_ANALYSIS, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="partials/analyse_view.html",
        context={"request": request, "files": user_files},
    )


@router.post("/api/analyse/upload", response_class=HTMLResponse)
async def analyse_upload(
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
        temp_path = os.path.join(user_upload_dir, f"analytics_{safe_filename}")

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
        for existing_state in await repo.list_for_user(repo.KIND_ANALYSIS, current_user.id):
            if (
                existing_state.original_filename == f.filename
                and getattr(existing_state, "upload_hash", "") == file_hash
                and getattr(existing_state, "upload_size", 0) == file_size
            ):
                processed_states.append(existing_state)
                is_duplicate = True
                break

        if is_duplicate:
            os.remove(temp_path)
            continue

        state = AnalysisState()
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
                if sheet_names:
                    state.selected_sheets = [sheet_names[0]]
                rows, _ = await run_cpu(
                    load_tabular_rows,
                    temp_path,
                    state.selected_sheets[0] if state.selected_sheets else "",
                )
                if not rows:
                    state.status = "Error: CSV/Excel file is empty or could not be read."
                else:
                    idx, headers = await run_cpu(find_header_row_and_headers_from_rows, rows)
                    if not headers or idx is None:
                        state.status = "Error: Could not find header row. Ensure file has at least 3 named columns."
                    else:
                        state.headers = [h for h in headers if h]
                        state.header_row_idx = idx
                        state.status = "Ready"

        except Exception as e:
            state.status = f"Error: {str(e)}"

        await repo.put(repo.KIND_ANALYSIS, state)
        processed_states.append(state)
        await log_audit(
            "analyse_upload",
            user=current_user,
            filename=state.original_filename,
            status=state.status,
            request=request,
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/analyse_file_cards.html",
        context={"request": request, "files": processed_states},
    )


@router.post("/api/analyse/config/{file_id}", response_class=HTMLResponse)
async def analyse_config(request: Request, file_id: str, current_user: User = Depends(get_current_user)):
    state = await repo.get(repo.KIND_ANALYSIS, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"

    form_data = await request.form()

    # Check if this is a sheet selection submit
    if form_data.getlist("selected_sheets"):
        state.selected_sheets = form_data.getlist("selected_sheets")
        rows, _ = await run_cpu(load_tabular_rows, state.saved_path, state.selected_sheets[0])
        idx, headers = await run_cpu(find_header_row_and_headers_from_rows, rows)
        state.headers = [h for h in headers if h]
        state.header_row_idx = idx
        state.status = "Ready"
    else:
        # Validate that we have a usable status before saving config
        if state.status not in ["Ready", "Configured"]:
            return templates.TemplateResponse(
                request=request,
                name="partials/analyse_file_card.html",
                context={"request": request, "file": state},
            )
        # Save actual configuration
        state.config["identity_col"] = form_data.get("identity_col", "")
        state.config["metric_col"] = form_data.get("metric_col", "")
        state.config["currency_col"] = form_data.get("currency_col", "")
        state.config["flow_type_col"] = form_data.get("flow_type_col", "")
        state.config["inflow_indicator"] = form_data.get("inflow_indicator", "CR")
        state.config["outflow_indicator"] = form_data.get(
            "outflow_indicator", "DR"
        )
        # Save optional separate credit/debit column selections
        state.config["credit_col"] = form_data.get("credit_col", "")
        state.config["debit_col"] = form_data.get("debit_col", "")
        state.config["flow_filter"] = form_data.get("flow_filter", "All")
        # Handle limit: empty or 0 shows all records.
        limit_val = form_data.get("limit", "50").strip()
        try:
            state.config["limit"] = int(limit_val) if limit_val and limit_val != "0" else None
        except ValueError:
            state.config["limit"] = 50
        # Handle min_amount_filter: optional
        min_amount_val = form_data.get("min_amount_filter", "").replace(",", "").strip()
        try:
            state.config["min_amount_filter"] = (
                float(min_amount_val) if min_amount_val and min_amount_val != "." else None
            )
        except ValueError:
            state.config["min_amount_filter"] = None
        state.config["title"] = form_data.get("title", "DATA ANALYSIS REPORT")
        state.config["keep_columns"] = form_data.getlist("keep_columns")
        
        # Save full-name/account-name concatenation in the user's selection order.
        concat_columns = [col for col in form_data.getlist("concat_columns") if col]
        state.config["concat_columns"] = concat_columns
        state.config["concat_order"] = {
            col: str(idx + 1) for idx, col in enumerate(concat_columns)
        }

        # Keep supporting the old typed-order controls if an older form posts them.
        if not state.config["concat_order"]:
            for header in state.headers:
                order_val = form_data.get(f"concat_order_{header}", "").strip()
                if order_val:
                    state.config["concat_order"][header] = order_val
            state.config["concat_columns"] = [
                col
                for col, _ in sorted(
                    state.config["concat_order"].items(),
                    key=lambda item: int(item[1]) if str(item[1]).isdigit() else 999,
                )
            ]
        
        state.config["concat_separator"] = form_data.get("concat_separator", " ")
        # New: cumulative-by-nuban option and nuban column
        state.config["cumulate_by_nuban"] = (
            form_data.get("cumulate_by_nuban", "off") == "on"
        )
        state.config["nuban_col"] = form_data.get("nuban_col", "")

        # Consider configured when either metric is selected OR both credit+debit are selected, with identity provided
        has_metric = state.config["metric_col"]
        has_credit_debit = state.config["credit_col"] and state.config["debit_col"]
        has_identity = state.config["identity_col"] or state.config["concat_order"]
        
        if has_identity and (has_metric or has_credit_debit):
            state.status = "Configured"

    await repo.put(repo.KIND_ANALYSIS, state)
    return templates.TemplateResponse(
        request=request,
        name="partials/analyse_file_card.html",
        context={"request": request, "file": state},
    )


@router.post(
    "/api/analyse/components/config-form/{file_id}", response_class=HTMLResponse
)
async def get_config_form(request: Request, file_id: str, current_user: User = Depends(get_current_user)):
    state = await repo.get(repo.KIND_ANALYSIS, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"

    preview_rows = []
    if (
        state.status != "Needs Sheet"
        and getattr(state, "header_row_idx", None) is not None
    ):
        try:
            rows, _ = await run_cpu(
                load_tabular_rows,
                state.saved_path,
                state.selected_sheets[0] if state.selected_sheets else "",
            )
            preview_rows = rows[state.header_row_idx + 1 : state.header_row_idx + 4]
        except Exception:
            pass

    if state.config.get("concat_order") and not state.config.get("concat_columns"):
        state.config["concat_columns"] = [
            col
            for col, _ in sorted(
                state.config["concat_order"].items(),
                key=lambda item: int(item[1]) if str(item[1]).isdigit() else 999,
            )
        ]

    return templates.TemplateResponse(
        request=request,
        name="partials/analyse_config_form.html",
        context={"request": request, "file": state, "preview_rows": preview_rows},
    )


@router.post("/api/analyse/generate/{file_id}", response_class=HTMLResponse)
async def analyse_generate(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    state = await repo.get(repo.KIND_ANALYSIS, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"

    try:
        reports_dir = get_user_reports_dir(current_user.id)
        if state.config.get("cumulate_by_nuban"):
            report_path = await run_cpu(
                process_cumulative_transactions, state, output_dir=reports_dir
            )
        else:
            report_path = await run_cpu(
                process_analytics, state, output_dir=reports_dir
            )
        state.report_path = report_path
        state.report_filename = os.path.basename(report_path)
        state.status = "Generated"
    except Exception as e:
        state.status = f"Failed ({str(e)})"

    await repo.put(repo.KIND_ANALYSIS, state)
    await log_audit(
        "analyse_generate",
        user=current_user,
        filename=state.original_filename,
        status=state.status,
        request=request,
    )
    return templates.TemplateResponse(
        request=request,
        name="partials/analyse_file_card.html",
        context={"request": request, "file": state},
    )


@router.delete("/api/analyse/delete/{file_id}")
async def delete_analyse_file(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    state = await repo.get(repo.KIND_ANALYSIS, file_id)
    if state is not None and state.user_id == current_user.id:
        # Delete physical files
        if state.saved_path and os.path.exists(state.saved_path):
            try:
                os.remove(state.saved_path)
            except OSError:
                pass
        if state.report_path and os.path.exists(state.report_path):
            try:
                os.remove(state.report_path)
            except OSError:
                pass
        await repo.delete(repo.KIND_ANALYSIS, file_id)
        await log_audit(
            "analyse_delete",
            user=current_user,
            filename=state.original_filename,
            request=request,
        )
    return Response(status_code=204)


@router.get("/api/analyse/download/{filename}")
async def download_analysis(filename: str, current_user: User = Depends(get_current_user)):
    safe_filename = os.path.basename(filename).replace("..", "").replace("/", "_").replace("\\", "_")
    user_reports_dir = get_user_reports_dir(current_user.id)
    file_path = os.path.join(user_reports_dir, safe_filename)
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            filename=safe_filename,
            media_type="text/markdown",
            content_disposition_type="attachment",
        )
    return HTMLResponse("File not found", status_code=404)


@router.get("/api/analyse/view-report/{filename}")
async def view_analysis_report(filename: str, current_user: User = Depends(get_current_user)):
    safe_filename = os.path.basename(filename).replace("..", "").replace("/", "_").replace("\\", "_")
    user_reports_dir = get_user_reports_dir(current_user.id)
    file_path = os.path.join(user_reports_dir, safe_filename)
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            filename=safe_filename,
            media_type="text/markdown",
            content_disposition_type="inline",
        )
    return HTMLResponse("File not found", status_code=404)
