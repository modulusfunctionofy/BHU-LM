import requests
import json
import time
import re
import sys
from pathlib import Path

# ---------------------------------------------------------
# CENTRALIZED CONFIGURATION
# ---------------------------------------------------------
MASTER_EMBED_FILE = Path("Master_embed.json")
MASTER_COUNT_FILE = Path("Master_count.json")

# 1. Fetch Variables from Master_embed.json
try:
    with open(MASTER_EMBED_FILE, "r", encoding="utf-8") as f:
        master_config = json.load(f)
except Exception as e:
    print(f"SYSTEM_MESSAGE_TO_ADMIN[Error reading Master_embed.json: {e}]")
    sys.exit(1)

OPTION = int(master_config.get("OPTION", 0))
CATEGORY = master_config.get("CATEGORY", "Uncategorized")
PAGES_TO_PROCESS = master_config.get("PAGES_TO_PROCESS", [])
HEADERS = master_config.get("HEADERS", {"User-Agent": "Mozilla/5.0"})
MAX_IMAGE_RETRIEVAL = 50   #this needs to be changed if in future you want some changes

# 2. Fetch Set Count from the Universal Master_count.json Ledger
try:
    with open(MASTER_COUNT_FILE, "r", encoding="utf-8") as f:
        count_config = json.load(f)
        # Look up the specific count for THIS category
        SET_COUNT = count_config.get(CATEGORY)
        
        if SET_COUNT is None:
            print(f"SYSTEM_MESSAGE_TO_ADMIN[Error: Category '{CATEGORY}' not found in Master_count.json. Cannot version the storage.]")
            sys.exit(1)
except Exception as e:
    print(f"SYSTEM_MESSAGE_TO_ADMIN[Error reading Master_count.json: {e}]")
    sys.exit(1)

# ---------------------------------------------------------
# DIRECTORY SETUP (Versioned by SET_COUNT)
# ---------------------------------------------------------
WIKI_BASE_URL = "https://en.wikipedia.org"
API_URL = f"{WIKI_BASE_URL}/w/api.php"

BASE_OUTPUT_DIR = Path("extracted_images")
CATEGORY_DIR = BASE_OUTPUT_DIR / CATEGORY

# Isolated target folders for the CURRENT run
SET_IMAGE_DIR = CATEGORY_DIR / f"{SET_COUNT}_images"
PAGE_TRACKER_FILE = CATEGORY_DIR / f"{SET_COUNT}_processed_pages.json"
IMAGE_TRACKER_FILE = CATEGORY_DIR / f"{SET_COUNT}_processed_images.json"

# Strict patterns to only catch files created by this script's SET_COUNT convention
PAGE_TRACKER_PATTERN = "[0-9]*_processed_pages.json"
IMAGE_TRACKER_PATTERN = "[0-9]*_processed_images.json"

# ---------------------------------------------------------
# AGGREGATED TRACKER LOGIC
# ---------------------------------------------------------
def get_global_tracker_data(category_dir: Path, file_pattern: str, key: str) -> set:
    """Reads strictly matching tracker files to build a global memory of existing assets."""
    combined_set = set()
    if not category_dir.exists():
        return combined_set
        
    for filepath in category_dir.glob(file_pattern):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    combined_set.update(data.get(key, []))
                elif isinstance(data, list):
                    combined_set.update(data)
        except Exception:
            pass
    return combined_set

def load_local_tracker(filepath: Path, key: str) -> set:
    """Loads only the current set's tracker file (if resuming)."""
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return set(data.get(key, []))
                elif isinstance(data, list):
                    return set(data)
        except Exception:
            pass
    return set()

