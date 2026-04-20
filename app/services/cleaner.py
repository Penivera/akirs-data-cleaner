import os
import csv
import openpyxl
from typing import Tuple, List, Dict
from app.core.state import SYNONYMS, TARGET_FIELDS

def find_header_row_and_headers(sheet) -> Tuple[int, List[str]]:
    """Heuristic to find the real header row in an Excel file."""
    for i, row in enumerate(sheet.iter_rows(values_only=True)):
        if i > 20: # Dont look past first 20 rows
            break
        # Count non-empty strings
        str_count = sum(1 for val in row if val and isinstance(val, str))
        if str_count > 3: # If a row has more than 3 strings, it's highly likely to be the header row
            headers = [str(h).strip() if h else '' for h in row]
            return i, headers
    return 0, []

def auto_map_headers(excel_headers: List[str]) -> Tuple[Dict[str, str], str]:
    """Tries to automatically map target fields based on synonyms."""
    mapped_fields = {}
    
    # Pre-process excel headers to uppercase
    upper_headers = {h.upper(): h for h in excel_headers if h}
    
    for target in TARGET_FIELDS:
        mapped = False
        if target in SYNONYMS:
            for synonym in SYNONYMS[target]:
                if synonym in upper_headers:
                    mapped_fields[target] = upper_headers[synonym]
                    mapped = True
                    break
        if not mapped:
            mapped_fields[target] = "" # Needs manual mapping
            
    status = "Ready" if all(mapped_fields.values()) else "Needs Mapping"
    return mapped_fields, status

def process_and_save(file_path: str, mapped_fields: Dict[str, str], header_row_idx: int, selected_sheet: str, selected_branches: List[str]) -> Tuple[int, int, str]:
    """Extracts, cleans, and deduplicates records, saving to cleaned/."""
    wb = openpyxl.load_workbook(file_path, data_only=True)
    
    if selected_sheet:
        sheet = wb[selected_sheet]
    else:
        sheet = wb.active
        for sheetname in wb.sheetnames:
            if 'RETAIL' in sheetname.upper():
                sheet = wb[sheetname]
                break
            
    rows = list(sheet.iter_rows(values_only=True))
    if len(rows) <= header_row_idx:
        return 0, 0, ""
        
    excel_headers = [str(h).strip() if h else '' for h in rows[header_row_idx]]
    header_map = {header: idx for idx, header in enumerate(excel_headers)}

    def get_val(row, source_field):
        if source_field == "__NA__":
            return ""
        if source_field and source_field in header_map:
            val = row[header_map[source_field]]
            return str(val).strip() if val is not None else ""
        return ""

    processed = 0
    skipped_duplicates = 0
    seen_nubans = set()
    
    os.makedirs('cleaned', exist_ok=True)
    out_filename = os.path.basename(file_path)
    if out_filename.endswith('.xlsx'):
        out_filename = out_filename.replace('.xlsx', '.csv')
        
    target_file = os.path.join('cleaned', out_filename)
        
    with open(target_file, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(TARGET_FIELDS)
        
        for row in rows[header_row_idx + 1:]:
            if not any(row):
                continue
                
            # Filter branch if configured
            if selected_branches:
                # Find the column containing the branch value with smart inference
                branch_keywords = ['BRANCH_NAME', 'BRANCH NAME', 'BRANCH', 'STATE', 'LOCATION', 'REGION', 'SOL', 'HUB']
                candidate_headers = [k for k in header_map.keys() if k and any(kw in k.upper() for kw in branch_keywords)]
                
                if candidate_headers:
                    # Use the same robust heuristic to pick the best column
                    best_header = candidate_headers[0]
                    max_score = -100
                    
                    for h_name in candidate_headers:
                        h_idx = header_map[h_name]
                        val_str = str(row[h_idx]).strip() if row[h_idx] is not None else ""
                        
                        # Alpha score
                        alpha_count = sum(1 for c in val_str if c.isalpha())
                        curr_score = (alpha_count / (len(val_str) + 1)) if val_str else 0
                        
                        # Numeric penalty
                        if val_str.isdigit():
                            curr_score -= 5.0
                        
                        # Header name boost
                        if 'NAME' in h_name.upper():
                            curr_score += 2.0
                            
                        if curr_score > max_score:
                            max_score = curr_score
                            best_header = h_name
                            
                    b_idx = header_map[best_header]
                    branch_val = str(row[b_idx]).strip() if row[b_idx] else ""
                    
                    matched = False
                    for sb in selected_branches:
                        if sb.upper() in branch_val.upper():
                            matched = True
                            break
                    if not matched:
                        continue
                
            extracted = []
            for target in TARGET_FIELDS:
                source_field = mapped_fields.get(target, "")
                val = get_val(row, source_field) or "N/A"
                extracted.append(val)
            
            # Index 2 is NUBAN
            nuban = extracted[2]
            
            # Simple duplication logic
            if nuban != "N/A":
                if nuban in seen_nubans:
                    skipped_duplicates += 1
                    continue
                seen_nubans.add(nuban)
                
            # Skip if critical target is essentially empty
            if nuban == "N/A" and extracted[1] == "N/A":
                continue
                
            writer.writerow(extracted)
            processed += 1
            
    return processed, skipped_duplicates, target_file
