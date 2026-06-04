from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import CLIPModel, CLIPProcessor
from google import genai

# ---------------------------------------------------------
# CENTRALIZED CONFIGURATION
# ---------------------------------------------------------
MASTER_EMBED_FILE = Path("Master_embed.json")
MASTER_COUNT_FILE = Path("Master_count.json")

try:
    with open(MASTER_EMBED_FILE, "r", encoding="utf-8") as f:
        master_config = json.load(f)
except Exception as e:
    print(f"SYSTEM_MESSAGE_TO_ADMINS[Error reading Master_embed.json: {e}]")
    sys.exit(1)

# Prioritize IMAGE_OPTION if explicitly set, else fallback to OPTION
IMAGE_OPTION = int(master_config.get("IMAGE_OPTION", master_config.get("OPTION", 0)))
CATEGORY = master_config.get("CATEGORY", "Uncategorized")

try:
    with open(MASTER_COUNT_FILE, "r", encoding="utf-8") as f:
        count_config = json.load(f)
        SET_COUNT = count_config.get(CATEGORY)
        if SET_COUNT is None:
            print(f"SYSTEM_MESSAGE_TO_ADMINS[Error: Category '{CATEGORY}' not found in Master_count.json]")
            sys.exit(1)
except Exception as e:
    print(f"SYSTEM_MESSAGE_TO_ADMINS[Error reading Master_count.json: {e}]")
    sys.exit(1)

# ---------------------------------------------------------
# DIRECTORY SETUP (Versioned by SET_COUNT)
# ---------------------------------------------------------
BASE_INPUT_DIR = Path("extracted_images")
INPUT_DIR = BASE_INPUT_DIR / CATEGORY / f"{SET_COUNT}_images"

BASE_OUTPUT_DIR = Path("image_processed")
CATEGORY_OUTPUT_DIR = BASE_OUTPUT_DIR / CATEGORY

# Target files and folders for the CURRENT run
LOCAL_TRACKER_FILE = CATEGORY_OUTPUT_DIR / f"{SET_COUNT}_processed_images_option_{IMAGE_OPTION}.json"
BASIC_DIR = CATEGORY_OUTPUT_DIR / f"{SET_COUNT}_basic"
ADVANCED_DIR = CATEGORY_OUTPUT_DIR / f"{SET_COUNT}_advanced"

# Strict pattern to catch past trackers of the same option
TRACKER_PATTERN = f"[0-9]*_processed_images_option_{IMAGE_OPTION}.json"

# ---------------------------------------------------------
# AGGREGATED TRACKER LOGIC
# ---------------------------------------------------------
def get_global_tracker_data(category_dir: Path, file_pattern: str) -> dict:
    """Reads ALL matching tracker files across sets to build a global memory."""
    global_data = {}
    if not category_dir.exists():
        return global_data
        
    for filepath in category_dir.glob(file_pattern):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k not in global_data:
                            global_data[k] = {}
                        global_data[k].update(v)
        except Exception:
            pass
    return global_data

def load_local_tracker(filepath: Path) -> dict:
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def save_local_tracker(filepath: Path, data: dict):
    CATEGORY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def safe_name(path: Path) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", path.stem).strip("_")

def image_key(img_path: Path) -> str:
    return str(img_path.relative_to(INPUT_DIR)).replace("\\", "/")

def ensure_dirs() -> None:
    CATEGORY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if IMAGE_OPTION == 1:
        BASIC_DIR.mkdir(parents=True, exist_ok=True)
    elif IMAGE_OPTION == 2:
        ADVANCED_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------
# CLIP LOGIC (Preserved Original)
# ---------------------------------------------------------
CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"
BASIC_LABELS = [
    "a screenshot of a user interface", "a handwritten notebook page",
    "a calendar or planner page", "a scanned document page",
    "a table with rows and columns", "a diagram or flowchart",
    "a chart or graph", "an infographic", "a presentation slide",
    "a signature on paper", "a text-heavy page", "a photograph of people",
    "a political event photo", "a meeting or conference photo"
]

clip_processor = None
clip_model = None

def load_clip() -> None:
    global clip_processor, clip_model
    if clip_processor is not None and clip_model is not None:
        return
    clip_processor = CLIPProcessor.from_pretrained(CLIP_MODEL_NAME)
    clip_model = CLIPModel.from_pretrained(CLIP_MODEL_NAME)
    clip_model.eval()

