# Attachment A: System Architecture Overview

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          AKIRS Batch File Cleaner                        │
│                              (On-Premise Server)                         │
│                                                                          │
│  ┌─────────────┐    ┌──────────────────┐    ┌─────────────────────────┐ │
│  │   Browser    │◄──►│   FastAPI Web    │◄──►│    In-Memory State      │ │
│  │   (HTMX)     │    │    (Uvicorn)     │    │  (pickle persistence)   │ │
│  │              │    │                  │    │                         │ │
│  │  Drag-drop   │    │  ┌────────────┐  │    │  file_db                │ │
│  │  Upload UI   │    │  │  routes.py  │  │    │  intelsync_db           │ │
│  │              │    │  │            │  │    │  nuban_db               │ │
│  │  Config      │    │  │ analytics  │  │    │  analysis_db            │ │
│  │  Forms       │    │  │   .py      │  │    └─────────────────────────┘ │
│  │              │    │  │            │  │                                │
│  │  Review UI   │    │  │ nuban.py   │  │    ┌─────────────────────────┐ │
│  │              │    │  │            │  │    │      File System        │ │
│  │  Download    │    │  │intelligence│  │    │                         │ │
│  │              │    │  │   .py      │  │    │  uploads/  (raw files)  │ │
│  └─────────────┘    │  └────────────┘  │    │  cleaned/  (CSV output)  │ │
│                     └──────────────────┘    │  reports/ (analytics)    │ │
│                                             └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                           │           │           │
                           ▼           ▼           ▼
               ┌───────────────┐ ┌──────────┐ ┌──────────────────────┐
               │   Paystack    │ │Flutterwave│ │  AKIRS Intelligence  │
               │     API       │ │    API    │ │   Database (REST)    │
               │               │ │           │ │                      │
               │  NUBAN→Name   │ │ NUBAN→Name│ │ Search by Name,      │
               │  resolution   │ │ (fallback)│ │ Email, or Phone      │
               │               │ │           │ │                      │
               │  Bank list    │ │           │ │ /intelligenceGathering│
               └───────────────┘ └──────────┘ └──────────────────────┘
```

## Component Breakdown

| Component | Technology | Role |
|-----------|-----------|------|
| **Web Server** | FastAPI + Uvicorn | Routes HTTP requests, serves HTML via Jinja2 templates |
| **Frontend** | HTMX + CSS + Vanilla JS | Dynamic SPA-like UI without framework. Drag-drop upload, config forms, review panels |
| **State Layer** | Python dicts + pickle | All application state is in-memory; persisted to `uploads/state_database.pkl` on every mutation |
| **File Parser** | openpyxl | Reads `.xlsx` files, detects header rows, extracts tabular data |
| **Cleaning Engine** | Python (`cleaner.py`) | Auto-maps columns via synonym matching, validates TIN/BVN/NUBAN, deduplicates (exact + fuzzy) |
| **NUBAN Resolution** | Paystack (primary) + Flutterwave (fallback) | Resolves 10-digit NUBAN to account holder name |
| **DB Sync** | AKIRS Intelligence Database REST API | Checks records against live taxpayer database |
| **Analytics** | Python (`analyser.py`) | Generates Markdown financial reports (inflows/outflows/currency grouping) |
| **Output** | CSV files | Cleaned, deduplicated, validated data in `cleaned/` directory |

## Deployment Topology

```
┌──────────────┐     HTTP :8000     ┌──────────────────────┐
│  Client      │───────────────────►│  AKIRS On-Prem Server│
│  Browser     │                    │  Windows / Linux     │
│  (LAN)       │◄───────────────────│  uvicorn main:app    │
└──────────────┘     HTML/HTMX      └──────────┬───────────┘
                                               │
                    ┌──────────────────────────┼──────────┐
                    ▼                          ▼          ▼
           ┌──────────────┐          ┌─────────────────┐
           │  Internet    │          │  AKIRS Intranet  │
           │  Paystack    │          │  TMS Database    │
           │  Flutterwave │          │  REST API        │
           └──────────────┘          └─────────────────┘
```
