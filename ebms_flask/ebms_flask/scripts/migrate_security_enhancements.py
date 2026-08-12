"""
Database migration script to add security enhancements.
Run this to update the database schema.

Usage: python -c "from app import create_app; from app.extensions import db; app = create_app(); app.app_context().push(); exec(open('scripts/migrate_security_enhancements.py').read())"
"""

from app import create_app
from app.extensions import db
from sqlalchemy import text

def migrate_security_enhancements():
    """Apply security-related database migrations."""
    app = create_app()
    
    with app.app_context():
        try:
            # Check if notifications table has sender_id column
            result = db.session.execute(text("PRAGMA table_info(notifications)"))
            columns = [row[1] for row in result]
            
            if 'sender_id' not in columns:
                print("Adding sender_id column to notifications table...")
                db.session.execute(text(
                    "ALTER TABLE notifications ADD COLUMN sender_id INTEGER"
                ))
                db.session.commit()
                print("✓ Added sender_id column")
            else:
                print("✓ sender_id column already exists")
            
            if 'reply_to' not in columns:
                print("Adding reply_to column to notifications table...")
                db.session.execute(text(
                    "ALTER TABLE notifications ADD COLUMN reply_to INTEGER"
                ))
                db.session.commit()
                print("✓ Added reply_to column")
            else:
                print("✓ reply_to column already exists")
            
            print("\n✓ Security migrations completed successfully!")
            
        except Exception as e:
            print(f"✗ Migration error: {e}")
            print("Note: If using PostgreSQL, you may need to create these columns manually:")
            print("  ALTER TABLE notifications ADD COLUMN sender_id INTEGER REFERENCES users(id);")
            print("  ALTER TABLE notifications ADD COLUMN reply_to INTEGER REFERENCES notifications(id);")


if __name__ == '__main__':
    migrate_security_enhancements()
