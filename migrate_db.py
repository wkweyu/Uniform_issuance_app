import pymysql

def migrate_db():
    connection = pymysql.connect(
        host='xc4m60.h.filess.io',
        user='schoolmngt_ladydotdog',
        password='7b49a61787b9469706bff65533530653ed114b06',
        database='schoolmngt_ladydotdog',
        port=61030,
        autocommit=True
    )

    with connection.cursor() as cursor:
        with open('schema.sql', 'r') as f:
            sql_script = f.read()

        # Split by semicolon and run each statement
        for statement in sql_script.split(';'):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)
    connection.close()
    print("✔️ Database tables migrated successfully.")

if __name__ == "__main__":
    migrate_db()
