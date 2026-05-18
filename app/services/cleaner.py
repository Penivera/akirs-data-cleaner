import os
import csv
import openpyxl
from collections import defaultdict
from typing import Tuple, List, Dict, Any
from app.core.state import SYNONYMS, TARGET_FIELDS


def load_tabular_rows(
    file_path: str, selected_sheet: str = ""
) -> Tuple[List[Tuple[Any, ...]], List[str]]:
    """Load tabular rows from CSV or Excel and return rows plus available sheet names."""
    lower_path = file_path.lower()
    if lower_path.endswith(".csv"):
        rows: List[Tuple[Any, ...]] = []
        # Try utf-8-sig first to support files exported with BOM.
        try:
            with open(file_path, mode="r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                rows = [tuple(row) for row in reader]
        except UnicodeDecodeError:
            with open(file_path, mode="r", encoding="latin-1", newline="") as f:
                reader = csv.reader(f)
                rows = [tuple(row) for row in reader]
        return rows, []

    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    sheet_names = wb.sheetnames

    if selected_sheet and selected_sheet in wb.sheetnames:
        sheet = wb[selected_sheet]
    else:
        sheet = wb.active
        for sheetname in wb.sheetnames:
            if "RETAIL" in sheetname.upper():
                sheet = wb[sheetname]
                break

    rows = list(sheet.iter_rows(values_only=True))
    return rows, sheet_names


def resolve_output_filename(original_filename: str, output_pattern: str = "{filename}") -> str:
    """Resolves output filename based on a pattern like 'INTELIGENCE_GATHERING_{filename}'."""
    base_name = os.path.basename(original_filename)
    if base_name.endswith(".xlsx"):
        base_name = base_name.replace(".xlsx", ".csv")
    
    if output_pattern:
        return output_pattern.replace("{filename}", base_name)
    return base_name


def pre_flight_validate(file_path: str, selected_sheet: str = "") -> Dict[str, Any]:
    """Scans and checks uploaded Excel/CSV files for structural malformations, merged ranges, empty/duplicate headers, and formula errors."""
    report = {
        "score": 100,
        "status": "Excellent",
        "issues": []
    }
    
    lower_path = file_path.lower()
    
    # 1. Format/Readability Check for CSV
    if lower_path.endswith(".csv"):
        try:
            rows = []
            try:
                with open(file_path, mode="r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.reader(f)
                    rows = list(reader)
            except UnicodeDecodeError:
                with open(file_path, mode="r", encoding="latin-1", newline="") as f:
                    reader = csv.reader(f)
                    rows = list(reader)
            
            if not rows:
                report["score"] = 0
                report["status"] = "Critical"
                report["issues"].append({
                    "severity": "CRITICAL",
                    "reason": "The CSV file is completely empty.",
                    "location": "File Root",
                    "solution": "Please ensure the file has header columns and data rows."
                })
                return report
                
            header_row_idx, headers = find_header_row_and_headers_from_rows(rows)
            if not headers:
                report["score"] = min(report["score"], 30)
                report["status"] = "Critical"
                report["issues"].append({
                    "severity": "CRITICAL",
                    "reason": "Could not identify a valid header row.",
                    "location": "First 20 rows",
                    "solution": "Ensure your CSV file has a row with at least 3 column labels."
                })
            
            # Check row length mismatch
            header_len = len(headers) if headers else 0
            mismatched_rows = []
            for idx, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
                if any(row) and len(row) != header_len:
                    mismatched_rows.append(idx)
                    if len(mismatched_rows) <= 5:
                        report["issues"].append({
                            "severity": "WARNING",
                            "reason": f"Row has {len(row)} columns instead of the header's {header_len} columns.",
                            "location": f"Row {idx}",
                            "solution": "We will automatically pad or truncate this row, but verify alignment."
                        })
            if mismatched_rows:
                report["score"] = max(10, report["score"] - 15)
                if len(mismatched_rows) > 5:
                    report["issues"].append({
                        "severity": "WARNING",
                        "reason": f"There are {len(mismatched_rows) - 5} other rows with column count mismatches.",
                        "location": "Multiple rows",
                        "solution": "Check your CSV export settings to make sure column separators are uniform."
                      })
                      
        except Exception as e:
            report["score"] = 0
            report["status"] = "Critical"
            report["issues"].append({
                "severity": "CRITICAL",
                "reason": f"Failed to parse CSV file: {str(e)}",
                "location": "File System",
                "solution": "Verify that the file is not corrupted and is saved as a standard CSV."
            })
            return report
    else:
        # Excel pre-flight check
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True, read_only=False)
            
            sheet_names = wb.sheetnames
            if not sheet_names:
                report["score"] = 0
                report["status"] = "Critical"
                report["issues"].append({
                    "severity": "CRITICAL",
                    "reason": "The Excel file has no worksheets.",
                    "location": "Workbook",
                    "solution": "Ensure the Excel file has at least one active worksheet with data."
                })
                return report
            
            target_sheet_name = selected_sheet if selected_sheet in sheet_names else sheet_names[0]
            sheet = wb[target_sheet_name]
            
            # Check merged cells
            merged_ranges = list(sheet.merged_cells.ranges)
            if merged_ranges:
                report["score"] = max(30, report["score"] - 20)
                report["issues"].append({
                    "severity": "WARNING",
                    "reason": f"Merged cells detected: {', '.join(str(r) for r in merged_ranges[:3])}.",
                    "location": f"Sheet '{target_sheet_name}'",
                    "solution": "Merged cells can misalign columns during parsing. We highly recommend unmerging them in Excel."
                })
                
            # Count rows and cells
            rows = list(sheet.iter_rows(values_only=True))
            if not rows or len(rows) == 0:
                report["score"] = 0
                report["status"] = "Critical"
                report["issues"].append({
                    "severity": "CRITICAL",
                    "reason": "The selected worksheet is completely empty.",
                    "location": f"Sheet '{target_sheet_name}'",
                    "solution": "Check the spreadsheet and fill in the records."
                })
                return report
                
            header_row_idx, headers = find_header_row_and_headers_from_rows(rows)
            if not headers:
                report["score"] = min(report["score"], 30)
                report["status"] = "Critical"
                report["issues"].append({
                    "severity": "CRITICAL",
                    "reason": "Header row with at least 3 named columns could not be identified.",
                    "location": f"Sheet '{target_sheet_name}'",
                    "solution": "Place names on the first row of your table (e.g. NAME, PHONE, etc.)."
                })
            else:
                # Check empty headers or duplicate headers
                seen_headers = set()
                duplicates = []
                empty_header_indices = []
                for i, h in enumerate(headers):
                    h_clean = h.strip() if h else ""
                    if not h_clean:
                        empty_header_indices.append(i + 1)
                    elif h_clean in seen_headers:
                        duplicates.append(h_clean)
                    else:
                        seen_headers.add(h_clean)
                        
                if empty_header_indices:
                    report["score"] = max(20, report["score"] - 15)
                    report["issues"].append({
                        "severity": "WARNING",
                        "reason": f"Empty header labels detected at columns: {empty_header_indices}.",
                        "location": "Header row",
                        "solution": "Name all columns in the header row or remove the empty columns."
                    })
                if duplicates:
                    report["score"] = max(20, report["score"] - 15)
                    report["issues"].append({
                        "severity": "WARNING",
                        "reason": f"Duplicate column header names detected: {list(set(duplicates))}.",
                        "location": "Header row",
                        "solution": "Rename duplicate headers to make them unique."
                    })
                    
            # Check for Excel errors
            excel_errors = {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A"}
            found_errors = []
            for r_idx, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
                for c_idx, val in enumerate(row):
                    if isinstance(val, str) and val.upper().strip() in excel_errors:
                        col_letter = openpyxl.utils.get_column_letter(c_idx + 1)
                        found_errors.append((r_idx, col_letter, val))
                        if len(found_errors) <= 5:
                            report["issues"].append({
                                "severity": "WARNING",
                                "reason": f"Formula error '{val}' found.",
                                "location": f"Cell {col_letter}{r_idx}",
                                "solution": "We will treat this cell as empty/blank, but verify the Excel formula."
                            })
            if found_errors:
                report["score"] = max(20, report["score"] - 15)
                if len(found_errors) > 5:
                    report["issues"].append({
                        "severity": "WARNING",
                        "reason": f"There are {len(found_errors) - 5} other formula error cells in the sheet.",
                        "location": "Multiple cells",
                        "solution": "Search for #VALUE!, #REF!, or #DIV/0! in Excel and replace them with static values."
                    })
                    
        except Exception as e:
            report["score"] = 0
            report["status"] = "Critical"
            report["issues"].append({
                "severity": "CRITICAL",
                "reason": f"Failed to parse Excel file: {str(e)}",
                "location": "File System",
                "solution": "Ensure that the file is not corrupted, is a valid .xlsx or .xls, and is not password protected."
            })
            return report
            
    if report["score"] <= 30:
        report["status"] = "Critical"
    elif report["score"] < 95:
        report["status"] = "Warning"
    else:
        report["status"] = "Excellent"
        
    return report


def find_similar_duplicates_sorted_neighborhood(
    records: List[Dict[str, Any]],
    window_size: int = 15,
    similarity_threshold: float = 0.82
) -> List[Dict[str, Any]]:
    """
    Highly optimized duplicate finder using Sorted Neighborhood Method (SNM).
    Runs in O(N log N + N * W) which processes 10k+ rows in <1.5s.
    """
    if len(records) < 2:
        return []
    
    # 1. Generate sorting keys and pre-compute 3-gram sets
    n = 3
    for rec in records:
        key_parts = []
        for val in rec["values"]:
            if val and val != "N/A":
                clean_val = "".join(c.lower() for c in str(val) if c.isalnum())
                key_parts.append(clean_val)
        sort_key = "|".join(key_parts)
        rec["_sort_key"] = sort_key
        
        if len(sort_key) < n:
            rec["_grams"] = set()
        else:
            rec["_grams"] = {sort_key[i:i+n] for i in range(len(sort_key)-n+1)}
    
    # 2. Sort records by sorting key
    sorted_records = sorted(records, key=lambda r: r["_sort_key"])
    
    # 3-gram Jaccard similarity helper using precomputed sets
    def get_jaccard_similarity(r1: Dict[str, Any], r2: Dict[str, Any]) -> float:
        s1, s2 = r1["_sort_key"], r2["_sort_key"]
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 1.0
        
        g1, g2 = r1["_grams"], r2["_grams"]
        if not g1 or not g2:
            return 1.0 if s1 == s2 else 0.0
            
        return len(g1 & g2) / len(g1 | g2)
    
    # 3. Slide window and identify pairs that exceed threshold
    duplicate_pairs = []
    n_rec = len(sorted_records)
    for i in range(n_rec):
        for j in range(i + 1, min(i + window_size, n_rec)):
            r1 = sorted_records[i]
            r2 = sorted_records[j]
            
            if r1["_sort_key"] == r2["_sort_key"]:
                duplicate_pairs.append((r1["id"], r2["id"]))
                continue
                
            sim = get_jaccard_similarity(r1, r2)
            if sim >= similarity_threshold:
                duplicate_pairs.append((r1["id"], r2["id"]))
                
    # 4. Transitive closure to group duplicate sets (using Union-Find)
    parent = {r["id"]: r["id"] for r in records}
    
    def find(x):
        if parent[x] == x:
            return x
        parent[x] = find(parent[x])
        return parent[x]
        
    def union(x, y):
        root_x = find(x)
        root_y = find(y)
        if root_x != root_y:
            parent[root_x] = root_y
            
    for u, v in duplicate_pairs:
        union(u, v)
        
    # Group by roots
    groups = defaultdict(list)
    for r in records:
        root = find(r["id"])
        groups[root].append(r)
        
    # Construct duplicate groups structure
    duplicate_groups = []
    for root, group in groups.items():
        if len(group) > 1:
            duplicate_groups.append({
                "group_id": root,
                "nuban": group[0]["values"][2] if (len(group[0]["values"]) > 2 and group[0]["values"][2] != "N/A") else f"Fuzzy-{root[:8]}",
                "records": sorted(group, key=lambda x: x["source_row"])
            })
            
    duplicate_groups.sort(key=lambda g: min(r["source_row"] for r in g["records"]))
    return duplicate_groups


def find_header_row_and_headers(sheet) -> Tuple[int, List[str]]:
    """Heuristic to find the real header row in an Excel file."""
    for i, row in enumerate(sheet.iter_rows(values_only=True)):
        if i > 20:  # Dont look past first 20 rows
            break
        # Count non-empty strings
        str_count = sum(1 for val in row if val and isinstance(val, str))
        if (
            str_count > 3
        ):  # If a row has more than 3 strings, it's highly likely to be the header row
            headers = [str(h).strip() if h else "" for h in row]
            return i, headers
    return 0, []


def find_header_row_and_headers_from_rows(
    rows: List[Tuple[Any, ...]],
) -> Tuple[int, List[str]]:
    """Heuristic to find the real header row from generic row tuples."""
    for i, row in enumerate(rows):
        if i > 20:
            break
        str_count = sum(
            1 for val in row if val and isinstance(val, str) and val.strip()
        )
        if str_count > 3:
            headers = [str(h).strip() if h else "" for h in row]
            return i, headers
    return 0, []


def detect_distinct_branches(
    headers: List[str],
    rows: List[Tuple[Any, ...]],
    header_row_idx: int,
) -> List[str]:
    """Infer branch-like column and return distinct branch values."""
    branch_keywords = [
        "BRANCH_NAME",
        "BRANCH NAME",
        "BRANCH",
        "STATE",
        "LOCATION",
        "REGION",
        "SOL",
        "HUB",
    ]
    candidate_indices = [
        i
        for i, h in enumerate(headers)
        if h and any(k in h.upper() for k in branch_keywords)
    ]
    if not candidate_indices:
        return []

    best_idx = candidate_indices[0]
    max_score = -100
    rows_peek = rows[header_row_idx + 1 : header_row_idx + 11]

    for c_idx in candidate_indices:
        alpha_chars = 0
        total_chars = 0
        pure_numeric_count = 0
        row_count = 0

        for row in rows_peek:
            if len(row) > c_idx and row[c_idx] is not None:
                row_count += 1
                val_str = str(row[c_idx]).strip()
                if not val_str:
                    continue

                alpha_chars += sum(1 for c in val_str if c.isalpha())
                total_chars += len(val_str)
                if val_str.isdigit():
                    pure_numeric_count += 1

        score = (alpha_chars / (total_chars + 1)) if total_chars > 0 else 0
        if row_count > 0 and pure_numeric_count / row_count > 0.8:
            score -= 5.0
        if "NAME" in headers[c_idx].upper():
            score += 2.0

        if score > max_score:
            max_score = score
            best_idx = c_idx

    distinct_branches = set()
    for row in rows[header_row_idx + 1 :]:
        if len(row) > best_idx and row[best_idx]:
            distinct_branches.add(str(row[best_idx]).strip())

    return sorted(list(distinct_branches))

def auto_map_headers(excel_headers: List[str], preset_name: str = "retail", custom_fields: List[str] = None) -> Tuple[Dict[str, str], str]:
    """Tries to automatically map target fields based on synonyms and preset config."""
    from app.core.state import PRESETS
    preset = PRESETS.get(preset_name)
    
    if preset_name == "custom":
        fields = custom_fields or []
        synonyms = {}
    else:
        fields = preset["fields"] if preset else TARGET_FIELDS
        synonyms = preset["synonyms"] if preset else SYNONYMS
        
    mapped_fields = {}
    upper_headers = {h.upper(): h for h in excel_headers if h}

    for target in fields:
        mapped = False
        if target in synonyms:
            for synonym in synonyms[target]:
                if synonym.upper() in upper_headers:
                    mapped_fields[target] = upper_headers[synonym.upper()]
                    mapped = True
                    break
        if not mapped and target.upper() in upper_headers:
            mapped_fields[target] = upper_headers[target.upper()]
            mapped = True
        if not mapped:
            mapped_fields[target] = ""  # Needs manual mapping

    status = "Ready" if all(mapped_fields.values()) else "Needs Mapping"
    return mapped_fields, status


def extract_records(
    file_path: str,
    mapped_fields: Dict[str, str],
    header_row_idx: int,
    selected_sheets: List[str],
    selected_branches: List[str],
    account_name_concat_order: Dict[str, str] = None,
    account_name_concat_separator: str = " ",
    preset_name: str = "retail",
    custom_fields: List[str] = None,
    duplicate_logic: str = "primary_key",
    primary_key_field: str = "NUBAN",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extract normalized records from source workbook with source row numbers."""
    if account_name_concat_order is None:
        account_name_concat_order = {}
    
    from app.core.state import PRESETS
    preset = PRESETS.get(preset_name)
    if preset_name == "custom":
        fields = custom_fields or []
    else:
        fields = preset["fields"] if preset else TARGET_FIELDS
        
    all_extracted_records: List[Dict[str, Any]] = []
    all_skipped_records: List[Dict[str, Any]] = []
    
    sheets_to_process = [selected_sheets] if isinstance(selected_sheets, str) else selected_sheets

    for sheet_name in sheets_to_process:
        rows, _ = load_tabular_rows(file_path, sheet_name)
        if len(rows) <= header_row_idx:
            continue

        excel_headers = [str(h).strip() if h else "" for h in rows[header_row_idx]]
        header_map = {header: idx for idx, header in enumerate(excel_headers)}

        def get_val(row, source_field):
            if source_field == "__NA__":
                return ""
            if source_field and source_field in header_map:
                h_idx = header_map[source_field]
                if h_idx < len(row):
                    val = row[h_idx]
                    return str(val).strip() if val is not None else ""
            return ""

        # Identify best branch header once per sheet
        b_idx = None
        if selected_branches:
            branch_keywords = [
                "BRANCH_NAME", "BRANCH NAME", "BRANCH", "STATE",
                "LOCATION", "REGION", "SOL", "HUB"
            ]
            candidate_headers = [
                k for k in header_map.keys()
                if k and any(kw in k.upper() for kw in branch_keywords)
            ]

            if candidate_headers:
                best_header = candidate_headers[0]
                max_score = -100

                # Peek at some rows to score
                rows_peek = rows[header_row_idx + 1 : header_row_idx + 11]

                for h_name in candidate_headers:
                    h_idx = header_map[h_name]
                    alpha_count = 0
                    total_len = 0
                    pure_numeric = 0
                    peek_count = 0

                    for p_row in rows_peek:
                        if h_idx < len(p_row) and p_row[h_idx] is not None:
                            peek_count += 1
                            val_s = str(p_row[h_idx]).strip()
                            if not val_s: continue
                            alpha_count += sum(1 for c in val_s if c.isalpha())
                            total_len += len(val_s)
                            if val_s.isdigit(): pure_numeric += 1

                    curr_score = (alpha_count / (total_len + 1)) if total_len > 0 else 0
                    if peek_count > 0 and pure_numeric / peek_count > 0.8:
                        curr_score -= 5.0
                    if "NAME" in h_name.upper():
                        curr_score += 2.0
                    if "BRANCH" in h_name.upper():
                        curr_score += 1.5

                    if curr_score > max_score:
                        max_score = curr_score
                        best_header = h_name
                
                b_idx = header_map[best_header]

        extracted_records: List[Dict[str, Any]] = []
        skipped_records: List[Dict[str, Any]] = []
        for idx, row in enumerate(rows[header_row_idx + 1 :], start=header_row_idx + 2):
            if not any(row):
                continue

            # Filter branch if configured
            if b_idx is not None:
                branch_val = str(row[b_idx]).strip() if b_idx < len(row) and row[b_idx] else ""
                if not any(
                    sb.upper() in branch_val.upper() for sb in selected_branches
                ):
                    continue

            values: List[str] = []
            for target in fields:
                if target == "ACCOUNT_NAME":
                    account_name = "N/A"
                    if account_name_concat_order:
                        # Sort concatenation columns by user-specified order
                        def get_order_key(item):
                            val = str(item[1]).strip()
                            return int(val) if val.isdigit() else 999
                            
                        sorted_cols = sorted(account_name_concat_order.items(), key=get_order_key)
                        
                        # Concatenate selected columns for account name
                        concat_parts = []
                        for col_name, _ in sorted_cols:
                            if col_name in header_map:
                                col_idx = header_map[col_name]
                                if col_idx < len(row):
                                    val = row[col_idx]
                                    part = str(val).strip() if val is not None else ""
                                    if part:
                                        concat_parts.append(part)
                        
                        if concat_parts:
                            separator = account_name_concat_separator if account_name_concat_separator else " "
                            account_name = separator.join(concat_parts)

                    # Fallback to mapped field if concatenation is empty or not configured
                    if account_name == "N/A":
                        source_field = mapped_fields.get("ACCOUNT_NAME", "")
                        account_name = get_val(row, source_field) or "N/A"
                    
                    values.append(account_name)
                else:
                    source_field = mapped_fields.get(target, "")
                    values.append(get_val(row, source_field) or "N/A")

            # Validate TIN (mostly at least 5 alphanumeric characters with some numbers)
            if "TAXPAYER_ID" in fields:
                tin_idx = fields.index("TAXPAYER_ID")
                if values[tin_idx] != "N/A":
                    tin_str = values[tin_idx]
                    tin_digits = sum(1 for c in tin_str if c.isdigit())
                    if len(tin_str) < 5 or tin_digits < 3:
                        values[tin_idx] = "N/A"

            # Validate BVN (strictly 11 digits)
            if "BVN" in fields:
                bvn_idx = fields.index("BVN")
                if values[bvn_idx] != "N/A":
                    bvn_str = str(values[bvn_idx]).strip()
                    bvn_digits = "".join(filter(str.isdigit, bvn_str))
                    if len(bvn_digits) != 11:
                        values[bvn_idx] = "N/A"

            # Validate NUBAN (strictly 10 digits)
            if "NUBAN" in fields:
                nuban_idx = fields.index("NUBAN")
                if values[nuban_idx] != "N/A":
                    nuban_str = str(values[nuban_idx]).strip()
                    nuban_digits = "".join(filter(str.isdigit, nuban_str))
                    if len(nuban_digits) != 10:
                        values[nuban_idx] = "N/A"

            # Skip rows with no meaningful data at all
            if all(v == "N/A" or not v for v in values):
                continue

            # Skip records with missing Primary Key and capture them
            is_skipped = False
            pk_val = "N/A"
            if duplicate_logic == "primary_key" and primary_key_field:
                if primary_key_field in fields:
                    pk_idx = fields.index(primary_key_field)
                    pk_val = values[pk_idx]
                    if pk_val == "N/A" or not pk_val:
                        skipped_records.append({
                            "source_row": idx,
                            "sheet": sheet_name,
                            "values": values,
                        })
                        is_skipped = True
            elif "NUBAN" in fields:
                nuban_idx = fields.index("NUBAN")
                pk_val = values[nuban_idx]
                if pk_val == "N/A" or not pk_val:
                    skipped_records.append({
                        "source_row": idx,
                        "sheet": sheet_name,
                        "values": values,
                    })
                    is_skipped = True

            if is_skipped:
                continue

            # Unique key value fallback
            if pk_val == "N/A":
                # Find first non-empty value
                for val in values:
                    if val and val != "N/A":
                        pk_val = val
                        break

            extracted_records.append({
                "id": f"s{sheets_to_process.index(sheet_name)}r{idx}",
                "source_row": idx,
                "sheet": sheet_name,
                "nuban": pk_val,
                "values": values,
            })
        
        all_extracted_records.extend(extracted_records)
        all_skipped_records.extend(skipped_records)

    return all_extracted_records, all_skipped_records


def find_duplicate_groups(
    records: List[Dict[str, Any]],
    duplicate_logic: str = "primary_key",
    primary_key_field: str = "NUBAN",
    fields: List[str] = None
) -> List[Dict[str, Any]]:
    """Return duplicate groups for non-empty primary key values or fuzzy matching."""
    if duplicate_logic == "weirdly_similar":
        return find_similar_duplicates_sorted_neighborhood(records)
        
    grouped = defaultdict(list)
    for record in records:
        nuban = record.get("nuban", "N/A")
        if nuban and nuban != "N/A":
            grouped[nuban].append(record)

    duplicate_groups = []
    for nuban, group in grouped.items():
        if len(group) > 1:
            duplicate_groups.append({"nuban": nuban, "records": group})

    duplicate_groups.sort(key=lambda item: item["nuban"])
    return duplicate_groups


def resolve_duplicate_records(
    records: List[Dict[str, Any]],
    duplicate_groups: List[Dict[str, Any]],
    decision: str,
    accepted_record_ids: List[str],
    fields: List[str] = None,
) -> List[Dict[str, Any]]:
    """Resolve duplicate records by merge strategy or manual selection."""
    if fields is None:
        fields = TARGET_FIELDS
        
    duplicate_nubans = {group["nuban"] for group in duplicate_groups}
    final_records: List[Dict[str, Any]] = []

    # Keep all records that are not part of duplicate groups.
    for record in records:
        if record.get("nuban") not in duplicate_nubans:
            final_records.append(record)

    if decision == "merge":
        for group in duplicate_groups:
            merged_values: List[str] = []
            group_records = group["records"]

            for field_idx in range(len(fields)):
                chosen = "N/A"
                for rec in group_records:
                    if field_idx < len(rec["values"]):
                        val = rec["values"][field_idx]
                        if val and val != "N/A":
                            chosen = val
                            break
                merged_values.append(chosen)

            source_row = min(rec["source_row"] for rec in group_records)
            final_records.append({
                "id": f"merged-{group['nuban']}",
                "source_row": source_row,
                "nuban": group["nuban"],
                "values": merged_values,
            })
    else:
        accepted = set(accepted_record_ids)
        for group in duplicate_groups:
            for rec in group["records"]:
                if rec["id"] in accepted:
                    final_records.append(rec)

    final_records.sort(key=lambda rec: rec.get("source_row", 0))
    return final_records


def save_cleaned_records(
    file_path: str,
    records: List[Dict[str, Any]],
    fields: List[str] = None,
    output_pattern: str = "{filename}"
) -> str:
    """Save selected/merged records to cleaned directory and return file path."""
    if fields is None:
        fields = TARGET_FIELDS
        
    os.makedirs("cleaned", exist_ok=True)
    out_filename = resolve_output_filename(file_path, output_pattern)
    target_file = os.path.join("cleaned", out_filename)
    
    with open(target_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        for record in records:
            writer.writerow(record["values"])

    return target_file


def process_and_save(
    file_id: str,
    file_path: str,
    mapped_fields: Dict[str, str],
    header_row_idx: int,
    selected_sheets: List[str],
    selected_branches: List[str],
    account_name_concat_order: Dict[str, str] = None,
    account_name_concat_separator: str = " ",
    preset_name: str = "retail",
    custom_fields: List[str] = None,
    duplicate_logic: str = "primary_key",
    primary_key_field: str = "NUBAN",
    output_pattern: str = "{filename}",
) -> str:
    """Run full extraction, cleaning, and CSV save process."""
    if account_name_concat_order is None:
        account_name_concat_order = {}
    
    from app.core.state import PRESETS
    preset = PRESETS.get(preset_name)
    if preset_name == "custom":
        fields = custom_fields or []
    else:
        fields = preset["fields"] if preset else TARGET_FIELDS
        
    records, skipped_records = extract_records(
        file_path,
        mapped_fields,
        header_row_idx,
        selected_sheets,
        selected_branches,
        account_name_concat_order,
        account_name_concat_separator,
        preset_name,
        custom_fields,
        duplicate_logic,
        primary_key_field,
    )
    duplicate_groups = find_duplicate_groups(records, duplicate_logic, primary_key_field, fields)
    resolved = resolve_duplicate_records(records, duplicate_groups, "merge", [], fields)
    target_file = save_cleaned_records(file_path, resolved, fields, output_pattern)
    return target_file
