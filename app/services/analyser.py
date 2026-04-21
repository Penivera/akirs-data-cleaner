import os
from typing import List, Dict, Any, Tuple
from collections import defaultdict
from app.services.cleaner import load_tabular_rows
from datetime import datetime

def parse_float(val: Any) -> float:
    if val is None:
        return 0.0
    s = str(val).replace(',', '').strip()
    try:
        return float(s)
    except ValueError:
        return 0.0

def format_currency(val: float) -> str:
    return f"NGN{val:,.2f}"

def generate_markdown_report(state, rows: List[Tuple[Any, ...]], header_row_idx: int) -> str:
    config = state.config
    identity_col = config.get("identity_col")
    metric_col = config.get("metric_col")
    limit = int(config.get("limit", 50))
    keep_columns = config.get("keep_columns", [])
    title = config.get("title", "DATA ANALYSIS REPORT").upper()
    
    if not identity_col or not metric_col:
        raise ValueError("Identity and Metric columns must be selected.")

    # Get headers and row data
    headers = [str(h).strip() if h else "" for h in rows[header_row_idx]]
    header_map = {h: i for i, h in enumerate(headers) if h}
    
    id_idx = header_map.get(identity_col)
    met_idx = header_map.get(metric_col)
    
    if id_idx is None or met_idx is None:
        raise ValueError("Selected columns not found in dataset")
        
    keep_indices = []
    for col in keep_columns:
        if col in header_map and col not in [identity_col, metric_col]:
            keep_indices.append((col, header_map[col]))

    # Aggregation dictionaries
    # Struct: { identity_val: {"metric_sum": 0.0, "count": 0, "metadata": {}} }
    groups = defaultdict(lambda: {"metric_sum": 0.0, "count": 0, "metadata": {}})
    
    total_analyzed_rows = 0
    total_metric_sum = 0.0
    
    for i, row in enumerate(rows[header_row_idx+1:], start=1):
        if not any(row):
            continue
            
        if id_idx >= len(row):
            continue
            
        id_val = str(row[id_idx]).strip() if row[id_idx] is not None else ""
        if not id_val or str(id_val).upper() in ["N/A", "NULL", "NONE"]:
            continue
            
        metric_val_str = row[met_idx] if met_idx < len(row) else 0.0
        m_val = parse_float(metric_val_str)
        
        target_group = groups[id_val]
        target_group["metric_sum"] += m_val
        target_group["count"] += 1
        
        # Populate metadata on first hit
        if not target_group["metadata"]:
            meta = {}
            for col_name, c_idx in keep_indices:
                val = str(row[c_idx]).strip() if c_idx < len(row) and row[c_idx] is not None else "Not available"
                meta[col_name] = val
            target_group["metadata"] = meta
            
        total_analyzed_rows += 1
        total_metric_sum += m_val

    # Sort groups by metric descending
    sorted_groups = sorted(groups.items(), key=lambda x: x[1]["metric_sum"], reverse=True)
    top_n = sorted_groups[:limit]
    
    # Calculate some summary stats
    top_n_sum = sum(v["metric_sum"] for _, v in top_n)
    
    # Generate Output
    lines = []
    lines.append(f"{title}")
    lines.append("=" * len(title))
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Data Source: {state.original_filename}")
    lines.append(f"Total Transactions Parsed: {total_analyzed_rows}")
    lines.append(f"Total Metric Size All Transactions: {format_currency(total_metric_sum)}")
    lines.append(f"Metric Analyzed: {metric_col}")
    lines.append("")
    lines.append(f"TOP {limit} BY {metric_col}:")
    lines.append("")
    
    most_active_k = ""
    most_active_v = 0
    
    for idx, (ident, data) in enumerate(top_n, 1):
        metric_fmt = format_currency(data["metric_sum"])
        lines.append(f"{idx}. {ident} - {metric_fmt}")
        lines.append(f"   Transactions: {data['count']}")
        
        if data["count"] > most_active_v:
            most_active_v = data["count"]
            most_active_k = ident
            
        if data["count"] > 0:
            avg = data["metric_sum"] / data["count"]
            lines.append(f"   Average Transaction: {format_currency(avg)}")
            
        for k, v in data["metadata"].items():
            lines.append(f"   {k}: {v}")
        
        lines.append("")
        
    lines.append("===============================================")
    lines.append("SUMMARY STATISTICS:")
    lines.append(f"- Total '{metric_col}' of Top {limit}: {format_currency(top_n_sum)}")
    if top_n:
        lines.append(f"- Highest Single '{metric_col}': {top_n[0][0]} ({format_currency(top_n[0][1]['metric_sum'])})")
        lines.append(f"- Most Active Record: {most_active_k} ({most_active_v} transactions)")
        lines.append(f"- Average '{metric_col}' per Top Account: {format_currency(top_n_sum / len(top_n))}")
    lines.append("")
    lines.append("Data compiled automatically.")

    return "\n".join(lines)


def process_analytics(state) -> str:
    from app.services.cleaner import find_header_row_and_headers_from_rows
    
    rows, _ = load_tabular_rows(state.saved_path, state.selected_sheet)
    if getattr(state, 'header_row_idx', None) is None:
         idx, hdrs = find_header_row_and_headers_from_rows(rows)
         state.header_row_idx = idx
         state.headers = hdrs
         
    md_content = generate_markdown_report(state, rows, state.header_row_idx)
    
    os.makedirs("reports", exist_ok=True)
    out_filename = os.path.basename(state.saved_path)
    if "." in out_filename:
        out_filename = out_filename[:out_filename.rfind(".")] + "_report.md"
    else:
        out_filename += "_report.md"
        
    report_path = os.path.join("reports", out_filename)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    return report_path
