"""Copy the local SQLite database into SQL Server Express.

Usage from ``ebms_flask/ebms_flask``::

    python scripts/migrate_sqlserver.py --source instance/ebms.db

The source database is opened read-only. The target database is created from
the SQLAlchemy model metadata, then rows are copied in foreign-key order with
explicit identity and common SQLite-to-SQL Server conversions.
"""
import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, time
from urllib.parse import quote_plus

import pyodbc
from sqlalchemy import create_engine


SERVER = r"localhost\SQLEXPRESS"
DATABASE = "ProcurementDB"
DRIVER = "ODBC Driver 17 for SQL Server"


def connection_string(database):
    return (
        f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={database};"
        "Trusted_Connection=yes;TrustServerCertificate=yes"
    )


def ensure_database():
    with pyodbc.connect(connection_string("master"), autocommit=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"IF DB_ID(N'{DATABASE}') IS NULL CREATE DATABASE [{DATABASE}]"
        )


def repair_sqlserver_constraints():
    """Replace SQLite's nullable UNIQUE semantics with a filtered index."""
    with pyodbc.connect(connection_string(DATABASE), autocommit=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT i.name, kc.name FROM sys.indexes i "
            "JOIN sys.tables t ON t.object_id = i.object_id "
            "JOIN sys.index_columns ic ON ic.object_id = i.object_id "
            "AND ic.index_id = i.index_id "
            "JOIN sys.columns c ON c.object_id = ic.object_id "
            "AND c.column_id = ic.column_id "
            "LEFT JOIN sys.key_constraints kc ON kc.parent_object_id = i.object_id "
            "AND kc.unique_index_id = i.index_id "
            "WHERE t.name = 'bidders' AND c.name = 'ppra_registration_number' "
            "AND i.is_unique = 1 "
            "AND i.name <> 'uq_bidders_ppra_registration_number'"
        )
        for index_name, constraint_name in cursor.fetchall():
            if constraint_name:
                cursor.execute(f"ALTER TABLE [bidders] DROP CONSTRAINT [{constraint_name}]")
            else:
                cursor.execute(f"DROP INDEX [{index_name}] ON [bidders]")
        cursor.execute(
            "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = "
            "'uq_bidders_ppra_registration_number') "
            "CREATE UNIQUE INDEX [uq_bidders_ppra_registration_number] "
            "ON [bidders] ([ppra_registration_number]) "
            "WHERE [ppra_registration_number] IS NOT NULL"
        )


def source_tables(source):
    with sqlite3.connect(f"file:{os.path.abspath(source)}?mode=ro", uri=True) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]


def load_app_metadata():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)
    from app import models  # noqa: F401
    from app.extensions import db

    return db.metadata


def foreign_key_order(metadata, tables):
    remaining = set(tables)
    ordered = []
    while remaining:
        ready = sorted(
            name
            for name in remaining
            if all(
                fk.column.table.name not in remaining or fk.column.table.name == name
                for column in metadata.tables[name].columns
                for fk in column.foreign_keys
            )
        )
        if not ready:
            raise RuntimeError(f"Foreign-key cycle prevents migration: {sorted(remaining)}")
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered


def convert_value(value, column):
    if value is None:
        return None
    type_name = column.type.__class__.__name__.lower()
    if "boolean" in type_name:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if "datetime" in type_name:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    if type_name == "date":
        return date.fromisoformat(str(value)[:10])
    if type_name == "time":
        return time.fromisoformat(str(value))
    return value


