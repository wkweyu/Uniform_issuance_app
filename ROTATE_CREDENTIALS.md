# Rotate Database Credentials

This document outlines recommended steps to rotate database credentials after secrets were exposed in the repo history.

1. Generate a new strong password for the DB user (or create a new user):

```bash
# Example: create a new password
NEW_PWD=$(openssl rand -base64 24)
echo "$NEW_PWD"
```

2. Update the DB user password on the database server (example for MySQL):

```sql
-- Connect as a privileged DB user (root or admin)
-- Option A: change password for existing user
ALTER USER 'u80655_schoolmngt'@'%' IDENTIFIED BY 'NEWPASSWORD';

-- Option B: create a new user (recommended) and grant privileges
CREATE USER 'u80655_schoolmngt_v2'@'%' IDENTIFIED BY 'NEWPASSWORD';
GRANT ALL PRIVILEGES ON `u80655_schoolmngt`.* TO 'u80655_schoolmngt_v2'@'%';
FLUSH PRIVILEGES;
```

3. Update runtime configuration (preferred order):
- Update runtime environment variables in your production environment or secrets manager.
- Update `.env` locally (do NOT commit `.env`).

4. Deploy the change and verify the application connects using the new credentials.

5. Revoke or remove the old credentials:

```sql
-- If you created a new user, drop the old user after verification
DROP USER 'u80655_schoolmngt'@'%';
```

6. Clean repository history (optional but recommended if secrets were committed):
- Use `git filter-repo` or BFG to remove the secret from history. This is a destructive operation for the repo history and requires force-pushing and coordinating with collaborators.

Example (BFG):
```bash
# Install BFG (Java required)
bfg --delete-files .env
# or to replace the secret string
bfg --replace-text replacements.txt
# After using BFG or filter-repo, run:
git reflog expire --expire=now --all && git gc --prune=now --aggressive
# Then force-push to origin
git push --force
```

7. Rotate any other systems that might have used the leaked credentials (CI, backups, monitoring).

If you want, I can:
- Draft the exact SQL commands for your DB host (if you tell me whether you have root access or a managed DB provider),
- Help run the `git filter-repo` commands safely and create a migration/coordination plan.
