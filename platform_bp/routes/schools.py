from flask import render_template, request, redirect, url_for, flash
from ..decorators import platform_required


def index():
    return render_template('platform/index.html')


@platform_required(role='platform_admin')
def list_schools():
    from app import School
    schools = School.query.order_by(School.name).all()
    return render_template('platform/schools_list.html', schools=schools)


@platform_required(role='platform_admin')
def create_school():
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        tz = request.form.get('timezone')
        from app import db, School
        school = School(name=name, code=code, timezone=tz)
        db.session.add(school)
        db.session.commit()
        flash('School created', 'success')
        return redirect(url_for('platform.list_schools'))
    return render_template('platform/schools_create.html')


def register_routes(bp):
    bp.add_url_rule('/', endpoint='index', view_func=index)
    bp.add_url_rule('/schools', endpoint='list_schools', view_func=list_schools)
    bp.add_url_rule('/schools/create', endpoint='create_school', view_func=create_school, methods=['GET', 'POST'])
