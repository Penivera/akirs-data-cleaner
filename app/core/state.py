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
    mapped_fields: Dict[str, str]
    preset_name: str
    custom_fields: List[str]
    duplicate_logic: str
    primary_key_field: Optional[str]
    output_pattern: str
    health_report: Optional[Dict[str, Any]]

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
        self.account_name_concat_order = {}
        self.account_name_concat_separator = " "
        self.preset_name = "retail"
        self.custom_fields = []
        self.duplicate_logic = "primary_key"
        self.primary_key_field = "NUBAN"
        self.output_pattern = "{filename}"
        self.health_report = None


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
            "inflow_indicator": "INFLOW",
            "outflow_indicator": "OUTFLOW",
            "flow_filter": "All",
            "limit": 50,
            "title": "DATA ANALYSIS REPORT",
            "keep_columns": [],
            "concat_order": {},
            "concat_separator": " ",
            "cumulate_by_nuban": False,
            "nuban_col": ""
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
