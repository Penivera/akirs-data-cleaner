import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from app.services.cleaner import extract_records, load_tabular_rows, find_header_row_and_headers_from_rows
from app.core.state import TARGET_FIELDS

file_path = "uploads/Akwa Ibom.csv"
rows, _ = load_tabular_rows(file_path, "")
idx, headers = find_header_row_and_headers_from_rows(rows)

print(f"Header row index: {idx}")
print(f"Headers: {headers}")

# Simulate manual mapping
mapped_fields = {
    "TAXPAYER_ID": "TAXID",
    "ACCOUNT_NAME": "ACCOUNTNAME",
    "NUBAN": "ACCOUNTNUMBER",
    "BVN": "NIN",
    "PHONE": "PHONE",
    "ADDRESS": "CUSTOMERADDRESS",
    "DATE": "DATEOFACCTOPENING",
}

print(f"Mapped fields: {mapped_fields}")

print(f"Total rows loaded: {len(rows)}")
if len(rows) > 0:
    print(f"Row 0: {rows[0]}")
if len(rows) > 1:
    print(f"Row 1: {rows[1]}")

excel_headers = [str(h).strip() if h else "" for h in rows[idx]]
header_map = {header: i for i, header in enumerate(excel_headers)}
print(f"Header map: {header_map}")

records, skipped = extract_records(
    file_path,
    mapped_fields,
    idx,
    [""],
    [] 
)

print(f"Total records extracted: {len(records)}")
print(f"Total records skipped: {len(skipped)}")

if records:
    print(f"First record: {records[0]}")
else:
    print("NO RECORDS EXTRACTED")
    # Let's check why
    if skipped:
        print(f"First skipped record values: {skipped[0]['values']}")
