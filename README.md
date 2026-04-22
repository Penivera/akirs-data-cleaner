# AKIRS Batch File Cleaner

The `akirs-data-cleaner` project is designed to automate the cleaning, deduplication, and standardization of customer data from Excel batch files into well-formatted CSV files. It ensures that critical identity data points, specifically NUBAN, Taxpayer ID (TIN), BVN, and contact information, are properly mapped, verified, and filtered.

The system is used to generate clean datasets of newly opened accounts and tax intelligence data, ready for ingestion into government or analytical databases.

## Features

- **Automated Column Mapping**: Detects expected column headers (e.g., TAXPAYER_ID, NUBAN, PHONE NO 1) even with varying header names across different spreadsheets.
- **Branch Filtering**: Scans branch or location columns to filter out specific records (e.g., extracting only "UYO" branch records).
- **Duplicate Handling**: Identifies duplicates based on primary identifiers like the NUBAN. It resolves these conflicts by either dropping subsequent duplicates, manually selecting records, or merging data fields.
- **Data Validation**: Enforces minimum length constraints and structural logic on TIN and NUBAN fields to drop invalid entries.
- **Standardized Export**: Converts the clean and grouped datasets into consolidated CSV files.

## Project Structure

The tool offers both standalone Python data-migration scripts and a fully interactive web application.

### Web Application

A robust FastAPI web application provides a browser-based UI for users to upload files, preview mapping rules, resolve duplicates securely, and download files visually.

- **`bot.py`**: The main entry point to start the FastAPI server via Uvicorn.
- **`app/`**: Contains the backend code.
  - **`app/main.py`**: The FastAPI application initialization and routing setup.
  - **`app/api/`**: The FastAPI route handlers (`routes.py` main UI routes and `analytics.py` for API/stats).
  - **`app/services/`**: The core business logic.
    - `cleaner.py`: Algorithms to extract rows, heuristic header detection, data mapping, duplicate resolution, and writing to CSV.
    - `analyser.py`: Generates summarized intelligence metrics.
- **`static/` & `templates/`**: The frontend UI dependencies (CSS/JS) and HTML templates used by the FastAPI backend to render the dashboard interface.
- **`uploads/` / `cleaned/`**: Server directories to temporarily hold user uploads and outputs.

### Standalone Migration Scripts

These scripts are used for quick, hardcoded, one-off cleanup operations against specific internal reporting formats without needing the GUI.

- **`migrate_data.py`**, **`migrate2.py`**, **`migrate3.py`**: Standalone scripts tailored to iteratively migrate specific batch formats like `"OCT AKWA IBOM NEW CUSTOMERS Q3 2025.xlsx"` and `"Newly Opened Accts UYO OCTOBER 2024.xlsx"`. By slightly modifying their configurations or header mapping indices, they target unique anomalies in individual datasets.

## How to Run

### 1. Running the Interactive Web App
This is the recommended way to process new batch files.

```bash
# Install requirements (assumes standard dependencies like fastapi, uvicorn, openpyxl)
pip install fastapi uvicorn openpyxl python-multipart

# Start the web interface
python bot.py
```
After starting the server, go to `http://localhost:8080/` via your web browser to upload Excel files and conduct the cleaning process.

### 2. Using the Standalone Scripts
If you want to manually run the migration with the hardcoded mappings (make sure the Excel files exist locally or adjust paths as needed in the script):
```bash
python migrate_data.py
```
This will generate and log the cleanup process straight to your terminal and save the output CSV in the same parent or `cleaned/` folder.