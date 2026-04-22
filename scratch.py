import openpyxl

wb = openpyxl.load_workbook('individual and corporate amount.xlsx', read_only=True, data_only=True)
sheet = wb.active

types = set()
for row in sheet.iter_rows(min_row=2, max_row=1000, values_only=True):
    if len(row) > 6 and row[6]:
        types.add(row[6])
print("Transaction Types found:", types)
