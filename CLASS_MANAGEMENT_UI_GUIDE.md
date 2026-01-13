# Class Management UI - Quick Reference Guide

## 🎯 Getting Started (2 minutes)

### For Administrators

1. **Login** to SkoolTrack Pro
2. Look for **"Classes"** link in top navigation bar (desktop) or hamburger menu (mobile)
3. Click **"Classes"** → Opens Class Management Dashboard

---

## 📊 Dashboard Overview

### Class Management Dashboard (`/admin/manage_classes`)

**Quick Stats** (at top):
- 📅 Academic Years - How many years configured
- 🏫 Total Classes - All classes in system
- 👥 Total Students - Currently enrolled students
- 📖 Subjects - Available subjects

**6 Main Features**:

| # | Feature | Icon | Action |
|---|---------|------|--------|
| 1 | ➕ Create New Class | Plus Circle | Add a new class to system |
| 2 | 🚀 Promote Students | Arrow Up | Move students to next grade |
| 3 | 📚 Class Subjects | Book | Select subjects for classes |
| 4 | 👨‍🏫 Teacher Allocation | Chalkboard User | Assign teachers to subjects |
| 5 | 👤 Student Enrollment | User Check | Enroll students in subjects |
| 6 | 📊 Reports | Chart Bar | View analytics & reports |

**Workflow Guide** (5-step process shown at bottom):
1. Create Classes
2. Allocate Subjects to Classes
3. Assign Teachers
4. Enroll Students
5. Promote Students (year-end)

---

## 🔄 Typical User Workflows

### Workflow A: New School Year Setup

```
1. Dashboard → Click "Create New Class"
   ├─ Select Academic Year (e.g., 2025)
   ├─ Select Class Group (e.g., Grade 1-3)
   ├─ Select Stream (e.g., A)
   └─ Submit → Class created ✅

2. For each class, click "Manage Class Subjects"
   ├─ Select subjects to offer
   ├─ Mark compulsory vs optional
   └─ Submit → Subjects assigned ✅

3. For each class-subject, click "Allocate Teacher"
   ├─ Enter teacher ID
   ├─ Select class & subject
   └─ Submit → Teacher assigned ✅

4. For each student, click "Enroll Student"
   ├─ Enter student ID
   ├─ Verify class assignment
   ├─ Select their subjects
   └─ Submit → Enrolled ✅

5. System ready for teaching!
```

### Workflow B: Year-End Promotions

```
1. At year end, Dashboard → Click "Promote Students"

2. Select source class (e.g., Grade 1 Stream A 2025)

3. Select destination class (e.g., Grade 2 Stream A 2026)

4. Review student count in confirmation modal

5. Click "Confirm Promotion"

6. ✅ All students promoted atomically with:
   - Automatic history preservation
   - Full audit trail logged
   - New class allocations created
```

### Workflow C: Mid-Year Changes

```
1. Student moved to different stream?
   Dashboard → "Manage Class Subjects"
   (To update what subjects are offered)

2. Teacher changed for a subject?
   Dashboard → "Teacher Allocation"
   (To reassign teacher)

3. Student elects different subject?
   Dashboard → "Student Enrollment"
   (To update student's subject selection)
```

---

## 🧭 Navigation Map

```
Dashboard
│
├─ Classes (admin only)
│  ├─ ➕ Create Class
│  │  ├─ Select Year
│  │  ├─ Select Class Group
│  │  ├─ Select Stream
│  │  └─ Submit
│  │
│  ├─ 🚀 Promote Students
│  │  ├─ Select source class
│  │  ├─ Select destination class
│  │  ├─ Review count
│  │  └─ Confirm
│  │
│  ├─ 📚 Manage Subjects
│  │  ├─ Select class
│  │  ├─ Choose subjects
│  │  ├─ Mark compulsory
│  │  └─ Submit
│  │
│  ├─ 👨‍🏫 Allocate Teacher
│  │  ├─ Enter teacher ID
│  │  ├─ Select class
│  │  ├─ Select subject
│  │  └─ Submit
│  │
│  ├─ 👤 Enroll Student
│  │  ├─ Enter student ID
│  │  ├─ Verify class
│  │  ├─ Select subjects
│  │  └─ Submit
│  │
│  └─ 📊 Reports
│     ├─ Class Allocations
│     ├─ Student Subjects
│     ├─ Promotion History
│     └─ Statistics
```

---

## 🎨 Color Guide (What Each Color Means)

| Color | Meaning | Example |
|-------|---------|---------|
| 🔵 Blue | Neutral/Info actions | Create, Dashboard |
| 🟢 Green | Success/Promotion | Promote Students |
| 🟣 Purple | Academic/Subjects | Class Subjects |
| 🟠 Orange | Personnel/Teachers | Teacher Allocation |
| 🟦 Teal | Student-related | Student Enrollment |
| 🟦 Indigo | Analytics | Reports |

---

## 📱 Mobile vs Desktop

### Desktop View
- **Navigation**: Horizontal menu bar at top
- **Grid**: 3 columns for feature cards (on large screens)
- **Text**: Full menu labels visible

### Mobile View
- **Navigation**: Hamburger menu (☰) at top-right
- **Grid**: 1 column (full width)
- **Touch-friendly**: Larger tap targets, spacing

**How to access Classes on mobile**:
1. Tap hamburger menu (☰)
2. Scroll to find "Classes"
3. Tap "Classes" → Opens dashboard
4. Tap desired feature

---

## ✅ Form Checklist

Every form in the class management system includes:

