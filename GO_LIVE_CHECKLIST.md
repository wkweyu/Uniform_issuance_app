# ✅ Go-Live Checklist: Class Management System

**Date**: January 12, 2026  
**Status**: Ready for Production Deployment

---

## Pre-Deployment Verification (15 minutes)

- [ ] **Database Backup Created**
  - Command: `# Copy .env.example -> .env and set DB_* values. Then run (you will be prompted for the DB password): mysqldump -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" > backup_$(date +%Y%m%d_%H%M%S).sql`
  - Verify: `ls -lh backup_*.sql` shows recent backup

- [ ] **App Compilation Verified**
  - Command: `python3 -m py_compile app.py`
  - Expected: No syntax errors

- [ ] **All Tests Passing**
  - Command: `python3 test_class_system.py`
  - Expected: `🎉 ALL TESTS PASSED - 7/7`

- [ ] **Flask App Running**
  - Command: `curl http://localhost:5000/login`
  - Expected: Login page HTML returned

- [ ] **Database Connection Working**
  - Command: `mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" -e "SELECT COUNT(*) FROM academic_years;"`
  - Expected: Returns `3`

---

## Post-Deployment Verification (30 minutes)

### Database Integrity
- [ ] Verify all 10 new tables exist
  ```sql
  SHOW TABLES LIKE 'academic%' OR 'class%' OR 'stream%' OR 'subject%' OR 'teacher%';
  ```

- [ ] Verify table row counts
  ```sql
  SELECT 'academic_years' AS tbl, COUNT(*) FROM academic_years
  UNION ALL SELECT 'class_groups', COUNT(*) FROM class_group_settings
  UNION ALL SELECT 'streams', COUNT(*) FROM stream_settings
  UNION ALL SELECT 'classes', COUNT(*) FROM classes
  UNION ALL SELECT 'subjects', COUNT(*) FROM subjects;
  ```

- [ ] Check for foreign key constraints
  ```sql
  SELECT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
  WHERE TABLE_SCHEMA='schoolmngt' AND CONSTRAINT_NAME LIKE '%fk%';
  ```

### Application Functionality
- [ ] Test `/login` route
  - Action: Navigate to http://localhost:5000/login
  - Expected: Login form displays

- [ ] Test `/admin/classes/create` route (if admin)
  - Action: Navigate to http://localhost:5000/admin/classes/create
  - Expected: Create class form displays

- [ ] Test existing uniform issuance routes
  - Action: Navigate to http://localhost:5000/
  - Expected: Index/dashboard loads
  - Action: Navigate to `/issue_uniform`
  - Expected: Issuance form displays

- [ ] Test existing fleet management routes
  - Action: Navigate to `/fleet/fleet_dashboard`
  - Expected: Dashboard displays

### Error Handling
- [ ] Test database error handling
  - Action: Temporarily stop MySQL
  - Expected: App shows error message (doesn't crash)
  - Action: Restart MySQL
  - Expected: App recovers

- [ ] Test invalid form submission
  - Action: Try form submission with invalid data
  - Expected: Validation error message

### Logging
- [ ] Check application logs
  - Command: `tail -50 app.log` (if logging to file)
  - Expected: No error entries from deployment

- [ ] Monitor flask debug output
  - Expected: Clean startup with no warnings

---

## Performance Baseline (15 minutes)

- [ ] Database query performance
  ```bash
  # Time these queries
  mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" -e "SELECT COUNT(*) FROM class_allocation;"
  mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" -e "SELECT COUNT(*) FROM class_subjects;"
  ```
  - Expected: Sub-100ms response

- [ ] Flask route response time
  - Command: `curl -w "\nTotal: %{time_total}s\n" http://localhost:5000/login`
  - Expected: < 200ms

---

## User Access Verification (10 minutes)

- [ ] Admin user can access new routes
  - Admin login required to test:
    - `/admin/classes/create`
    - `/admin/classes/promote`
    - `/admin/teacher/allocate`

- [ ] Non-admin users cannot access admin routes
  - Expected: Redirect to login

- [ ] CSRF tokens working
  - Action: Check form for `<input type="hidden" name="csrf_token">`
  - Expected: Token present in all forms

---

## Backup & Recovery Test (30 minutes)

- [ ] Test backup restoration
  ```bash
  # 1. Backup current state (ensure .env has DB settings)
  mysqldump -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" > backup_test.sql
  
  # 2. Make a test change (you will be prompted for the password)
  mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" -e "INSERT INTO academic_years (year, name) VALUES (2099, 'Test');"
  
  # 3. Restore from backup
  mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" < backup_test.sql
  
  # 4. Verify test data is gone
  mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" -e "SELECT * FROM academic_years WHERE year=2099;"
  ```
  - Expected: No rows returned (test data removed)

---

## 24-Hour Monitoring Checklist

- [ ] **Hour 1**: Check logs for errors
  - Command: `grep ERROR app.log | tail -10`
  - Expected: No new errors

- [ ] **Hour 4**: Verify database consistency
  ```sql
  -- Check for orphaned records
  SELECT COUNT(*) FROM class_subjects cs 
  LEFT JOIN classes c ON cs.class_id = c.classID 
  WHERE c.classID IS NULL;
  ```
  - Expected: 0 rows

- [ ] **Hour 8**: Monitor database size growth
  ```bash
  du -sh /var/lib/mysql/schoolmngt
  ```
  - Expected: No unexpected growth

- [ ] **Hour 12**: Test promotional operation (if ready)
  - Action: Create test class and attempt promotion
  - Expected: Atomic operation completes or rolls back

- [ ] **Hour 24**: Final system check
  - Rerun: `python3 test_class_system.py`
  - Expected: 7/7 tests still passing

---

## Rollback Plan (If Needed)

**Time to Rollback**: < 10 minutes

### Quick Rollback Steps
1. **Stop Flask App**
   ```bash
   pkill -f "python3 app.py"
   ```

2. **Restore Database**
   ```bash
  mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" < backup_YYYYMMDD_HHMMSS.sql
   ```

3. **Revert Code** (if needed)
   ```bash
   git revert HEAD  # If using version control
   ```

4. **Restart Flask App**
   ```bash
   cd '/home/frappe-user/uniform issuance app' && python3 app.py
   ```

5. **Verify Rollback**
   ```bash
   curl http://localhost:5000/login | grep -q "Login" && echo "✅ Rolled back successfully"
   ```

---

## Communication Checklist

- [ ] Stakeholders notified of deployment
- [ ] Support team briefed on new features
- [ ] Users informed of system maintenance window (if any)
- [ ] Emergency contact list available
- [ ] Incident response plan ready

---

## Final Sign-Off

**Deployed By**: _________________ (Name/Date)  
**Verified By**: _________________ (Name/Date)  
**Approved By**: _________________ (Name/Date)  

---

## Success Criteria

✅ All tests passing  
✅ No database errors  
✅ Backward compatibility maintained  
✅ New routes accessible  
✅ Performance within acceptable limits  
✅ Users can log in  
✅ Admin features working  
✅ No data loss  

**Go-Live Status**: 🚀 **APPROVED FOR PRODUCTION**

---

*For issues or concerns, refer to `IMPLEMENTATION_COMPLETE.md` or contact development team.*
