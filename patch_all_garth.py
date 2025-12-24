import os
import glob

# Path to the data directory
base_path = "venv/lib/python3.14/site-packages/garth/data/"
files = glob.glob(os.path.join(base_path, "*.py"))

print(f"Found {len(files)} files to check in {base_path}")

for file_path in files:
    with open(file_path, "r") as f:
        content = f.read()

    original_content = content
    
    # Check if we need to patch
    if "list[" in content:
        print(f"Patching {os.path.basename(file_path)}...")
        
        # Add import if missing
        if "from typing import List" not in content:
            # Try to insert after imports
            if "from datetime" in content:
                 content = content.replace("from datetime", "from typing import List\nfrom datetime")
            else:
                 content = "from typing import List\n" + content
        
        # Replace list[...] with List[...]
        # A simple replace "list[" -> "List[" works for most cases
        content = content.replace("list[", "List[")
        
        if content != original_content:
            with open(file_path, "w") as f:
                f.write(content)
            print(f"  -> Patched.")
    else:
        print(f"Skipping {os.path.basename(file_path)} (no 'list[' found)")

print("All files processed.")
