from core.permissions import login_required, admin_required, super_admin_required
from werkzeug.security import check_password_hash
import hashlib

def verify_legacy_password(input_password, stored_password, user_id=None):
    if not stored_password:
        return False
    try:
        if check_password_hash(stored_password, input_password):
            return True
    except ValueError:
        pass
    md5_hash = hashlib.md5(input_password.encode()).hexdigest()
    if stored_password == md5_hash:
        return True
    if stored_password == input_password:
        return True
    return False
