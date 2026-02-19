import pymysql
import os
import config

def apply_fix():
    print("🚀 Connecting to SkySQL to apply multi-tenant schema fix...")
    
    # Enable SSL for SkySQL
    ssl_config = None
    ca_path = 'globalsignrootca.pem'
    if os.path.exists(ca_path):
        # Full path for better reliability
        abs_ca_path = os.path.abspath(ca_path)
        ssl_config = {'ca': abs_ca_path, 'check_hostname': False}
        print(f"DEBUG: Using SSL cert at {abs_ca_path}")
    else:
        ssl_config = True
        print("DEBUG: SSL cert not found, using permissive mode.")

    try:
        DB_HOST = os.environ.get('DB_HOST', getattr(config, 'DB_HOST', 'localhost'))
        DB_PORT = int(os.environ.get('DB_PORT', getattr(config, 'DB_PORT', 3306)))
        DB_USER = os.environ.get('DB_USER', getattr(config, 'DB_USER', 'root'))
        DB_PASSWORD = os.environ.get('DB_PASSWORD') or os.environ.get('DB_PASS', getattr(config, 'DB_PASSWORD', ''))
        DB_NAME = os.environ.get('DB_NAME', getattr(config, 'DB_NAME', 'schoolmngt'))

        connection = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            ssl=ssl_config,
            autocommit=True
        )
        print("✅ Connected successfully.")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return

    with connection.cursor() as cursor:
        print("🛠️ Applying schema changes...")
        
        # List of statements to execute
        statements = [
            # 1. Buses
            "ALTER TABLE `buses` ADD COLUMN IF NOT EXISTS `active` TINYINT(1) DEFAULT 1",
            "ALTER TABLE `buses` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `buses` ADD KEY IF NOT EXISTS `idx_buses_school_id` (`school_id`)",
            
            # 2. Fuel Vouchers
            "ALTER TABLE `fuel_vouchers` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `fuel_vouchers` ADD KEY IF NOT EXISTS `idx_fuel_vouchers_school_id` (`school_id`)",
            
            # 3. Fuel Invoices
            "ALTER TABLE `fuel_invoices` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `fuel_invoices` ADD KEY IF NOT EXISTS `idx_fuel_invoices_school_id` (`school_id`)",
            
            # 4. Service Records
            "ALTER TABLE `service_records` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `service_records` ADD KEY IF NOT EXISTS `idx_service_records_school_id` (`school_id`)",
            
            # 5. Oil Records
            "ALTER TABLE `oil_records` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `oil_records` ADD KEY IF NOT EXISTS `idx_oil_records_school_id` (`school_id`)",
            
            # 6. Item Stock
            "ALTER TABLE `item_stock` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `item_stock` ADD KEY IF NOT EXISTS `idx_item_stock_school_id` (`school_id`)",
            
            # 7. Stock Movements
            "ALTER TABLE `stock_movements` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `stock_movements` ADD KEY IF NOT EXISTS `idx_stock_movements_school_id` (`school_id`)",
            
            # 8. Uniform Receipts
            "ALTER TABLE `uniform_receipts` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `uniform_receipts` ADD KEY IF NOT EXISTS `idx_uniform_receipts_school_id` (`school_id`)",
            
            # 9. Uniform Prices
            "ALTER TABLE `uniform_prices` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `uniform_prices` ADD KEY IF NOT EXISTS `idx_uniform_prices_school_id` (`school_id`)",
            
            # 10. Academic Years
            "ALTER TABLE `academic_years` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `academic_years` ADD KEY IF NOT EXISTS `idx_academic_years_school_id` (`school_id`)",

            # 11. Fees Tables (if they exist)
            "ALTER TABLE `fee_ledger` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1",
            "ALTER TABLE `fodebit` ADD COLUMN IF NOT EXISTS `school_id` INT(11) NOT NULL DEFAULT 1"
        ]

        for sql in statements:
            try:
                cursor.execute(sql)
                print(f"✔️ Executed: {sql[:50]}...")
            except Exception as e:
                # 1060 is "Duplicate column name", 1061 is "Duplicate key name"
                if "(1060," in str(e) or "(1061," in str(e):
                    print(f"ℹ️ Skipping: {sql[:50]}... (Already exists)")
                else:
                    print(f"⚠️ Error executing {sql}: {e}")

    connection.close()
    print("🎉 All missing school_id columns have been added!")

if __name__ == "__main__":
    apply_fix()
