from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from llama_index.embeddings.ollama import OllamaEmbedding

# ---------------------------------------------------------
# CENTRALIZED CONFIGURATION
# ---------------------------------------------------------
MASTER_EMBED_FILE = Path("Master_embed.json")
MASTER_RETRIEVE_FILE = Path("Master_retrieve.json")

try:
    with open(MASTER_EMBED_FILE, "r", encoding="utf-8") as f:
        embed_config = json.load(f)
except Exception as e:
    print(f"SYSTEM_MESSAGE_TO_ADMINS[Error reading Master_embed.json: {e}]")
    sys.exit(1)

CATEGORY = embed_config.get("CATEGORY", "Uncategorized")
# Priority to IMAGE_OPTION, fallback to OPTION
OPTION = int(embed_config.get("IMAGE_OPTION", embed_config.get("OPTION", 0)))

try:
    with open(MASTER_RETRIEVE_FILE, "r", encoding="utf-8") as f:
        retrieve_config = json.load(f)
except Exception as e:
    print(f"SYSTEM_MESSAGE_TO_ADMINS[Error reading Master_retrieve.json: {e}]")
    sys.exit(1)

IMAGE_RETRIEVE = int(retrieve_config.get("IMAGE_RETRIEVE", 0))
RETRIEVED_IMAGE_CHUNKS = int(retrieve_config.get("RETRIEVED_IMAGES_CHUNKS", retrieve_config.get("RETRIEVED_IMAGE_CHUNKS", 2)))

# ---------------------------------------------------------
# DIRECTORY & MODEL SETUP
# ---------------------------------------------------------
BASE_PROCESSED_DIR = Path("image_processed") / CATEGORY
OUTPUT_FILE = BASE_PROCESSED_DIR / "retrieved_images.json"

CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"
TEXT_EMBED_MODEL_NAME = "snowflake-arctic-embed"

# Strict pattern to catch past trackers based on the active Option
TRACKER_PATTERN = f"[0-9]*_processed_images_option_{OPTION}.json"

# ---------------------------------------------------------
# MULTI-DATABASE MEMORY LOGIC
# ---------------------------------------------------------
def get_global_tracker_data() -> dict[str, Any]:
    """Reads ALL matching tracker files across sets to build a global memory of images."""
    global_tracker = {}
    if not BASE_PROCESSED_DIR.exists():
        return global_tracker

    for filepath in BASE_PROCESSED_DIR.glob(TRACKER_PATTERN):
        try:
            # Extract set count from filename (e.g., "1_processed..." -> "1")
            set_count = filepath.name.split('_')[0]
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        v['set_count'] = set_count
                        # Ensure keys are unique across sets
                        global_tracker[f"{set_count}_{k}"] = v
        except Exception:
            pass
            
    return global_tracker

def save_output(data: dict[str, Any]) -> None:
    BASE_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def tracker_to_records(tracker: dict[str, Any]):
    basic_records = []
    advanced_records = []

    for unique_key, modes in tracker.items():
        if not isinstance(modes, dict):
            continue
            
        set_count = modes.get("set_count", "?")

        basic_info = modes.get("basic")
        if isinstance(basic_info, dict):
            basic_records.append(
                {
                    "key": unique_key,
                    "mode": "basic",
                    "set_count": set_count,
                    "image_path": Path(basic_info.get("source_image_path", "")),
                    "artifact_path": Path(basic_info.get("embedding_path", "")),
                    "labels_path": Path(basic_info.get("labels_path", "")),
                    "summary_path": Path(basic_info.get("summary_path", "")),
                }
            )

        advanced_info = modes.get("advanced")
        if isinstance(advanced_info, dict):
            advanced_records.append(
                {
                    "key": unique_key,
                    "mode": "advanced",
                    "set_count": set_count,
                    "image_path": Path(advanced_info.get("source_image_path", "")),
                    "artifact_path": Path(advanced_info.get("description_path", "")),
                    "meta_path": Path(advanced_info.get("meta_path", "")),
                }
            )

    return basic_records, advanced_records

def ensure_tensor(features) -> torch.Tensor:
    if isinstance(features, torch.Tensor):
        return features

    for attr in ("image_embeds", "text_embeds", "pooler_output"):
        if hasattr(features, attr):
            val = getattr(features, attr)
            if isinstance(val, torch.Tensor):
                return val

    if isinstance(features, (list, tuple, np.ndarray)):
        return torch.tensor(features)

    raise TypeError(f"Unsupported feature type: {type(features)}")

# ---------------------------------------------------------
# INDEXING & VECTOR MATH (Preserved)
# ---------------------------------------------------------
def load_basic_index(basic_records, clip_model, clip_processor):
    index = []
    for rec in basic_records:
        image_path = rec["image_path"]
        if not image_path.exists():
            continue

        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                inputs = clip_processor(images=img, return_tensors="pt")
                with torch.no_grad():
                    feats = clip_model.get_image_features(**inputs)
            feats = ensure_tensor(feats).float()
            feats = F.normalize(feats, p=2, dim=-1)
            vec = feats.squeeze(0).cpu().numpy().astype(np.float32)

            index.append({"**rec": rec, **rec, "vector": vec})
        except Exception:
            pass

    return index

def load_advanced_index(advanced_records, text_embedder):
    index = []
    for rec in advanced_records:
        desc_path = rec["artifact_path"]
        if not desc_path.exists():
            continue

        try:
            description = desc_path.read_text(encoding="utf-8").strip()
            if not description:
                continue
            
            if hasattr(text_embedder, "get_text_embedding"):
                vec = text_embedder.get_text_embedding(description)
            else:
                vec = text_embedder.get_query_embedding(description)
            
            arr = np.asarray(vec, dtype=np.float32)
            norm = np.linalg.norm(arr)
            vec = arr / norm if norm != 0 else arr

            index.append({**rec, "description": description, "vector": vec})
        except Exception:
            pass

    return index

