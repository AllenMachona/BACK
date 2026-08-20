"""Smoke test: boots the app, signs in each demo user, and hits every GET route.

Run: python smoke_run.py  (from the ebms_flask/ebms_flask folder)
"""
import os
import re
import sys
import traceback

os.environ.setdefault('FLASK_DEBUG', 'false')
os.environ.setdefault('APP_ENV', 'development')
os.environ.setdefault('WERKZEUG_RUN_MAIN', 'true')
REPORT = os.environ.get('SMOKE_REPORT', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'smoke_report.txt'))

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app  # noqa: E402

OUT = []


def log(msg):
    OUT.append(str(msg))
    print(msg)


app = create_app()


def rest_path(path, proc_ids):
    if '<int:' not in path:
        return path

    def rep(m):
        return str(proc_ids[0]) if proc_ids else '1'

    return re.sub(r'<int:[^>]+>', rep, path)


def main():
    from app.models.user import User

    with app.app_context():
        users = User.query.count()
        log(f"Users in DB: {users}")
        if users == 0:
            log("No users - seeding...")
            import seed
            seed.seed_data()

    with app.app_context():
        present = sorted({u.username for u in User.query.all()})
        log(f"Users present: {present}")

    endpoints = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint and not rule.endpoint.startswith('static') \
                and not rule.endpoint.startswith('auth.') and 'GET' in rule.methods:
            endpoints.append((rule.endpoint, rule.rule))
    endpoints = sorted(endpoints)

    with app.app_context():
        from app.models.procurement import Procurement
        proc_ids = [p.id for p in Procurement.query.order_by(Procurement.id.asc()).all()]
        log(f"Procurement ids in DB: {proc_ids}")

    usernames = ['admin', 'd.tlou', 'k.motsumi', 'n.kgosi', 'p.seleka',
                 'bidder1', 'j.molefe', 's.kgosi', 'g.motsumi', 'p.seleka2']

    for username in usernames:
        log(f"\n=== LOGIN: {username} ===")
        client = app.test_client()
        try:
            r = client.post('/login',
                            data={'username': username, 'password': 'ChangeMe123!'},
                            follow_redirects=True)
            log(f"login -> {r.status_code}")
        except Exception as e:
            log(f"login -> EXCEPTION: {type(e).__name__}: {e}")
            traceback.print_exc()
            continue
        if r.status_code >= 400:
            log(f"login body: {r.data[:300]!r}")
            continue

        tested = set()
        for endpoint, path in endpoints:
            path = rest_path(path, proc_ids)
            if path in tested or path == '/':
                continue
            tested.add(path)
            try:
                r2 = client.get(path, follow_redirects=True)
                status = r2.status_code
                if status >= 400:
                    log(f"  GET {path} ({endpoint}) -> {status}")
                    body = r2.data.decode('utf-8', errors='replace')
                    marker = body.find('Traceback')
                    if marker >= 0:
                        log(f"    TRACE: {body[marker:marker + 700]}")
                else:
                    log(f"  GET {path} -> {status}")
            except Exception as e:
                log(f"  GET {path} -> EXCEPTION: {type(e).__name__}: {e}")
                traceback.print_exc()


if __name__ == '__main__':
    main()
    print("\n\n===== SMOKE TEST COMPLETE =====")
    with open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write("\n".join(OUT))