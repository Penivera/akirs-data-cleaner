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
            mapped_fields[target] = ""  # Needs manual mapping

    status = "Ready" if all(mapped_fields.values()) else "Needs Mapping"
    return mapped_fields, status


def extract_records(
    file_path: str,
    mapped_fields: Dict[str, str],
    header_row_idx: int,
    selected_sheet: str,
    selected_branches: List[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extract normalized records from source workbook with source row numbers."""
    rows, _ = load_tabular_rows(file_path, selected_sheet)
    if len(rows) <= header_row_idx:
        return [], []

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

    extracted_records: List[Dict[str, Any]] = []
    skipped_records: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows[header_row_idx + 1 :], start=header_row_idx + 2):
        if not any(row):
            continue

        # Filter branch if configured
        if selected_branches:
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
            candidate_headers = [
                k
                for k in header_map.keys()
                if k and any(kw in k.upper() for kw in branch_keywords)
            ]

            if candidate_headers:
                best_header = candidate_headers[0]
                max_score = -100

                for h_name in candidate_headers:
                    h_idx = header_map[h_name]
                    if h_idx >= len(row):
                        continue
                    val_str = str(row[h_idx]).strip() if row[h_idx] is not None else ""

                    alpha_count = sum(1 for c in val_str if c.isalpha())
                    curr_score = (alpha_count / (len(val_str) + 1)) if val_str else 0

                    if val_str.isdigit():
                        curr_score -= 5.0
                    if "NAME" in h_name.upper():
                        curr_score += 2.0

                    if curr_score > max_score:
                        max_score = curr_score
                        best_header = h_name

                b_idx = header_map[best_header]
                branch_val = str(row[b_idx]).strip() if b_idx < len(row) and row[b_idx] else ""

                if not any(
                    sb.upper() in branch_val.upper() for sb in selected_branches
                ):
                    continue

        values: List[str] = []
        for target in TARGET_FIELDS:
            source_field = mapped_fields.get(target, "")
            values.append(get_val(row, source_field) or "N/A")

        # Validate TIN (mostly at least 5 alphanumeric characters with some numbers)
        if values[0] != "N/A":
            tin_str = values[0]
            tin_digits = sum(1 for c in tin_str if c.isdigit())
            if len(tin_str) < 5 or tin_digits < 3:
                values[0] = "N/A"

        # Validate NUBAN (should be around 10 digits, minimum 8 characters to not be gibberish)
        if values[2] != "N/A":
            nuban_str = values[2]
            nuban_digits = sum(1 for c in nuban_str if c.isdigit())
            if len(nuban_str) < 8 or nuban_digits < 7:
                values[2] = "N/A"

        # Skip rows with no meaningful identity data
        if values[2] == "N/A" and values[1] == "N/A":
            continue

        # Skip records with missing NUBAN and capture them
        if values[2] == "N/A":
            skipped_records.append(
                {
                    "source_row": idx,
                    "values": values,
                }
            )
            continue

        extracted_records.append(
            {
                "id": f"r{idx}",
                "source_row": idx,
                "nuban": values[2],
                "values": values,
            }
        )

    return extracted_records, skipped_records


def find_duplicate_groups(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return duplicate groups for non-empty NUBAN values."""
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
) -> List[Dict[str, Any]]:
    """Resolve duplicate records by merge strategy or manual selection."""
    duplicate_nubans = {group["nuban"] for group in duplicate_groups}
    final_records: List[Dict[str, Any]] = []

    # Keep all records that are not part of duplicate NUBAN groups.
    for record in records:
        if record.get("nuban") not in duplicate_nubans:
            final_records.append(record)

    if decision == "merge":
        for group in duplicate_groups:
            merged_values: List[str] = []
            group_records = group["records"]

            for field_idx in range(len(TARGET_FIELDS)):
                chosen = "N/A"
                for rec in group_records:
                    val = rec["values"][field_idx]
                    if val and val != "N/A":
                        chosen = val
                        break
                merged_values.append(chosen)

            source_row = min(rec["source_row"] for rec in group_records)
            final_records.append(
                {
                    "id": f"merged-{group['nuban']}",
                    "source_row": source_row,
                    "nuban": group["nuban"],
                    "values": merged_values,
                }
            )
    else:
        accepted = set(accepted_record_ids)
        for group in duplicate_groups:
            for rec in group["records"]:
                if rec["id"] in accepted:
                    final_records.append(rec)

    final_records.sort(key=lambda rec: rec.get("source_row", 0))
    return final_records


def save_cleaned_records(file_path: str, records: List[Dict[str, Any]]) -> str:
    """Save selected/merged records to cleaned directory and return file path."""
    os.makedirs("cleaned", exist_ok=True)
    out_filename = os.path.basename(file_path)
    if out_filename.endswith(".xlsx"):
        out_filename = out_filename.replace(".xlsx", ".csv")

    target_file = os.path.join("cleaned", out_filename)
    with open(target_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(TARGET_FIELDS)
        for record in records:
            writer.writerow(record["values"])

    return target_file


def process_and_save(
    file_path: str,
    mapped_fields: Dict[str, str],
    header_row_idx: int,
    selected_sheet: str,
    selected_branches: List[str],
) -> Tuple[int, int, str]:
    """Extracts, cleans, and deduplicates records, saving to cleaned/."""
    records, skipped_records = extract_records(
        file_path,
        mapped_fields,
        header_row_idx,
        selected_sheet,
        selected_branches,
    )
    duplicate_groups = find_duplicate_groups(records)
    resolved = resolve_duplicate_records(records, duplicate_groups, "merge", [])
    target_file = save_cleaned_records(file_path, resolved)
    return len(resolved), len(records) - len(resolved) + len(skipped_records), target_file
