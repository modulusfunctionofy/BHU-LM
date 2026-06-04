from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import chromadb
from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore
from unstructured.chunking.basic import chunk_elements
from unstructured.chunking.title import chunk_by_title
from unstructured.partition.html import partition_html

# ---------------------------------------------------------
# master config
# ---------------------------------------------------------
MASTER_EMBED_FILE = Path("Master_embed.json")
MASTER_COUNT_FILE = Path("Master_count.json")

def load_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Error reading {label}: {e}]")
        sys.exit(1)

    print(f"SYSTEM_MESSAGE_TO_ADMINS[Error: {label} is not a valid JSON object]")
    sys.exit(1)


master_config = load_json_file(MASTER_EMBED_FILE, "Master_embed.json")
count_config = load_json_file(MASTER_COUNT_FILE, "Master_count.json")

CATEGORY = master_config.get("CATEGORY", "Uncategorized")
OPTION = int(master_config.get("OPTION", 1))
MAX_CHUNKS = int(master_config.get("MAX_CHUNKS", 10))
MIN_CHUNKS = int(master_config.get("MIN_CHUNKS", 3))

SET_COUNT_RAW = count_config.get(CATEGORY)
if SET_COUNT_RAW is None:
    print(
        f"SYSTEM_MESSAGE_TO_ADMINS[Error: Category '{CATEGORY}' not found in Master_count.json]"
    )
    sys.exit(1)

try:
    SET_COUNT = int(SET_COUNT_RAW)
except Exception:
    print(
        f"SYSTEM_MESSAGE_TO_ADMINS[Error: Invalid set count for category '{CATEGORY}' in Master_count.json]"
    )
    sys.exit(1)

# ---------------------------------------------------------
# model / chunking mapping
# ---------------------------------------------------------
FAST_EMBED_MODEL = "nomic-embed-text"
DEEP_EMBED_MODEL = "snowflake-arctic-embed"

TITLE_CHUNKING = "title"
SEMANTIC_CHUNKING = "semantic"

if OPTION == 1:
    EMBED_MODEL_NAME = FAST_EMBED_MODEL
    CHUNKING_STRATEGY = TITLE_CHUNKING
elif OPTION == 2:
    EMBED_MODEL_NAME = DEEP_EMBED_MODEL
    CHUNKING_STRATEGY = TITLE_CHUNKING
elif OPTION == 3:
    EMBED_MODEL_NAME = DEEP_EMBED_MODEL
    CHUNKING_STRATEGY = SEMANTIC_CHUNKING
else:
    EMBED_MODEL_NAME = FAST_EMBED_MODEL
    CHUNKING_STRATEGY = TITLE_CHUNKING

MAX_CHARACTERS = 1500
COMBINE_TEXT_UNDER_N_CHARS = 300
NEW_AFTER_N_CHARS = 1200

Settings.embed_model = OllamaEmbedding(model_name=EMBED_MODEL_NAME)
Settings.llm = None

# ---------------------------------------------------------
# directories , please dont edit this section
# ---------------------------------------------------------
BASE_INPUT_DIR = Path("cleaned_html")
INPUT_DIR = BASE_INPUT_DIR / CATEGORY

BASE_DB_DIR = Path("databases")
CATEGORY_DB_DIR = BASE_DB_DIR / CATEGORY

CHROMA_DIR = CATEGORY_DB_DIR / f"{SET_COUNT}chromadb"
LOCAL_TRACKER_FILE = CATEGORY_DB_DIR / f"{SET_COUNT}_rag_tracker.json"
TRACKER_PATTERN = "[0-9]*_rag_tracker.json"


def is_table_element(element: Any) -> bool:
    name = type(element).__name__.lower()
    cat = str(getattr(element, "category", "")).lower()
    return name == "table" or cat == "table"

def is_heading_element(element: Any) -> bool:
    name = type(element).__name__.lower()
    cat = str(getattr(element, "category", "")).lower()
    return name == "title" or cat == "title" or name in {"header", "heading"}

def element_text(element: Any) -> str:
    text = getattr(element, "text", "")
    if text and str(text).strip():
        return str(text).strip()
    return str(element).strip()

def previous_title(elements: list[Any], idx: int) -> str:
    for j in range(idx - 1, -1, -1):
        prev = elements[j]
        if is_heading_element(prev):
            title = element_text(prev)
            if title:
                return title
    return ""



# tracker helpers
def get_global_tracker_data(category_dir: Path, file_pattern: str) -> set[str]:
    combined_set: set[str] = set()

    if not category_dir.exists():
        return combined_set

    for filepath in category_dir.glob(file_pattern):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    combined_set.update(data.get("processed_files", []))
                elif isinstance(data, list):
                    combined_set.update(data)
        except Exception:
            pass

    return combined_set


def load_local_tracker(filepath: Path) -> set[str]:
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return set(data.get("processed_files", []))
                if isinstance(data, list):
                    return set(data)
        except Exception:
            pass
    return set()


def save_local_tracker(filepath: Path, data_set: set[str]) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({"processed_files": sorted(list(data_set))}, f, indent=2, ensure_ascii=False)


#vector db(chromadb)

