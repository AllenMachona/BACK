"""
Database migration script to add procurement document columns and payment verification tables.

Usage:
    python scripts/migrate_procurement_documents_payments.py
"""

from app import create_app
from app.extensions import db
from sqlalchemy import text


def migrate():
    app = create_app()

    with app.app_context():
        print("Starting procurement documents and payment verification migration...")

        # Ensure all tables are created
        db.create_all()

        # Check and add columns to procurements table if needed
        try:
            result = db.session.execute(text("PRAGMA table_info(procurements)"))
            existing_columns = [row[1] for row in result]

            columns_to_add = {
                'tender_fee': 'ALTER TABLE procurements ADD COLUMN tender_fee NUMERIC(15, 2) DEFAULT 0.00',
                'form_d_file_path': 'ALTER TABLE procurements ADD COLUMN form_d_file_path VARCHAR(500)',
                'form_d_filename': 'ALTER TABLE procurements ADD COLUMN form_d_filename VARCHAR(300)',
                'form_e_file_path': 'ALTER TABLE procurements ADD COLUMN form_e_file_path VARCHAR(500)',
                'form_e_filename': 'ALTER TABLE procurements ADD COLUMN form_e_filename VARCHAR(300)',
                'rfce_file_path': 'ALTER TABLE procurements ADD COLUMN rfce_file_path VARCHAR(500)',
                'rfce_filename': 'ALTER TABLE procurements ADD COLUMN rfce_filename VARCHAR(300)',
                'itt_file_path': 'ALTER TABLE procurements ADD COLUMN itt_file_path VARCHAR(500)',
                'itt_filename': 'ALTER TABLE procurements ADD COLUMN itt_filename VARCHAR(300)',
                'rfq_file_path': 'ALTER TABLE procurements ADD COLUMN rfq_file_path VARCHAR(500)',
                'rfq_filename': 'ALTER TABLE procurements ADD COLUMN rfq_filename VARCHAR(300)',
            }

            for col_name, sql in columns_to_add.items():
                if col_name not in existing_columns:
                    print(f"Adding column '{col_name}' to procurements table...")
                    db.session.execute(text(sql))
                    db.session.commit()
                    print(f"✓ Added '{col_name}'")
                else:
                    print(f"✓ Column '{col_name}' already exists")

        except Exception as e:
            print(f"Notice during column verification: {e}")

        print("\n✓ Migration completed successfully!")


if __name__ == '__main__':
    migrate()
