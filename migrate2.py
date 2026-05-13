import csv
import openpyxl

source_file = 'Newly Opened Accts UYO OCTOBER 2024.xlsx'
target_file = 'Newly Opened Accts UYO OCTOBER 2024.csv'

def migrate_data():
    print(f"Loading data from '{source_file}'...")
    wb = openpyxl.load_workbook(source_file, data_only=True)
    sheet = wb.active

    target_headers = ['TAXPAYER_ID', 'ACCOUNT_NAME', 'NUBAN', 'BVN', 'PHONE', 'ADDRESS', 'DATE']
    
    # Read all rows
    rows = list(sheet.iter_rows(values_only=True))
    
    # Row index 3 is the header row
    excel_headers = [str(h).strip() if h else '' for h in rows[3]]
    header_map = {header: idx for idx, header in enumerate(excel_headers)}
    print(excel_headers)
    print(header_map)

    def get_val(row, header_name):
        if header_name in header_map:
            val = row[header_map[header_name]]
            return str(val) if val is not None else ""
        return ""

    processed = 0
    skipped_duplicates = 0
    duplicate_nubans=[]
    seen_nubans = set()
    print(f"Writing mapped data to '{target_file}'...")
    with open(target_file, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(target_headers)
        
        # Data starts from row index 4
        for row in rows[4:]:
            # Skip completely empty rows
            if not any(row):
                continue
                
            branch_name = get_val(row, 'BRANCH NAME')
            if 'UYO' not in branch_name.upper():
                continue
                
            taxpayer_id = get_val(row, 'TIN') or "N/A"
            account_name = get_val(row, 'ACCT_NAME')
            nuban = get_val(row, 'ACCOUNT_NO')
            bvn = get_val(row, 'BVN') or "N/A"
            phone = get_val(row, 'PHONE NO 1')
            address = get_val(row,"ADDRESS") or "N/A"
            date_str = get_val(row, 'ACCT_OPN_DATE') or "N/A"

            if not nuban:
                raise Exception("Nuban not found")
            
            # If the NUBAN is already seen, discard this duplicate row
            if nuban and nuban in seen_nubans:
                duplicate_nubans.append(nuban)
                skipped_duplicates += 1
                continue
                
            if nuban:
                seen_nubans.add(nuban)
            
            # Fallback to PHONE NO 2 if PHONE NO 1 is missing
            if not phone:
                phone = get_val(row, 'PHONE NO 2') or "N/A"
            
            writer.writerow([taxpayer_id, account_name, nuban, bvn, phone, address, date_str])
            processed += 1
    print(duplicate_nubans)
    print(f"Success! Migrated {processed} rows. Skipped {skipped_duplicates} duplicate records.")

if __name__ == "__main__":
    migrate_data()
