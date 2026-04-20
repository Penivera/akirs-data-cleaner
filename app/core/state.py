import uuid
from typing import Dict, Any, List

class FileState:
    id: str
    original_filename: str
    saved_path: str
    headers: List[str]
    status: str # "Ready", "Needs Mapping", "Needs Sheet"
    sheet_names: List[str]
    selected_sheet: str
    available_branches: List[str]
    selected_branches: List[str]
    
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.headers = []
        self.mapped_fields = {}
        self.status = "New"
        self.sheet_names = []
        self.selected_sheet = ""
        self.available_branches = []
        self.selected_branches = []

# Global state to keep track of uploaded files in memory
file_db: Dict[str, FileState] = {}

TARGET_FIELDS = ['TAXPAYER_ID', 'ACCOUNT_NAME', 'NUBAN', 'BVN', 'PHONE', 'ADDRESS', 'DATE']

SYNONYMS = {
    'TAXPAYER_ID': ['TIN', 'TAXPAYER_ID', 'TAXPAYER ID'],
    'ACCOUNT_NAME': ['ACCOUNT_NAME', 'ACCT_NAME', 'ACCOUNT NAME', 'CUSTOMER NAME'],
    'NUBAN': ['NUBAN', 'ACCOUNT_NO', 'ACCT_NO', 'ACCOUNT NUMBER'],
    'BVN': ['BVN', 'BANK VERIFICATION NUMBER'],
    'PHONE': ['PHONE', 'PHONE NO 1', 'PHONE NO 2', 'PHONE NUMBER', 'MOBILE'],
    'ADDRESS': ['ADDRESS', 'RESIDENTIAL ADDRESS', 'HOME ADDRESS'],
    'DATE': ['DATE', 'ACCT_OPN_DATE', 'ACCOUNT OPEN DATE', 'OPEN DATE', 'DATE OPENED']
}
