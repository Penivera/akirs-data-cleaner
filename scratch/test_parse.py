from app.services.cleaner import load_tabular_rows, find_header_row_and_headers_from_rows

path = "uploads/individual and corporate amount.csv"
rows, sheets = load_tabular_rows(path, "")
print("Loaded Rows:", rows)
print("Sheets:", sheets)
idx, headers = find_header_row_and_headers_from_rows(rows)
print("Header Index:", idx)
print("Headers:", headers)
