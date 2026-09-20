# PythonAnywhere deployment without Docker

PythonAnywhere can host this Flask application on its free web-app plan
without requiring a payment card. Supabase can remain the database if the
account allows outbound access to the Supabase connection host.

## 1. Create the web app

1. Create an account at [pythonanywhere.com](https://www.pythonanywhere.com/).
2. Open **Web > Add a new web app**.
3. Choose **Manual configuration** and Python 3.12 (or the closest available
   version).
4. Clone this GitHub repository in a Bash console:

   ```bash
   cd ~
   git clone https://github.com/AllenMachona/BACK.git
   cd BACK
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

## 2. Configure the WSGI file

Open the WSGI file shown on the Web page and replace its contents with this,
changing `YOUR_USERNAME`:

```python
import os
import sys

project_path = '/home/YOUR_USERNAME/BACK'
sys.path.insert(0, project_path)

os.environ['APP_ENV'] = 'production'
os.environ['DATABASE_URL'] = 'YOUR_SUPABASE_CONNECTION_STRING'
os.environ['SECRET_KEY'] = 'YOUR_RANDOM_SECRET_KEY'
os.environ['SUBMISSION_ENCRYPTION_KEY'] = 'YOUR_FERNET_KEY'

from wsgi import app as application
```

Keep the WSGI file private. Do not commit these values to GitHub.

In the Web page, set **Virtualenv** to:

```text
/home/YOUR_USERNAME/BACK/venv
```

Set the source code directory to:

```text
/home/YOUR_USERNAME/BACK
```

Click **Reload** and open the displayed PythonAnywhere URL.

## Supabase connectivity note

PythonAnywhere free accounts may restrict outbound database connections. If
the Supabase connection is blocked, set `DATABASE_URL` to:

```text
sqlite:////home/YOUR_USERNAME/BACK/ebms_flask/ebms_flask/instance/ebms.db
```

That SQLite database is stored on PythonAnywhere's persistent filesystem and
will let the app run without Supabase. Supabase remains the recommended
database for a production deployment.

## File uploads

The free web app filesystem is persistent, but storage is limited. Keep bid
uploads small during testing and use durable object storage before production.