def _extract_tensor(features):
    if isinstance(features, torch.Tensor): 
        return features
    for attr in ("image_embeds", "text_embeds", "pooler_output"):
        if hasattr(features, attr):
            value = getattr(features, attr)
            if isinstance(value, torch.Tensor): 
                return value
    raise TypeError(f"Unsupported feature type: {type(features)}")

def clip_basic_process(image_path: Path) -> dict[str, Any]:
    with Image.open(image_path) as img:
        image = img.convert("RGB")
        inputs = clip_processor(
            text=[f"a photo of {label}" for label in BASIC_LABELS],
            images=image, return_tensors="pt", padding=True,
        )
        with torch.no_grad():
            outputs = clip_model(**inputs)
            logits = outputs.logits_per_image.squeeze(0)
            probs = torch.softmax(logits, dim=0)
            image_inputs = clip_processor(images=image, return_tensors="pt")
            image_features = clip_model.get_image_features(**image_inputs)
            
        image_features = _extract_tensor(image_features).float()
        image_features = F.normalize(image_features, p=2, dim=-1)
        embedding = image_features.squeeze(0).cpu().numpy().astype(np.float32)

    top_idx = torch.topk(probs, k=min(5, len(BASIC_LABELS))).indices.tolist()
    top_labels = [{"label": BASIC_LABELS[i], "score": float(probs[i].item())} for i in top_idx]
    return {"embedding": embedding, "top_labels": top_labels}

# ---------------------------------------------------------
# GEMINI LOGIC 
# ---------------------------------------------------------
GEMINI_API_KEY = "AIzaSyAZ5KIhNS9qPvYz5x4XsDy2U7WUGpNAMg0" # Put your key back here
GEMINI_MODEL_CANDIDATES = ["gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.5-flash"]
MAX_IMAGE_SIZE = 768
MAX_RETRIES = 5

ADVANCED_PROMPT = """
YOUR TASK:
Generate a highly searchable multimodal retrieval description of this image for a RAG pipeline.
The output should maximize semantic retrieval quality and future query matching.
Analyze and describe:
1. Visible text (OCR-style extraction)
   - headings, labels, numbers, dates, names, captions, UI text, table entries
2. Visual structure
   - layout, sections, panels, tables, charts, diagrams, screenshots, menus
3. Semantic meaning
   - what the image is trying to convey, contextual interpretation
4. Retrieval-oriented metadata
   - searchable keywords, related concepts, alternative query phrasings
5. Image category classification
   - photograph, chart, graph, infographic, table, document, UI screenshot, flowchart
6. Detailed image-specific reasoning
   - summarize rows/columns/trends/important values
IMPORTANT RULES:
- prioritize retrieval quality over brevity
- preserve important terminology exactly
- do not mention that you are an AI
Return ONLY the final retrieval description.
""".strip()

gemini_client = None
GEMINI_MODEL_NAME = None

def load_gemini() -> None:
    global gemini_client, GEMINI_MODEL_NAME
    if gemini_client is not None:
        return
    
    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_API_KEY_HERE":
        raise ValueError("GEMINI_API_KEY missing or invalid.")

    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    available = []
    
    for model in gemini_client.models.list():
        actions = getattr(model, "supported_actions", []) or []
        if "generateContent" in actions:
            name = getattr(model, "name", "")
            if name: available.append(name.split("/", 1)[-1])
                
    for candidate in GEMINI_MODEL_CANDIDATES:
        if candidate in available:
            GEMINI_MODEL_NAME = candidate
            return
            
    if available:
        GEMINI_MODEL_NAME = available[0]
        return
        
    raise RuntimeError("No Gemini generateContent model found.")

