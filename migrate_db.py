import pymysql
import os

def migrate_db():
    # Enable SSL for SkySQL
    ssl_config = None
    ca_path = 'globalsignrootca.pem'
    if os.path.exists(ca_path):
        ssl_config = {'ca': ca_path}
    else:
        ssl_config = True

    connection = pymysql.connect(
        host='serverless-eu-west-3.sysp0000.db1.skysql.com',
        user='dbpwf28831395',
        password='4FjBYp4aP0p3g{cx5?GCHbs',
        database='schoolmngt',
        port=4018,
        ssl=ssl_config,
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
