import requests
import json
import sys
from pathlib import Path

MASTER_EMBED_FILE = Path("Master_embed.json")

try:
    with open(MASTER_EMBED_FILE, "r", encoding="utf-8") as f:
        master_config = json.load(f)
except Exception as e:
    print(f"SYSTEM_MESSAGE_TO_ADMINS[Error reading Master_embed.json: {e}]")
    sys.exit(1)

CATEGORY = master_config.get("CATEGORY", "Uncategorized")
HEADERS = master_config.get("HEADERS", {"User-Agent": "Campus-Wiki-Extractor/1.0"})
PAGES_TO_FETCH = master_config.get("PAGES_TO_FETCH", master_config.get("PAGES_TO_PROCESS", []))

WIKI_BASE_URL = "https://en.wikipedia.org"
API_URL = f"{WIKI_BASE_URL}/w/api.php"

BASE_OUTPUT_DIR = Path("wiki_html")
CATEGORY_DIR = BASE_OUTPUT_DIR / CATEGORY
CATEGORY_DIR.mkdir(parents=True, exist_ok=True)

LOCAL_TRACKER_FILE = CATEGORY_DIR / "processed_pages.json"

CATEGORY_DB_DIR = Path("databases") / CATEGORY
RAG_TRACKER_PATTERN = "[0-9]*_rag_tracker.json"

def normalize_name(page: str) -> str:
    return page.replace(" ", "_").lower()

def load_local_tracker() -> set[str]:
    if not LOCAL_TRACKER_FILE.exists():
        return set()
    try:
        with open(LOCAL_TRACKER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {str(x).strip().lower().replace(".html", "") for x in data if str(x).strip()}
    except Exception:
        pass
    return set()

def save_local_tracker(processed_set: set[str]) -> None:    #updates processed.json with the 
    with open(LOCAL_TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(processed_set)), f, indent=4)

def get_global_embedded_pages() -> set[str]:
    combined_set = set()
    if not CATEGORY_DB_DIR.exists():
        return combined_set

    for filepath in CATEGORY_DB_DIR.glob(RAG_TRACKER_PATTERN):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for item in data.get("processed_files", []):
                    combined_set.add(str(item).strip().lower().replace(".html", ""))
            elif isinstance(data, list):
                for item in data:
                    combined_set.add(str(item).strip().lower().replace(".html", ""))
        except Exception:
            pass

    return combined_set

def get_page_html(page_title: str):
    params = {
        "action": "parse",
        "page": page_title,
        "prop": "text",
        "format": "json",
    }
    try:
        response = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
        if "parse" in data:
            return data["parse"]["text"]["*"]
    except Exception as e:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Wikipedia parse error for '{page_title}': {str(e)[:80]}]")
    return None

def get_raw_wikitext(page_title: str):
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": page_title,
        "rvprop": "content",
        "format": "json",
        "formatversion": "2",
    }
    try:
        response = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
        pages = data.get("query", {}).get("pages", [])
        if pages and "revisions" in pages[0]:
            return pages[0]["revisions"][0]["content"]
    except Exception as e:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Wikipedia wikitext error for '{page_title}': {str(e)[:80]}]")
    return None

def main():
    if not PAGES_TO_FETCH:
        print("SYSTEM_MESSAGE_TO_ADMINS[Warning: No pages found in PAGES_TO_FETCH. Skipping.]")
        return

    global_embedded_pages = get_global_embedded_pages()
    local_processed_pages = load_local_tracker()

    pages_to_download = []
    skipped_pages = []

    for page in PAGES_TO_FETCH:
        safe_name = normalize_name(page)

        if safe_name in global_embedded_pages or safe_name in local_processed_pages:
            skipped_pages.append(page)
            continue

        pages_to_download.append(page)

    if not pages_to_download:
        print("SYSTEM_MESSAGE_TO_ADMINS[All requested pages are already processed.]")
        if skipped_pages:
            print("Skipped:", ", ".join(skipped_pages))
        return

    print("Fetching")

    success_count = 0
    failed_count = 0
    fetched_pages = []
    skipped_failures = []

    for page_title in pages_to_download:
        safe_name = normalize_name(page_title)

        html_content = get_page_html(page_title)
        raw_text = get_raw_wikitext(page_title)

        if not html_content or not raw_text:
            failed_count += 1
            skipped_failures.append(page_title)
            print(f"SYSTEM_MESSAGE_TO_ADMINS[Skipped '{page_title}' due to empty content]")
            continue

        try:
            html_path = CATEGORY_DIR / f"{safe_name}.html"
            raw_path = CATEGORY_DIR / f"{safe_name}.txt"

            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(raw_text)

            local_processed_pages.add(safe_name)
            save_local_tracker(local_processed_pages)

            success_count += 1
            fetched_pages.append(page_title)
            print(f"{page_title} Fetched")

        except Exception as e:
            failed_count += 1
            skipped_failures.append(page_title)
            print(f"SYSTEM_MESSAGE_TO_ADMINS[Skipped '{page_title}' due to file write error: {str(e)[:60]}]")

    print("------------------")
    print("Fetching Successful")

    if fetched_pages:
        print("Fetched:", ", ".join(fetched_pages))
    if skipped_failures:
        print("Skipped:", ", ".join(skipped_failures))

    if failed_count > 0:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Fetched {success_count} pages, skipped {failed_count} pages]")

if __name__ == "__main__":
    main()