def cosine_rank(query_vec: np.ndarray, items: list[dict[str, Any]], limit: int):
    if not items:
        return []

    query_vec = np.asarray(query_vec, dtype=np.float32)
    qnorm = np.linalg.norm(query_vec)
    if qnorm != 0:
        query_vec = query_vec / qnorm

    results = []
    for item in items:
        score = float(np.dot(query_vec, item["vector"]))
        results.append(
            {
                "mode": item["mode"],
                "score": score,
                "image_path": str(item["image_path"].resolve()),
                "original_path": str(item["image_path"]),
                "artifact_path": str(item["artifact_path"]) if str(item["artifact_path"]) else "",
                "key": item["key"],
                "set_count": item["set_count"],
                "summary": item.get("description", ""),
            }
        )

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]

def print_results(query: str, branch: str, results: list[dict[str, Any]]):
    print("\n" + "=" * 100)
    print(f"IMAGE QUERY: {query}")
    print(f"ROUTED TO: {branch} (Category: {CATEGORY})")
    print("=" * 100)

    if not results:
        print("SYSTEM_MESSAGE_TO_USER[No highly relevant images found.]")
        return

    print(f"\nSYSTEM_MESSAGE_TO_USER[Retrieved {len(results)} image chunks.]\n")

    for i, item in enumerate(results, start=1):
        print("-" * 100)
        print(f"[{i}] Score: {item['score']:.4f} | Set: {item['set_count']}")
        print(f"Mode       : {item['mode']}")
        print(f"Image Path : {item['image_path']}")
        if item["artifact_path"]:
            print(f"Artifact   : {item['artifact_path']}")
        if item["summary"]:
            print(f"Summary    : {item['summary'][:400]}")
        print("-" * 100)

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    if IMAGE_RETRIEVE == 0:
        print("SYSTEM_MESSAGE_TO_USER[Image retrieval is currently disabled (IMAGE_RETRIEVE = 0).]")
        return
        
    if OPTION == 0:
        print("SYSTEM_MESSAGE_TO_USER[Image processing was disabled (OPTION = 0). No images to retrieve.]")
        return
    
    # 1. Global Database Fetch
    global_tracker = get_global_tracker_data()
    if not global_tracker:
        print(f"SYSTEM_MESSAGE_TO_USER[No processed images found for category '{CATEGORY}' under Option {OPTION}.]")
        return
        
    basic_records, advanced_records = tracker_to_records(global_tracker)

    print("\n" + "=" * 100)
    print("IMAGE RETRIEVAL ONLINE")
    print(f"Category: {CATEGORY}")
    print(f"Active Option: {OPTION}")
    print(f"Top image chunks: {RETRIEVED_IMAGE_CHUNKS}")
    print("=" * 100)

    # 2. Targeted Model Initialization
    basic_index = []
    advanced_index = []
    
    clip_processor = None
    clip_model = None
    text_embedder = None

    if OPTION == 1:
        print("\nLoading basic CLIP model and unified index...")
        clip_processor = CLIPProcessor.from_pretrained(CLIP_MODEL_NAME)
        clip_model = CLIPModel.from_pretrained(CLIP_MODEL_NAME)
        clip_model.eval()
        basic_index = load_basic_index(basic_records, clip_model, clip_processor)
        print(f"Global Basic index ready: {len(basic_index)} images")
        
    elif OPTION in [2, 3]:
        print("\nLoading advanced Semantic model and unified index...")
        text_embedder = OllamaEmbedding(model_name=TEXT_EMBED_MODEL_NAME)
        advanced_index = load_advanced_index(advanced_records, text_embedder)
        print(f"Global Advanced index ready: {len(advanced_index)} images")
    else:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Error: Unknown processing option: {OPTION}]")
        sys.exit(1)

    while True:
        try:
            query = input("\nImage query (or 'q' to quit): ").strip()
        except EOFError:
            break
            
        if not query or query.lower() == "q":
            break
            
        try:
            # 3. Strict Routing based on Option
            if OPTION == 1:
                branch = "CLIP"
                inputs = clip_processor(text=[query], return_tensors="pt", padding=True, truncation=True)
                with torch.no_grad():
                    feats = clip_model.get_text_features(**inputs)
                feats = ensure_tensor(feats).float()
                feats = F.normalize(feats, p=2, dim=-1)
                qvec = feats.squeeze(0).cpu().numpy().astype(np.float32)
                results = cosine_rank(qvec, basic_index, RETRIEVED_IMAGE_CHUNKS)
                
            elif OPTION in [2, 3]:
                branch = "ADVANCED"
                if hasattr(text_embedder, "get_text_embedding"):
                    vec = text_embedder.get_text_embedding(query)
                else:
                    vec = text_embedder.get_query_embedding(query)
                arr = np.asarray(vec, dtype=np.float32)
                norm = np.linalg.norm(arr)
                qvec = arr / norm if norm != 0 else arr
                results = cosine_rank(qvec, advanced_index, RETRIEVED_IMAGE_CHUNKS)

            print_results(query, branch, results)
            
            save_output({
                "query": query,
                "routed_to": branch,
                "results": results,
            })
            
        except Exception as e:
            print(f"SYSTEM_MESSAGE_TO_ADMINS[Search Error: {e}]")

if __name__ == "__main__":
    main()