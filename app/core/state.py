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

    def __init__(self):
        self.id = str(uuid.uuid4())
        self.headers = []
        self.mapped_fields = {}
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


# Global state to keep track of uploaded files in memory
file_db: Dict[str, FileState] = {}

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
            "inflow_indicator": "INFLOW",
            "outflow_indicator": "OUTFLOW",
            "flow_filter": "All",
            "limit": 50,
            "title": "DATA ANALYSIS REPORT",
            "keep_columns": []
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
