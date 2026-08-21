"""Verify the layout fix: pages render and dashboard has icons + sidebar nav."""
import os
import sys

os.environ.setdefault('FLASK_DEBUG', 'false')
os.environ.setdefault('APP_ENV', 'development')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app import create_app

app = create_app()

# 1) theme.css validation
css = app.test_client().get('/static/theme.css').data.decode('utf-8', errors='replace')
print('sidebar-width in theme.css:', '--sidebar-width: 252px;' in css)
print('no self-ref in theme.css:', '--sidebar-width: var(--sidebar-width)' not in css)

# 2) Render dashboard for admin and check icons + nav
client = app.test_client()
client.post('/login', data={'username': 'admin', 'password': 'ChangeMe123!'}, follow_redirects=True)
body = client.get('/dashboard').data.decode('utf-8', errors='replace')

icons = ['bi-hourglass-split', 'bi-people', 'bi-inbox', 'bi-file-earmark-text']
for ic in icons:
    print(f'  dashboard icon {ic}:', ic in body)

nav_icons = ['bi-speedometer2', 'bi-folder2-open', 'bi-graph-up-arrow', 'bi-shield-check',
             'bi-chat-square-text', 'bi-bell', 'bi-person-gear']
for ic in nav_icons:
    print(f'  nav icon {ic}:', ic in body)

# 3) Basic page loads
for username, path in [('admin', '/reports/operational'),
                       ('admin', '/procurements/'),
                       ('admin', '/messages/')]:
    c = app.test_client()
    c.post('/login', data={'username': username, 'password': 'ChangeMe123!'}, follow_redirects=True)
    r = c.get(path)
    print(f'GET {path} -> {r.status_code}')
