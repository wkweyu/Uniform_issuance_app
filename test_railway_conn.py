import pymysql

try:
    conn = pymysql.connect(
        host='serverless-eu-west-3.sysp0000.db1.skysql.com',
        port=4018,
        user='dbpwf28831395',
        password='4FjBYp4aP0p3g{cx5?GCHbs',
        database='schoolmngt'
    )
    print("Connection Successful to SkySQL!")
    conn.close()
except Exception as e:
    print(f"Connection Failed: {e}")
