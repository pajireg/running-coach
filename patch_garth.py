import os

# Path to the failing file
file_path = "venv/lib/python3.14/site-packages/garth/data/hrv.py"

with open(file_path, "r") as f:
    content = f.read()

# Fix imports
if "from typing import List" not in content:
    content = content.replace("from datetime import date, datetime", "from datetime import date, datetime\nfrom typing import List")

# Fix the breaking line
old_line = "hrv_readings: list[HRVReading]"
new_line = "hrv_readings: List[HRVReading]"

if old_line in content:
    content = content.replace(old_line, new_line)
    print("Patched 'list[HRVReading]' to 'List[HRVReading]'.")
else:
    print("Target line not found (maybe already patched).")

with open(file_path, "w") as f:
    f.write(content)

print("Patch applied successfully.")
