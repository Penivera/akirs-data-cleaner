import uuid
from typing import Dict, Any, List,Optional


class FileState:
    id: str
    original_filename: str
    saved_path: str
    headers: List[str]
    status: str  # NOTE: "Ready", "Needs Mapping", "Needs Sheet"
    sheet_names: List[str]
    selected_sheets: List[str]
    available_branches: List[str]
    selected_branches: List[str]
    upload_hash: str
    upload_size: int
    uploaded_at: float
    extracted_records: List[Dict[str, Any]]
    duplicate_groups: List[Dict[str, Any]]
    skipped_records: List[Dict[str, Any]]
    header_row_idx: int
    account_name_concat_order: Dict[str, str]
    account_name_concat_separator: str
    mapped_fields: Dict[str, Any]
    field_separators: Dict[str, str]
    preset_name: str
    custom_fields: List[str]
    duplicate_logic: str
    primary_key_field: Optional[str]
    output_pattern: str
    health_report: Optional[Dict[str, Any]]
    verify_db: bool
    verify_db_query_field: Optional[str]
    verify_db_target_column: str
    verify_db_fuzzy: bool
    db_matches: List[Dict[str, Any]]
    db_decisions: Dict[str, str]

    def __init__(self):
        self.id = str(uuid.uuid4())
        self.headers = []
        self.mapped_fields = {}
        self.field_separators = {}
        self.status = "New"
        self.sheet_names = []
        self.selected_sheets = []
        self.available_branches = []
        self.selected_branches = []
        self.upload_hash = ""
        self.upload_size = 0
        self.uploaded_at = 0.0
        self.extracted_records = []
        self.duplicate_groups = []
        self.skipped_records = []
        self.header_row_idx = 0
        self.account_name_concat_order = {}
        self.account_name_concat_separator = " "
        self.preset_name = "retail"
        self.custom_fields = []
        self.duplicate_logic = "primary_key"
        self.primary_key_field = "NUBAN"
        self.output_pattern = "{filename}"
        self.health_report = None
        self.verify_db = False
        self.verify_db_query_field = ""
        self.verify_db_target_column = "ANY"
        self.verify_db_fuzzy = False
        self.db_matches = []
        self.db_decisions = {}


# Global state to keep track of uploaded files in memory
file_db: Dict[str, FileState] = {}

PRESETS = {
    "retail": {
        "name": "retail",
        "label": "Retail Migration",
        "fields": [
            "TAXPAYER_ID",
            "ACCOUNT_NAME",
            "NUBAN",
            "BVN",
            "PHONE",
            "ADDRESS",
            "DATE",
        ],
        "synonyms": {
            "TAXPAYER_ID": ["TIN", "TAXPAYER_ID", "TAXPAYER ID"],
            "ACCOUNT_NAME": ["ACCOUNT_NAME", "ACCT_NAME", "ACCOUNT NAME", "CUSTOMER NAME"],
            "NUBAN": ["NUBAN", "ACCOUNT_NO", "ACCT_NO", "ACCOUNT NUMBER"],
            "BVN": ["BVN", "BANK VERIFICATION NUMBER"],
            "PHONE": ["PHONE", "PHONE NO 1", "PHONE NO 2", "PHONE NUMBER", "MOBILE"],
            "ADDRESS": ["ADDRESS", "RESIDENTIAL ADDRESS", "HOME ADDRESS"],
            "DATE": ["DATE", "ACCT_OPN_DATE", "ACCOUNT OPEN DATE", "OPEN DATE", "DATE OPENED"],
        },
        "output_pattern": "{filename}",
        "duplicate_logic": "primary_key",
        "primary_key_field": "NUBAN",
    },
    "intelligence": {
        "name": "intelligence",
        "label": "Intelligence Gathering",
        "fields": [
            "NAME",
            "ADDRESS",
            "PHONE_NUMBER",
            "NATURE_OF_BUSINESS",
            "EMAIL",
        ],
        "synonyms": {
            "NAME": ["NAME", "FULLNAME", "FULL NAME", "TAXPAYER NAME", "ACCOUNT_NAME", "CUSTOMER NAME"],
            "ADDRESS": ["ADDRESS", "RESIDENTIAL ADDRESS", "HOME ADDRESS", "LOCATION"],
            "PHONE_NUMBER": ["PHONE_NUMBER", "PHONE", "PHONE NO", "PHONE NUMBER", "MOBILE"],
            "NATURE_OF_BUSINESS": ["NATURE_OF_BUSINESS", "BUSINESS", "LINE OF BUSINESS", "NATURE OF BUSINESS", "OCCUPATION"],
            "EMAIL": ["EMAIL", "EMAIL ADDRESS", "EMAIL_ADDRESS"],
        },
        "output_pattern": "INTELIGENCE_GATHERING_{filename}",
        "duplicate_logic": "weirdly_similar",
        "primary_key_field": "",
    }
}

TARGET_FIELDS = [
    "TAXPAYER_ID",
    "ACCOUNT_NAME",
    "NUBAN",
    "BVN",
    "PHONE",
    "ADDRESS",
    "DATE",
]

