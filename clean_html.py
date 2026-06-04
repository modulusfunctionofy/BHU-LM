import json
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString

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

# Pull classes and noise strings from Master Config with safe defaults
REMOVE_CLASSES = master_config.get("CLASSES", [
    "infobox", "sidebar", "navbox", "vertical-navbox", 
    "portable-infobox", "reflist", "toc", "hatnote", 
    "mw-editsection", "mw-references-wrap"
])

NOISE_SUBSTRINGS = master_config.get("NOISE_SUBSTRINGS", [
    "reference", "see also", "further reading", "external link", 
    "bibliography", "notes", "sources", "citation"
])

# ---------------------------------------------------------
# DIRECTORY SETUP (NO SET_COUNT PREFIX - TEMPORARY STORAGE)
# ---------------------------------------------------------
BASE_INPUT_DIR = Path("wiki_html")
BASE_OUTPUT_DIR = Path("cleaned_html")

INPUT_DIR = BASE_INPUT_DIR / CATEGORY
OUTPUT_DIR = BASE_OUTPUT_DIR / CATEGORY

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_TRACKER_FILE = OUTPUT_DIR / "processed_cleaning.json"

# ---------------------------------------------------------
# GLOBAL MEMORY CHECK (Cross-referencing RAG databases)
# ---------------------------------------------------------
CATEGORY_DB_DIR = Path("databases") / CATEGORY
RAG_TRACKER_PATTERN = "[0-9]*_rag_tracker.json"

def get_global_embedded_pages() -> set:
    """Reads global RAG trackers to see what is ALREADY permanently in the vector databases."""
    combined_set = set()
    if not CATEGORY_DB_DIR.exists():
        return combined_set
        
    for filepath in CATEGORY_DB_DIR.glob(RAG_TRACKER_PATTERN):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    combined_set.update(data.get("processed_files", []))
        except Exception:
            pass
    return combined_set

def load_local_tracker() -> set:
    """Loads temporary local tracker to resume gracefully if script crashes mid-clean."""
    if LOCAL_TRACKER_FILE.exists():
        try:
            with open(LOCAL_TRACKER_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_local_tracker(processed_set: set):
    with open(LOCAL_TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(processed_set)), f, indent=4)

# ---------------------------------------------------------
# HTML CLEANING CORE LOGIC (Preserved)
# ---------------------------------------------------------
def clean_mediawiki_html(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    main = soup.select_one(".mw-parser-output")
    
    if main is None:
        return html_content

    # STEP A: Eradicate Wikipedia CSS Classes
    for cls in REMOVE_CLASSES:
        for tag in main.find_all(class_=cls):
            tag.decompose()

    # STEP B: Eradicate structural sidebars/infoboxes
    for table in main.find_all("table"):
        style = table.get("style", "").lower()
        if "float: right" in style or "float: left" in style or "float:right" in style:
            table.decompose()

    # STEP C: Eradicate Manual and Extension Citations (e.g., [1], [a], [note 1])
    for sup in main.find_all("sup", class_="reference"):
        sup.decompose()
    
    pattern = re.compile(r'\[[a-zA-Z0-9\s]+\]')
    for text_node in main.find_all(string=True):
        if isinstance(text_node, NavigableString):
            cleaned_text = pattern.sub('', text_node)
            if cleaned_text != text_node:
                text_node.replace_with(cleaned_text)

    # STEP D: Resilient Sequential Sibling Sweep
    elements = main.find_all(True) 
    skip_mode = False
    
    for element in elements:
        if not element.parent:
            continue
            
        is_heading = False
        heading_text = ""
        
        if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            is_heading = True
            heading_text = element.get_text(" ", strip=True).lower()
        elif element.name == 'div' and 'mw-heading' in element.get('class', []):
            is_heading = True
            inner_h = element.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if inner_h:
                heading_text = inner_h.get_text(" ", strip=True).lower()
        
        if is_heading and heading_text:
            if any(noise in heading_text for noise in NOISE_SUBSTRINGS):
                skip_mode = True
            else:
                skip_mode = False
                
        if skip_mode:
            element.decompose()

    return str(main)

# ---------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------
def process_directory():
    if not INPUT_DIR.exists():
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Error: Input directory {INPUT_DIR} missing. Run get_html.py first.]")
        return

    html_files = list(INPUT_DIR.glob("*.html"))
    if not html_files:
        return

    # 1. Build Memories
    global_embedded_pages = get_global_embedded_pages()
    local_processed_pages = load_local_tracker()
    
    files_to_process = []
    for html_file in html_files:
        # Cross-reference existing RAG databases and local tracker
        if html_file.name in global_embedded_pages or html_file.name in local_processed_pages:
            continue
        files_to_process.append(html_file)

    if not files_to_process:
        return

    # Strict Logging Format
    print("Cleaning")
    
    success_count = 0
    failed_count = 0
    error_reasons = set()

    for html_file in files_to_process:
        try:
            with open(html_file, "r", encoding="utf-8") as f:
                raw_html = f.read()

            cleaned_html = clean_mediawiki_html(raw_html)

            output_path = OUTPUT_DIR / html_file.name
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(cleaned_html)

            local_processed_pages.add(html_file.name)
            save_local_tracker(local_processed_pages)
            
            success_count += 1
            
            # Output clean display name (e.g. "narendra_modi.html" -> "Narendra Modi")
            clean_log_name = html_file.stem.replace("_", " ").title()
            print(f"{clean_log_name} Cleaned")
            
        except Exception as e:
            failed_count += 1
            error_reasons.add(f"Parse/Write Error: {str(e)[:40]}")

    print("------------------")
    print("Cleaning Successful")

    if failed_count > 0:
        errors_str = ", ".join(error_reasons)
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Processed {success_count} out of {len(files_to_process)} pages due to: {errors_str}]")

if __name__ == "__main__":
    process_directory()