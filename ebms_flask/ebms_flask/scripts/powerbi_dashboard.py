"""EBMS data profiler and interactive dashboard generator.

Connects to the SQL Server database configured by DATABASE_URL, discovers every
user table and column, exports all readable fields, and creates an interactive
HTML dashboard for procurement, submissions, awards, finance, complaints, and
field-level data quality.

Install once:
    pip install pandas plotly openpyxl sqlalchemy pyodbc python-dotenv

Run from ebms_flask/ebms_flask:
    python scripts/powerbi_dashboard.py

Useful options:
    python scripts/powerbi_dashboard.py --output analytics_output
    python scripts/powerbi_dashboard.py --limit 0
    python scripts/powerbi_dashboard.py --connection "mssql+pyodbc://..."
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, inspect, text
except ImportError as exc:
    raise SystemExit(
        "Missing analytics dependency. Install with: "
        "pip install pandas plotly openpyxl sqlalchemy pyodbc python-dotenv"
    ) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
load_dotenv(APP_DIR / ".env")

DEFAULT_CONNECTION = (
    "mssql+pyodbc:///?odbc_connect="
    "DRIVER%3D%7BODBC%2BDriver%2B17%2Bfor%2BSQL%2BServer%7D%3B"
    "SERVER%3Dlocalhost%255CSQLEXPRESS%3BDATABASE%3DProcurementDB%3B"
    "Trusted_Connection%3Dyes%3BTrustServerCertificate%3Dyes"
)

SENSITIVE_NAME_PARTS = {
    "password", "secret", "token", "key", "hash", "encrypted", "cipher",
    "sealed", "document_path", "file_path", "attachment_path",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--connection",
        default=os.environ.get("DATABASE_URL") or DEFAULT_CONNECTION,
        help="SQLAlchemy database URL. Defaults to DATABASE_URL or local SQL Server.",
    )
    parser.add_argument(
        "--output",
        default=str(APP_DIR / "analytics_output"),
        help="Directory for CSV, Excel, JSON, and HTML output.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Rows per table to export; 0 exports every row.",
    )
    parser.add_argument(
        "--include-sensitive",
        action="store_true",
        help="Include columns whose names look sensitive. Avoid for shared reports.",
    )
    return parser.parse_args()


def safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._") or "table"


def is_sensitive(column: str) -> bool:
    lowered = column.lower()
    return any(part in lowered for part in SENSITIVE_NAME_PARTS)


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def read_table(engine, table_name: str, columns: list[str], limit: int) -> pd.DataFrame:
    selected = ", ".join(f"[{column.replace(']', ']]')}]" for column in columns)
    table_sql = f"[{table_name.replace(']', ']]')}]"
    query = f"SELECT {selected} FROM {table_sql}"
    if limit > 0:
        query = f"SELECT TOP {limit} {selected} FROM {table_sql}"
    return pd.read_sql(text(query), engine)


def profile_table(frame: pd.DataFrame, table_name: str) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []
    for column in frame.columns:
        series = frame[column]
        non_null = series.dropna()
        sample = None if non_null.empty else non_null.iloc[0]
        columns.append({
            "column": str(column),
            "dtype": str(series.dtype),
            "rows": int(len(series)),
            "non_null": int(series.notna().sum()),
            "null_count": int(series.isna().sum()),
            "null_percent": round(float(series.isna().mean() * 100), 2) if len(series) else 0,
            "distinct": int(series.nunique(dropna=True)),
            "sample": json_default(sample) if sample is not None else None,
        })
    return {
        "table": table_name,
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "column_profile": columns,
    }


def find_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    lowered = {str(column).lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    for column in frame.columns:
        name = str(column).lower()
        if any(candidate.lower() in name for candidate in candidates):
            return str(column)
    return None


def count_by(frame: pd.DataFrame, candidates: tuple[str, ...], label: str = "value") -> pd.DataFrame:
    column = find_column(frame, candidates)
    if not column:
        return pd.DataFrame(columns=[label, "count"])
    result = frame[column].fillna("Unknown").astype(str).value_counts().reset_index()
    result.columns = [label, "count"]
    return result.head(20)


def make_empty_figure(title: str, message: str = "No matching data was found") -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(text=message, showarrow=False, font={"size": 16})
    figure.update_layout(title=title, template="plotly_white", height=360)
    return figure


def chart_for_counts(frame: pd.DataFrame, title: str, color: str = "#176b87") -> go.Figure:
    if frame.empty:
        return make_empty_figure(title)
    figure = px.bar(frame, x=frame.columns[0], y="count", title=title, color_discrete_sequence=[color])
    figure.update_layout(template="plotly_white", height=360, margin={"t": 60, "l": 30, "r": 20, "b": 80})
    return figure


def make_dashboard(frames: dict[str, pd.DataFrame], profiles: list[dict[str, Any]], output: Path) -> None:
    procurement = next((frame for name, frame in frames.items() if name.lower() == "procurements"), pd.DataFrame())
    submissions = next((frame for name, frame in frames.items() if name.lower() == "submissions"), pd.DataFrame())
    awards = next((frame for name, frame in frames.items() if name.lower() == "awards"), pd.DataFrame())
    payments = next((frame for name, frame in frames.items() if "payment" in name.lower()), pd.DataFrame())
    complaints = next((frame for name, frame in frames.items() if "complaint" in name.lower()), pd.DataFrame())

    status = count_by(procurement, ("status",), "status")
    category = count_by(procurement, ("category", "procurement_category"), "category")
    method = count_by(procurement, ("method", "procurement_method"), "method")
    submission_status = count_by(submissions, ("status",), "status")
    payment_status = count_by(payments, ("status",), "status")
    complaint_status = count_by(complaints, ("status",), "status")

    value_column = find_column(procurement, ("estimated_value", "budget", "value"))
    total_value = float(pd.to_numeric(procurement[value_column], errors="coerce").sum()) if value_column else 0
    award_value_column = find_column(awards, ("award_value", "value", "amount"))
    total_awarded = float(pd.to_numeric(awards[award_value_column], errors="coerce").sum()) if award_value_column else 0

    cards = [
        ("Tables analysed", len(frames)),
        ("Total records", sum(len(frame) for frame in frames.values())),
        ("Procurements", len(procurement)),
        ("Submissions", len(submissions)),
        ("Awards", len(awards)),
        ("Estimated value", f"{total_value:,.2f}"),
        ("Awarded value", f"{total_awarded:,.2f}"),
        ("Data fields", sum(profile["columns"] for profile in profiles)),
    ]

    figures = [
        chart_for_counts(status, "Procurement status", "#176b87"),
        chart_for_counts(category, "Procurements by category", "#d9822b"),
        chart_for_counts(method, "Procurements by method", "#2f855a"),
        chart_for_counts(submission_status, "Submission status", "#6b46c1"),
        chart_for_counts(payment_status, "Payment status", "#c53030"),
        chart_for_counts(complaint_status, "Complaint status", "#805ad5"),
    ]
    chart_html = "".join(figure.to_html(full_html=False, include_plotlyjs=False) for figure in figures)

    profile_rows = []
    for profile in profiles:
        nulls = sum(column["null_count"] for column in profile["column_profile"])
        profile_rows.append(
            f"<tr><td>{html.escape(profile['table'])}</td><td>{profile['rows']:,}</td>"
            f"<td>{profile['columns']:,}</td><td>{nulls:,}</td></tr>"
        )

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EBMS Analytics Dashboard</title><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root {{ --ink:#16323f; --muted:#647780; --line:#dce6e9; --accent:#176b87; --paper:#f7faf9; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:15px Segoe UI,Arial,sans-serif; }}
header {{ background:#16323f; color:white; padding:34px 5vw 28px; }} h1 {{ margin:0 0 8px; font-size:30px; }} header p {{ margin:0; color:#c5d8dc; }} main {{ max-width:1500px; margin:auto; padding:24px 5vw 60px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:22px; }}
.card {{ background:white; border:1px solid var(--line); padding:17px; border-radius:8px; }} .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; }} .value {{ font-size:25px; font-weight:700; margin-top:7px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(390px,1fr)); gap:16px; }} .chart {{ background:white; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
h2 {{ margin:34px 0 12px; font-size:21px; }} table {{ width:100%; border-collapse:collapse; background:white; }} th,td {{ border-bottom:1px solid var(--line); text-align:left; padding:10px 12px; }} th {{ background:#eaf2f3; }} .note {{ color:var(--muted); }}
@media(max-width:520px) {{ .grid {{ grid-template-columns:1fr; }} .chart {{ min-width:0; }} }}
</style></head><body><header><h1>EBMS Analytics Dashboard</h1><p>Generated from all readable SQL Server tables and fields. Sensitive columns are excluded by default.</p></header><main>
<section class="cards">{''.join(f'<div class="card"><div class="label">{html.escape(str(label))}</div><div class="value">{html.escape(str(value))}</div></div>' for label, value in cards)}</section>
<section class="grid">{chart_html}</section>
<h2>Table coverage</h2><p class="note">Every discovered table is exported to CSV. The full field-level profile is in <b>data_profile.json</b>.</p>
<table><thead><tr><th>Table</th><th>Rows exported</th><th>Fields</th><th>Null cells</th></tr></thead><tbody>{''.join(profile_rows)}</tbody></table>
</main></body></html>"""
    (output / "ebms_dashboard.html").write_text(page, encoding="utf-8")


