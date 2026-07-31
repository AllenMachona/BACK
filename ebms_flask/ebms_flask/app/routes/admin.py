from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.user import User
from app.models.role import Role
from app.utils.decorators import permission_required
from app.utils.audit import log_action

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/users')
@login_required
@permission_required('can_admin_system')
def users():
    all_users = User.query.order_by(User.last_name).all()
    roles = Role.query.all()

    role_distribution = []
    for role in roles:
        count = User.query.filter_by(role_id=role.id).count()
        if count:
            role_distribution.append((role.name, count))

    mfa_enabled = User.query.filter_by(mfa_enabled=True).count()
    mfa_disabled = User.query.filter_by(mfa_enabled=False).count()
    locked = User.query.filter(User.locked_until.isnot(None), User.locked_until > datetime.utcnow()).count()

    return render_template(
        'admin_users.html', users=all_users, roles=roles,
        role_distribution=role_distribution, mfa_enabled=mfa_enabled,
        mfa_disabled=mfa_disabled, locked=locked,
    )


@admin_bp.route('/users/create', methods=['POST'])
@login_required
@permission_required('can_admin_system')
def create_user():
    role = Role.query.get(request.form.get('role_id', type=int))
    if not role:
        flash('Select a valid role.', 'danger')
        return redirect(url_for('admin.users'))

    user = User(
        username=request.form['username'],
        email=request.form['email'],
        first_name=request.form['first_name'],
        last_name=request.form['last_name'],
        department=request.form.get('department'),
        designation=request.form.get('designation'),
        role_id=role.id,
        created_by=current_user.id,
    )
    user.set_password(request.form['password'])
    db.session.add(user)
    db.session.commit()

    log_action('USER_CREATED', entity_type='User', entity_id=user.id, new_value={'username': user.username, 'role': role.code})
    flash(f'User {user.username} created.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@permission_required('can_admin_system')
def toggle_active(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    log_action('USER_ACTIVE_TOGGLED', entity_type='User', entity_id=user.id, new_value={'is_active': user.is_active})
    flash(f'{user.username} is now {"active" if user.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin.users'))
