from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
import hashlib
import os
import time
import uuid
from typing import List, Optional

from app.core import repository as repo
from app.core.config import settings
from app.core.deps import get_current_user
from app.core.executor import run_cpu
from app.core.models import User
from app.core.state import (
    PRESETS,
    SpaceFileState,
    get_space_upload_dir,
)
from app.services import spaces as space_svc
from app.services.audit import log_audit
from app.services.cleaner import (
    auto_map_headers,
    detect_distinct_branches,
    find_header_row_and_headers_from_rows,
    load_tabular_rows,
    pre_flight_validate,
)
from app.services.space_processor import process_space_files
from app.services.validators import validate_upload

router = APIRouter()
templates = Jinja2Templates(directory="templates")


async def _space_for_user(space_id: str, user_id: int):
    """Return the space if the user owns it or is a member, else None."""
    space = await space_svc.get_space(space_id)
    if space is None:
        return None
    if space.owner_id == user_id:
        return space
    members = await space_svc.list_members(space_id)
    if any(m.id == user_id for m in members):
        return space
    return None


def _request_base_url(request: Request) -> str:
    """Build the public base URL from the live request.

    Prefers X-Forwarded-* headers so the link uses the real domain even when the
    app sits behind a reverse proxy (Coolify, IIS/ARR, nginx, ...).
    """
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    return f"{proto.split(',')[0].strip()}://{host.split(',')[0].strip()}"


def _space_ctx(request: Request, space, files, members, user: User) -> dict:
    return {
        "request": request,
        "space": space,
        "files": files,
        "members": members,
        "user": user,
        "presets": PRESETS,
        "share_link": f"{_request_base_url(request).rstrip('/')}/cowork/join/{space.share_token}",
        "min_ttl": settings.cowork_min_ttl_hours,
        "max_ttl": settings.cowork_max_ttl_hours,
    }


@router.get("/api/cowork/view", response_class=HTMLResponse)
async def cowork_view(request: Request, current_user: User = Depends(get_current_user)):
    spaces = await space_svc.list_spaces_for_user(current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="partials/cowork_view.html",
        context={"request": request, "spaces": spaces, "user": current_user},
    )


@router.get("/api/cowork/join/{token}")
async def cowork_join(token: str, current_user: User = Depends(get_current_user)):
    space = await space_svc.get_space_by_token(token)
    if space is None:
        return HTMLResponse("Space not found or link expired", status_code=404)
    if space.owner_id != current_user.id:
        await space_svc.add_member(space.id, current_user.id)
    return RedirectResponse(f"/app?space={space.id}", status_code=303)


@router.post("/api/cowork/join/{token}")
async def cowork_join_api(token: str, current_user: User = Depends(get_current_user)):
    space = await space_svc.get_space_by_token(token)
    if space is None:
        raise HTTPException(status_code=404, detail="Space not found or link expired")
    if space.owner_id != current_user.id:
        await space_svc.add_member(space.id, current_user.id)
    return {"status": "ok", "space_id": space.id, "space_name": space.name}


@router.post("/api/cowork/spaces", response_class=HTMLResponse)
async def create_space(request: Request, current_user: User = Depends(get_current_user)):
    form = await request.form()
    name = (form.get("name") or "Coworking Space").strip()
    if len(name) > 80:
        name = name[:80]
    space = await space_svc.create_space(current_user.id, name)
    await log_audit(
        "cowork_space_created",
        user=current_user,
        status="success",
        detail=f"space={space.id} name={space.name}",
        request=request,
    )
    return RedirectResponse(f"/api/cowork/spaces/{space.id}", status_code=303)


@router.get("/api/cowork/spaces/{space_id}", response_class=HTMLResponse)
async def space_detail(
    request: Request,
    space_id: str,
    current_user: User = Depends(get_current_user),
):
    space = await _space_for_user(space_id, current_user.id)
    if space is None:
        return HTMLResponse("Not available", status_code=404)
    files = await repo.list_space_files(space_id)
    members = await space_svc.list_members(space_id)
    return templates.TemplateResponse(
        request=request,
        name="partials/cowork_space.html",
        context=_space_ctx(request, space, files, members, current_user),
    )