- ✅ **Breadcrumbs** at top (Dashboard / Classes / Feature)
- ✅ **Title** explaining what you're doing
- ✅ **Required fields** marked with *
- ✅ **Help text** explaining field purposes
- ✅ **CSRF token** for security
- ✅ **Submit button** at bottom
- ✅ **Cancel button** to go back
- ✅ **Error messages** if something fails
- ✅ **Success messages** after submission

---

## 🔒 Security Features

All class management features are protected by:

1. **Login Required**: Must be logged in to access
2. **Admin Only**: Must have admin privileges
3. **CSRF Protection**: Forms are CSRF-token protected
4. **Session Security**: 8-hour session timeout
5. **Audit Logging**: All changes are logged to database

---

## 🐛 Troubleshooting

### "I don't see Classes in the menu"
- ✅ Make sure you're an admin user
- ✅ Refresh the page (Ctrl+R or Cmd+R)
- ✅ Check desktop menu if on mobile, or vice versa

### "Classes menu is gray/disabled"
- This shouldn't happen - it means there's an error
- Contact support with a screenshot

### "A form won't submit"
- Check for required fields (marked with *)
- Make sure all dropdowns have selections
- Check browser console for errors (F12)
- Try refreshing and re-entering data

### "Class creation says 'already exists'"
- That class name is already in the system
- Try a different class name
- Or check the existing classes list

### "Teacher allocation won't work"
- Verify teacher ID exists
- Verify class and subject exist
- Try using teacher's full ID from HR system

---

## ⏱️ Typical Time Estimates

| Task | Time | Notes |
|------|------|-------|
| Create 1 class | 2 min | Select year, group, stream |
| Add subjects to class | 5 min | Select from list of 63 |
| Allocate 1 teacher | 2 min | Simple form |
| Enroll 1 student | 2 min | Quick form |
| Promote all students | 1 min | One click after selection |
| Setup complete new year | 4 hours | For school of ~600 students |

---

## 💡 Tips & Tricks

### Pro Tips

1. **Use Tab key** to quickly navigate between form fields
2. **Breadcrumbs are clickable** - Go back to Classes anytime
3. **Confirmation modals** - Review before big changes like promotions
4. **Stats update live** - Dashboard refreshes with latest numbers
5. **Search is keyboard shortcut** - Ctrl+F on any page

### Common Gotchas

- Classes must have unique year+group+stream combinations
- One teacher per class-subject combo (enforced)
- Student subjects must be subset of class subjects
- Promotions are atomic (all-or-nothing)
- Academic years must exist before creating classes

---

## 📞 Need Help?

### Frequently Asked Questions

**Q: Can I promote students mid-year?**
A: You can change which classes they're in via "Manage Subjects" or re-enroll them. Promotion feature is typically for end-of-year.

**Q: What if I make a mistake during promotion?**
A: Promotions are logged. Contact admin to review the promotion log and make corrections if needed.

**Q: Can I have multiple classes with same name?**
A: Only if they have different streams (A/B/C/D) or different years.

**Q: What happens to student history after promotion?**
A: All history is preserved. The `promoted_from_id` field tracks the link.

**Q: Can students take subjects not offered by their class?**
A: No, student subjects must be subset of class subjects (enforced in system).

---

## 🎓 System Constraints

- **Max subjects per class**: 63 available (all offered by school)
- **Max students per class**: No limit (depends on capacity setting)
- **Teachers per combo**: Exactly 1 (one-to-one enforcement)
- **Academic years**: Can create as many as needed
- **Streams**: Configurable (typically A, B, C, D)
- **Class groups**: Playgroup-PP2, Grade 1-3, Grade 4-6, Grade 7-9

---

## 📊 Example Scenario

### Small Primary School Example

**Setup** (happens once per year):

```
1. Create classes:
   - Grade 1 Stream A (2025)
   - Grade 1 Stream B (2025)
   - Grade 2 Stream A (2025)
   - Grade 2 Stream B (2025)
   Total: 4 classes

2. Allocate subjects (same to all):
   - English, Math, Science, Social Studies, PE, Arts
   Total: 6 subjects per class

3. Allocate teachers:
   - Grade 1A: Mrs. Smith (English), Mr. Jones (Math), etc.
   Total: 6 teachers per class

4. Enroll students (happens as they register)
   - Student 001 → Grade 1A → All 6 subjects
   - Student 002 → Grade 1A → All 6 subjects
   Total: ~25 students per class
```

**Year-End**:

```
5. Promote students:
   - All Grade 1A students → Grade 2A (2026)
   - All Grade 1B students → Grade 2B (2026)
   
   This is ONE atomic operation - no need to manually move each student!
```

---

## 🚀 Go-Live Checklist

Before going live with class management:

- [ ] All classes created for current year
- [ ] All subjects allocated to each class
- [ ] All teachers assigned to class-subject combos
- [ ] Test accounts exist for admins
- [ ] Database backup created
- [ ] Test suite passing (7/7)
- [ ] All forms tested with real data
- [ ] Team trained on workflows
- [ ] Documentation shared with staff
- [ ] Go-live announcement made

---

## 📖 Related Documents

- **Full Implementation**: See `IMPLEMENTATION_COMPLETE.md`
- **Deployment Checklist**: See `GO_LIVE_CHECKLIST.md`
- **Database Schema**: See `SCHEMA_DESIGN.md`
- **API Integration**: See `FLASK_INTEGRATION_GUIDE.md`
- **Architecture**: See `.github/copilot-instructions.md`

---

**Last Updated**: January 13, 2026  
**Status**: ✅ Production Ready