SYNONYMS = {
    "TAXPAYER_ID": ["TIN", "TAXPAYER_ID", "TAXPAYER ID"],
    "ACCOUNT_NAME": ["ACCOUNT_NAME", "ACCT_NAME", "ACCOUNT NAME", "CUSTOMER NAME"],
    "NUBAN": ["NUBAN", "ACCOUNT_NO", "ACCT_NO", "ACCOUNT NUMBER"],
    "BVN": ["BVN", "BANK VERIFICATION NUMBER"],
    "PHONE": ["PHONE", "PHONE NO 1", "PHONE NO 2", "PHONE NUMBER", "MOBILE"],
    "ADDRESS": ["ADDRESS", "RESIDENTIAL ADDRESS", "HOME ADDRESS"],
    "DATE": ["DATE", "ACCT_OPN_DATE", "ACCOUNT OPEN DATE", "OPEN DATE", "DATE OPENED"],
}

class AnalysisState:
    id: str
    original_filename: str
    saved_path: str
    headers: List[str]
    sheet_names: List[str]
    selected_sheets: List[str]
    status: str
    config: Dict[str, Any]
    report_path: Optional[str] = None
    report_filename: Optional[str] = None
    schema_version: str = "1.0"
    upload_hash: str
    upload_size: int
    uploaded_at: float
    header_row_idx: Optional[int] = None

    def __init__(self):
        self.id = str(uuid.uuid4())
        self.headers = []
        self.sheet_names = []
        self.selected_sheets = []
        self.status = "New"
        # store configuration
        self.config = {
            "identity_col": "",
            "metric_col": "",
            "currency_col": "",
            "flow_type_col": "",
            "credit_col": "",
            "debit_col": "",
            "inflow_indicator": "CR",
            "outflow_indicator": "DR",
            "flow_filter": "All",
            "limit": 50,
            "title": "DATA ANALYSIS REPORT",
            "keep_columns": [],
            "concat_order": {},
            "concat_separator": " ",
            "cumulate_by_nuban": False,
            "nuban_col": "",
            "min_amount_filter": None
        }
        self.report_path = ""
        self.upload_hash = ""
        self.upload_size = 0
        self.uploaded_at = 0.0
        self.header_row_idx = None

analysis_db: Dict[str, AnalysisState] = {}

class NubanState:
    id: str
    original_filename: str
    saved_path: str
    headers: List[str]
    sheet_names: List[str]
    selected_sheets: List[str]
    status: str
    upload_hash: str
    upload_size: int
    uploaded_at: float
    mapped_nuban_col: str
    mapped_target_col: str
    selected_bank_code: str
    resolved_path: Optional[str] = None
    resolved_filename: Optional[str] = None

    def __init__(self):
        self.id = str(uuid.uuid4())
        self.headers = []
        self.sheet_names = []
        self.selected_sheets = []
        self.status = "New"
        self.upload_hash = ""
        self.upload_size = 0
        self.uploaded_at = 0.0
        self.mapped_nuban_col = ""
        self.mapped_target_col = ""
        self.selected_bank_code = ""
        self.resolved_path = None
        self.resolved_filename = None

nuban_db: Dict[str, NubanState] = {}

class IntelSyncState:
    id: str
    original_filename: str
    saved_path: str
    headers: List[str]
    sheet_names: List[str]
    selected_sheets: List[str]
    status: str
    upload_hash: str
    upload_size: int
    uploaded_at: float
    matched_records: List[Dict[str, Any]]
    unique_records_count: int
    unique_path: Optional[str] = None
    unique_filename: Optional[str] = None
    verify_db_query_field: str
    verify_db_target_column: str
    verify_db_fuzzy: bool

    def __init__(self):
        self.id = str(uuid.uuid4())
        self.headers = []
        self.sheet_names = []
        self.selected_sheets = []
        self.status = "New"
        self.upload_hash = ""
        self.upload_size = 0
        self.uploaded_at = 0.0
        self.matched_records = []
        self.unique_records_count = 0
        self.unique_path = None
        self.unique_filename = None
        self.verify_db_query_field = ""
        self.verify_db_target_column = "ANY"
        self.verify_db_fuzzy = False

intelsync_db: Dict[str, IntelSyncState] = {}

import pickle
import os

DB_DIR = "uploads"
DB_FILE = os.path.join(DB_DIR, "state_database.pkl")

def save_all_states():
    os.makedirs(DB_DIR, exist_ok=True)
    try:
        temp_file = DB_FILE + ".tmp"
        data = {
            "file_db": file_db,
            "analysis_db": analysis_db,
            "nuban_db": nuban_db,
            "intelsync_db": intelsync_db,
        }
        with open(temp_file, "wb") as f:
            pickle.dump(data, f)
        os.replace(temp_file, DB_FILE)
    except Exception as e:
        print(f"Error persisting states: {e}")

def load_all_states():
    global file_db, analysis_db, nuban_db, intelsync_db
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "rb") as f:
                data = pickle.load(f)
                file_db.clear()
                file_db.update(data.get("file_db", {}))
                analysis_db.clear()
                analysis_db.update(data.get("analysis_db", {}))
                nuban_db.clear()
                nuban_db.update(data.get("nuban_db", {}))
                intelsync_db.clear()
                intelsync_db.update(data.get("intelsync_db", {}))
                print(f"Successfully loaded persisted states from {DB_FILE} ({len(file_db)} files, {len(intelsync_db)} syncs)")
                return
        except Exception as e:
            print(f"Error loading persisted states: {e}")

# Initial load
load_all_states()