@router.post("/api/cowork/spaces/{space_id}/upload", response_class=HTMLResponse)
async def space_upload(
    request: Request,
    space_id: str,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
):
    space = await _space_for_user(space_id, current_user.id)
    if space is None:
        return HTMLResponse("Not available", status_code=404)
    if space.owner_id != current_user.id:
        return HTMLResponse("Only the space owner can upload files", status_code=403)

    form = await request.form()
    try:
        ttl_hours = int(form.get("ttl_hours") or settings.cowork_min_ttl_hours)
    except ValueError:
        ttl_hours = settings.cowork_min_ttl_hours
    ttl_hours = max(settings.cowork_min_ttl_hours, min(settings.cowork_max_ttl_hours, ttl_hours))

    upload_dir = get_space_upload_dir(space_id)
    now = time.time()
    states = []

    for f in files:
        validate_upload(f)
        safe_filename = (
            os.path.basename(f.filename).replace("..", "").replace("/", "_").replace("\\", "_")
        )
        temp_path = os.path.join(upload_dir, safe_filename)

        hasher = hashlib.sha256()
        file_size = 0
        max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
        with open(temp_path, "wb") as file_out:
            while chunk := await f.read(1024 * 1024):
                file_size += len(chunk)
                if file_size > max_size_bytes:
                    file_out.close()
                    os.remove(temp_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File size exceeds the maximum allowed size of {settings.max_upload_size_mb}MB",
                    )
                hasher.update(chunk)
                file_out.write(chunk)

        state = SpaceFileState()
        state.user_id = space.owner_id
        state.space_id = space_id
        state.uploaded_by = current_user.id
        state.original_filename = f.filename
        state.saved_path = temp_path
        state.upload_hash = hasher.hexdigest()
        state.upload_size = file_size
        state.uploaded_at = now
        state.ttl_hours = ttl_hours
        state.expires_at = now + ttl_hours * 3600

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

        try:
            state.health_report = await run_cpu(pre_flight_validate, temp_path)
            _, sheet_names = await run_cpu(load_tabular_rows, temp_path, "")
            state.sheet_names = sheet_names
            if sheet_names:
                state.selected_sheets = [sheet_names[0]]
                rows, _ = await run_cpu(load_tabular_rows, temp_path, sheet_names[0])
                idx, headers = await run_cpu(find_header_row_and_headers_from_rows, rows)
                state.headers = [h for h in headers if h]
                state.header_row_idx = idx
                state.health_report = await run_cpu(
                    pre_flight_validate, temp_path, sheet_names[0]
                )
                mapped_fields, status = auto_map_headers(state.headers, state.preset_name)
                state.mapped_fields = mapped_fields
                state.status = status
                state.available_branches = await run_cpu(
                    detect_distinct_branches, state.headers, rows, idx
                )
            else:
                state.status = "Ready"
        except Exception as exc:
            state.status = f"Error: {exc}"

        await repo.put(repo.KIND_SPACE_FILE, state)
        states.append(state)

    await log_audit(
        "cowork_upload",
        user=current_user,
        filename=", ".join(s.original_filename for s in states),
        status=f"space={space_id} ttl={ttl_hours}h",
        request=request,
    )

    members = await space_svc.list_members(space_id)
    return templates.TemplateResponse(
        request=request,
        name="partials/cowork_files.html",
        context=_space_ctx(request, space, await repo.list_space_files(space_id), members, current_user),
    )


