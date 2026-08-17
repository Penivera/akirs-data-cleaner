# Attachment B: Data Flow Diagram

## End-to-End Processing Pipeline

### Main Cleaning Pipeline

```
User Uploads
  Excel/CSV
     │
     ▼
┌─────────────────────┐
│  1. UPLOAD          │  POST /api/upload
│  - SHA-256 hash     │  - Validates file type (.xlsx, .csv)
│  - Duplicate check  │  - Saves to uploads/
│  - Health scan      │  - Identifies merged cells, formula errors,
│                     │    empty headers, column count mismatches
│  Health Report      │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  2. AUTO-MAPPING    │  POST /api/components/mapping/{file_id}
│  - Heuristic header │  - Synonym matching against preset fields
│    detection        │    (e.g., "PHONE NO 1" → PHONE)
│  - Preset selection │  - User can override mappings manually
│    (retail/intel)   │
│  - Branch scan      │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  3. PROCESS         │  POST /api/process/{file_id}
│  - Extract records  │  - Reads rows below header
│  - Validate fields  │  - TIN: ≥5 chars, ≥3 digits
│  - Filter branches  │  - BVN: exactly 11 digits
│                     │  - NUBAN: exactly 10 digits
│                     │  - Invalid records go to skipped_records
├─────────────────────┤
│                     │
│  ┌─── DUPLICATES?   │
│  │                  │
│  │  YES ──► 3a. Duplicate Review  ──► Resolve (merge/pick)
│  │                  │
│  │  NO             │
│  └─────────────────►│
│                     │
│  ┌─── DB VERIFY?    │
│  │                  │
│  │  YES ──► 3b. DB Review  ──► Resolve (skip/overwrite/keep)
│  │                  │
│  │  NO             │
│  └─────────────────►│
│                     │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  4. EXPORT          │
│  - Write CSV        │  saved to cleaned/{filename}.csv
│  - Status: Done     │  Available for download
└─────────────────────┘
```

### NUBAN Resolution Pipeline

```
Upload file
     │
     ▼
Select bank ──────────────────────► GET api.paystack.co/bank (fetch bank list)
     │
     ▼
Map NUBAN column + Target column
     │
     ▼
┌────────────────────────────────────────────┐
│  For each row:                             │
│                                            │
│  Read NUBAN (10-digit)                     │
│       │                                    │
│       ▼                                    │
│  ┌─────────────────┐                       │
│  │ Paystack Resolve │──► Success ──► Name  │
│  │ GET /bank/resolve│                       │
│  └────────┬────────┘                       │
│           │ Fail                           │
│           ▼                                │
│  ┌─────────────────┐                       │
│  │ Flutterwave     │──► Success ──► Name   │
│  │ POST /resolve   │                       │
│  └────────┬────────┘                       │
│           │ Fail                           │
│           ▼                                │
│     "Resolution Failed"                    │
└────────────────────────────────────────────┘
     │
     ▼
Write resolved CSV to cleaned/
```

### Intelligence DB Sync Pipeline

```
Upload file
     │
     ▼
Select sheet + config
  (query field, target column, fuzzy toggle)
     │
     ▼
Auto-map to intelligence preset fields:
  NAME, ADDRESS, PHONE_NUMBER, NATURE_OF_BUSINESS, EMAIL
     │
     ▼
┌─────────────────────────────────────────────┐
│  For each record:                           │
│                                             │
│  Build query string (NAME / EMAIL / PHONE)  │
│       │                                     │
│       ▼                                     │
│  GET akirs-tms.net/intelligence_db/...      │
│      ?search={query}&page=1&limit=10        │
│       │                                     │
│       ├── Match found (substring or fuzzy)  │
│       │      → tagged as existing           │
│       │                                     │
│       └── No match                          │
│              → tagged as unique             │
└─────────────────────────────────────────────┘
     │
     ▼
Output: CLEANED_UNIQUE_{filename}.csv
  (only records NOT found in live DB)
```

### DB Verification in Main Pipeline

```
After duplicate resolution ──► verify_db=true?
                                    │
                                    ▼
                          ┌─────────────────────┐
                          │  check_file_records │
                          │  _against_db()      │
                          │                     │
                          │  Semaphore(15)      │
                          │  concurrent queries │
                          └─────────┬───────────┘
                                    │
                          ┌─────────▼───────────┐
                          │  Results:           │
                          │                     │
                          │  [rec, DB_rec] pairs│
                          │                     │
                          │  DB match? ──► DB   │
                          │               Review│
                          │               screen│
                          │                     │
                          │  No match ──► Export│
                          │               to CSV│
                          └─────────────────────┘
```

## Key Decision Points

| Stage | User Action | Outcome |
|-------|------------|---------|
| Duplicates found | Merge / Pick records | Remaining records proceed to DB check |
| DB verification enabled | Skip / Overwrite / Keep | Skipped → excluded. Overwrite → uploaded record replaces DB. Keep → upload record kept |
| No duplicates + No DB matches | Automatic | Records written directly to CSV |

## File States

```
New → Needs Sheet (multi-sheet) → Needs Config → Needs Mapping →
Processing → Needs Duplicate Review → Needs DB Review →
Processed (N rows)
```
