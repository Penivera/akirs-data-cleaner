from fastapi import APIRouter, UploadFile, File, Request, Form, Depends
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import hashlib
import os
import time
from typing import List

from app.core import repository as repo
from app.core.config import settings
from app.core.deps import get_current_user
from app.core.executor import run_cpu
from app.core.models import User
from app.core.state import NubanState, get_user_upload_dir
from app.services.audit import log_audit
from app.services.validators import validate_upload
from app.services.cleaner import load_tabular_rows, find_header_row_and_headers_from_rows
from app.services.nuban import get_bank_list, process_nuban_resolution

router = APIRouter()
templates = Jinja2Templates(directory="templates")

DUPLICATE_UPLOAD_WINDOW_SECONDS = 5

@router.get("/api/nuban/view", response_class=HTMLResponse)
async def get_nuban_view(request: Request, current_user: User = Depends(get_current_user)):
    user_files = await repo.list_for_user(repo.KIND_NUBAN, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="partials/nuban_view.html",
        context={"request": request, "files": user_files},
    )

@router.post("/api/nuban/upload", response_class=HTMLResponse)
async def nuban_upload(
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
        temp_path = os.path.join(user_upload_dir, f"nuban_{safe_filename}")

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
        for existing_state in await repo.list_for_user(repo.KIND_NUBAN, current_user.id):
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

        state = NubanState()
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
                rows, _ = await run_cpu(load_tabular_rows, temp_path, state.selected_sheets[0])
                idx, headers = await run_cpu(find_header_row_and_headers_from_rows, rows)
                state.headers = [h for h in headers if h]
                state.header_row_idx = idx
                state.status = "Ready"

        except Exception as e:
            state.status = f"Error: {str(e)}"

        await repo.put(repo.KIND_NUBAN, state)
        processed_states.append(state)
        await log_audit(
            "nuban_upload",
            user=current_user,
            filename=state.original_filename,
            status=state.status,
            request=request,
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/nuban_file_cards.html",
        context={"request": request, "files": processed_states},
    )

@router.post("/api/nuban/config-form/{file_id}", response_class=HTMLResponse)
async def get_nuban_config_form(request: Request, file_id: str, current_user: User = Depends(get_current_user)):
    state = await repo.get(repo.KIND_NUBAN, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"
        
    banks = await get_bank_list()
    
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
        name="partials/nuban_config_form.html",
        context={"request": request, "file": state, "banks": banks, "preview_rows": preview_rows},
    )

@router.post("/api/nuban/save-config/{file_id}", response_class=HTMLResponse)
async def save_nuban_config(request: Request, file_id: str, current_user: User = Depends(get_current_user)):
    state = await repo.get(repo.KIND_NUBAN, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"
        
    form_data = await request.form()
    
    if form_data.getlist("selected_sheets"):
        state.selected_sheets = form_data.getlist("selected_sheets")
        rows, _ = await run_cpu(load_tabular_rows, state.saved_path, state.selected_sheets[0])
        idx, headers = await run_cpu(find_header_row_and_headers_from_rows, rows)
        state.headers = [h for h in headers if h]
        state.header_row_idx = idx
        state.status = "Ready"
    else:
        state.mapped_nuban_col = form_data.get("nuban_col", "")
        state.mapped_target_col = form_data.get("target_col", "")
        state.selected_bank_code = form_data.get("bank_code", "")
        
        if state.mapped_nuban_col and state.mapped_target_col and state.selected_bank_code:
            state.status = "Configured"

    await repo.put(repo.KIND_NUBAN, state)
    return templates.TemplateResponse(
        request=request,
        name="partials/nuban_file_card.html",
        context={"request": request, "file": state},
    )

@router.post("/api/nuban/resolve/{file_id}", response_class=HTMLResponse)
async def resolve_nuban_action(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    state = await repo.get(repo.KIND_NUBAN, file_id)
    if not state or state.user_id != current_user.id:
        return "File not found"

    state.status = "Resolving..."
    # Note: For production, this should be a background task
    try:
        await process_nuban_resolution(state)
        state.status = "Resolved"
    except Exception as e:
        state.status = f"Failed ({str(e)})"

    await repo.put(repo.KIND_NUBAN, state)
    await log_audit(
        "nuban_resolve",
        user=current_user,
        filename=state.original_filename,
        status=state.status,
        request=request,
    )
    return templates.TemplateResponse(
        request=request,
        name="partials/nuban_file_card.html",
        context={"request": request, "file": state},
    )


@router.delete("/api/nuban/delete/{file_id}")
async def delete_nuban_file(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    state = await repo.get(repo.KIND_NUBAN, file_id)
    if state is not None and state.user_id == current_user.id:
        # Delete physical files
        if state.saved_path and os.path.exists(state.saved_path):
            try:
                os.remove(state.saved_path)
            except OSError:
                pass
        if state.resolved_path and os.path.exists(state.resolved_path):
            try:
                os.remove(state.resolved_path)
            except OSError:
                pass
        await repo.delete(repo.KIND_NUBAN, file_id)
        await log_audit(
            "nuban_delete",
            user=current_user,
            filename=state.original_filename,
            request=request,
        )
    return Response(status_code=204)
