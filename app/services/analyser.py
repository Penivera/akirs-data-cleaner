import os
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Tuple

from app.services.cleaner import load_tabular_rows


def parse_float(val: Any) -> float:
    if val is None:
        return 0.0
    s = str(val).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


FX_RATES = {
    "USD": 1500.0,
    "GBP": 1900.0,
    "EUR": 1600.0,
    "NGN": 1.0,
}


def get_fx_rate(curr: str) -> float:
    c = str(curr).strip().upper()
    return FX_RATES.get(c, 1.0)


def format_currency(val: float, currency="NGN") -> str:
    curr = str(currency).strip().upper() if currency else "NGN"
    return f"{curr} {val:,.2f}"


def generate_markdown_report(
    state, rows: List[Tuple[Any, ...]], header_row_idx: int
) -> str:
    config = state.config
    identity_col = config.get("identity_col")
    metric_col = config.get("metric_col")
    currency_col = config.get("currency_col")
    limit = int(config.get("limit", 50))
    keep_columns = config.get("keep_columns", [])
    title = config.get("title", "DATA ANALYSIS REPORT").upper()

    concat_order = config.get("concat_order")
    concat_separator = config.get("concat_separator", " ")

    flow_type_col = config.get("flow_type_col")
    inflow_indicator = str(config.get("inflow_indicator", "INFLOW")).strip().upper()
    outflow_indicator = str(config.get("outflow_indicator", "OUTFLOW")).strip().upper()
    flow_filter = config.get("flow_filter", "All")

    if (not identity_col or not metric_col) and not concat_order:
        raise ValueError(
            "Identity (or concat columns) and Metric columns must be selected."
        )

    # Get headers and row data
    headers = [str(h).strip() if h else "" for h in rows[header_row_idx]]
    header_map = {h: i for i, h in enumerate(headers) if h}

    id_idx = header_map.get(identity_col) if identity_col else None
    met_idx = header_map.get(metric_col) if metric_col else None
    curr_idx = header_map.get(currency_col) if currency_col else None
    flow_idx = header_map.get(flow_type_col) if flow_type_col else None

    if (id_idx is None and not concat_order) or met_idx is None:
        raise ValueError("Selected columns not found in dataset")

    keep_indices = []
    for col in keep_columns:
        if col in header_map and col not in [
            identity_col,
            metric_col,
            currency_col,
            flow_type_col,
        ]:
            keep_indices.append((col, header_map[col]))

    # Aggregation dictionaries
    # Struct: { (identity_val, currency_val): {"metric_sum": 0.0, "inflow_sum": 0.0, "outflow_sum": 0.0, "count": 0, "metadata": {}} }
    groups = defaultdict(
        lambda: {
            "metric_sum": 0.0,
            "inflow_sum": 0.0,
            "outflow_sum": 0.0,
            "count": 0,
            "metadata": {},
        }
    )

    total_analyzed_rows = 0
    total_metric_sums = defaultdict(float)
    total_inflows = defaultdict(float)
    total_outflows = defaultdict(float)

    for i, row in enumerate(rows[header_row_idx + 1 :], start=1):
        if not any(row):
            continue

        # Compute identity value either via a single identity column or concatenated cols
        id_val = ""
        concat_order = config.get("concat_order")
        if concat_order:
            def get_order_key(item):
                val = str(item[1]).strip()
                return int(val) if val.isdigit() else 999
            
            sorted_cols = sorted(concat_order.items(), key=get_order_key)
            parts = []
            for col_name, _ in sorted_cols:
                if col_name in header_map:
                    c_idx = header_map[col_name]
                    if c_idx < len(row):
                        part = str(row[c_idx]).strip() if row[c_idx] is not None else ""
                        if part:
                            parts.append(part)
            
            if parts:
                id_val = concat_separator.join(parts)

        # Fallback to single identity column if concatenation is empty or not configured
        if not id_val:
            if id_idx is not None and id_idx < len(row):
                id_val = str(row[id_idx]).strip() if row[id_idx] is not None else ""
            
        if not id_val or str(id_val).upper() in ["N/A", "NULL", "NONE"]:
            continue

        metric_val_str = row[met_idx] if met_idx < len(row) else 0.0
        m_val = parse_float(metric_val_str)

        c_val = ""
        if curr_idx is not None and curr_idx < len(row):
            c_val = str(row[curr_idx]).strip() if row[curr_idx] is not None else ""

        # Determine flow type
        is_inflow = False
        is_outflow = False
        if flow_idx is not None and flow_idx < len(row):
            f_val = (
                str(row[flow_idx]).strip().upper() if row[flow_idx] is not None else ""
            )
            if f_val == inflow_indicator:
                is_inflow = True
            elif f_val == outflow_indicator:
                is_outflow = True
        else:
            if m_val >= 0:
                is_inflow = True
            else:
                is_outflow = True

        # Filter based on flow
        if flow_filter == "Inflows Only" and not is_inflow:
            continue
        if flow_filter == "Outflows Only" and not is_outflow:
            continue

        abs_m_val = abs(m_val)

        group_key = (id_val, c_val)

        target_group = groups[group_key]
        target_group["metric_sum"] += m_val
        target_group["scaled_metric_sum"] = target_group.get(
            "scaled_metric_sum", 0.0
        ) + (m_val * get_fx_rate(c_val))
        target_group["count"] += 1

        if is_inflow:
            target_group["inflow_sum"] += abs_m_val
            total_inflows[c_val] += abs_m_val
        elif is_outflow:
            target_group["outflow_sum"] += abs_m_val
            total_outflows[c_val] += abs_m_val

        # Populate metadata on first hit
        if not target_group["metadata"]:
            meta = {}
            for col_name, c_idx in keep_indices:
                val = (
                    str(row[c_idx]).strip()
                    if c_idx < len(row) and row[c_idx] is not None
                    else "Not available"
                )
                meta[col_name] = val
            target_group["metadata"] = meta

        total_analyzed_rows += 1
        total_metric_sums[c_val] += m_val

    # Sort groups by scaled metric descending for accurate cross-currency FX ranking
    sorted_groups = sorted(
        groups.items(),
        key=lambda x: x[1].get("scaled_metric_sum", x[1]["metric_sum"]),
        reverse=True,
    )
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

    for c_val, t_sum in total_metric_sums.items():
        curr_label = f"({c_val})" if c_val else "(Default Currency)"
        lines.append(f"Net Total {curr_label}: {format_currency(t_sum, c_val)}")
        lines.append(
            f"   - Total Inflows: {format_currency(total_inflows[c_val], c_val)}"
        )
        lines.append(
            f"   - Total Outflows: {format_currency(total_outflows[c_val], c_val)}"
        )

    lines.append(f"Metric Analyzed: {metric_col}")
    if currency_col:
        lines.append(f"Currency Grouping: {currency_col}")
    lines.append("")
    lines.append(f"TOP {limit} BY {metric_col}:")
    lines.append("")

    most_active_k = ""
    most_active_v = 0

    for idx, (group_key, data) in enumerate(top_n, 1):
        ident, c_val = group_key
        display_ident = f"{ident} ({c_val})" if c_val else ident

        metric_fmt = format_currency(data["metric_sum"], c_val)
        lines.append(f"{idx}. {display_ident} - Net: {metric_fmt}")
        lines.append(
            f"   Inflows: {format_currency(data['inflow_sum'], c_val)} | Outflows: {format_currency(data['outflow_sum'], c_val)}"
        )
        lines.append(f"   Transactions: {data['count']}")

        if data["count"] > most_active_v:
            most_active_v = data["count"]
            most_active_k = display_ident

        if data["count"] > 0:
            avg = data["metric_sum"] / data["count"]
            lines.append(f"   Average Transaction: {format_currency(avg, c_val)}")

        for k, v in data["metadata"].items():
            lines.append(f"   {k}: {v}")

        lines.append("")

    lines.append("===============================================")
    lines.append("SUMMARY STATISTICS:")

    for c_val, t_sum in total_metric_sums.items():
        # Get just the top ranking items specifically matching this currency
        c_top = [(k, v) for k, v in top_n if k[1] == c_val]
        c_top_sum = sum(v["metric_sum"] for _, v in c_top)
        curr_label = f"({c_val})" if c_val else "(Default Currency)"

        lines.append(f"--- Breakdown {curr_label} ---")
        lines.append(
            f"- Total '{metric_col}' of Top {limit}: {format_currency(c_top_sum, c_val)}"
        )
        if c_top:
            lines.append(
                f"- Highest Single '{metric_col}': {c_top[0][0][0]} ({format_currency(c_top[0][1]['metric_sum'], c_val)})"
            )
            lines.append(
                f"- Average '{metric_col}' per Top Account: {format_currency(c_top_sum / len(c_top), c_val)}"
            )
        lines.append("")

    lines.append(
        f"- Most Active Record (Overall): {most_active_k} ({most_active_v} transactions)"
    )
    lines.append("")
    lines.append("Data compiled automatically.")

    return "\n".join(lines)


