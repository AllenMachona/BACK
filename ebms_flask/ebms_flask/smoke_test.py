"""Smoke test: boots the app, signs in each demo user, and hits every route.

Run: python smoke_test.py  (from the ebms_flask/ebms_flask folder)
"""
import os
import sys
import traceback

os.environ.setdefault('FLASK_DEBUG', 'false')
os.environ.setdefault('APP_ENV', 'development')

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

OUT = []


def log(msg):
    OUT.append(str(msg))
    print(msg)


app = create_app()


def get_route_map():
    routes = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint and not rule.endpoint.startswith('static'):
            routes[rule.endpoint] = rule.rule
    return routes


def main():
    from app.models.role import Role
    from app.models.user import User
    from werkzeug.security import check_password_hash

    with app.app_context():
        roles = Role.query.count()
        users = User.query.count()
        log(f"Roles in DB: {roles}, Users in DB: {users}")
        if users == 0:
            log("No users - seeding...")
            import seed
            seed.seed_data()
        routes = get_route(app)

    client = app.test_client()

    # 1) unauthenticated pages
    log("\n--- Unauthenticated checks ---")
    unauth_paths = [
        ('/auth/login', 'login'),
        ('/', 'root'),
    ]
    for path, name in unauth_paths:
        try:
            r = client.get(path, follow_redirects=True)
            log(f"GET {path} -> {r.status_code}")
        except Exception as e:
            log(f"GET {path} -> EXCEPTION: {e}")
            traceback.print_exc()

    # 2) Log in as each demo user and hit their pages.
    #    Map endpoint -> HTTP method. We test GET for pages.
    users = ['admin', 'd.tlou', 'k.motsumi', 'n.kgosi', 'p.seleka', 'bidder1', 'j.molefe', 's.kgosi', 'g.motsumi', 'p.seleka2']
    with app.app_context():
        present = {u.username for u in User.query.all()}
        log(f"Users present: {sorted(present)}")

    # Collect GET-only endpoints
    get_endpoints = sorted({e: r for e, r in routes.items() if 'GET' in str(r.methods)}.items())

    for username in defs:
        log(f"\n=== LOGIN AS: {username} ===")
        client = app.test_client()
        r = client.post('/auth/login', data={'username': username, 'password': 'ChangeMe123!'}, follow_redirects=True)
        log(f"LOGIN {username} -> {r.status_code}")
        if r.status_code >= 400:
            log(f"LOGIN BODY (first 300): {r.data[:300]}")
            continue
        # Now get every GET route that is safe to fetch
        for endpoint, path in get_endpoints:
            if path.startswith('/auth/') or '/static/' in path:
                continue
            try:
                r2 = client.get(path, follow_redirects=True)
                status = r2.status_code
                if status >= 400:
                    log(f"  GET {path} ({endpoint}) -> {status}")
                    # look for template error markers
                    body = r2.data.decode('utf-8', errors='replace')
                    if 'Traceback' in body:
                        log(f"    TRACEBACK SNIPPET: {body[body.find('Traceback'):body.find('Traceback')+800]}")
                else:
                    if status == 200:
                        log(f"  GET {path} -> 200")
        if username in ('admin',):
            # test a few URL-param routes
            with app.app_context():
                from app.models.procurement import Procurement
                pid = Procurement.query.first().id if Procurement.query.first() else None
                if pid:
                    for p in [f'/procurements/{pid}', f'/procurements/{pid}/edit']:
                        r2 = client.get(p)
                        log(f"  GET {p} -> {r2.status_code}")


def get_endpoints():
    routes = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint and not rule.endpoint.startswith('static'):
            if 'GET' in rule.methods:
                routes[rule.endpoint] = rule.rule
    return sorted(routes.items())


if __name__ == '__main__':
    main()
    print("\n\n===== SMOKE TEST COMPLETE =====")
    print("\n".join(OUT))