def gemini_advanced_process(image_path: Path) -> str:
    with Image.open(image_path) as img:
        image = img.convert("RGB")
        image.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE))
        
        for attempt in range(MAX_RETRIES):
            try:
                response = gemini_client.models.generate_content(
                    model=GEMINI_MODEL_NAME, contents=[ADVANCED_PROMPT, image],
                )
                return (response.text or "").strip()
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    raise RuntimeError("Gemini Quota Exceeded")
                if attempt == MAX_RETRIES - 1:
                    raise RuntimeError(f"Gemini API Error: {str(e)[:50]}")
                time.sleep(2 ** attempt)
    return ""

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def process_images() -> None:
    if IMAGE_OPTION == 0:
        return

    ensure_dirs()
    if not INPUT_DIR.exists():
        return

    # 1. Build Global Memory & Local Tracker
    global_images = get_global_tracker_data(CATEGORY_OUTPUT_DIR, TRACKER_PATTERN)
    local_images = load_local_tracker(LOCAL_TRACKER_FILE)

    all_image_files = sorted(
        p for p in INPUT_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    
    mode_name = "basic" if IMAGE_OPTION == 1 else "advanced"
    files_to_process = []
    
    for img_path in all_image_files:
        key = image_key(img_path)
        # Check massive global memory first to prevent duplicate processing
        if not global_images.get(key, {}).get(mode_name):
            files_to_process.append(img_path)
            
    if not files_to_process:
        return
    
    # Strictly formatted admin log
    print("Processing Images")

    try:
        if IMAGE_OPTION == 1: load_clip()
        elif IMAGE_OPTION == 2: load_gemini()
    except Exception as e:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Error loading AI models: {e}]")
        sys.exit(1)

    success_count = 0
    failed_count = 0
    error_reasons = set()

    for image_path in files_to_process:
        key = image_key(image_path)
        image_entry = local_images.setdefault(key, {})
        stem = safe_name(image_path)
        
        try:
            if IMAGE_OPTION == 1:
                result = clip_basic_process(image_path)
                emb_path = BASIC_DIR / f"{stem}_clip.npy"
                labels_path = BASIC_DIR / f"{stem}_clip_labels.json"
                summary_path = BASIC_DIR / f"{stem}_clip.txt"
                
                np.save(emb_path, result["embedding"])
                with open(labels_path, "w", encoding="utf-8") as f:
                    json.dump(result["top_labels"], f, indent=2, ensure_ascii=False)
                with open(summary_path, "w", encoding="utf-8") as f:
                    f.write(", ".join(f"{x['label']} ({x['score']:.3f})" for x in result["top_labels"]))
                    
                image_entry["basic"] = {
                    "processed_at": datetime.utcnow().isoformat() + "Z",
                    "mode": "basic",
                    "source_image_path": str(image_path),
                    "embedding_path": str(emb_path),
                    "labels_path": str(labels_path),
                    "summary_path": str(summary_path),
                }
                
            else:
                description = gemini_advanced_process(image_path)
                desc_path = ADVANCED_DIR / f"{stem}_description.txt"
                meta_path = ADVANCED_DIR / f"{stem}_description.json"
                
                with open(desc_path, "w", encoding="utf-8") as f:
                    f.write(description)
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "image_file": key,
                            "mode": "advanced",
                            "source_image_path": str(image_path),
                            "description_path": str(desc_path),
                            "description": description,
                            "processed_at": datetime.utcnow().isoformat() + "Z",
                        }, f, indent=2, ensure_ascii=False,
                    )
                    
                image_entry["advanced"] = {
                    "processed_at": datetime.utcnow().isoformat() + "Z",
                    "mode": "advanced",
                    "source_image_path": str(image_path),
                    "description_path": str(desc_path),
                    "meta_path": str(meta_path),
                }
            
            # Immediately add to global memory for this run, and save to local JSON
            global_images.setdefault(key, {})[mode_name] = image_entry[mode_name]
            save_local_tracker(LOCAL_TRACKER_FILE, local_images)
            success_count += 1
            
        except Exception as e:
            failed_count += 1
            error_msg = str(e)
            if "Quota Exceeded" in error_msg:
                error_reasons.add("Gemini API Quota Exceeded")
            elif "corrupt" in error_msg.lower() or "unidentified" in error_msg.lower():
                error_reasons.add("Corrupted Image File")
            else:
                error_reasons.add("Processing Error")

    # Strictly formatted admin error reporting
    if failed_count > 0:
        errors = ", ".join(error_reasons)
        print(f"SYSTEM_MESSAGE_TO_ADMINS[Processed {success_count} out of {len(files_to_process)} images due to: {errors}]")
    
    print("Image Processing Successful")

if __name__ == "__main__":
    process_images()