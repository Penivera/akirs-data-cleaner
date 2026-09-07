"""
Generate industry-standard architecture diagrams for AKIRS Data Cleaner.

Style reference: C4-inspired, clean technical documentation diagrams with:
- Light (#F5F6F8) background
- Dark navy (#1B3A4B) primary boxes
- Teal (#2E7D8C) secondary boxes
- White (#FFFFFF) neutral boxes with dark borders
- Thin connecting lines with italic labels
- Bold title top-left, page number top-right
- Legend bottom-left, footer bottom

Produces 7 PNG images in docs/:
  01_system_context.png
  02_component_architecture.png
  03_batch_cleaner_flow.png
  04_analytics_pipeline.png
  05_nuban_pipeline.png
  06_db_sync_pipeline.png
  07_state_model.png
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))

# ── Color palette (matches reference images) ────────────────────────────────
BG       = "#F5F6F8"
NAVY     = "#1B3A4B"
TEAL     = "#2E7D8C"
LTBLUE   = "#D6EAF0"
WHITE    = "#FFFFFF"
LGRAY    = "#E8EBED"
BORDER   = "#9EAFB7"
TXT_DARK = "#1B3A4B"
TXT_MID  = "#5A6D75"
TXT_LT   = "#FFFFFF"
ACCENT   = "#C65D3E"   # warm accent for external APIs


# ── Drawing helpers ──────────────────────────────────────────────────────────

def _setup(figsize=(16, 10)):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.axis("off")
    return fig, ax


def _box(ax, x, y, w, h, title, subtitle="", fill=NAVY, text_color=TXT_LT,
         border_color=None, title_size=10, sub_size=8, bold=True):
    """Draw a rectangle with title and optional italic subtitle."""
    bc = border_color or fill
    rect = FancyBboxPatch(
        (x - w/2, y - h/2), w, h,
        boxstyle="round,pad=0.06", facecolor=fill, edgecolor=bc,
        linewidth=1.2,
    )
    ax.add_patch(rect)
    weight = "bold" if bold else "normal"
    if subtitle:
        ax.text(x, y + 0.12, title, ha="center", va="center", fontsize=title_size,
                color=text_color, weight=weight, fontfamily="sans-serif")
        ax.text(x, y - 0.15, subtitle, ha="center", va="center", fontsize=sub_size,
                color=text_color, style="italic", fontfamily="sans-serif", alpha=0.85)
    else:
        ax.text(x, y, title, ha="center", va="center", fontsize=title_size,
                color=text_color, weight=weight, fontfamily="sans-serif")


def _wide_box(ax, x, y, w, h, title, subtitle="", fill=NAVY, text_color=TXT_LT,
              border_color=None, title_size=10, sub_size=8):
    bc = border_color or fill
    rect = FancyBboxPatch(
        (x - w/2, y - h/2), w, h,
        boxstyle="round,pad=0.04", facecolor=fill, edgecolor=bc,
        linewidth=1.0,
    )
    ax.add_patch(rect)
    if subtitle:
        ax.text(x, y + 0.10, title, ha="center", va="center", fontsize=title_size,
                color=text_color, weight="bold", fontfamily="sans-serif")
        ax.text(x, y - 0.12, subtitle, ha="center", va="center", fontsize=sub_size,
                color=text_color, style="italic", fontfamily="sans-serif", alpha=0.85)
    else:
        ax.text(x, y, title, ha="center", va="center", fontsize=title_size,
                color=text_color, weight="bold", fontfamily="sans-serif")


def _container(ax, x, y, w, h, title="", fill="none", border=BORDER):
    """Draw a dashed container rectangle with optional top-left label."""
    rect = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.08", facecolor=fill, edgecolor=border,
        linewidth=1.0, linestyle="--",
    )
    ax.add_patch(rect)
    if title:
        ax.text(x + 0.15, y + h - 0.15, title, ha="left", va="top",
                fontsize=8, color=TXT_MID, style="italic", fontfamily="sans-serif")


def _arrow(ax, x1, y1, x2, y2, label="", color=TXT_MID, lw=1.2, style="-|>"):
    ax.annotate(
        "", xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle=style, color=color, lw=lw),
    )
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        # offset label slightly based on arrow direction
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        ox = 0.08 if dy > dx else 0
        oy = 0.08 if dx > dy else 0
        ax.text(mx + ox, my + oy, label, fontsize=7, color=TXT_MID,
                style="italic", fontfamily="sans-serif")


def _page_header(ax, title, subtitle, page_num, xlim, ylim):
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.text(xlim[0] + 0.3, ylim[1] - 0.3, title,
            fontsize=16, weight="bold", color=TXT_DARK, fontfamily="sans-serif")
    ax.text(xlim[0] + 0.3, ylim[1] - 0.65, subtitle,
            fontsize=9, color=TXT_MID, style="italic", fontfamily="sans-serif")
    ax.text(xlim[1] - 0.3, ylim[1] - 0.3, f"{page_num:02d}",
            fontsize=11, color=BORDER, ha="right", fontfamily="sans-serif")


def _footer(ax, xlim, ylim):
    ax.text(xlim[0] + 0.3, ylim[0] + 0.15,
            "AKIRS Data Cleaner  ·  Architecture Doc  ·  v1.0",
            fontsize=7, color=BORDER, fontfamily="sans-serif")
    ax.text(xlim[1] - 0.3, ylim[0] + 0.15, "Living Document",
            fontsize=7, color=BORDER, ha="right", style="italic", fontfamily="sans-serif")


def _legend(ax, x, y, items):
    """items: list of (color, label) tuples."""
    rect = FancyBboxPatch(
        (x, y), 3.2, 0.35 * len(items) + 0.3,
        boxstyle="round,pad=0.08", facecolor=WHITE, edgecolor=BORDER, linewidth=0.8,
    )
    ax.add_patch(rect)
    ax.text(x + 0.15, y + 0.35 * len(items) + 0.1, "Legend",
            fontsize=8, weight="bold", color=TXT_DARK, fontfamily="sans-serif")
    for i, (color, label) in enumerate(items):
        iy = y + 0.35 * (len(items) - i - 1) + 0.15
        swatch = FancyBboxPatch(
            (x + 0.15, iy - 0.08), 0.35, 0.18,
            boxstyle="round,pad=0.02", facecolor=color, edgecolor=color, linewidth=0.5,
        )
        ax.add_patch(swatch)
        ax.text(x + 0.6, iy, label, fontsize=7, color=TXT_DARK,
                va="center", fontfamily="sans-serif")


def _save(fig, name):
    path = os.path.join(DOCS_DIR, name)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor=BG, edgecolor="none")
    plt.close(fig)
    print(f"  {name}")


# ═══════════════════════════════════════════════════════════════════════════
# 01 — System Context
# ═══════════════════════════════════════════════════════════════════════════

def gen_01_system_context():
    fig, ax = _setup((16, 10))
    _page_header(ax, "System Context",
                 "AKIRS Data Cleaner sits between browser users and external banking/tax APIs.",
                 1, (0, 16), (0, 10))
    _footer(ax, (0, 16), (0, 10))

    # Client
    _box(ax, 8, 8.5, 3.0, 0.7, "Clients / Browser", "HTMX + Jinja2 UI", fill=LGRAY,
         text_color=TXT_DARK, border_color=BORDER)

    _arrow(ax, 8, 8.15, 8, 7.15, "HTTPS / HTMX requests")

    # Core system
    _container(ax, 3.5, 3.8, 9.0, 3.2, "")
    ax.text(4.0, 6.8, "AKIRS DATA CLEANER", fontsize=12, weight="bold",
            color=NAVY, fontfamily="sans-serif")
    ax.text(4.0, 6.5, "FastAPI Application", fontsize=8, color=TXT_MID,
            style="italic", fontfamily="sans-serif")

    _box(ax, 5.5, 5.8, 2.2, 0.6, "Batch Cleaner", "19 API endpoints", fill=NAVY)
    _box(ax, 8.0, 5.8, 2.2, 0.6, "Analytics", "8 API endpoints", fill=NAVY)
    _box(ax, 10.5, 5.8, 2.2, 0.6, "NUBAN Resolver", "6 API endpoints", fill=TEAL)
    _box(ax, 8.0, 4.6, 2.2, 0.6, "DB Sync", "5 API endpoints", fill=TEAL)

    # File system
    _box(ax, 3.0, 2.5, 2.5, 0.7, "Local File System", "uploads/ · cleaned/ · reports/",
         fill=WHITE, text_color=TXT_DARK, border_color=BORDER)

    _arrow(ax, 5.5, 3.8, 3.5, 2.9, "read/write files")

    # External APIs
    _box(ax, 8.5, 1.8, 2.5, 0.6, "Paystack API", "NUBAN resolution", fill=ACCENT, text_color=TXT_LT)
    _box(ax, 11.5, 1.8, 2.5, 0.6, "Flutterwave API", "NUBAN fallback", fill=ACCENT, text_color=TXT_LT)
    _box(ax, 10.0, 2.6, 2.8, 0.6, "AKIRS TMS API", "intelligence DB search", fill=ACCENT, text_color=TXT_LT)

    _arrow(ax, 10.5, 3.8, 9.5, 3.22, "Bearer token")
    _arrow(ax, 10.5, 3.8, 10.0, 2.45, "")
    _arrow(ax, 10.5, 3.8, 11.5, 2.12, "")

    _legend(ax, 0.3, 0.5, [
        (LGRAY, "External actor / browser client"),
        (NAVY, "Core application module"),
        (TEAL, "Integration module"),
        (ACCENT, "External third-party API"),
        (WHITE, "Local storage"),
    ])

    _save(fig, "01_system_context.png")


# ═══════════════════════════════════════════════════════════════════════════
# 02 — Component Architecture
# ═══════════════════════════════════════════════════════════════════════════

def gen_02_component_architecture():
    fig, ax = _setup((16, 11))
    _page_header(ax, "Component Architecture",
                 "Four feature modules share a common core for file parsing, configuration, and state persistence.",
                 2, (0, 16), (0, 11))
    _footer(ax, (0, 16), (0, 11))

    cols = [
        ("Batch Cleaner", NAVY, [
            ("routes.py", "19 endpoints"),
            ("cleaner.py", "870 LOC"),
            ("FileState", ""),
        ], [
            "load_tabular_rows",
            "pre_flight_validate",
            "auto_map_headers",
            "extract_records",
            "find_duplicate_groups",
            "resolve_duplicate_records",
            "save_cleaned_records",
        ]),
        ("Analytics", TEAL, [
            ("analytics.py", "8 endpoints"),
            ("analyser.py", "596 LOC"),
            ("AnalysisState", ""),
        ], [
            "generate_markdown_report",
            "process_analytics",
            "process_cumulative_txns",
            "FX conversion",
        ]),
        ("NUBAN Resolver", ACCENT, [
            ("nuban.py", "6 endpoints"),
            ("nuban.py", "164 LOC"),
            ("NubanState", ""),
        ], [
            "get_bank_list",
            "resolve_account",
            "process_nuban_resolution",
        ]),
        ("DB Sync", "#4A7C59", [
            ("intelligence.py", "5 endpoints"),
            ("intelligence.py", "163 LOC"),
            ("IntelSyncState", ""),
        ], [
            "check_db_record",
            "check_records_batch",
            "jaccard_similarity",
        ]),
    ]

    tier_labels = ["API", "Service", "State"]
    x_start = 1.5
    col_w = 3.2
    gap = 0.5

    for ci, (name, color, tiers, funcs) in enumerate(cols):
        cx = x_start + ci * (col_w + gap) + col_w / 2

        # Column header
        _wide_box(ax, cx, 9.2, col_w, 0.5, name, fill=color)

        for ti, (tname, tsub) in enumerate(tiers):
            ty = 8.1 - ti * 1.6
            label = tier_labels[ti]

            if ti == 1:  # service tier — add function list
                box_h = 0.45 + len(funcs) * 0.2
                _box(ax, cx, ty - (box_h - 0.55) / 2, col_w - 0.2, box_h,
                     f"{label}: {tname}", tsub,
                     fill=WHITE, text_color=TXT_DARK, border_color=color,
                     title_size=9, sub_size=7, bold=True)
                for fi, fn in enumerate(funcs):
                    fy = ty - 0.15 - fi * 0.2
                    ax.text(cx - col_w / 2 + 0.35, fy, f"  {fn}",
                            fontsize=6.5, color=TXT_MID, fontfamily="monospace")
            else:
                _box(ax, cx, ty, col_w - 0.2, 0.55,
                     f"{label}: {tname}", tsub,
                     fill=WHITE, text_color=TXT_DARK, border_color=color,
                     title_size=9, sub_size=7)

            if ti < 2:
                _arrow(ax, cx, ty - 0.3, cx, ty - 1.0, color=color)

    # Shared base
    base_y = 2.8
    _wide_box(ax, 8, base_y, 14, 0.6,
              "state.py  --  Pickle Persistence (uploads/state_database.pkl)        "
              "config.py  --  Pydantic Settings (.env)",
              fill=LGRAY, text_color=TXT_DARK, border_color=BORDER, title_size=8)

    # Arrows from State tier to base
    for ci in range(4):
        cx = x_start + ci * (col_w + gap) + col_w / 2
        _arrow(ax, cx, 4.6, cx, 3.15, color=BORDER, style="->", lw=0.8)

    _legend(ax, 0.3, 0.5, [
        (NAVY, "Batch Cleaner module"),
        (TEAL, "Analytics module"),
        (ACCENT, "NUBAN Resolver module"),
        ("#4A7C59", "DB Sync module"),
    ])

    _save(fig, "02_component_architecture.png")


# ═══════════════════════════════════════════════════════════════════════════
# 03 — Batch Cleaner Flow
# ═══════════════════════════════════════════════════════════════════════════

def gen_03_batch_cleaner_flow():
    fig, ax = _setup((14, 16))
    _page_header(ax, "Batch Data Cleaner Pipeline",
                 "End-to-end flow from file upload through validation, mapping, deduplication, and export.",
                 3, (0, 14), (0, 16))
    _footer(ax, (0, 14), (0, 16))

    cx = 7  # center x
    steps = [
        (14.6, "User uploads .xlsx / .csv",         LGRAY, TXT_DARK),
        (13.6, "Save to uploads/",                   NAVY,  TXT_LT),
        (12.6, "Pre-flight Validate (score 0-100)",  NAVY,  TXT_LT),
        (11.6, "Load Rows + Find Header Row",        NAVY,  TXT_LT),
        (10.6, "Detect Branches",                    NAVY,  TXT_LT),
        (9.6,  "Auto-Map Headers (synonym matching)",NAVY,  TXT_LT),
    ]

    for y, label, fill, tc in steps:
        _box(ax, cx, y, 4.5, 0.55, label, fill=fill, text_color=tc, border_color=BORDER if fill == LGRAY else fill)

    # Arrows between steps
    for i in range(len(steps) - 1):
        _arrow(ax, cx, steps[i][0] - 0.3, cx, steps[i+1][0] + 0.3)

    # Decision: All fields mapped?
    dy1 = 8.7
    diamond_pts = [(cx, dy1 + 0.35), (cx + 0.55, dy1), (cx, dy1 - 0.35), (cx - 0.55, dy1)]
    d1 = plt.Polygon(diamond_pts, closed=True, facecolor=WHITE, edgecolor=NAVY, linewidth=1.2)
    ax.add_patch(d1)
    ax.text(cx, dy1, "All fields\nmapped?", ha="center", va="center", fontsize=7,
            weight="bold", color=TXT_DARK, fontfamily="sans-serif")

    _arrow(ax, cx, 9.6 - 0.3, cx, dy1 + 0.35)

    # No branch
    _box(ax, 11.0, dy1, 2.5, 0.5, "Manual Mapping Form", fill=WHITE, text_color=TXT_DARK,
         border_color=ACCENT, title_size=8)
    _arrow(ax, cx + 0.55, dy1, 11.0 - 1.25, dy1, "No")
    # loop back
    ax.annotate("", xy=(11.0, dy1 + 0.25), xytext=(11.0, 9.6 + 0.05),
                arrowprops=dict(arrowstyle="-|>", color=TXT_MID, lw=1.0,
                                connectionstyle="arc3,rad=-0.4"))

    # Yes continues
    _arrow(ax, cx, dy1 - 0.35, cx, 7.6 + 0.3, "Yes")

    # More steps
    steps2 = [
        (7.6, "Extract Records -- Validate TIN / BVN / NUBAN", NAVY, TXT_LT),
        (6.6, "Find Duplicate Groups",                          NAVY, TXT_LT),
    ]
    for y, label, fill, tc in steps2:
        _box(ax, cx, y, 4.8, 0.55, label, fill=fill, text_color=tc)

    _arrow(ax, cx, 7.6 - 0.3, cx, 6.6 + 0.3)

    # Decision: Duplicates?
    dy2 = 5.6
    dp2 = [(cx, dy2 + 0.35), (cx + 0.55, dy2), (cx, dy2 - 0.35), (cx - 0.55, dy2)]
    d2 = plt.Polygon(dp2, closed=True, facecolor=WHITE, edgecolor=NAVY, linewidth=1.2)
    ax.add_patch(d2)
    ax.text(cx, dy2, "Duplicates\nfound?", ha="center", va="center", fontsize=7,
            weight="bold", color=TXT_DARK, fontfamily="sans-serif")

    _arrow(ax, cx, 6.6 - 0.3, cx, dy2 + 0.35)

    _box(ax, 11.0, dy2, 2.8, 0.5, "Duplicate Review", "merge or pick rows",
         fill=WHITE, text_color=TXT_DARK, border_color=ACCENT, title_size=8, sub_size=6.5)
    _arrow(ax, cx + 0.55, dy2, 11.0 - 1.4, dy2, "Yes")

    # Decision: DB verify?
    dy3 = 4.4
    dp3 = [(cx, dy3 + 0.35), (cx + 0.55, dy3), (cx, dy3 - 0.35), (cx - 0.55, dy3)]
    d3 = plt.Polygon(dp3, closed=True, facecolor=WHITE, edgecolor=NAVY, linewidth=1.2)
    ax.add_patch(d3)
    ax.text(cx, dy3, "DB verify\nenabled?", ha="center", va="center", fontsize=7,
            weight="bold", color=TXT_DARK, fontfamily="sans-serif")

    _arrow(ax, cx, dy2 - 0.35, cx, dy3 + 0.35, "No")

    _box(ax, 11.0, dy3, 2.8, 0.5, "Check Live TMS API", "async HTTP queries",
         fill=WHITE, text_color=TXT_DARK, border_color=ACCENT, title_size=8, sub_size=6.5)
    _arrow(ax, cx + 0.55, dy3, 11.0 - 1.4, dy3, "Yes")

    # Final
    _arrow(ax, cx, dy3 - 0.35, cx, 3.2 + 0.3, "No")
    _box(ax, cx, 3.2, 3.5, 0.55, "Save Cleaned Records", fill=NAVY, text_color=TXT_LT)
    _arrow(ax, cx, 3.2 - 0.3, cx, 2.2 + 0.3)
    _box(ax, cx, 2.2, 3.5, 0.55, "cleaned/{filename}.csv", fill=TEAL, text_color=TXT_LT)

    _legend(ax, 0.3, 0.5, [
        (NAVY, "Processing step"),
        (WHITE, "Decision / user interaction"),
        (TEAL, "Output artifact"),
    ])

    _save(fig, "03_batch_cleaner_flow.png")


# ═══════════════════════════════════════════════════════════════════════════
# 04 — Analytics Pipeline
# ═══════════════════════════════════════════════════════════════════════════

def gen_04_analytics_pipeline():
    fig, ax = _setup((14, 12))
    _page_header(ax, "Analytics & Reporting Pipeline",
                 "Transaction logs are aggregated, grouped by identity, FX-converted, and rendered as Markdown reports.",
                 4, (0, 14), (0, 12))
    _footer(ax, (0, 14), (0, 12))

    cx = 7

    _box(ax, cx, 10.5, 4.5, 0.55, "Upload Transaction Log (.xlsx/.csv)",
         fill=LGRAY, text_color=TXT_DARK, border_color=BORDER)
    _arrow(ax, cx, 10.2, cx, 9.6)

    _box(ax, cx, 9.3, 3.5, 0.55, "Load Tabular Rows + Find Header", fill=NAVY)
    _arrow(ax, cx, 9.0, cx, 8.4)

    # Config box (tall)
    config_lines = [
        "Identity column (or multi-col concat)",
        "Metric / Credit / Debit columns",
        "Flow indicators (CR / DR)",
        "FX currency & conversion rate",
        "Record limit, min amount filter",
    ]
    box_h = 1.8
    box_center_y = 7.3
    box_top = box_center_y + box_h / 2
    _box(ax, cx, box_center_y, 4.5, box_h, "", fill=WHITE,
         text_color=TXT_DARK, border_color=TEAL, title_size=10)
    ax.text(cx, box_top - 0.25, "Configure Analysis", ha="center", va="center",
            fontsize=10, weight="bold", color=TXT_DARK, fontfamily="sans-serif")
    for i, line in enumerate(config_lines):
        ax.text(cx, box_top - 0.6 - 0.24 * i, line, ha="center", fontsize=7,
                color=TXT_MID, fontfamily="sans-serif")

    _arrow(ax, cx, box_center_y - box_h/2, cx, 5.85)

    # Decision
    dy = 5.5
    dp = [(cx, dy + 0.35), (cx + 0.55, dy), (cx, dy - 0.35), (cx - 0.55, dy)]
    d = plt.Polygon(dp, closed=True, facecolor=WHITE, edgecolor=NAVY, linewidth=1.2)
    ax.add_patch(d)
    ax.text(cx, dy, "Cumulate by\nNUBAN?", ha="center", va="center", fontsize=7,
            weight="bold", color=TXT_DARK, fontfamily="sans-serif")

    # Yes branch (left)
    _arrow(ax, cx - 0.55, dy, 3.5, dy, "Yes")
    _box(ax, 3.5, 4.5, 3.2, 0.55, "process_cumulative_transactions()", fill=NAVY, title_size=8)
    _arrow(ax, 3.5, dy - 0.35, 3.5, 4.8)
    _arrow(ax, 3.5, 4.2, 3.5, 3.6)
    _box(ax, 3.5, 3.3, 3.5, 0.55, "reports/*_cumulative_report.md", fill=TEAL, title_size=8)

    # No branch (right)
    _arrow(ax, cx + 0.55, dy, 10.5, dy, "No")
    _box(ax, 10.5, 4.5, 2.8, 0.55, "process_analytics()", fill=NAVY, title_size=8)
    _arrow(ax, 10.5, dy - 0.35, 10.5, 4.8)
    _arrow(ax, 10.5, 4.2, 10.5, 3.6)

    # Report generation detail
    rpt_lines = [
        "Group by identity",
        "Sum inflows / outflows",
        "FX conversion (USD/GBP/EUR -> NGN)",
        "Top-N ranking + summary stats",
    ]
    rh = 1.5
    rpt_center = 2.6
    rpt_top = rpt_center + rh / 2
    _box(ax, 10.5, rpt_center, 3.5, rh, "", fill=WHITE,
         text_color=TXT_DARK, border_color=NAVY, title_size=8)
    ax.text(10.5, rpt_top - 0.22, "generate_markdown_report()", ha="center", va="center",
            fontsize=8, weight="bold", color=TXT_DARK, fontfamily="sans-serif")
    for i, line in enumerate(rpt_lines):
        ax.text(10.5, rpt_top - 0.55 - 0.24 * i, line, ha="center", fontsize=6.5,
                color=TXT_MID, fontfamily="sans-serif")

    _arrow(ax, 10.5, rpt_center - rh/2, 10.5, 1.55)
    _box(ax, 10.5, 1.3, 3.2, 0.55, "reports/*_report.md", fill=TEAL, title_size=8)

    _legend(ax, 0.3, 0.5, [
        (NAVY, "Processing step"),
        (TEAL, "Output artifact"),
        (WHITE, "Configuration / detail"),
    ])

    _save(fig, "04_analytics_pipeline.png")


# ═══════════════════════════════════════════════════════════════════════════
# 05 — NUBAN Pipeline
# ═══════════════════════════════════════════════════════════════════════════

def gen_05_nuban_pipeline():
    fig, ax = _setup((14, 12))
    _page_header(ax, "NUBAN Account Resolution Pipeline",
                 "Resolves NUBAN account numbers to legal names via Paystack with Flutterwave fallback.",
                 5, (0, 14), (0, 12))
    _footer(ax, (0, 14), (0, 12))

    cx = 7

    _box(ax, cx, 10.5, 3.5, 0.55, "Upload Bank Account File",
         fill=LGRAY, text_color=TXT_DARK, border_color=BORDER)
    _arrow(ax, cx, 10.2, cx, 9.6)

    _box(ax, cx, 9.3, 3.5, 0.55, "Fetch Bank List from Paystack API", fill=ACCENT)
    _arrow(ax, cx, 9.0, cx, 8.4)

    _box(ax, cx, 8.1, 4.2, 0.55, "User selects: Bank code, NUBAN col, Target col",
         fill=WHITE, text_color=TXT_DARK, border_color=TEAL)
    _arrow(ax, cx, 7.8, cx, 7.2)

    _box(ax, cx, 6.9, 3.5, 0.55, "For each row with a NUBAN ...", fill=NAVY)
    _arrow(ax, cx, 6.6, cx, 6.0)

    _box(ax, cx, 5.7, 3.8, 0.55, "Paystack: GET /bank/resolve", fill=ACCENT)
    _arrow(ax, cx, 5.4, cx, 4.85)

    # Decision
    dy = 4.5
    dp = [(cx, dy + 0.35), (cx + 0.55, dy), (cx, dy - 0.35), (cx - 0.55, dy)]
    d = plt.Polygon(dp, closed=True, facecolor=WHITE, edgecolor=NAVY, linewidth=1.2)
    ax.add_patch(d)
    ax.text(cx, dy, "Resolved?", ha="center", va="center", fontsize=7,
            weight="bold", color=TXT_DARK, fontfamily="sans-serif")

    # No -> Flutterwave
    _arrow(ax, cx - 0.55, dy, 3.0, dy, "No")
    _box(ax, 3.0, dy, 3.0, 0.55, "Flutterwave: POST /v3/resolve", fill=ACCENT, title_size=8)
    _arrow(ax, 3.0, dy - 0.3, 3.0, 3.1)
    _arrow(ax, 3.0, 3.1, cx - 1.75, 3.1)

    # Yes
    _arrow(ax, cx, dy - 0.35, cx, 3.4, "Yes")

    _box(ax, cx, 3.1, 3.5, 0.55, "Append Account Name to Row", fill=NAVY)
    _arrow(ax, cx, 2.8, cx, 2.2)

    _box(ax, cx, 1.9, 3.8, 0.55, "cleaned/resolved_{filename}.csv", fill=TEAL)

    _legend(ax, 0.3, 0.5, [
        (ACCENT, "External API call"),
        (NAVY, "Processing step"),
        (TEAL, "Output artifact"),
    ])

    _save(fig, "05_nuban_pipeline.png")


# ═══════════════════════════════════════════════════════════════════════════
# 06 — DB Sync Pipeline
# ═══════════════════════════════════════════════════════════════════════════

def gen_06_db_sync_pipeline():
    fig, ax = _setup((14, 12))
    _page_header(ax, "Intelligence DB Sync Pipeline",
                 "Extracts taxpayer records, queries the live AKIRS TMS API, and isolates net-new records.",
                 6, (0, 14), (0, 12))
    _footer(ax, (0, 14), (0, 12))

    cx = 7

    _box(ax, cx, 10.5, 3.5, 0.55, "Upload Taxpayer List",
         fill=LGRAY, text_color=TXT_DARK, border_color=BORDER)
    _arrow(ax, cx, 10.2, cx, 9.6)

    _box(ax, cx, 9.3, 4.5, 0.55, "Auto-Map Headers (Intelligence Preset)",
         subtitle="NAME  ·  ADDRESS  ·  PHONE  ·  BUSINESS  ·  EMAIL",
         fill=NAVY)
    _arrow(ax, cx, 9.0, cx, 8.4)

    _box(ax, cx, 8.1, 3.0, 0.55, "Extract Records", fill=NAVY)
    _arrow(ax, cx, 7.8, cx, 7.2)

    # Throttled queries (tall)
    _box(ax, cx, 6.6, 4.5, 0.9, "Throttled Parallel Queries",
         subtitle="asyncio.Semaphore(15) -> AKIRS TMS REST API",
         fill=ACCENT)
    _arrow(ax, cx, 6.1, cx, 5.5)

    # Match detail
    match_lines = [
        "Exact substring on Name / Email / Phone",
        "Jaccard token fuzzy match (>= 35% threshold)",
    ]
    _box(ax, cx, 5.0, 4.5, 0.8, "Match Strategies", fill=WHITE,
         text_color=TXT_DARK, border_color=NAVY)
    for i, line in enumerate(match_lines):
        ax.text(cx, 5.05 - 0.22 * i, line, ha="center", fontsize=7,
                color=TXT_MID, fontfamily="sans-serif")

    _arrow(ax, cx, 4.6, cx, 4.0)

    _box(ax, cx, 3.7, 2.5, 0.55, "Split Results", fill=NAVY)

    # Left: matched
    _arrow(ax, cx - 1.25, 3.7, 3.0, 3.7)
    _arrow(ax, 3.0, 3.7, 3.0, 2.8)
    _box(ax, 3.0, 2.2, 3.0, 0.9, "Matched Records", "existing in DB\naudit drawer for review",
         fill=ACCENT, title_size=9)

    # Right: unique
    _arrow(ax, cx + 1.25, 3.7, 11.0, 3.7)
    _arrow(ax, 11.0, 3.7, 11.0, 2.8)
    _box(ax, 11.0, 2.2, 3.5, 0.9, "Unique Records", "net-new taxpayers\nCLEANED_UNIQUE_{file}.csv",
         fill=TEAL, title_size=9)

    _legend(ax, 0.3, 0.5, [
        (NAVY, "Processing step"),
        (ACCENT, "External API / existing match"),
        (TEAL, "Output artifact (new records)"),
    ])

    _save(fig, "06_db_sync_pipeline.png")


# ═══════════════════════════════════════════════════════════════════════════
# 07 — State Model
# ═══════════════════════════════════════════════════════════════════════════

def _uml_class(ax, x, y, title, fields, color=NAVY, width=3.0):
    """Draw a UML class box, top-down from y."""
    line_h = 0.24
    title_h = 0.40
    total_h = title_h + len(fields) * line_h + 0.15

    # Title bar
    t_rect = FancyBboxPatch(
        (x - width/2, y - title_h), width, title_h,
        boxstyle="round,pad=0.04", facecolor=color, edgecolor=color, linewidth=1.2,
    )
    ax.add_patch(t_rect)
    ax.text(x, y - title_h/2, title, ha="center", va="center",
            fontsize=8.5, weight="bold", color=TXT_LT, fontfamily="monospace")

    # Fields body
    f_rect = FancyBboxPatch(
        (x - width/2, y - total_h), width, total_h - title_h,
        boxstyle="round,pad=0.04", facecolor=WHITE, edgecolor=color, linewidth=1.0,
    )
    ax.add_patch(f_rect)
    for i, field in enumerate(fields):
        fy = y - title_h - 0.12 - i * line_h
        ax.text(x - width/2 + 0.12, fy, field, ha="left", va="center",
                fontsize=6, color=TXT_DARK, fontfamily="monospace")

    return y - total_h


def gen_07_state_model():
    fig, ax = _setup((16, 12))
    _page_header(ax, "State Model",
                 "Four state classes stored in-memory and serialized to pickle. No SQL database.",
                 7, (0, 16), (0, 12))
    _footer(ax, (0, 16), (0, 12))

    top_y = 10.5
    class_w = 3.2

    # FileState
    fs_bottom = _uml_class(ax, 2.2, top_y, "FileState", [
        "id: str",
        "original_filename: str",
        "saved_path: str",
        "headers: List[str]",
        "status: str",
        "mapped_fields: Dict",
        "preset_name: str",
        "duplicate_logic: str",
        "primary_key_field: str",
        "health_report: Dict",
        "extracted_records: List",
        "duplicate_groups: List",
        "skipped_records: List",
        "verify_db: bool",
        "db_matches: List",
    ], NAVY, class_w)

    # AnalysisState
    as_bottom = _uml_class(ax, 6.2, top_y, "AnalysisState", [
        "id: str",
        "original_filename: str",
        "headers: List[str]",
        "status: str",
        "config: Dict",
        "  identity_col",
        "  metric_col",
        "  credit/debit_col",
        "  flow_indicators",
        "  FX / limits",
        "report_path: str",
        "report_filename: str",
    ], TEAL, class_w)

    # NubanState
    ns_bottom = _uml_class(ax, 10.2, top_y, "NubanState", [
        "id: str",
        "original_filename: str",
        "headers: List[str]",
        "status: str",
        "mapped_nuban_col: str",
        "mapped_target_col: str",
        "selected_bank_code: str",
        "resolved_path: str",
        "resolved_filename: str",
    ], ACCENT, class_w)

    # IntelSyncState
    is_bottom = _uml_class(ax, 14.2, top_y, "IntelSyncState", [
        "id: str",
        "original_filename: str",
        "headers: List[str]",
        "status: str",
        "matched_records: List",
        "unique_records_count: int",
        "unique_path: str",
        "verify_db_query_field: str",
        "verify_db_target_column: str",
        "verify_db_fuzzy: bool",
    ], "#4A7C59", class_w)

    # GlobalState box
    gs_y = 2.8
    gs_bottom = _uml_class(ax, 8.2, gs_y, "GlobalState  (state.py)", [
        "file_db: Dict[str, FileState]",
        "analysis_db: Dict[str, AnalysisState]",
        "nuban_db: Dict[str, NubanState]",
        "intelsync_db: Dict[str, IntelSyncState]",
        "---",
        "save_all_states() -> pickle",
        "load_all_states() <- pickle",
    ], NAVY, 5.5)

    # Dashed composition arrows
    min_bottom = min(fs_bottom, as_bottom, ns_bottom, is_bottom)
    for cx in [2.2, 6.2, 10.2, 14.2]:
        ax.annotate(
            "", xy=(cx, min_bottom - 0.05), xytext=(cx, gs_y + 0.05),
            arrowprops=dict(arrowstyle="-|>", color=BORDER, lw=1.0, linestyle="--"),
        )

    # Persistence note
    note_rect = FancyBboxPatch(
        (5.5, 0.7), 5.5, 0.6,
        boxstyle="round,pad=0.08", facecolor="#FFF8E7", edgecolor="#DAA520", linewidth=0.8,
    )
    ax.add_patch(note_rect)
    ax.text(8.25, 1.0, "Persisted to: uploads/state_database.pkl\n"
            "Atomic write:  .tmp  ->  os.replace()",
            ha="center", va="center", fontsize=7, color=TXT_MID,
            fontfamily="monospace", style="italic")

    _arrow(ax, 8.2, gs_bottom - 0.05, 8.2, 1.35, color="#DAA520", lw=0.8)

    _legend(ax, 0.3, 0.5, [
        (NAVY, "Batch Cleaner state"),
        (TEAL, "Analytics state"),
        (ACCENT, "NUBAN Resolver state"),
        ("#4A7C59", "DB Sync state"),
    ])

    _save(fig, "07_state_model.png")


# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Generating architecture diagrams...")
    gen_01_system_context()
    gen_02_component_architecture()
    gen_03_batch_cleaner_flow()
    gen_04_analytics_pipeline()
    gen_05_nuban_pipeline()
    gen_06_db_sync_pipeline()
    gen_07_state_model()
    print("\nDone! All diagrams saved to:", DOCS_DIR)
