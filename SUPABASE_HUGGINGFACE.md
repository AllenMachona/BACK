# Supabase + Hugging Face Spaces

This is the no-card hosting option for the Flask app. Supabase provides the
PostgreSQL database and Hugging Face Spaces runs the application in Docker.

If Docker hardware is paid in your account, use the no-card PythonAnywhere
deployment in [PYTHONANYWHERE.md](PYTHONANYWHERE.md) instead.

## Create the database

1. Create a project at [supabase.com](https://supabase.com/).
2. Open **Connect**, choose the **Session pooler**, and copy its PostgreSQL
   connection string.
3. Keep that string private because it contains the database password.

The Flask app creates its SQLAlchemy tables automatically on first startup.
Do not run `ebms_flask/ebms_flask/database_schema.sql` in Supabase because it
uses SQL Server syntax.

## Deploy without a payment card

1. Create a new Docker Space at [huggingface.co/new-space](https://huggingface.co/new-space).
2. Choose a name, select **Docker**, and choose the free CPU hardware.
3. In the Space, open **Settings > Variables and secrets**.
4. Add these secrets:
   - `APP_ENV=production`
   - `DATABASE_URL`: the Supabase session-pooler PostgreSQL URL
   - `SECRET_KEY`: a long random value
   - `SUBMISSION_ENCRYPTION_KEY`: generate with:
     `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
5. Push this repository's files to the Space, or connect the Space to the
   GitHub repository. The included `Dockerfile` starts the Flask app on port
   `7860`.

The Space URL will be similar to:
`https://huggingface.co/spaces/YOUR_ACCOUNT/YOUR_SPACE`

## Important limitations

- Free Spaces can sleep when idle, so the first request may be slow.
- The container filesystem is temporary. Do not rely on `uploads/` for
  permanent bid documents. Move encrypted uploads to Supabase Storage before
  using this for real procurement data.
- Keep the Fernet key unchanged or old encrypted files cannot be decrypted.
- Remove the demo users and change their passwords before sharing the app.