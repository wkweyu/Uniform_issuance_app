import pymysql

try:
    conn = pymysql.connect(
        host='xc4m60.h.filess.io',
        port=61030,
        user='schoolmngt_ladydotdog',
        password='7b49a61787b9469706bff65533530653ed114b06',
        database='schoolmngt_ladydotdog'
    )
    print("Connection Successful to filess.io!")
    conn.close()
except Exception as e:
    print(f"Connection Failed: {e}")
