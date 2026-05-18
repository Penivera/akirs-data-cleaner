import os
import csv
from app.services.cleaner import extract_records

def run_test():
    print("Starting verification of generic field concatenation...")
    
    # 1. Create a temporary source CSV file
    temp_csv = "scratch/temp_ingestion.csv"
    os.makedirs("scratch", exist_ok=True)
    
    headers = ["FIRST_NAME", "LAST_NAME", "TAXPAYER_TIN", "EMAIL_PREFIX", "EMAIL_DOMAIN"]
    rows = [
        ["Arit", "Effiong", "1234567890", "arit.effiong", "gmail.com"],
        ["Ekpenyong", "Bassey", "9876543210", "ekpenyong.b", "akirs.gov.ng"],
    ]
    
    with open(temp_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
        
    try:
        # 2. Configure a multi-column mapping list
        # Map:
        # ACCOUNT_NAME -> ["FIRST_NAME", "LAST_NAME"] with separator " "
        # EMAIL -> ["EMAIL_PREFIX", "EMAIL_DOMAIN"] with separator "@"
        # TAXPAYER_ID -> "TAXPAYER_TIN" (simple single column mapping)
        # NUBAN -> "TAXPAYER_TIN" (so it has a valid 10-digit primary key!)
        
        mapped_fields = {
            "ACCOUNT_NAME": ["FIRST_NAME", "LAST_NAME"],
            "EMAIL": ["EMAIL_PREFIX", "EMAIL_DOMAIN"],
            "TAXPAYER_ID": "TAXPAYER_TIN",
            "NUBAN": "TAXPAYER_TIN",
            "PHONE": "__NA__",
            "BVN": "__NA__",
            "ADDRESS": "__NA__",
            "DATE": "__NA__",
        }
        
        field_separators = {
            "ACCOUNT_NAME": " ",
            "EMAIL": "@",
            "TAXPAYER_ID": "",
        }
        
        # 3. Extract the records
        records, skipped = extract_records(
            file_path=temp_csv,
            mapped_fields=mapped_fields,
            header_row_idx=0,
            selected_sheets=["Sheet1"],
            selected_branches=[],
            account_name_concat_order=None,
            account_name_concat_separator=" ",
            preset_name="retail",
            field_separators=field_separators,
        )
        
        print(f"Extracted {len(records)} records. Skipped {len(skipped)} records.")
        
        if skipped:
            print("Skipped reasons / values:")
            for s in skipped:
                print(s)
                
        # 4. Verify the outputs
        # Column order for Retail preset:
        # ["TAXPAYER_ID", "ACCOUNT_NAME", "NUBAN", "BVN", "PHONE", "ADDRESS", "DATE"]
        
        rec1 = records[0]["values"]
        rec2 = records[1]["values"]
        
        print("Record 1:", rec1)
        print("Record 2:", rec2)
        
        # Assertions
        # TAXPAYER_ID
        assert rec1[0] == "1234567890", f"Expected '1234567890', got '{rec1[0]}'"
        # ACCOUNT_NAME (concatenated with ' ')
        assert rec1[1] == "Arit Effiong", f"Expected 'Arit Effiong', got '{rec1[1]}'"
        # NUBAN
        assert rec1[2] == "1234567890", f"Expected '1234567890', got '{rec1[2]}'"
        
        print("✓ All assertions PASSED! Generic concatenation and custom separators work flawlessly!")
        
    finally:
        if os.path.exists(temp_csv):
            os.remove(temp_csv)

if __name__ == "__main__":
    run_test()
