# System Design — AKIRS Data Toolkit

> Derived from the current codebase (`main.py`, `app/`, `templates/`, `static/`).

## 1. High-Level Context

```mermaid
flowchart TB
    User["AKIRS Staff<br/>(Browser / LAN)"]
    subgraph Server["AKIRS On-Premise Server"]
        App["AKIRS Data Toolkit<br/>FastAPI + Uvicorn"]
        FS[("File System<br/>uploads/ cleaned/ reports/")]
        State[("In-Memory State<br/>+ state_database.pkl")]
    end
    Paystack["Paystack API<br/>bank list + resolve"]
    Flutter["Flutterwave API<br/>resolve fallback"]
    Intel["AKIRS TMS Intelligence DB<br/>REST search"]

    User -->|"HTTP :8080 / HTMX"| App
    App <--> FS
    App <--> State
    App -->|"GET /bank, /bank/resolve"| Paystack
    App -->|"POST /accounts/resolve"| Flutter
    App -->|"GET intelligenceGathering"| Intel
```

## 2. Component / Layer Architecture

```mermaid
flowchart TB
    subgraph FE["Frontend (Jinja2 + HTMX + Vanilla JS)"]
        V1["Batch Process"]
        V2["Cleaned Datasets"]
        V3["Analyse & Report"]
        V4["NUBAN Audit"]
        V5["DB Sync"]
    end

    subgraph API["app/api — Routers"]
        R1["routes.py<br/>batch cleaning"]
        R2["analytics.py<br/>analysis + reports"]
        R3["nuban.py<br/>account resolution"]
        R4["intelligence.py<br/>DB sync"]
    end

    subgraph SVC["app/services — Business Logic"]
        S1["cleaner.py<br/>parse · map · validate · dedupe · export"]
        S2["analyser.py<br/>markdown reports · FX · aggregation"]
        S3["nuban.py<br/>Paystack/Flutterwave"]
        S4["intelligence.py<br/>live DB matching"]
    end

    subgraph CORE["app/core"]
        C1["config.py<br/>Settings (env)"]
        C2["state.py<br/>State models · PRESETS · pickle"]
    end

    subgraph EXT["External"]
        E1["openpyxl / csv"]
        E2["httpx"]
    end

    FE --> API
    R1 --> S1
    R2 --> S2
    R3 --> S3
    R4 --> S4
    S1 & S2 & S3 & S4 --> C2
    S3 & S4 --> E2
    S1 & S2 --> E1
    C2 --> C1
```

## 3. Module Dependency Graph

```mermaid
flowchart LR
    main["main.py"] --> R["app/api/*"]
    R --> services["app/services/*"]
    services --> core["app/core/state.py"]
    services --> config["app/core/config.py"]
    services --> cleaner["app/services/cleaner.py"]
    nuban_s["nuban.py"] --> cleaner
    intel_s["intelligence.py"] --> config
    analytics_r["analytics.py"] --> analyser
    routes_r["routes.py"] --> intel_s
```

`cleaner.py` is the shared kernel — `routes.py`, `analytics.py`, `nuban.py`, and `intelligence.py` all depend on it for `load_tabular_rows` / header detection / CSV writing.

## 4. Batch Cleaning Pipeline (sequence)

```mermaid
sequenceDiagram
    actor U as User
    participant API as routes.py
    participant CL as cleaner.py
    participant DB as intelligence.py
    participant FS as cleaned/

    U->>API: POST /api/upload (xlsx/csv)
    API->>CL: pre_flight_validate() + find_header_row()
    API->>CL: auto_map_headers() (synonyms/preset)
    API-->>U: file card (Ready / Needs Mapping / Needs Sheet)

    U->>API: POST /api/mapping/{id} (confirm/override)
    U->>API: POST /api/process/{id}
    API->>CL: extract_records() + validate TIN/BVN/NUBAN + branch filter
    API->>CL: find_duplicate_groups()
    alt duplicates found
        API-->>U: Needs Duplicate Review
        U->>API: POST /api/duplicates/{id} (merge | pick)
        API->>CL: resolve_duplicate_records()
    end
    opt verify_db enabled
        API->>DB: check_file_records_against_db() (Semaphore 15)
        DB-->>API: uploaded/DB match pairs
        API-->>U: Needs DB Review
        U->>API: POST /api/db-resolve/{id} (skip/overwrite/keep)
    end
    API->>CL: save_cleaned_records()
    CL->>FS: {pattern}.csv
    API-->>U: Processed (N rows) + download
```

