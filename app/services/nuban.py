import os
import csv
import httpx
import openpyxl
from typing import List, Dict, Any, Optional, Tuple
from app.core.state import NubanState
from app.services.cleaner import load_tabular_rows
from app.core.config import settings

async def get_bank_list() -> List[Dict[str, str]]:
    """Fetch bank list from Paystack."""
    key = settings.paystack_secret_key
    if not key:
        print("Error: PAYSTACK_SECRET_KEY not set in environment or .env file")
        return []
    url = "https://api.paystack.co/bank"
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            if data.get("status"):
                return [{"name": b["name"], "code": b["code"]} for b in data["data"]]
        except Exception as e:
            print(f"Error fetching banks: {e}")
    return []

async def resolve_account(account_number: str, bank_code: str) -> Optional[str]:
    """Resolve account name via Paystack with Flutterwave fallback."""
    # 1. Try Paystack first
    if settings.paystack_secret_key:
        name = await resolve_account_paystack(account_number, bank_code)
        if name:
            return name
            
    # 2. Try Flutterwave as fallback
    if settings.flutterwave_secret_key:
        # Translate bank code for Flutterwave if needed
        fw_bank_code = translate_to_flutterwave_code(bank_code)
        return await resolve_account_flutterwave(account_number, fw_bank_code)
        
    return None

async def resolve_account_paystack(account_number: str, bank_code: str) -> Optional[str]:
    """Internal helper for Paystack resolution."""
    key = settings.paystack_secret_key
    url = f"https://api.paystack.co/bank/resolve?account_number={account_number}&bank_code={bank_code}"
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if data.get("status"):
                    return data["data"]["account_name"]
        except Exception as e:
            print(f"Paystack resolution error: {e}")
    return None

async def resolve_account_flutterwave(account_number: str, bank_code: str) -> Optional[str]:
    """Internal helper for Flutterwave resolution."""
    key = settings.flutterwave_secret_key
    url = "https://api.flutterwave.com/v3/accounts/resolve"
    headers = {"Authorization": f"Bearer {key}"}
    payload = {"account_number": account_number, "account_bank": bank_code}
    async with httpx.AsyncClient() as client:
        try:
            # Note: Flutterwave uses POST for account resolution
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    return data["data"]["account_name"]
        except Exception as e:
            print(f"Flutterwave resolution error: {e}")
    return None

def translate_to_flutterwave_code(bank_code: str) -> str:
    """
    Map Paystack bank codes to Flutterwave bank codes.
    (Simple example mapping, should be expanded based on production needs)
    """
    mapping = {
        "044": "044",  # Access Bank
        "011": "011",  # First Bank
        "058": "058",  # GTBank
        "033": "033",  # UBA
        "232": "232",  # Sterling
    }
    return mapping.get(bank_code, bank_code)

async def process_nuban_resolution(state: NubanState):
    """Process file to resolve NUBANs and populate target field."""
    if not settings.paystack_secret_key and not settings.flutterwave_secret_key:
        raise Exception("Neither PAYSTACK_SECRET_KEY nor FLUTTERWAVE_SECRET_KEY set in environment")
    
    file_path = state.saved_path
    bank_code = state.selected_bank_code
    nuban_col = state.mapped_nuban_col
    target_col = state.mapped_target_col
    sheet_name = state.selected_sheets[0] if state.selected_sheets else ""

    rows, _ = load_tabular_rows(file_path, sheet_name)
    if not rows:
        raise Exception("No data found in file")

    header_row_idx = getattr(state, "header_row_idx", 0)
    headers = list(rows[header_row_idx])
    
    try:
        nuban_idx = headers.index(nuban_col)
    except ValueError:
        raise Exception(f"NUBAN column '{nuban_col}' not found in headers")

    # If target_col doesn't exist, we'll append it
    if target_col in headers:
        target_idx = headers.index(target_col)
        new_headers = headers
    else:
        target_idx = len(headers)
        new_headers = headers + [target_col]

    output_rows = [new_headers]
    
    # Process rows
    data_rows = rows[header_row_idx + 1:]
    for row in data_rows:
        if not any(row):
            continue
            
        row_list = list(row)
        # Ensure row has enough columns
        while len(row_list) < len(new_headers):
            row_list.append("")
            
        nuban = str(row_list[nuban_idx]).strip() if nuban_idx < len(row_list) else ""
        
        if nuban and len(nuban) >= 10:
            resolved_name = await resolve_account(nuban, bank_code)
            if resolved_name:
                row_list[target_idx] = resolved_name
            else:
                row_list[target_idx] = "Resolution Failed"
        else:
            row_list[target_idx] = "Invalid NUBAN"
            
        output_rows.append(row_list)

    # Save to cleaned directory
    os.makedirs("cleaned", exist_ok=True)
    out_filename = f"resolved_{os.path.basename(file_path)}"
    if out_filename.endswith(".xlsx"):
        out_filename = out_filename.replace(".xlsx", ".csv")
    
    out_path = os.path.join("cleaned", out_filename)
    with open(out_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(output_rows)
        
    state.resolved_path = out_path
    state.resolved_filename = out_filename
    return out_path