def save_local_tracker(filepath: Path, data_set: set, key: str):
    """Saves ONLY the items processed in the current set."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({key: sorted(list(data_set))}, f, indent=4, ensure_ascii=False)

def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "", filename)

# ---------------------------------------------------------
# IMAGE FETCHING LOGIC
# ---------------------------------------------------------
def fetch_images_for_page(
    page_title: str, 
    global_pages: set, 
    global_images: set, 
    local_pages: set, 
    local_images: set
):
    if page_title in global_pages:
        return

    session = requests.Session()
    safe_name = page_title.replace(" ", "_").lower()
    
    PAGE_DIR = SET_IMAGE_DIR / safe_name
    PAGE_DIR.mkdir(parents=True, exist_ok=True)

    valid_extensions = (".jpg", ".jpeg", ".png", ".webp")
    base_params = {
        "action": "query",
        "format": "json",
        "titles": page_title,
        "generator": "images",
        "gimlimit": str(MAX_IMAGE_RETRIEVAL),
        "prop": "imageinfo",
        "iiprop": "url",
    }

    continue_params = {}
    success_count = 0
    failed_count = 0
    error_reasons = set()
    total_attempted = 0

    while True:
        req_params = {**base_params, **continue_params}
        try:
            response = session.get(url=API_URL, params=req_params, headers=HEADERS, timeout=10).json()
        except Exception:
            error_reasons.add("Wikipedia API Connection Error")
            break

        pages = response.get("query", {}).get("pages", {})

        for p_id, img_data in pages.items():
            title = img_data.get("title", "")

            if not (title.lower().endswith(valid_extensions) and "icon" not in title.lower()):
                continue

            if "imageinfo" in img_data:
                img_url = img_data["imageinfo"][0]["url"]
                raw_filename = title.replace("File:", "")
                img_filename = sanitize_filename(raw_filename)
                save_path = PAGE_DIR / img_filename
                tracker_key = f"{safe_name}/{img_filename}"

                if tracker_key in global_images or save_path.exists():
                    continue

                total_attempted += 1

                try:
                    img_response = session.get(img_url, headers=HEADERS, timeout=10)
                    if img_response.status_code == 200:
                        with open(save_path, "wb") as f:
                            f.write(img_response.content)
                        success_count += 1
                        
                        global_images.add(tracker_key)
                        local_images.add(tracker_key)
                        
                        save_local_tracker(IMAGE_TRACKER_FILE, local_images, "processed_images")
                    else:
                        failed_count += 1
                        error_reasons.add(f"HTTP {img_response.status_code}")
                except Exception:
                    failed_count += 1
                    error_reasons.add("Download Timeout/Connection Error")

                time.sleep(0.5) 

        if "continue" in response:
            continue_params = response["continue"]
        else:
            break

    global_pages.add(page_title)
    local_pages.add(page_title)
    save_local_tracker(PAGE_TRACKER_FILE, local_pages, "processed_pages")

    if failed_count > 0:
        errors = ", ".join(error_reasons)
        print(f"SYSTEM_MESSAGE_TO_ADMIN[Extracted {success_count} images out of {total_attempted} for '{page_title}' due to: {errors}]")
    else:
        print(f"'{page_title}' images extracted.")

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    if OPTION == 0:
        return

    if not PAGES_TO_PROCESS:
        print("SYSTEM_MESSAGE_TO_ADMIN[Warning: No pages found in PAGES_TO_PROCESS. Skipping extraction.]")
        return

    print("Image Extraction started...")
    
    CATEGORY_DIR.mkdir(parents=True, exist_ok=True)
    SET_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Build the Global Memory
    global_pages = get_global_tracker_data(CATEGORY_DIR, PAGE_TRACKER_PATTERN, "processed_pages")
    global_images = get_global_tracker_data(CATEGORY_DIR, IMAGE_TRACKER_PATTERN, "processed_images")

    # 2. Load the Local Tracker 
    local_pages = load_local_tracker(PAGE_TRACKER_FILE, "processed_pages")
    local_images = load_local_tracker(IMAGE_TRACKER_FILE, "processed_images")

    for page in PAGES_TO_PROCESS:
        fetch_images_for_page(page, global_pages, global_images, local_pages, local_images)
        
    print("Image Extraction Successful")

if __name__ == "__main__":
    main()