def process_analytics(state) -> str:
    from app.services.cleaner import find_header_row_and_headers_from_rows

    all_rows = []
    header_row_idx = getattr(state, "header_row_idx", None)

    for idx, sheet_name in enumerate(state.selected_sheets):
        rows, _ = load_tabular_rows(state.saved_path, sheet_name)

        if idx == 0:
            if header_row_idx is None:
                header_idx, hdrs = find_header_row_and_headers_from_rows(rows)
                state.header_row_idx = header_idx
                state.headers = hdrs
                header_row_idx = header_idx
            all_rows.extend(rows)
        else:
            # For subsequent sheets, only add data rows
            if header_row_idx is not None and len(rows) > header_row_idx + 1:
                all_rows.extend(rows[header_row_idx + 1 :])

    md_content = generate_markdown_report(state, all_rows, state.header_row_idx)

    os.makedirs("reports", exist_ok=True)
    out_filename = os.path.basename(state.saved_path)
    if "." in out_filename:
        out_filename = out_filename[: out_filename.rfind(".")] + "_report.md"
    else:
        out_filename += "_report.md"

    report_path = os.path.join("reports", out_filename)
    state.report_filename = out_filename
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return report_path


# New: cumulative transactions report keyed by NUBAN (or a specified column)
def generate_cumulative_report(
    state, rows: List[Tuple[Any, ...]], header_row_idx: int
) -> str:
    config = state.config
    # nuban is the primary key for cumulation. Allow override via config
    nuban_col = config.get("nuban_col") or config.get("identity_col")
    metric_col = config.get("metric_col")
    keep_columns = config.get("keep_columns", [])
    title = config.get("title", "CUMULATIVE TRANSACTIONS REPORT").upper()

    if not nuban_col or not metric_col:
        raise ValueError(
            "NUBAN (or identity) and Metric columns must be selected for cumulative report."
        )

    headers = [str(h).strip() if h else "" for h in rows[header_row_idx]]
    header_map = {h: i for i, h in enumerate(headers) if h}

    if nuban_col not in header_map:
        raise ValueError(f"NUBAN column '{nuban_col}' not found in headers")
    if metric_col not in header_map:
        raise ValueError(f"Metric column '{metric_col}' not found in headers")

    nuban_idx = header_map[nuban_col]
    met_idx = header_map[metric_col]

    keep_indices = []
    for col in keep_columns:
        if col in header_map and col not in [nuban_col, metric_col]:
            keep_indices.append((col, header_map[col]))

    groups = defaultdict(lambda: {"metric_sum": 0.0, "count": 0, "metadata": {}})
    total_rows = 0

    for row in rows[header_row_idx + 1 :]:
        if not any(row):
            continue
        nuban = (
            str(row[nuban_idx]).strip()
            if nuban_idx < len(row) and row[nuban_idx] is not None
            else ""
        )
        if not nuban or str(nuban).upper() in ["N/A", "NULL", "NONE"]:
            continue
        metric_val = parse_float(row[met_idx] if met_idx < len(row) else 0.0)
        g = groups[nuban]
        g["metric_sum"] += metric_val
        g["count"] += 1
        if not g["metadata"]:
            meta = {}
            for col_name, c_idx in keep_indices:
                val = (
                    str(row[c_idx]).strip()
                    if c_idx < len(row) and row[c_idx] is not None
                    else "Not available"
                )
                meta[col_name] = val
            g["metadata"] = meta
        total_rows += 1

    # sort by metric_sum
    sorted_items = sorted(
        groups.items(), key=lambda x: x[1]["metric_sum"], reverse=True
    )

    lines = []
    lines.append(title)
    lines.append("=" * len(title))
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Data Source: {state.original_filename}")
    lines.append(f"Total Transactions Parsed: {total_rows}")
    lines.append("")

    lines.append(f"TOP {len(sorted_items)} ACCOUNTS BY {metric_col}:")
    lines.append("")

    for idx, (nuban, data) in enumerate(sorted_items, 1):
        lines.append(f"{idx}. {nuban} - Total: {format_currency(data['metric_sum'])}")
        lines.append(f"   Transactions: {data['count']}")
        if data["count"] > 0:
            lines.append(
                f"   Average Transaction: {format_currency(data['metric_sum'] / data['count'])}"
            )
        for k, v in data["metadata"].items():
            lines.append(f"   {k}: {v}")
        lines.append("")

    lines.append("Data compiled automatically.")
    return "\n".join(lines)


def process_cumulative_transactions(state) -> str:
    from app.services.cleaner import find_header_row_and_headers_from_rows

    all_rows = []
    header_row_idx = getattr(state, "header_row_idx", None)

    for idx, sheet_name in enumerate(state.selected_sheets):
        rows, _ = load_tabular_rows(state.saved_path, sheet_name)
        if idx == 0:
            if header_row_idx is None:
                header_idx, hdrs = find_header_row_and_headers_from_rows(rows)
                state.header_row_idx = header_idx
                state.headers = hdrs
                header_row_idx = header_idx
            all_rows.extend(rows)
        else:
            if header_row_idx is not None and len(rows) > header_row_idx + 1:
                all_rows.extend(rows[header_row_idx + 1 :])

    md_content = generate_cumulative_report(state, all_rows, state.header_row_idx)

    os.makedirs("reports", exist_ok=True)
    out_filename = os.path.basename(state.saved_path)
    if "." in out_filename:
        out_filename = out_filename[: out_filename.rfind(".")] + "_cumulative_report.md"
    else:
        out_filename += "_cumulative_report.md"

    report_path = os.path.join("reports", out_filename)
    state.report_filename = out_filename
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return report_path
