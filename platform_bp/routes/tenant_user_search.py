from flask import render_template, request

from ..decorators import platform_required
from ..services.tenant_users import search_tenant_users


@platform_required(permission='tenant_search')
def tenant_user_search():
    q = request.args.get('q', '').strip()
    results = search_tenant_users(q)
    return render_template('platform/tenant_user_search.html', q=q, results=results)


def register_routes(bp):
    bp.add_url_rule('/tenant-users/search', endpoint='tenant_user_search', view_func=tenant_user_search, methods=['GET'])