def migrate(source, metadata):
    tables = source_tables(source)
    missing = sorted(set(tables) - set(metadata.tables))
    if missing:
        raise RuntimeError(f"SQLite tables have no SQLAlchemy model: {missing}")

    ensure_database()
    target = pyodbc.connect(connection_string(DATABASE))
    target.autocommit = False
    try:
        # Use the application models as the single schema definition.
        engine = create_engine(
            f"mssql+pyodbc:///?odbc_connect={quote_plus(connection_string(DATABASE))}"
        )
        metadata.create_all(engine)
        engine.dispose()
        repair_sqlserver_constraints()

        ordered = foreign_key_order(metadata, tables)
        source_conn = sqlite3.connect(f"file:{os.path.abspath(source)}?mode=ro", uri=True)
        known_keys = {}
        skipped_counts = {}
        try:
            for table_name in ordered:
                table = metadata.tables[table_name]
                columns = [column for column in table.columns]
                names = [column.name for column in columns]
                placeholders = ", ".join("?" for _ in columns)
                quoted = ", ".join(f"[{name}]" for name in names)
                rows = source_conn.execute(f"SELECT {quoted} FROM [{table_name}]")
                values = []
                for row in rows:
                    converted = [
                        convert_value(value, column)
                        for value, column in zip(row, columns)
                    ]
                    skip_row = False
                    for column_index, column in enumerate(columns):
                        for foreign_key in column.foreign_keys:
                            parent_table = foreign_key.column.table.name
                            if parent_table == table_name:
                                continue
                            parent_keys = known_keys.get(parent_table, set())
                            value = converted[column_index]
                            if value is not None and value not in parent_keys:
                                if column.nullable:
                                    converted[column_index] = None
                                    print(
                                        f"{table_name}.{column.name}: converted "
                                        f"missing FK value {value!r} to NULL"
                                    )
                                else:
                                    skip_row = True
                                    skipped_counts[table_name] = skipped_counts.get(table_name, 0) + 1
                                    print(
                                        f"{table_name}: skipped row with invalid "
                                        f"non-nullable FK {column.name}={value!r} "
                                        f"-> {parent_table}"
                                    )
                    if skip_row:
                        continue
                    values.append(tuple(converted))
                if not values:
                    continue
                cursor = target.cursor()
                cursor.execute(f"SET IDENTITY_INSERT [{table_name}] ON")
                cursor.fast_executemany = True
                cursor.executemany(
                    f"INSERT INTO [{table_name}] ({quoted}) VALUES ({placeholders})",
                    values,
                )
                cursor.execute(f"SET IDENTITY_INSERT [{table_name}] OFF")
                primary_key = next(iter(table.primary_key.columns), None)
                if primary_key is not None:
                    key_index = names.index(primary_key.name)
                    known_keys[table_name] = {row[key_index] for row in values}
                print(f"{table_name}: {len(values)} rows")
            target.commit()
        finally:
            source_conn.close()
        return skipped_counts
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()


def validate(source, metadata, skipped_counts=None):
    skipped_counts = skipped_counts or {}
    target = pyodbc.connect(connection_string(DATABASE))
    try:
        with sqlite3.connect(f"file:{os.path.abspath(source)}?mode=ro", uri=True) as source_conn:
            for table_name in source_tables(source):
                source_count = source_conn.execute(
                    f"SELECT COUNT(*) FROM [{table_name}]"
                ).fetchone()[0]
                target_count = target.cursor().execute(
                    f"SELECT COUNT(*) FROM [{table_name}]"
                ).fetchone()[0]
                expected_count = source_count - skipped_counts.get(table_name, 0)
                result = "OK" if expected_count == target_count else "MISMATCH"
                print(
                    f"{table_name}: source={source_count} skipped="
                    f"{skipped_counts.get(table_name, 0)} target={target_count} {result}"
                )
                if result != "OK":
                    raise RuntimeError(f"Row count mismatch for {table_name}")
    finally:
        target.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=os.path.join("instance", "ebms.db"))
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    source = os.path.abspath(args.source)
    if not os.path.isfile(source):
        raise SystemExit(f"SQLite source not found: {source}")
    metadata = load_app_metadata()
    if args.validate_only:
        validate(source, metadata)
    else:
        skipped_counts = migrate(source, metadata)
        validate(source, metadata, skipped_counts)


if __name__ == "__main__":
    main()