def main() -> int:
    args = parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    engine = create_engine(args.connection, pool_pre_ping=True)
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    frames: dict[str, pd.DataFrame] = {}
    profiles: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for table_name in table_names:
        columns = [column["name"] for column in inspector.get_columns(table_name)]
        if not args.include_sensitive:
            columns = [column for column in columns if not is_sensitive(column)]
        if not columns:
            skipped.append({"table": table_name, "reason": "No non-sensitive columns"})
            continue
        try:
            frame = read_table(engine, table_name, columns, args.limit)
            frames[table_name] = frame
            frame.to_csv(output / f"{safe_filename(table_name)}.csv", index=False, encoding="utf-8-sig")
            profiles.append(profile_table(frame, table_name))
            print(f"Exported {table_name}: {len(frame):,} rows, {len(frame.columns):,} fields")
        except Exception as exc:
            skipped.append({"table": table_name, "reason": str(exc)})
            print(f"Skipped {table_name}: {exc}", file=sys.stderr)

    with (output / "data_profile.json").open("w", encoding="utf-8") as profile_file:
        json.dump({"tables": profiles, "skipped": skipped}, profile_file, indent=2, default=json_default)

    with pd.ExcelWriter(output / "ebms_all_data.xlsx", engine="openpyxl") as writer:
        for table_name, frame in frames.items():
            frame.to_excel(writer, sheet_name=safe_filename(table_name)[:31], index=False)

    make_dashboard(frames, profiles, output)
    print(f"\nDashboard: {output / 'ebms_dashboard.html'}")
    print(f"All-data workbook: {output / 'ebms_all_data.xlsx'}")
    print(f"Field profile: {output / 'data_profile.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
