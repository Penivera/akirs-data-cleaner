import os
import uuid
from typing import Any, Dict, List, Optional


class FileState:
    id: str
    user_id: Optional[int]
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
    cleaned_path: Optional[str]

    def __init__(self):
        self.id = str(uuid.uuid4())
        self.user_id = None
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
        self.cleaned_path = None


# NOTE: state is no longer kept in process memory. Work items and background
# task status are persisted via app.core.repository so that multiple worker
# processes see the same data.

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
    user_id: Optional[int]
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
        self.user_id = None
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


class NubanState:
    id: str
    user_id: Optional[int]
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
        self.user_id = None
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


class IntelSyncState:
    id: str
    user_id: Optional[int]
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
        self.user_id = None
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


def get_user_upload_dir(user_id: int) -> str:
    """Return the per-user upload directory, creating it if needed."""
    path = os.path.join("uploads", str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def get_user_cleaned_dir(user_id: int) -> str:
    """Return the per-user cleaned directory, creating it if needed."""
    path = os.path.join("cleaned", str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def get_user_reports_dir(user_id: int) -> str:
    """Return the per-user reports directory, creating it if needed."""
    path = os.path.join("reports", str(user_id))
    os.makedirs(path, exist_ok=True)
    return path
