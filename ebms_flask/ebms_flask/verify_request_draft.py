from io import BytesIO
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.role import Role
from app.models.request import FormDERequest

app = create_app()
app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False

with app.app_context():
    role = Role.query.filter_by(code='requester').first() or Role(code='requester', name='Requester')
    db.session.add(role)
    db.session.commit()

    user = User.query.filter_by(username='draft_requester_test').first()
    if not user:
        user = User(username='draft_requester_test', email='draft_req_test@example.com', first_name='Draft', last_name='Tester', role_id=role.id, department='Ministry of Health', is_active=True)
        user.set_password('Secret123!')
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    login = client.post('/login', data={'username': 'draft_requester_test', 'password': 'Secret123!'}, follow_redirects=True)
    print('login_status', login.status_code)

    draft = client.post('/requests/new', data={'department': 'Ministry of Health', 'justification': 'Draft test justification', 'action': 'save_draft'}, follow_redirects=True)
    print('save_draft_status', draft.status_code)
    print('save_draft_has_success', 'Draft saved successfully' in draft.get_data(as_text=True).replace('\n', ' '))

    my_requests = client.get('/requests/my')
    print('my_requests_status', my_requests.status_code)
    print('my_requests_has_draft', 'Draft' in my_requests.get_data(as_text=True))

    req = FormDERequest.query.filter_by(requester_id=user.id).order_by(FormDERequest.id.desc()).first()
    print('latest_request_status', req.status if req else None)
    print('latest_request_id', req.id if req else None)

    if req:
        edit_page = client.get(f'/requests/de/{req.id}/edit')
        print('edit_page_status', edit_page.status_code)
        print('edit_page_has_draft', 'Save as Draft' in edit_page.get_data(as_text=True))

        response = client.post('/requests/new', data={
            'request_id': req.id,
            'department': 'Ministry of Health',
            'justification': 'Updated draft before submission',
            'action': 'submit',
            'form_d_document': (BytesIO(b'%PDF-1.4 signed form d'), 'form_d.pdf'),
            'form_e_document': (BytesIO(b'%PDF-1.4 signed form e'), 'form_e.pdf'),
        }, content_type='multipart/form-data', follow_redirects=True)
        print('submit_after_edit_status', response.status_code)
        print('submit_after_edit_has_success', 'Request submitted to Procurement' in response.get_data(as_text=True).replace('\n', ' '))
        req2 = FormDERequest.query.get(req.id)
        print('updated_status', req2.status)
        print('updated_justification', req2.justification)
