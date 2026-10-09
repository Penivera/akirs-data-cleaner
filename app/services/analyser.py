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

#: How the movement register can be ordered, and what each answers.
MOVEMENT_SORT_LABELS = {
    "credit": "credit turnover (the assessable base)",
    "gross": "gross activity (either direction)",
    "largest": "largest single leg",
    "net": "net position",
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
    limit_config = config.get("limit", 50)
    # Handle limit: None, 0, or falsy = show all; otherwise use the number.
    # A negative limit used to reach the slice as [:limit], which drops rows from
    # the end and printed "TOP -35". Treat any non-positive value as "no limit".
    if limit_config is None or limit_config == 0:
        limit = None
    else:
        parsed = int(limit_config)
        limit = parsed if parsed > 0 else None
    keep_columns = config.get("keep_columns", [])
    title = config.get("title", "DATA ANALYSIS REPORT").upper()

    # Movements are recorded as individual legs and never netted away. A customer
    # whose credit and debit are both 500M has moved 1B and nets to zero, which
    # a threshold review must not miss.
    movement_threshold = config.get("movement_threshold", None)
    movement_threshold = (
        parse_float(movement_threshold)
        if movement_threshold not in (None, "")
        else None
    )
    # The movement register is keyed by account where one is mapped, so two
    # customers sharing a name are never pooled into one taxpayer.
    movement_identity_col = config.get("movement_identity_col") or config.get("nuban_col")
    movement_sort = config.get("movement_sort", "credit")
    if movement_sort not in ("credit", "gross", "largest", "net"):
        movement_sort = "credit"

    concat_order = config.get("concat_order")
    concat_separator = config.get("concat_separator", " ")

    flow_type_col = config.get("flow_type_col")
    # Support separate credit/debit columns as an alternative to a single flow type column
    credit_col = config.get("credit_col")
    debit_col = config.get("debit_col")
    # How the amount moved in each row. The two modes are mutually exclusive and
    # the user picks one explicitly in the config form, so a half-filled pair can
    # never silently override a metric column (or be silently ignored).
    # Older configs predate the choice, so infer it from what they actually set.
    amount_mode = config.get("amount_mode")
    if amount_mode not in ("single", "split"):
        amount_mode = "split" if (credit_col and debit_col) else "single"
    if amount_mode == "split":
        # The metric column plays no part in split mode; drop it so a stale
        # selection cannot leak into keep_columns or the report header.
        metric_col = None
    else:
        # Likewise a stale credit/debit selection must not shadow the metric.
        credit_col = None
        debit_col = None
    # Keep existing config keys for backward compatibility but accept common synonyms.
    inflow_indicator = str(config.get("inflow_indicator", "CREDIT")).strip().upper()
    outflow_indicator = str(config.get("outflow_indicator", "DEBIT")).strip().upper()
    flow_filter = config.get("flow_filter", "All")
    min_amount_filter = config.get("min_amount_filter", None)  # Optional: filter amounts above threshold
    if min_amount_filter is not None:
        min_amount_filter = parse_float(min_amount_filter)

    if (not identity_col and not concat_order):
        raise ValueError(
            "Identity column (or concat columns) must be selected."
        )
    if amount_mode == "split" and not (credit_col and debit_col):
        raise ValueError(
            "Split mode needs both a Credit column and a Debit column."
        )
    if amount_mode == "single" and not metric_col:
        raise ValueError(
            "Single mode needs a metric column to measure."
        )

    # Validate header_row_idx
    if header_row_idx is None or header_row_idx < 0 or header_row_idx >= len(rows):
        raise ValueError(
            f"Header row index {header_row_idx} is out of range for provided rows (len={len(rows)})"
        )

    # Get headers and row data
    headers = [str(h).strip() if h else "" for h in rows[header_row_idx]]
    header_map = {h: i for i, h in enumerate(headers) if h}

    id_idx = header_map.get(identity_col) if identity_col else None
    met_idx = header_map.get(metric_col) if metric_col else None
    curr_idx = header_map.get(currency_col) if currency_col else None
    flow_idx = header_map.get(flow_type_col) if flow_type_col else None
    credit_idx = header_map.get(credit_col) if credit_col else None
    debit_idx = header_map.get(debit_col) if debit_col else None

    # Validate required columns: identity (or concat), plus the columns the
    # chosen amount mode actually depends on.
    has_identity = id_idx is not None or concat_order
    if amount_mode == "split":
        amount_cols_present = credit_idx is not None and debit_idx is not None
    else:
        amount_cols_present = met_idx is not None

    if not has_identity:
        raise ValueError("Selected identity column not found in dataset")
    if not amount_cols_present:
        if amount_mode == "split":
            raise ValueError("Selected credit or debit column not found in dataset")
        raise ValueError("Selected metric column not found in dataset")

    # The movement register's own key and columns. Kept separate from the ranked
    # report's identity so a threshold review is never pooled by name.
    mv_key_idx = header_map.get(movement_identity_col) if movement_identity_col else None
    mv_name_idx = header_map.get(identity_col) if identity_col else None

    keep_indices = []
    for col in keep_columns:
        if col in header_map and col not in [
            identity_col,
            metric_col,
            currency_col,
            flow_type_col,
            credit_col,
            debit_col,
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

    # One entry per account, holding each leg separately. Movements are never
    # netted, so a 500M-in/500M-out account still reports 500M of each.
    movements = defaultdict(
        lambda: {
            "credit_total": 0.0,
            "debit_total": 0.0,
            "largest_leg": 0.0,
            "legs": 0,
            "name": "",
            "rows": set(),
        }
    )
    # Flat register of individual legs above the threshold, each traceable to
    # the spreadsheet row it came from.
    legs: List[Dict[str, Any]] = []

    total_analyzed_rows = 0
    total_metric_sums = defaultdict(float)
    total_inflows = defaultdict(float)
    total_outflows = defaultdict(float)

    for i, row in enumerate(rows[header_row_idx + 1 :], start=1):
        if not any(row):
            continue

        # Record the movement before anything can cancel it out. The spreadsheet
        # row is +1 more than the loop index because of the header row.
        if credit_idx is not None or debit_idx is not None:
            mv_credit = (
                parse_float(row[credit_idx])
                if credit_idx is not None and credit_idx < len(row)
                else 0.0
            )
            mv_debit = (
                parse_float(row[debit_idx])
                if debit_idx is not None and debit_idx < len(row)
                else 0.0
            )
            mv_name = (
                str(row[mv_name_idx]).strip()
                if mv_name_idx is not None and mv_name_idx < len(row) and row[mv_name_idx] is not None
                else ""
            )
            mv_key = ""
            if mv_key_idx is not None and mv_key_idx < len(row) and row[mv_key_idx] is not None:
                mv_key = str(row[mv_key_idx]).strip()
            # Without an account column, fall back to the name so the register
            # still records something rather than reporting no movements at all.
            if not mv_key:
                mv_key = mv_name
            if mv_key:
                entry = movements[mv_key]
                entry["credit_total"] += mv_credit
                entry["debit_total"] += mv_debit
                entry["largest_leg"] = max(
                    entry["largest_leg"], mv_credit, mv_debit
                )
                entry["legs"] += 1
                entry["rows"].add(i + header_row_idx)
                if not entry["name"]:
                    entry["name"] = mv_name

            # Both legs are evaluated independently so a threshold on one side
            # can never hide a large movement on the other.
            for side, amount in (("Credit", mv_credit), ("Debit", mv_debit)):
                if amount <= 0:
                    continue
                if movement_threshold is not None and amount < movement_threshold:
                    continue
                legs.append(
                    {
                        "side": side,
                        "amount": amount,
                        "account": mv_key,
                        "name": mv_name,
                        "sheet_row": i + header_row_idx,
                        "currency": (
                            str(row[curr_idx]).strip()
                            if curr_idx is not None
                            and curr_idx < len(row)
                            and row[curr_idx] is not None
                            else ""
                        ),
                    }
                )

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

        # Determine metric value: split mode nets credit against debit,
        # single mode reads the metric column as-is.
        if amount_mode == "split":
            credit_amount = parse_float(row[credit_idx]) if credit_idx is not None and credit_idx < len(row) else 0.0
            debit_amount = parse_float(row[debit_idx]) if debit_idx is not None and debit_idx < len(row) else 0.0
            # Net: credit is positive, debit is negative
            m_val = credit_amount - debit_amount
        else:
            metric_val_str = row[met_idx] if met_idx is not None and met_idx < len(row) else 0.0
            m_val = parse_float(metric_val_str)

        abs_m_val = abs(m_val)

        c_val = ""
        if curr_idx is not None and curr_idx < len(row):
            c_val = str(row[curr_idx]).strip() if row[curr_idx] is not None else ""

        # Determine flow type and amounts. Priority:
        # 1) Split mode: a credit and a debit can both appear on one row
        # 2) Single mode: the flow type column, when one is mapped
        # 3) Sign of the metric value
        is_inflow = False
        is_outflow = False
        inflow_amount = 0.0  # For credit/debit split accounting
        outflow_amount = 0.0  # For credit/debit split accounting

        if amount_mode == "split":
            # Read the pair once: these amounts are both the metric and the flow.
            credit_amount = parse_float(row[credit_idx]) if credit_idx is not None and credit_idx < len(row) else 0.0
            debit_amount = parse_float(row[debit_idx]) if debit_idx is not None and debit_idx < len(row) else 0.0

            # Both can be populated on the same row, so these are not exclusive.
            if credit_amount > 0:
                is_inflow = True
                inflow_amount = credit_amount
            if debit_amount > 0:
                is_outflow = True
                outflow_amount = debit_amount

            # Neither side populated: the row moved no money, so it belongs to
            # neither direction. Booking it as an inflow would smuggle it past
            # the "Inflows only" filter and inflate the inflow total with a 0.
            # It still counts as a transaction in the unfiltered report.

        elif flow_idx is not None and flow_idx < len(row):
            f_val = (
                str(row[flow_idx]).strip().upper() if row[flow_idx] is not None else ""
            )
            if f_val == inflow_indicator or f_val in ("CREDIT", "CR"):
                is_inflow = True
                inflow_amount = abs_m_val
            elif f_val == outflow_indicator or f_val in ("DEBIT", "DR"):
                is_outflow = True
                outflow_amount = abs_m_val
            else:
                # An unrecognised marker means the column is not really a flow
                # column; fall back to the sign rather than guessing a direction.
                if m_val >= 0:
                    is_inflow = True
                    inflow_amount = abs_m_val
                else:
                    is_outflow = True
                    outflow_amount = abs_m_val

        else:
            # Final fallback: use sign of metric
            if m_val >= 0:
                is_inflow = True
                inflow_amount = abs_m_val
            else:
                is_outflow = True
                outflow_amount = abs_m_val

        # Filter based on flow. Accept either Inflows/Outflows or Credits/Debits labels.
        if flow_filter in ("Inflows Only", "Credits Only") and not is_inflow:
            continue
        if flow_filter in ("Outflows Only", "Debits Only") and not is_outflow:
            continue

        group_key = (id_val, c_val)

        target_group = groups[group_key]
        target_group["metric_sum"] += m_val
        target_group["scaled_metric_sum"] = target_group.get(
            "scaled_metric_sum", 0.0
        ) + (m_val * get_fx_rate(c_val))
        target_group["count"] += 1

        # Add inflows and outflows separately (both can be present when using credit/debit columns)
        if is_inflow:
            target_group["inflow_sum"] += inflow_amount
            total_inflows[c_val] += inflow_amount
        if is_outflow:  # Note: 'if' not 'elif' to support credit/debit split rows
            target_group["outflow_sum"] += outflow_amount
            total_outflows[c_val] += outflow_amount

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
    
    # Apply minimum amount filter if specified. Test the absolute value of the
    # scaled total directly: a truthiness test here would silently drop every
    # account whose net position is exactly zero.
    if min_amount_filter is not None and min_amount_filter > 0:
        sorted_groups = [
            (k, v)
            for k, v in sorted_groups
            if abs(v.get("scaled_metric_sum", v["metric_sum"])) >= min_amount_filter
        ]
    
    # Apply limit (None means show all records)
    if limit is None or limit == 0:
        top_n = sorted_groups
    else:
        top_n = sorted_groups[:limit]

    # Calculate some summary stats
    top_n_sum = sum(v["metric_sum"] for _, v in top_n)

    # Order accounts for the register. Credit, gross and largest-single are all
    # offered because they answer different questions: credit turnover is the
    # assessable base, gross catches movement in either direction, and the largest
    # single leg catches one extreme transaction.
    def movement_rank(entry):
        if movement_sort == "gross":
            return entry["credit_total"] + entry["debit_total"]
        if movement_sort == "largest":
            return entry["largest_leg"]
        if movement_sort == "net":
            return entry["credit_total"] - entry["debit_total"]
        return entry["credit_total"]

    ranked_accounts = sorted(
        movements.items(), key=lambda kv: movement_rank(kv[1]), reverse=True
    )
    # The threshold is applied first and to everything; the limit only shortens
    # the printed table. Keeping them separate means the offsetting section
    # below is filtered by the same threshold, not by whatever the limit kept.
    above_threshold = [
        (account, entry)
        for account, entry in ranked_accounts
        if movement_threshold is None
        or max(entry["credit_total"], entry["debit_total"], entry["largest_leg"])
        >= movement_threshold
    ]
    flagged_accounts = (
        above_threshold if limit is None else above_threshold[:limit]
    )

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

    # Show metric label - the column(s) the chosen mode actually measured
    metric_label = f"{credit_col} - {debit_col}" if amount_mode == "split" else metric_col
    lines.append(f"Metric Analyzed: {metric_label}")
    if currency_col:
        lines.append(f"Currency Grouping: {currency_col}")
    if min_amount_filter and min_amount_filter > 0:
        lines.append(f"Minimum Amount Filter: {format_currency(min_amount_filter)}")

    # --- Movement register -------------------------------------------------
    # Recorded before any netting, so a customer who moves a large amount in and
    # the same amount out is still fully visible here.
    register_heading = f"{title} - MOVEMENT REGISTER"
    lines.append("")
    lines.append(register_heading)
    lines.append("=" * len(register_heading))
    lines.append("")
    lines.append(
        "Every movement is listed as its own leg. Credit and debit are never"
    )
    lines.append(
        "netted, so a customer who pays in and out at the same level still shows"
    )
    lines.append("their full activity here.")
    lines.append(f"Accounts recorded: {len(movements)}")
    lines.append(f"Individual legs recorded: {len(legs)}")
    if movement_threshold is not None:
        lines.append(
            f"Movement threshold: {format_currency(movement_threshold)} "
            f"(each leg tested on its own)"
        )
    if movement_identity_col:
        lines.append(f"Accounts keyed by: {movement_identity_col}")
    lines.append(f"Ordered by: {MOVEMENT_SORT_LABELS[movement_sort]}")
    lines.append("")

    header = (
        f"{'#':>3}  {'Account':<13} {'Credit':>18} {'Debit':>18} "
        f"{'Gross':>18} {'Largest':>18}  Name"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for rank, (account, entry) in enumerate(flagged_accounts, 1):
        gross = entry["credit_total"] + entry["debit_total"]
        lines.append(
            f"{rank:>3}  {account:<13} "
            f"{entry['credit_total']:>18,.2f} "
            f"{entry['debit_total']:>18,.2f} "
            f"{gross:>18,.2f} "
                f"{entry['largest_leg']:>18,.2f}  {entry['name']}"
            )

    if not flagged_accounts:
        lines.append(
            "  (no account reached the threshold)"
            if movement_threshold is not None
            else "  (no movements recorded)"
        )

    # --- Individual legs ----------------------------------------------------
    if legs:
        lines.append("")
        lines.append(f"INDIVIDUAL MOVEMENTS ({len(legs)} legs)")
        lines.append("-" * 60)
        for leg in sorted(legs, key=lambda l: l["amount"], reverse=True):
            currency = leg["currency"]
            account = leg["account"] or "(unkeyed)"
            name = leg["name"] or ""
            lines.append(
                f"  Row {leg['sheet_row']:>4}  {leg['side']:<6} "
                f"{format_currency(leg['amount'], currency):>20}  "
                f"{account}  {name}"
            )

    # Accounts above the threshold whose net is small, because that is exactly
    # the shape a net-ranked report hides. Filtered on the same footing as the
    # table above, so a threshold is never quietly bypassed by this section.
    flagged_set = {account for account, _ in above_threshold}
    offset_movers = [
        (account, entry)
        for account, entry in ranked_accounts
        if account in flagged_set
        and entry["credit_total"] > 0
        and abs(entry["credit_total"] - entry["debit_total"])
        < max(entry["credit_total"], entry["debit_total"]) * 0.25
    ]
    if offset_movers:
        lines.append("")
        lines.append("OFFSETTING ACTIVITY (large movements that net to near zero)")
        lines.append("-" * 60)
        for account, entry in sorted(
            offset_movers,
            key=lambda kv: max(kv[1]["credit_total"], kv[1]["debit_total"]),
            reverse=True,
        ):
            net = entry["credit_total"] - entry["debit_total"]
            lines.append(
                f"  {account}  {entry['name']}\n"
                f"      Credit {entry['credit_total']:,.2f} | "
                f"Debit {entry['debit_total']:,.2f} | Net {net:,.2f}"
            )

    lines.append("")
    # Format header based on whether limit is set
    if limit is None or limit == 0:
        lines.append(f"ALL RECORDS BY {metric_label}:")
    else:
        lines.append(f"TOP {limit} BY {metric_label}:")
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
        # Format summary based on whether limit is set
        if limit is None or limit == 0:
            lines.append(
                f"- Total '{metric_label}' (All Records): {format_currency(c_top_sum, c_val)}"
            )
        else:
            lines.append(
                f"- Total '{metric_label}' of Top {limit}: {format_currency(c_top_sum, c_val)}"
            )
        if c_top:
            lines.append(
                f"- Highest Single '{metric_label}': {c_top[0][0][0]} ({format_currency(c_top[0][1]['metric_sum'], c_val)})"
            )
            lines.append(
                f"- Average '{metric_label}' per Top Account: {format_currency(c_top_sum / len(c_top), c_val)}"
            )
        lines.append("")

    lines.append(
        f"- Most Active Record (Overall): {most_active_k} ({most_active_v} transactions)"
    )
    lines.append("")
    lines.append("Data compiled automatically.")

    return "\n".join(lines)


def process_analytics(state, output_dir: str = "reports") -> str:
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

    os.makedirs(output_dir, exist_ok=True)
    out_filename = os.path.basename(state.saved_path)
    # Sanitize filename
    out_filename = out_filename.replace("..", "").replace("/", "_").replace("\\", "_")
    if "." in out_filename:
        out_filename = out_filename[: out_filename.rfind(".")] + "_report.md"
    else:
        out_filename += "_report.md"

    report_path = os.path.join(output_dir, out_filename)
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
    limit_config = config.get("limit", 50)
    # Handle limit: None, 0, or falsy = show all; otherwise use the number
    limit = None if (limit_config is None or limit_config == 0) else int(limit_config)
    min_amount_filter = config.get("min_amount_filter", None)  # Optional: filter amounts above threshold
    if min_amount_filter is not None:
        min_amount_filter = parse_float(min_amount_filter)

    # The cumulative report totals the same amount the main report measures, so
    # it honours the chosen amount mode too. Otherwise "NUBAN cumulative" plus
    # credit/debit columns would fail at generate time with no way to recover.
    credit_col = config.get("credit_col")
    debit_col = config.get("debit_col")
    amount_mode = config.get("amount_mode")
    if amount_mode not in ("single", "split"):
        amount_mode = "split" if (credit_col and debit_col) else "single"
    if amount_mode == "single":
        metric_col = config.get("metric_col")
    else:
        metric_col = None

    if not nuban_col:
        raise ValueError("A NUBAN column must be selected for the cumulative report.")
    if amount_mode == "split" and not (credit_col and debit_col):
        raise ValueError(
            "Split mode needs both a Credit column and a Debit column."
        )
    if amount_mode == "single" and not metric_col:
        raise ValueError("Single mode needs a metric column to measure.")

    # Validate header_row_idx
    if header_row_idx is None or header_row_idx < 0 or header_row_idx >= len(rows):
        raise ValueError(
            f"Header row index {header_row_idx} is out of range for provided rows (len={len(rows)})"
        )

    headers = [str(h).strip() if h else "" for h in rows[header_row_idx]]
    header_map = {h: i for i, h in enumerate(headers) if h}

    if nuban_col not in header_map:
        raise ValueError(f"NUBAN column '{nuban_col}' not found in headers")

    nuban_idx = header_map[nuban_col]
    if amount_mode == "split":
        for col in (credit_col, debit_col):
            if col not in header_map:
                raise ValueError(f"Column '{col}' not found in headers")
        credit_idx = header_map[credit_col]
        debit_idx = header_map[debit_col]
        amount_label = f"{credit_col} - {debit_col}"
    else:
        if metric_col not in header_map:
            raise ValueError(f"Metric column '{metric_col}' not found in headers")
        credit_idx = debit_idx = None
        met_idx = header_map[metric_col]
        amount_label = metric_col

    keep_indices = []
    for col in keep_columns:
        if col in header_map and col not in [
            nuban_col,
            metric_col,
            credit_col,
            debit_col,
        ]:
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
        if amount_mode == "split":
            credit = parse_float(row[credit_idx] if credit_idx < len(row) else 0.0)
            debit = parse_float(row[debit_idx] if debit_idx < len(row) else 0.0)
            metric_val = credit - debit
        else:
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
    
    # Apply minimum amount filter if specified
    if min_amount_filter is not None and min_amount_filter > 0:
        sorted_items = [
            (k, v) for k, v in sorted_items 
            if abs(v["metric_sum"]) >= min_amount_filter
        ]
    
    # Apply limit (None means show all records)
    if limit is None or limit == 0:
        display_items = sorted_items
    else:
        display_items = sorted_items[:limit]

    lines = []
    lines.append(title)
    lines.append("=" * len(title))
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Data Source: {state.original_filename}")
    lines.append(f"Total Transactions Parsed: {total_rows}")
    if min_amount_filter and min_amount_filter > 0:
        lines.append(f"Minimum Amount Filter: {format_currency(min_amount_filter)}")
    lines.append("")
    # Format header based on whether limit is set
    if limit is None or limit == 0:
        lines.append(f"ALL ACCOUNTS BY {amount_label}:")
    else:
        lines.append(f"TOP {limit} ACCOUNTS BY {amount_label}:")
    lines.append("")

    for idx, (nuban, data) in enumerate(display_items, 1):
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


def process_cumulative_transactions(state, output_dir: str = "reports") -> str:
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

    os.makedirs(output_dir, exist_ok=True)
    out_filename = os.path.basename(state.saved_path)
    # Sanitize filename
    out_filename = out_filename.replace("..", "").replace("/", "_").replace("\\", "_")
    if "." in out_filename:
        out_filename = out_filename[: out_filename.rfind(".")] + "_cumulative_report.md"
    else:
        out_filename += "_cumulative_report.md"

    report_path = os.path.join(output_dir, out_filename)
    state.report_filename = out_filename
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return report_path
