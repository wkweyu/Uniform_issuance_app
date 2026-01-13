# Manage Prices Form Fix - Summary

## Problem Identified

Your form wasn't working due to three interconnected issues:

### 1. **Missing `action` Field**
- **Issue**: The Flask route `/admin/manage_uniform_prices` was looking for `action='update_prices'` in `request.form`
- **Your Code**: The form had no hidden input to specify the action
- **Result**: The POST handler didn't know what operation to perform

### 2. **Input Names with Spaces**
- **Issue**: Input field names like `price_School Shirt_Grade 1-3` contain spaces and special characters
- **Problem**: While spaces are technically allowed in form field names, they cause parsing ambiguity. When you have multiple items/groups with underscores as separators, spaces make it impossible to reliably parse which item and group a price belongs to
- **Example**: Is `price_School Shirt_Grade 1-3` parsed as:
  - Item: "School" + Group: "Shirt_Grade 1-3"? 
  - Item: "School Shirt" + Group: "Grade 1-3"?
  - Something else?

### 3. **Flask Route Parsing Logic**
- **Issue**: The Flask route was trying to parse the item/group names directly from the field names, which doesn't work reliably with spaces

## Solutions Implemented

### Fix 1: Added Hidden Action Field ✅
**File**: [templates/manage_prices.html](templates/manage_prices.html#L113)

```html
<form id="priceForm" method="POST" action="/admin/manage_uniform_prices">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <input type="hidden" name="action" value="update_prices">  <!-- ADDED THIS -->
  <div class="bg-white rounded-lg shadow overflow-hidden">
```

Now the Flask route knows to execute the `update_prices` action.

### Fix 2: Changed Input Names to Use Index Numbers ✅
**File**: [templates/manage_prices.html](templates/manage_prices.html#L130-L145)

**Before:**
```html
name="price_{{ item }}_{{ group }}"   <!-- Contains spaces! -->
```

**After:**
```html
{% set item_idx = loop.index0 %}
<!-- ... -->
name="price_{{ item_idx }}_{{ loop.index0 }}"  <!-- Index-based, no spaces -->
data-item="{{ item }}"
data-group="{{ group }}"
```

Now field names are guaranteed to be safe: `price_0_0`, `price_0_1`, `price_1_0`, etc.

### Fix 3: Updated Flask Route to Parse Indexed Names ✅
**File**: [app.py](app.py#L611-L629)

**Before:**
```python
for item in uniform_items:
    for group in class_groups:
        price_key = f'price_{item}_{group}'  # Unreliable parsing
        price = request.form.get(price_key)
```

**After:**
```python
for item_idx, item in enumerate(uniform_items):
    for group_idx, group in enumerate(class_groups):
        price_key = f'price_{item_idx}_{group_idx}'  # Use indices
        price = request.form.get(price_key)
        
        if price is not None and price.strip():
            price_value = Decimal(price.strip().replace(',', ''))
            cursor.execute("""
                INSERT INTO uniform_prices (item_name, class_group, price)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE price = VALUES(price)
            """, (item, group, price_value))
```

The route now correctly maps indexed field names back to actual items and groups.

## How the Fix Works

1. **User edits prices** in the form (e.g., enters $50.00 for "School Shirt" in "Grade 1-3")
2. **User clicks "Save Prices"** button
3. **Form submits** with:
   - `action=update_prices`
   - `price_0_1=50.00` (item index 0 = "School Shirt", group index 1 = "Grade 1-3")
4. **Flask route receives** the POST request and finds `action='update_prices'`
5. **Route iterates** through all items/groups by index
6. **Route looks up** `request.form.get('price_0_1')` → finds "50.00"
7. **Route executes** SQL to insert/update the price in `uniform_prices` table
8. **Success message** flashes: "1 price(s) updated successfully"
9. **Page reloads** with updated prices

## Testing

To verify the fix works:

1. Go to **Admin Settings** → **Manage Uniform Prices**
2. Edit any price field (e.g., change $0.00 to $50.00)
3. Click **"Save Prices"** button
4. You should see: **"1 price(s) updated successfully"** message
5. Refresh the page → price persists ✅

## Technical Details

### Form Structure
- **Method**: POST
- **Action**: `/admin/manage_uniform_prices`
- **Hidden Fields**: `csrf_token`, `action`
- **Input Names**: `price_{item_idx}_{group_idx}` where indices are 0-based

### Database Impact
- **Table**: `uniform_prices`
- **Columns**: `item_name`, `class_group`, `price`
- **SQL**: Uses `ON DUPLICATE KEY UPDATE` for insert-or-update

### Security
- CSRF protection via `csrf_token` field ✅
- Admin check: `if not session.get('is_admin')` ✅
- SQL injection prevention via parameterized queries ✅

## Files Modified

1. **[templates/manage_prices.html](templates/manage_prices.html)**
   - Added hidden action field
   - Changed input names from item/group names to indices
   - Added data attributes for reference

2. **[app.py](app.py#L611-L629)**
   - Updated POST handler to use indexed field names
   - Added proper error handling with `connection.rollback()`
   - Maintained Decimal precision for prices

---

**Note**: The fixes maintain backward compatibility with the database schema and don't require any SQL migrations.
