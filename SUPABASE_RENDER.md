# Supabase + Render deployment

If Render asks for payment details, use the no-card alternative in
[SUPABASE_HUGGINGFACE.md](SUPABASE_HUGGINGFACE.md). It uses the same Supabase
database and the included Dockerfile.

This app can use Supabase PostgreSQL through SQLAlchemy and run on Render as a
Python web service.

## 1. Create the Supabase database

1. Create a project at [supabase.com](https://supabase.com/).
2. Open **Connect**, choose the **Session pooler** connection, and copy the
   SQLAlchemy-style URI. The session pooler is a good default for this Flask
   app because it supports normal connection pooling.
3. Keep the URI private. It contains the database password.

The app creates its SQLAlchemy model tables automatically on first startup.
Do not run `database_schema.sql` in Supabase: that file is SQL Server syntax.

## 2. Deploy the app to Render

1. Push this repository to GitHub.
2. In Render, choose **New + > Blueprint** and select the repository.
3. Render will read `render.yaml` and create the web service.
4. Set these prompted secrets in the Render service environment:
   - `DATABASE_URL`: the Supabase session pooler URI
   - `SUBMISSION_ENCRYPTION_KEY`: generate locally with:
     `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - `MAIL_SERVER`, `MAIL_DEFAULT_SENDER`, and any SMTP credentials
5. Deploy and open the Render URL.

## Important production notes

- Change or remove the demo accounts and passwords before inviting real users.
- Render's local filesystem is ephemeral. Uploaded encrypted bid files should
  be moved to Supabase Storage or another durable object-storage service before
  production use; the current app stores them under `UPLOAD_FOLDER`.
- Store the Fernet key permanently. If it changes, previously encrypted bid
  documents cannot be decrypted.