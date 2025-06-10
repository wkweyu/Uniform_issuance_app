📖 Uniform Issuance & Fleet Management App — Deployment Instructions
Version: 1.0
Developer: [Your Name / Business Name]
Database: MySQL 5.7+/8.x
Platform: Windows (Python 3.10+)

🔹 Requirements:
Python 3.10 or higher installed

MySQL Server running with schoolmngt database created

🔹 One-Time Setup:
Install required Python libraries:
Open Command Prompt in the app folder:

nginx
Copy
Edit
pip install -r requirements.txt
Import the required database tables:

Open MySQL Workbench or your preferred SQL client

Create a new database if not already:

sql
Copy
Edit
CREATE DATABASE schoolmngt;
Run the SQL script uniform_app_setup.sql to create all tables.

🔹 Running the App:
Double-click launch_uniform_app.bat on your Desktop
(Or copy it to Desktop and create a shortcut)

The app will start in a terminal window and show:

nginx
Copy
Edit
Running on http://127.0.0.1:5000
Open your browser and navigate to:

cpp
Copy
Edit
http://127.0.0.1:5000
🔹 Notes:
Ensure MySQL service is running before launching the app

You can customize school name and details inside the app.py in the /print_receipt route

Receipt auto-print will trigger when opened

Database connection settings are set to:

ini
Copy
Edit
host = 'localhost'
user = 'root'
password = 'jbs'
db = 'schoolmngt'
Adjust them inside app.py if needed

🔹 Developer Utilities:
If needed later:

Freeze environment packages:

pgsql
Copy
Edit
pip freeze > requirements.txt
Convert to executable (optional):

css
Copy
Edit
pip install pyinstaller
pyinstaller --onefile --windowed app.py
