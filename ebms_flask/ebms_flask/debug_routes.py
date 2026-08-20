"""Focused debug: capture full tracebacks for failing routes.

Run: python debug_routes.py
"""
import os
import sys
import traceback

os.environ.setdefault('FLASK_DEBUG', 'false')
os.environ.setdefault('APP_ENV', 'development')
os.environ.setdefault('WERKZEUG_RUN_MAIN', 'true')

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app  # noqa: E402

OUT = []
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug_report.txt')


def log(msg):
    OUT.append(str(msg))
    print(msg)


app = create_app()
app.testing = True  # propagate exceptions to the test client


def main():
    paths = [
        '/messages/',
        '/messages/search?q=test',
        '/reports/audit-trail',
        '/reports/bidder-participation',
        '/reports/complaints',
        '/reports/procurement-summary',
        '/reports/audit-trail/export',
        '/reports/bidder-participation/export',
        '/reports/complaints/export',
        '/reports/procurement-summary/export',
    ]
    client = app.test_client()
    r = client.post('/login', data={'username': 'admin', 'password': 'ChangeMe123!'}, follow_redirects=True)
    log(f"login -> {r.status_code}")

    for path in paths:
        try:
            resp = client.get(path, follow_redirects=True)
            log(f"GET {path} -> {resp.status_code}")
        except Exception:
            log(f"GET {path} -> EXCEPTION\n{traceback.format_exc()}")


if __name__ == '__main__':
    try:
        main()
    except Exception:
        with open(REPORT, 'w', encoding='utf-8') as fh:
            fh.write("UNHANDLED EXCEPTION DURING MAIN:\n" + traceback.format_exc())
        raise
    with open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write("\n".join(OUT))