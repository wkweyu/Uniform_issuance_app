import pymysql

try:
    # Enable SSL for SkySQL
    ssl_config = None
    ca_path = 'globalsignrootca.pem'
    if os.path.exists(ca_path):
        ssl_config = {'ca': ca_path}
    else:
        ssl_config = True

    conn = pymysql.connect(
        host='serverless-eu-west-3.sysp0000.db1.skysql.com',
        port=4018,
        user='dbpwf28831395',
        password='4FjBYp4aP0p3g{cx5?GCHbs',
        database='schoolmngt',
        ssl=ssl_config
    )
    print("Connection Successful to SkySQL!")
    conn.close()
except Exception as e:
    print(f"Connection Failed: {e}")
