"""Generate a SQL Server schema script from the application's SQLAlchemy models.

Run from the repository root with:

    python ebms_flask/ebms_flask/scripts/generate_schema_sql.py

The generated file is written beside this script as ``database_schema.sql``.
This imports model definitions only; it does not connect to a database.
"""
from pathlib import Path
import sys

from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects import mssql


APP_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = APP_ROOT / "database_schema.sql"
sys.path.insert(0, str(APP_ROOT))

from app import models  # noqa: E402,F401
from app.extensions import db  # noqa: E402


def generate_schema():
    dialect = mssql.dialect()
    metadata = db.metadata
    statements = [
        "-- EBMS SQL Server database schema",
        "-- Generated from ebms_flask/app/models using SQLAlchemy metadata.",
        "-- This creates structure only; it does not insert application data.",
        "",
        "IF DB_ID(N'ProcurementDB') IS NULL",
        "    CREATE DATABASE [ProcurementDB];",
        "GO",
        "USE [ProcurementDB];",
        "GO",
        "",
    ]

    tables = metadata.sorted_tables
    for table in tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)) + ";")
        statements.append("GO")
        statements.append("")

    for table in tables:
        for index in table.indexes:
            statements.append(str(CreateIndex(index).compile(dialect=dialect)) + ";")
            statements.append("GO")
            statements.append("")

    return "\n".join(statements).rstrip() + "\n"


if __name__ == "__main__":
    schema = generate_schema()
    OUTPUT.write_text(schema, encoding="utf-8")
    print(f"Generated {OUTPUT} ({len(db.metadata.tables)} tables)")