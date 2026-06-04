import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------
# CENTRALIZED CONFIGURATION
# ---------------------------------------------------------
MASTER_EMBED_FILE = Path("Master_embed.json")
MASTER_COUNT_FILE = Path("Master_count.json")

def init_master_count() -> str:
    """
    Step 1: Fetch CATEGORY from Master_embed.json. 
    Create Master_count.json if it doesn't exist, and initialize the category count to 1 if missing.
    """
    try:
        with open(MASTER_EMBED_FILE, "r", encoding="utf-8") as f:
            embed_config = json.load(f)
            category = embed_config.get("CATEGORY")
            if not category:
                print("SYSTEM_MESSAGE_TO_ADMINS[Error: CATEGORY not found in Master_embed.json]")
                sys.exit(1)
    except Exception as e:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Error reading Master_embed.json: {e}]")
        sys.exit(1)

    if not MASTER_COUNT_FILE.exists():
        with open(MASTER_COUNT_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

    try:
        with open(MASTER_COUNT_FILE, "r", encoding="utf-8") as f:
            count_config = json.load(f)
    except Exception as e:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Error reading Master_count.json: {e}]")
        sys.exit(1)

    if category not in count_config:
        count_config[category] = 1
        with open(MASTER_COUNT_FILE, "w", encoding="utf-8") as f:
            json.dump(count_config, f, indent=4)

    return category

def run_script(script_name: str):
    """Executes a script and waits for its strict completion."""
    result = subprocess.run([sys.executable, script_name])
    if result.returncode != 0:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Pipeline halted. {script_name} failed with exit code {result.returncode}]")
        sys.exit(result.returncode)

def run_parallel(script1: str, script2: str):
    """Executes two scripts simultaneously and waits for BOTH to finish."""
    p1 = subprocess.Popen([sys.executable, script1])
    p2 = subprocess.Popen([sys.executable, script2])

    p1.wait()
    p2.wait()

    if p1.returncode != 0 or p2.returncode != 0:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Pipeline halted. Parallel execution failed. {script1} code: {p1.returncode}, {script2} code: {p2.returncode}]")
        sys.exit(1)

def update_master_count(category: str):
    """Step 8: Updates the current category in Master_count.json by adding 1 to it."""
    try:
        with open(MASTER_COUNT_FILE, "r", encoding="utf-8") as f:
            count_config = json.load(f)

        count_config[category] += 1

        with open(MASTER_COUNT_FILE, "w", encoding="utf-8") as f:
            json.dump(count_config, f, indent=4)
    except Exception as e:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Error updating Master_count.json: {e}]")
        sys.exit(1)

# ---------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------
def main():

    category = init_master_count()


    run_parallel("get_html.py", "image_extraction.py")


    run_script("clean_html.py")


    run_parallel("image_process.py", "RAG.py")


    #run_script("clean.py")


    print("COMPLETED")


    update_master_count(category)

   
    print("Updated Environment Variables")

if __name__ == "__main__":
    main()