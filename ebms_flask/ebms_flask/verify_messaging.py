"""Validate messaging attachment, recipient, and preview changes."""
import os, sys, io, tempfile
os.environ.setdefault('FLASK_DEBUG', 'false')
os.environ.setdefault('APP_ENV', 'development')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()
from app import create_app

app = create_app()
client = app.test_client()
client.post('/login', data={'username': 'admin', 'password': 'ChangeMe123!'}, follow_redirects=True)

# 1) Preview endpoints return JSON
for url, label in [('/messages/preview', 'messages.preview'),
                   ('/notifications/preview', 'notifications.preview')]:
    r = client.get(url)
    print(label, '->', r.status_code, 'json=', 'items' in r.get_json() if r.is_json else r.data[:80])

# 2) Find a thread to open (fetch inbox and pick first conversation)
inbox = client.get('/messages/').data.decode('utf-8', errors='replace')
print('inbox status:', 'messages' if '/messages/thread/' in 'x' else 'inline')
# Thread links look like /messages/thread/<id>
import re
ids = set(re.findall(r'/messages/thread/(\d+)', inbox))
print('thread ids found in inbox:', sorted(ids, key=int)[:5] if ids else 'none')

# 3) Send a broadcast message WITH a PDF attachment
att_path = None
try:
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w', encoding='utf-8') as tf:
        tf.write('Hello attachment world')
        att_path = tf.name
    with open(att_path, 'rb') as fp:
        data = {
            'message_type': 'broadcast', 'subject': 'Attachment test ' + os.path.basename(att_path),
            'body': 'Testing message attachments across recipients.',
        }
        files = {'attachments': (os.path.basename(att_path), fp, 'text/plain')}
        r = client.post('/messages/send', data=data, files=files,
                        headers={'X-Requested-With': 'XMLHttpRequest'})
    print('send w/ attachment ->', r.status_code, r.get_data(as_text=True)[:200])
finally:
    import traceback
    if 'r' not in locals():
        traceback.print_exc()
        r = None
    try:
        if att_path:
            os.remove(att_path)
    except OSError:
        pass

# 4. Find a message id to test recipients + attachment download
mids = set(re.findall(r'"message_id":\s*(\d+)', r.get_data(as_text=True)))
# Search db directly for the newest message
from app.models.message import Message
with app.app_context():
    latest = Message.query.order_by(Message.id.desc()).first()
    if latest:
        print('latest message id=', latest.id, 'attachments=', len(latest.attachments))
        if latest.attachments:
            aid = latest.attachments[0].id
            dl = client.get(f'/messages/attachment/{aid}/download')
            print('attachment download ->', dl.status_code, 'ctype=', dl.headers.get('Content-Type'))
        # recipients snapshot
        tv = client.get(f'/messages/thread/{latest.thread_root_id()}')
        print('thread view ->', tv.status_code, 'has-sent-to=', 'Sent to' in tv.data.decode('utf-8', errors='replace'))

print('\nDONE')