@router.post("/api/cowork/spaces/{space_id}/invite", response_class=HTMLResponse)
async def invite_member(
    request: Request,
    space_id: str,
    current_user: User = Depends(get_current_user),
):
    space = await _space_for_user(space_id, current_user.id)
    if space is None:
        return HTMLResponse("Not available", status_code=404)

    form = await request.form()
    identifier = (form.get("identifier") or "").strip()
    target = await space_svc.find_user_by_email_or_username(identifier)
    if target is None:
        return templates.TemplateResponse(
            request=request,
            name="partials/cowork_members.html",
            context={
                "request": request,
                "space": space,
                "members": await space_svc.list_members(space_id),
                "user": current_user,
                "invite_error": f"No approved account found for '{identifier}'",
            },
        )
    if target.id == current_user.id:
        target = None

    if target is not None:
        await space_svc.add_member(space_id, target.id)
        await log_audit(
            "cowork_invite",
            user=current_user,
            status="success",
            detail=f"space={space_id} target={target.email}",
            request=request,
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/cowork_members.html",
        context={
            "request": request,
            "space": space,
            "members": await space_svc.list_members(space_id),
            "user": current_user,
        },
    )


@router.post("/api/cowork/spaces/{space_id}/remove-member/{user_id}")
async def remove_member(
    request: Request,
    space_id: str,
    user_id: int,
    current_user: User = Depends(get_current_user),
):
    space = await _space_for_user(space_id, current_user.id)
    if space is None or space.owner_id != current_user.id:
        return HTMLResponse("Not available", status_code=403)
    await space_svc.remove_member(space_id, user_id)
    return templates.TemplateResponse(
        request=request,
        name="partials/cowork_members.html",
        context={
            "request": request,
            "space": space,
            "members": await space_svc.list_members(space_id),
            "user": current_user,
        },
    )