def build_index():
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    # keep this stable so retrieval can find it
    collection_name = "wiki_collection"

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    index = VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        storage_context=storage_context,
    )

    return index, collection

# ---------------------------------------------------------
# chunking

def semantic_chunk_elements(elements):
    return chunk_elements(
        elements,
        max_characters=MAX_CHARACTERS,
        new_after_n_chars=NEW_AFTER_N_CHARS,
    )


def title_chunk_elements(elements):
    return chunk_by_title(
        elements,
        max_characters=MAX_CHARACTERS,
        combine_text_under_n_chars=COMBINE_TEXT_UNDER_N_CHARS,
    )


def extract_chunks_from_html(html_file: Path):
    elements = partition_html(filename=str(html_file))

    table_docs: list[TextNode] = []
    non_table_elements: list[Any] = []

    for idx, element in enumerate(elements):
        if is_table_element(element):
            table_text = element_text(element)
            if not table_text:
                continue

            title_above = previous_title(elements, idx)
            if title_above:
                table_text = f"{title_above}\n{table_text}"

            table_docs.append(
                TextNode(
                    text=table_text,
                    id_=f"{html_file.stem}_table_{len(table_docs) + 1}",
                    metadata={
                        "category": CATEGORY,
                        "embedding_model": EMBED_MODEL_NAME,
                        "chunking_strategy": CHUNKING_STRATEGY,
                        "source_file": html_file.name,
                        "source_path": str(html_file),
                        "chunk_id": f"table_{len(table_docs) + 1}",
                        "set_count": SET_COUNT,
                        "is_table": True,
                        "table_title": title_above,
                    },
                )
            )
        else:
            non_table_elements.append(element)

    if CHUNKING_STRATEGY == TITLE_CHUNKING:
        chunks = title_chunk_elements(non_table_elements)
    elif CHUNKING_STRATEGY == SEMANTIC_CHUNKING:
        chunks = semantic_chunk_elements(non_table_elements)
    else:
        raise ValueError(f"Unknown chunking strategy: {CHUNKING_STRATEGY}")

    docs: list[TextNode] = []
    docs.extend(table_docs)

    for chunk_id, chunk in enumerate(chunks, start=1):
        text = (chunk.text or "").strip()
        if not text:
            continue

        docs.append(
            TextNode(
                text=text,
                id_=f"{html_file.stem}_{chunk_id}",
                metadata={
                    "category": CATEGORY,
                    "embedding_model": EMBED_MODEL_NAME,
                    "chunking_strategy": CHUNKING_STRATEGY,
                    "source_file": html_file.name,
                    "source_path": str(html_file),
                    "chunk_id": chunk_id,
                    "set_count": SET_COUNT,
                    "is_table": False,
                },
            )
        )

    return docs

# ---------------------------------------------------------
# main
# ---------------------------------------------------------
def main():
    if not INPUT_DIR.exists():
        print(
            f"SYSTEM_MESSAGE_TO_ADMINS[Error: Cleaned HTML directory missing at {INPUT_DIR}]"
        )
        sys.exit(1)

    html_files = sorted(INPUT_DIR.glob("*.html"))
    if not html_files:
        print("COMPLETED")
        return

    global_files = get_global_tracker_data(CATEGORY_DB_DIR, TRACKER_PATTERN)
    local_files = load_local_tracker(LOCAL_TRACKER_FILE)

    files_to_process = [
        f for f in html_files
        if f.name not in global_files and f.name not in local_files
    ]

    if not files_to_process:
        print("COMPLETED")
        return

    print("Chunking")

    all_docs: list[TextNode] = []
    successfully_chunked_files: list[str] = []
    chunk_errors: set[str] = set()

    for html_file in files_to_process:
        try:
            docs = extract_chunks_from_html(html_file)
            all_docs.extend(docs)
            successfully_chunked_files.append(html_file.name)

            clean_log_name = html_file.stem.replace("_", " ").title()
            print(f"{clean_log_name} Chunked")
        except Exception as e:
            chunk_errors.add(f"{html_file.name}: {str(e)[:60]}")

    print("------------------")
    print("Chunking Successful")

    if not all_docs:
        if chunk_errors:
            print(
                f"SYSTEM_MESSAGE_TO_ADMINS[Processed 0 out of {len(files_to_process)} pages due to: {', '.join(sorted(chunk_errors))}]"
            )
        print("COMPLETED")
        return

    print("Ingesting")
    ingest_errors: set[str] = set()

    try:
        index, collection = build_index()
        print("--")

        # insert without changing your retrieval-compatible metadata
        index.insert_nodes(all_docs)

        print("--")
        print("--")

        for file_name in successfully_chunked_files:
            local_files.add(file_name)

        save_local_tracker(LOCAL_TRACKER_FILE, local_files)

    except Exception as e:
        ingest_errors.add(f"Database Write Error: {str(e)[:80]}")

    print("_____________________")
    print("Ingesting Successful")

    if chunk_errors or ingest_errors:
        all_errors = sorted(chunk_errors | ingest_errors)
        print(
            f"SYSTEM_MESSAGE_TO_ADMINS[Processed {len(successfully_chunked_files)} out of {len(files_to_process)} documents due to: {', '.join(all_errors)}]"
        )

    print("COMPLETED")


if __name__ == "__main__":
    main()