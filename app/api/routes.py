from fastapi import APIRouter, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os
import openpyxl
from io import BytesIO
from typing import Dict, Any

from app.core.state import file_db, FileState, TARGET_FIELDS
from app.services.cleaner import find_header_row_and_headers, auto_map_headers, process_and_save

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={
        "request": request, 
        "files": file_db.values()
    })

@router.post("/api/upload", response_class=HTMLResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    os.makedirs('uploads', exist_ok=True)
    temp_path = os.path.join('uploads', file.filename)
    
    with open(temp_path, "wb") as f:
        f.write(await file.read())
        
    state = FileState()
    state.original_filename = file.filename
    state.saved_path = temp_path
    
    # Analyze headers
    try:
        wb = openpyxl.load_workbook(temp_path, data_only=True, read_only=True)
        state.sheet_names = wb.sheetnames
        
        if len(wb.sheetnames) > 1:
            state.status = "Needs Sheet"
        else:
            state.selected_sheet = wb.sheetnames[0]
            sheet = wb.active
            
            idx, headers = find_header_row_and_headers(sheet)
            state.headers = headers
            state.header_row_idx = idx
            
            mapped_fields, status = auto_map_headers(state.headers)
            state.mapped_fields = mapped_fields
            state.status = status
            
            # Extract distinct branches with smarter inference
            branch_keywords = ['BRANCH_NAME', 'BRANCH NAME', 'BRANCH', 'STATE', 'LOCATION', 'REGION', 'SOL', 'HUB']
            candidate_indices = [i for i, h in enumerate(state.headers) if h and any(k in h.upper() for k in branch_keywords)]
            
            print(f"\n--- BRANCH DETECTION: {state.original_filename} ---")
            print(f"Candidate Columns: {[state.headers[i] for i in candidate_indices]}")

            if candidate_indices:
                # Content-aware check: peek at the first 10 rows
                best_idx = candidate_indices[0]
                max_score = -100
                
                rows_peek = list(sheet.iter_rows(values_only=True, min_row=idx+2, max_row=idx+12))
                
                for c_idx in candidate_indices:
                    alpha_chars = 0
                    total_chars = 0
                    pure_numeric_count = 0
                    row_count = 0
                    
                    for row in rows_peek:
                        if len(row) > c_idx and row[c_idx] is not None:
                            row_count += 1
                            val_str = str(row[c_idx]).strip()
                            if not val_str: continue
                            
                            alpha_chars += sum(1 for c in val_str if c.isalpha())
                            total_chars += len(val_str)
                            if val_str.isdigit():
                                pure_numeric_count += 1
                    
                    # Score logic
                    # Base score: ratio of alphabetic chars
                    score = (alpha_chars / (total_chars + 1)) if total_chars > 0 else 0
                    
                    # Strong penalty for pure numeric columns (like SOL ID)
                    if row_count > 0 and pure_numeric_count / row_count > 0.8:
                        score -= 5.0
                        
                    # Boost score if 'NAME' is in the header
                    if 'NAME' in state.headers[c_idx].upper():
                        score += 2.0
                    
                    print(f"Column '{state.headers[c_idx]}' score: {score:.2f}")
                        
                    if score > max_score:
                        max_score = score
                        best_idx = c_idx
                
                print(f"Picked: '{state.headers[best_idx]}'")
                
                distinct_branches = set()
                # Re-traverse to get all distinct values from the best column
                for r_idx, row in enumerate(sheet.iter_rows(values_only=True, min_row=idx+2)):
                    if len(row) > best_idx and row[best_idx]:
                        distinct_branches.add(str(row[best_idx]).strip())
                
                state.available_branches = sorted(list(distinct_branches))
                
    except Exception as e:
        state.status = f"Error: {str(e)}"
    
    file_db[state.id] = state
    
    return templates.TemplateResponse(request=request, name="partials/file_card.html", context={
        "request": request,
        "file": state,
        "targets": TARGET_FIELDS
    })

@router.post("/api/components/mapping/{file_id}", response_class=HTMLResponse)
async def edit_mapping(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"
        
    return templates.TemplateResponse(request=request, name="partials/mapping_form.html", context={
        "request": request,
        "file": state,
        "targets": TARGET_FIELDS
    })

@router.post("/api/mapping/{file_id}", response_class=HTMLResponse)
async def save_mapping(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"
        
    form_data = await request.form()
    
    # Handle Sheet Selection
    if form_data.get("selected_sheet") and form_data.get("selected_sheet") in state.sheet_names:
        state.selected_sheet = form_data.get("selected_sheet")
        # Proceed with parsing this sheet
        try:
            wb = openpyxl.load_workbook(state.saved_path, data_only=True, read_only=True)
            sheet = wb[state.selected_sheet]
            
            idx, headers = find_header_row_and_headers(sheet)
            state.headers = [h for h in headers if h]
            state.header_row_idx = idx
            
            mapped_fields, status = auto_map_headers(state.headers)
            state.mapped_fields = mapped_fields
            state.status = status
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
        
    return templates.TemplateResponse(request=request, name="partials/file_card.html", context={
        "request": request,
        "file": state,
        "targets": TARGET_FIELDS
    })

@router.delete("/api/delete/{file_id}")
async def delete_file(file_id: str):
    if file_id in file_db:
        del file_db[file_id]
    return ""

@router.post("/api/process/{file_id}", response_class=HTMLResponse)
async def process_file(request: Request, file_id: str):
    state = file_db.get(file_id)
    if not state:
        return "File not found"
        
    try:
        proc, skipped, out_path = process_and_save(
            state.saved_path, 
            state.mapped_fields, 
            getattr(state, 'header_row_idx', 3),
            state.selected_sheet,
            state.selected_branches
        )
        state.status = f"Processed ({proc} rows)"
        setattr(state, 'cleaned_path', out_path)
    except Exception as e:
        state.status = f"Failed ({str(e)})"
        
    return templates.TemplateResponse(request=request, name="partials/file_card.html", context={
        "request": request,
        "file": state,
        "targets": TARGET_FIELDS
    })

@router.get("/api/view/{file_id}", response_class=HTMLResponse)
async def view_data(request: Request, file_id: str):
    import csv
    state = file_db.get(file_id)
    if not state or not getattr(state, 'cleaned_path', None):
        return "Not available"
    
    rows = []
    try:
        with open(state.cleaned_path, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i > 50:
                    break
                rows.append(row)
    except Exception:
        return "Error reading file"
        
    return templates.TemplateResponse(request=request, name="partials/data_view.html", context={
        "request": request,
        "file": state,
        "rows": rows
    })

@router.get("/api/view/process", response_class=HTMLResponse)
async def get_process_view(request: Request):
    return templates.TemplateResponse(request=request, name="partials/process_view.html", context={
        "request": request, 
        "files": file_db.values()
    })

@router.get("/api/view/cleaned", response_class=HTMLResponse)
async def get_cleaned_view(request: Request):
    import math
    cleaned_dir = "cleaned"
    os.makedirs(cleaned_dir, exist_ok=True)
    files_info = []
    
    for fname in os.listdir(cleaned_dir):
        if fname.endswith('.csv') or fname.endswith('.xlsx'):
            fpath = os.path.join(cleaned_dir, fname)
            size_bytes = os.path.getsize(fpath)
            size_mb = round(size_bytes / (1024 * 1024), 2) if size_bytes > 0 else 0
            files_info.append({"name": fname, "size": size_mb})
            
    # Sort files by name or modified time if needed
    files_info.sort(key=lambda x: x['name'])
            
    return templates.TemplateResponse(request=request, name="partials/cleaned_view.html", context={
        "request": request, 
        "cleaned_files": files_info
    })

@router.get("/api/download/{filename}")
async def download_single(filename: str):
    from fastapi.responses import FileResponse
    file_path = os.path.join("cleaned", filename)
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename, media_type='text/csv')
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
        headers={"Content-Disposition": "attachment; filename=AKIRS_Cleaned_Batch.zip"}
    )
