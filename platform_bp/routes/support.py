from flask import render_template, request, redirect, url_for, flash
from ..decorators import platform_required


@platform_required(role='support')
def list_tickets():
    from ..models import SupportTicket
    tickets = SupportTicket.query.order_by(SupportTicket.created_at.desc()).all()
    return render_template('platform/support_list.html', tickets=tickets)


def create_ticket():
    if request.method == 'POST':
        school_id = request.form.get('school_id')
        email = request.form.get('email')
        subject = request.form.get('subject')
        description = request.form.get('description')
        from app import db
        from ..models import SupportTicket
        ticket = SupportTicket(school_id=school_id, raised_by_email=email, subject=subject, description=description)
        db.session.add(ticket)
        db.session.commit()
        flash('Ticket created', 'success')
        return redirect(url_for('platform.list_tickets'))
    return render_template('platform/support_create.html')


def register_routes(bp):
    bp.add_url_rule('/support', endpoint='list_tickets', view_func=list_tickets)
    bp.add_url_rule('/support/create', endpoint='create_ticket', view_func=create_ticket, methods=['GET', 'POST'])
