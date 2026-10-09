import os
import time
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.core import repository as repo
from app.core.deps import get_current_user
from app.core.executor import run_cpu
from app.core.models import User
from app.core.state import AnalysisState, get_user_upload_dir, get_user_reports_dir
from app.services.analyser import (
    MOVEMENT_SORT_LABELS,
    process_analytics,
    process_cumulative_transactions,
)
from app.services.audit import log_audit
from app.services.uploads import ANALYSING_STATUS, stream_upload_to_disk
from app.services.validators import validate_upload
from app.services.cleaner import (
    find_header_row_and_headers_from_rows,
    load_tabular_rows,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

DUPLICATE_UPLOAD_WINDOW_SECONDS = 5

#: Orderings the movement register accepts.
MOVEMENT_SORTS = tuple(MOVEMENT_SORT_LABELS)


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
        temp_path = os.path.join(user_upload_dir, f"analytics_{safe_filename}")

        file_hash, file_size = await stream_upload_to_disk(f, temp_path)

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
        state.status = ANALYSING_STATUS

        task_id = f"ana_{state.id}"
        await repo.put(repo.KIND_ANALYSIS, state)
        await repo.set_task(
            task_id, state.id, current_user.id, "processing", "Queued for analysis…"
        )
        background_tasks.add_task(
            _analyse_analysis_background,
            file_id=state.id,
            user_id=current_user.id,
            task_id=task_id,
        )
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


async def _analyse_analysis_background(file_id: str, user_id: int, task_id: str) -> None:
    """Detect sheets and headers for an accepted analytics upload."""
    state = await repo.get(repo.KIND_ANALYSIS, file_id)
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
            if sheet_names:
                state.selected_sheets = [sheet_names[0]]
            await repo.update_task(task_id, message="Reading rows…")
            rows, _ = await run_cpu(
                load_tabular_rows,
                state.saved_path,
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

    # Deleted mid-analysis? repo.put() recreates a missing row, so bail out
    # rather than resurrecting a file the user removed.
    if await repo.get(repo.KIND_ANALYSIS, file_id) is None:
        await repo.set_task(
            task_id, file_id, user_id, "failed", "Cancelled — file removed"
        )
        return

    await repo.put(repo.KIND_ANALYSIS, state)
    failed = state.status.startswith(("Error", "Failed"))
    await repo.set_task(
        task_id, file_id, user_id, "failed" if failed else "done", state.status
    )
    await log_audit(
        "analyse_analysed",
        user=None,
        filename=state.original_filename,
        status=state.status,
        detail=f"user_id={user_id}",
    )


@router.get("/api/analyse/card/{file_id}", response_class=HTMLResponse)
async def get_analyse_card(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    """Re-render one analytics card (used to poll an in-progress analysis)."""
    state = await repo.get(repo.KIND_ANALYSIS, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"
    return templates.TemplateResponse(
        request=request,
        name="partials/analyse_file_card.html",
        context={"request": request, "file": state},
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
        state.config["metric_col"] = form_data.get("metric_col", "").strip()
        state.config["currency_col"] = form_data.get("currency_col", "")
        state.config["flow_type_col"] = form_data.get("flow_type_col", "")
        # Save optional separate credit/debit column selections
        state.config["credit_col"] = form_data.get("credit_col", "").strip()
        state.config["debit_col"] = form_data.get("debit_col", "").strip()
        state.config["flow_filter"] = form_data.get("flow_filter", "All")
        # Handle limit: empty or 0 shows all records. A negative value used to
        # reach the report as [:limit], which sliced from the end and printed
        # "TOP -35", so it is rejected here rather than clamped downstream.
        limit_val = form_data.get("limit", "50").strip()
        try:
            parsed_limit = int(limit_val) if limit_val and limit_val != "0" else None
        except ValueError:
            parsed_limit = 50
        if parsed_limit is not None and parsed_limit < 1:
            state.config["config_error"] = (
                "Limit must be 1 or more. Leave it blank to include every record."
            )
            parsed_limit = None
        else:
            state.config.pop("config_error", None)
        state.config["limit"] = parsed_limit
        # Handle min_amount_filter: optional
        min_amount_val = form_data.get("min_amount_filter", "").replace(",", "").strip()
        try:
            state.config["min_amount_filter"] = (
                float(min_amount_val) if min_amount_val and min_amount_val != "." else None
            )
        except ValueError:
            state.config["min_amount_filter"] = None

        # Movement register: legs recorded individually, never netted. The
        # threshold is per leg, so a large debit cannot hide behind a small net.
        threshold_val = (
            form_data.get("movement_threshold", "").replace(",", "").strip()
        )
        try:
            state.config["movement_threshold"] = (
                float(threshold_val) if threshold_val and threshold_val != "." else None
            )
        except ValueError:
            state.config["movement_threshold"] = None
        movement_sort = form_data.get("movement_sort", "credit")
        state.config["movement_sort"] = (
            movement_sort if movement_sort in MOVEMENT_SORTS else "credit"
        )
        # Default the register's account key to the NUBAN column when one is
        # mapped, so customers sharing a name are not pooled by default.
        movement_key = form_data.get("movement_identity_col", "").strip()
        if not movement_key:
            movement_key = form_data.get("nuban_col", "").strip()
        state.config["movement_identity_col"] = movement_key
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

        # The two amount modes are mutually exclusive, so normalise whichever one
        # the user chose and clear the other's columns. Without this a stale
        # selection survives the save and silently wins at report time.
        mode = form_data.get("amount_mode", "single")
        if mode not in ("single", "split"):
            mode = "single"
        state.config["amount_mode"] = mode
        if mode == "split":
            state.config["metric_col"] = ""
            state.config["flow_type_col"] = ""
        else:
            state.config["credit_col"] = ""
            state.config["debit_col"] = ""

        # A mode is only configured once it has the columns it needs, plus identity.
        has_identity = bool(state.config["identity_col"] or state.config["concat_order"])
        if mode == "split":
            has_amount = bool(state.config["credit_col"] and state.config["debit_col"])
        else:
            has_amount = bool(state.config["metric_col"])

        if has_identity and has_amount:
            state.status = "Configured"
        elif state.status == "Configured":
            # An edit that leaves the config unsatisfiable must not keep
            # advertising itself as ready to generate.
            state.status = "Ready"

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
    return Response(status_code=200)


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