@router.get("/api/cowork/spaces/{space_id}/view/{file_id}", response_class=HTMLResponse)
async def view_space_file(
    request: Request,
    space_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    if await _space_for_user(space_id, current_user.id) is None:
        return HTMLResponse("Not available", status_code=404)
    state = await repo.get(repo.KIND_SPACE_FILE, file_id)
    if state is None or state.space_id != space_id:
        return HTMLResponse("Not available", status_code=404)

    rows = []
    headers = []
    try:
        sheet = state.selected_sheets[0] if state.selected_sheets else ""
        all_rows, _ = await run_cpu(load_tabular_rows, state.saved_path, sheet)
        if all_rows:
            idx, found_headers = await run_cpu(find_header_row_and_headers_from_rows, all_rows)
            if found_headers:
                headers = found_headers
                rows = all_rows[idx + 1 : idx + 101]
            elif getattr(state, "headers", None):
                headers = state.headers
                header_idx = getattr(state, "header_row_idx", 0)
                rows = all_rows[header_idx + 1 : header_idx + 101]
            else:
                headers = [str(h).strip() for h in all_rows[0] if str(h).strip()]
                rows = all_rows[1:101]
    except Exception:
        pass

    return templates.TemplateResponse(
        request=request,
        name="partials/cowork_preview.html",
        context={
            "request": request,
            "file": state,
            "space_id": space_id,
            "headers": headers,
            "rows": rows,
        },
    )


@router.post("/api/cowork/spaces/{space_id}/process", response_class=HTMLResponse)
async def process_space_files_view(
    request: Request,
    space_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    space = await _space_for_user(space_id, current_user.id)
    if space is None:
        return HTMLResponse("Not available", status_code=404)

    form = await request.form()
    file_ids = [fid for fid in form.getlist("file_ids") if fid]
    if not file_ids:
        return HTMLResponse("Select at least one file to process", status_code=400)
    notify_email = form.get("email_notify") == "true"

    valid_ids = []
    for fid in file_ids:
        state = await repo.get(repo.KIND_SPACE_FILE, fid)
        if state is None or state.space_id != space_id:
            continue
        if (
            state.status != "Ready"
            and not state.status.startswith("Processed")
            and not state.status.startswith("Failed")
        ):
            continue
        state.status = "Queued..."
        await repo.put(repo.KIND_SPACE_FILE, state)
        valid_ids.append(fid)

    if not valid_ids:
        return HTMLResponse("No eligible files selected", status_code=400)

    task_id = f"cowork_{uuid.uuid4().hex[:12]}"
    await repo.set_task(task_id, space_id, current_user.id, "queued", "Waiting for worker...")

    await log_audit(
        "cowork_process",
        user=current_user,
        filename=", ".join(valid_ids),
        status=f"space={space_id} task={task_id}",
        request=request,
    )

    try:
        from app.tasks.space_tasks import process_space_files_task

        process_space_files_task.delay(
            task_id=task_id,
            space_id=space_id,
            file_ids=valid_ids,
            runner_user_id=current_user.id,
            owner_user_id=space.owner_id,
            runner_email=current_user.email,
            runner_name=current_user.full_name or current_user.email,
            space_name=space.name,
            notify_email=notify_email,
            base_url=_request_base_url(request),
        )
    except Exception:
        # Redis/Celery unavailable: fall back to in-process background execution.
        background_tasks.add_task(
            process_space_files,
            task_id=task_id,
            space_id=space_id,
            file_ids=valid_ids,
            runner_user_id=current_user.id,
            owner_user_id=space.owner_id,
            runner_email=current_user.email if notify_email else None,
            runner_name=current_user.full_name or current_user.email,
            space_name=space.name,
            notify_email=notify_email,
            base_url=_request_base_url(request),
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/cowork_files.html",
        context=_space_ctx(
            request,
            space,
            await repo.list_space_files(space_id),
            await space_svc.list_members(space_id),
            current_user,
        ),
        headers={"HX-Trigger": "coworkTaskStarted"},
    )


@router.get("/api/cowork/task/{task_id}")
async def cowork_task_status(task_id: str, current_user: User = Depends(get_current_user)):
    task = await repo.get_task(task_id)
    if not task or task.get("user_id") != current_user.id:
        return JSONResponse({"status": "unknown", "message": "Task not found"}, status_code=404)
    return task


@router.get("/api/cowork/spaces/{space_id}/active-task")
async def active_task(
    space_id: str,
    current_user: User = Depends(get_current_user),
):
    if await _space_for_user(space_id, current_user.id) is None:
        return JSONResponse({"status": "none"}, status_code=404)
    task = await repo.get_active_task(space_id)
    if task is None:
        return {"status": "none"}
    return task


@router.get("/api/cowork/spaces/{space_id}/download/{file_id}")
async def download_space_result(
    space_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    space = await _space_for_user(space_id, current_user.id)
    if space is None:
        return HTMLResponse("Not available", status_code=404)
    state = await repo.get(repo.KIND_SPACE_FILE, file_id)
    if state is None or state.space_id != space_id:
        return HTMLResponse("Not available", status_code=404)

    # Only the space owner and the member who ran the job may download results.
    if current_user.id not in (space.owner_id, state.processed_by):
        return HTMLResponse("Download not allowed", status_code=403)

    if not state.cleaned_path or not os.path.exists(state.cleaned_path):
        return HTMLResponse("Result not available", status_code=404)

    await log_audit(
        "cowork_download",
        user=current_user,
        filename=state.result_filename,
        request=None,
    )
    return FileResponse(
        path=state.cleaned_path,
        filename=state.result_filename or os.path.basename(state.cleaned_path),
        media_type="text/csv",
    )


@router.delete("/api/cowork/spaces/{space_id}/files/{file_id}")
async def delete_space_file(
    request: Request,
    space_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    space = await _space_for_user(space_id, current_user.id)
    if space is None or space.owner_id != current_user.id:
        return Response(status_code=204)
    state = await repo.get(repo.KIND_SPACE_FILE, file_id)
    if state is not None and state.space_id == space_id:
        if state.saved_path and os.path.exists(state.saved_path):
            try:
                os.remove(state.saved_path)
            except OSError:
                pass
        if state.cleaned_path and os.path.exists(state.cleaned_path):
            try:
                os.remove(state.cleaned_path)
            except OSError:
                pass
        await repo.delete(repo.KIND_SPACE_FILE, file_id)
    return Response(status_code=204)


@router.post("/api/cowork/spaces/{space_id}/mapping/{file_id}", response_class=HTMLResponse)
async def save_space_mapping(
    request: Request,
    space_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    if await _space_for_user(space_id, current_user.id) is None:
        return HTMLResponse("Not available", status_code=404)
    state = await repo.get(repo.KIND_SPACE_FILE, file_id)
    if state is None or state.space_id != space_id:
        return HTMLResponse("Not available", status_code=404)

    form = await request.form()
    if form.getlist("selected_sheets"):
        state.selected_sheets = form.getlist("selected_sheets")
        try:
            state.health_report = await run_cpu(
                pre_flight_validate, state.saved_path, state.selected_sheets[0]
            )
            rows, _ = await run_cpu(load_tabular_rows, state.saved_path, state.selected_sheets[0])
            idx, headers = await run_cpu(find_header_row_and_headers_from_rows, rows)
            state.headers = [h for h in headers if h]
            state.header_row_idx = idx
            mapped_fields, status = auto_map_headers(state.headers, state.preset_name)
            state.mapped_fields = mapped_fields
            state.status = status
        except Exception as exc:
            state.status = f"Error: {exc}"
    else:
        state.preset_name = form.get("preset_name", state.preset_name)
        if state.preset_name == "custom":
            custom_raw = form.get("custom_fields", "")
            state.custom_fields = [f.strip().upper() for f in custom_raw.split(",") if f.strip()]
            fields = state.custom_fields
        else:
            fields = PRESETS.get(state.preset_name, PRESETS["retail"])["fields"]
            state.custom_fields = []

        state.output_pattern = form.get("output_pattern") or state.output_pattern
        state.duplicate_logic = form.get("duplicate_logic") or state.duplicate_logic
        state.primary_key_field = form.get("primary_key_field") or ""
        state.verify_db = form.get("verify_db") == "true"
        state.verify_db_query_field = form.get("verify_db_query_field") or ""
        state.verify_db_target_column = form.get("verify_db_target_column") or "ANY"
        state.verify_db_fuzzy = form.get("verify_db_fuzzy") == "true"

        state.mapped_fields = {}
        state.field_separators = {}
        for target in fields:
            val = [v for v in form.getlist(target) if v]
            state.mapped_fields[target] = val[0] if len(val) == 1 else (val if val else "")
            sep = form.get(f"separator_{target}", " ")
            state.field_separators[target] = sep if sep else " "

        if form.getlist("selected_branches"):
            state.selected_branches = form.getlist("selected_branches")
        else:
            state.selected_branches = []

        if all(state.mapped_fields.get(t) for t in fields):
            state.status = "Ready"
        else:
            state.status = "Needs Mapping"

    await repo.put(repo.KIND_SPACE_FILE, state)
    space = await _space_for_user(space_id, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="partials/cowork_file_card.html",
        context={"request": request, "file": state, "space_id": space_id, "user": current_user, "is_owner": space.owner_id == current_user.id},
    )


@router.post("/api/cowork/spaces/{space_id}/components/mapping/{file_id}", response_class=HTMLResponse)
async def space_mapping_component(
    request: Request,
    space_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    if await _space_for_user(space_id, current_user.id) is None:
        return HTMLResponse("Not available", status_code=404)
    state = await repo.get(repo.KIND_SPACE_FILE, file_id)
    if state is None or state.space_id != space_id:
        return HTMLResponse("Not available", status_code=404)

    preset_arg = request.query_params.get("preset")
    if preset_arg in ["retail", "intelligence", "custom"]:
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
        mapped_fields, status = auto_map_headers(state.headers, state.preset_name, state.custom_fields)
        state.mapped_fields = mapped_fields
        state.status = status
        await repo.put(repo.KIND_SPACE_FILE, state)

    preview_rows = []
    if state.status != "Needs Sheet" and getattr(state, "header_row_idx", None) is not None:
        try:
            rows, _ = await run_cpu(
                load_tabular_rows,
                state.saved_path,
                state.selected_sheets[0] if state.selected_sheets else "",
            )
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
        context={
            "request": request,
            "file": state,
            "targets": fields,
            "preview_rows": preview_rows,
            "presets": PRESETS,
            "mapping_base": f"/api/cowork/spaces/{space_id}",
        },
    )
