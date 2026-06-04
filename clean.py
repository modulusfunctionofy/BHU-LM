import json
import sys
from pathlib import Path

# ---------------------------------------------------------
# CENTRALIZED CONFIGURATION
# ---------------------------------------------------------
MASTER_EMBED_FILE = Path("Master_embed.json")

try:
    with open(MASTER_EMBED_FILE, "r", encoding="utf-8") as f:
        master_config = json.load(f)
except Exception as e:
    print(f"SYSTEM_MESSAGE_TO_ADMINS[Error reading Master_embed.json: {e}]")
    sys.exit(1)

CATEGORY = master_config.get("CATEGORY", "Uncategorized")

# ---------------------------------------------------------
# DIRECTORY SETUP
# ---------------------------------------------------------
WIKI_DIR = Path("wiki_html") / CATEGORY
CLEAN_DIR = Path("cleaned_html") / CATEGORY

def cleanup_directory(directory: Path, extensions: list[str]) -> int:
    """Deletes files matching the given extensions in the target directory."""
    if not directory.exists():
        return 0
    
    deleted_count = 0
    for ext in extensions:
        # Glob for all files with the specific extension (.html, .txt)
        for file_path in directory.glob(f"*{ext}"):
            try:
                file_path.unlink()
                deleted_count += 1
            except Exception as e:
                print(f"SYSTEM_MESSAGE_TO_ADMINS[Error deleting {file_path.name}: {e}]")
                
    return deleted_count

# ---------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------
def main():
    print("Cleaning Temporary Files")
    
    # Delete both .html and .txt since both are generated during the extraction phase
    wiki_deleted = cleanup_directory(WIKI_DIR, [".html", ".txt"])
    clean_deleted = cleanup_directory(CLEAN_DIR, [".html", ".txt"])
    
    total_deleted = wiki_deleted + clean_deleted
    
    print("------------------")
    print(f"Deleted {wiki_deleted} files from wiki_html")
    print(f"Deleted {clean_deleted} files from cleaned_html")
    print("Cleanup Successful")
    
    # Optional: Log it for the admin console to catch
    print(f"SYSTEM_MESSAGE_TO_ADMINS[Storage optimized. {total_deleted} temporary files removed.]")
    
    # Final pipeline completion flag
    print("COMPLETED")

if __name__ == "__main__":
    main()