## 5. NUBAN Resolution Pipeline

```mermaid
sequenceDiagram
    actor U as User
    participant N as nuban.py
    participant PS as Paystack
    participant FW as Flutterwave

    U->>N: POST /api/nuban/upload + save-config
    N->>PS: GET /bank (bank list)
    U->>N: POST /api/nuban/resolve/{id}
    loop each row
        N->>PS: GET /bank/resolve
        alt success
            PS-->>N: account_name
        else fail
            N->>FW: POST /accounts/resolve
            FW-->>N: account_name / failed
        end
    end
    N-->>U: cleaned/resolved_*.csv
```

## 6. Intelligence DB Sync Pipeline

```mermaid
sequenceDiagram
    actor U as User
    participant I as intelligence.py
    participant TMS as AKIRS TMS DB

    U->>I: POST /api/intel/upload + save-config
    I->>I: extract_records + auto_map (NAME/ADDRESS/PHONE/BUSINESS/EMAIL)
    I->>TMS: parallel GET ?search= (Semaphore 15, optional Jaccard fuzzy >= 0.35)
    TMS-->>I: matches / empty
    I-->>U: CLEANED_UNIQUE_*.csv (records not in live DB)
```

## 7. State Model

```mermaid
classDiagram
    class FileState {
        +id, original_filename, saved_path
        +headers, status, sheet_names, selected_sheets
        +available_branches, selected_branches
        +extracted_records, duplicate_groups, skipped_records
        +mapped_fields, field_separators, preset_name
        +duplicate_logic, primary_key_field, output_pattern
        +health_report, verify_db
        +db_matches, db_decisions
    }
    class AnalysisState {
        +config: identity/metric/currency/flow/limit
        +report_path, report_filename
    }
    class NubanState {
        +mapped_nuban_col, mapped_target_col
        +selected_bank_code, resolved_path
    }
    class IntelSyncState {
        +matched_records, unique_records_count
        +verify_db_query_field, verify_db_target_column, verify_db_fuzzy
    }
    FileState --> "file_db"
    AnalysisState --> "analysis_db"
    NubanState --> "nuban_db"
    IntelSyncState --> "intelsync_db"
```

All four dicts are persisted together via `pickle` to `uploads/state_database.pkl` on every mutation (`save_all_states()`), and loaded at startup (`load_all_states()`).

## 8. Deployment Topology

```mermaid
flowchart LR
    subgraph LAN["AKIRS Intranet"]
        B["Client Browser"]
        subgraph Host["Windows/Linux Host"]
            UV["uvicorn main:app :8080"]
            subgraph Dirs["Working Directories"]
                UP["uploads/"]
                CL["cleaned/"]
                RP["reports/"]
                PK["uploads/state_database.pkl"]
            end
        end
    end
    subgraph Internet["Public Internet"]
        PS["api.paystack.co"]
        FW["api.flutterwave.com"]
    end
    subgraph TMSNet["AKIRS TMS"]
        TMS["akirs-tms.net/intelligence_db"]
    end
    B -->|"HTML/HTMX"| UV
    UV --> Dirs
    UV --> PS & FW
    UV --> TMS
```

## 9. API Surface

| Router | Endpoints |
|--------|-----------|
| `routes.py` | `/`, `/api/upload`, `/api/components/mapping/{id}`, `/api/mapping/{id}`, `/api/process/{id}`, `/api/duplicates/{id}`, `/api/db-resolve/{id}`, `/api/view/*`, `/api/download/{f}`, `/api/download-batch` |
| `analytics.py` | `/api/analyse/view`, `/upload`, `/config/{id}`, `/components/config-form/{id}`, `/generate/{id}`, `/delete/{id}`, `/download/{f}`, `/view-report/{f}` |
| `nuban.py` | `/api/nuban/view`, `/upload`, `/config-form/{id}`, `/save-config/{id}`, `/resolve/{id}`, `/delete/{id}` |
| `intelligence.py` | `/api/intel/view`, `/upload`, `/config-form/{id}`, `/save-config/{id}`, `/delete/{id}` |

## 10. Key Decision Points

| Stage | User Action | Outcome |
|-------|-------------|---------|
| Duplicates found | Merge / Pick records | Remaining records proceed to DB check |
| DB verification enabled | Skip / Overwrite / Keep | Skipped excluded; Overwrite replaces DB; Keep retains upload |
| No duplicates + no DB matches | Automatic | Records written directly to CSV |
| Multi-sheet workbook | Select sheet(s) | Headers/branches re-detected for the chosen sheet |
