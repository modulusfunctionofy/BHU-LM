from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import chromadb
import numpy as np

from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.chroma import ChromaVectorStore

try:
    from sentence_transformers import CrossEncoder
except Exception:
    CrossEncoder = None



# CONFIG
MASTER_EMBED_FILE = Path("Master_embed.json")
MASTER_RETRIEVE_FILE = Path("Master_retrieve.json")

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


embed_config = load_json_file(MASTER_EMBED_FILE, "Master_embed.json")
retrieve_config = load_json_file(MASTER_RETRIEVE_FILE, "Master_retrieve.json")

CATEGORY = str(embed_config.get("CATEGORY", "Uncategorized"))
OPTION = int(embed_config.get("OPTION", 1))
MAX_CHUNKS = int(embed_config.get("MAX_CHUNKS", 10))
MIN_CHUNKS = int(embed_config.get("MIN_CHUNKS", 3))

QUERY = str(retrieve_config.get("QUERY", retrieve_config.get("question", ""))).strip()
if not QUERY:
    print("SYSTEM_MESSAGE_TO_USER[QUERY is missing in Master_retrieve.json]")
    sys.exit(0)

MMR = int(retrieve_config.get("MMR", 0))
MULTI_QUERY = int(retrieve_config.get("MULTI_QUERY", 0))
RERANKING = int(retrieve_config.get("RERANKING", 0))
DENSE_WEIGHT = 0.6
BM25_WEIGHT = 0.4

#IMAGE_RETRIEVE = int(retrieve_config.get("IMAGE_RETRIEVE", 0))
#RETRIEVED_IMAGES_CHUNKS = int(retrieve_config.get("RETRIEVED_IMAGES_CHUNKS", 2))

SCORE_WINDOW = 0.95 #keep very close
RRF_K = 60 #change this if you want a diffrent value RRF rrf, Rrf, RRf
TOP_K_PER_RETRIEVER = 50
RERANK_POOL_SIZE = int(retrieve_config.get("RERANK_POOL_SIZE", max(25, MAX_CHUNKS * 3)))
MMR_LAMBDA = float(retrieve_config.get("MMR_LAMBDA", 0.7))
HISTORY_TURNS = int(retrieve_config.get("HISTORY_TURNS", 3))
LLM_MODEL_NAME = str(retrieve_config.get("LLM_MODEL_NAME", "llama3"))
RERANK_MODEL_NAME = str(
    retrieve_config.get("RERANK_MODEL_NAME", "cross-encoder/ms-marco-MiniLM-L-6-v2")
)

CHAT_HISTORY = retrieve_config.get("CHAT_HISTORY", retrieve_config.get("chat_history", []))
if not isinstance(CHAT_HISTORY, list):
    CHAT_HISTORY = []

# keep the embedding model aligned with ingestion
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

Settings.embed_model = OllamaEmbedding(model_name=EMBED_MODEL_NAME)
Settings.llm = Ollama(model=LLM_MODEL_NAME, request_timeout=120.0)

# ---------------------------------------------------------
# DB DISCOVERY
# ---------------------------------------------------------
CATEGORY_DB_DIR = Path("databases") / CATEGORY

def normalize_text(s: str) -> str:
    return str(s).strip().lower().replace(".html", "")

def sort_key_for_db(p: Path) -> tuple[int, str]:
    m = re.match(r"^(\d+)", p.name)
    return (int(m.group(1)) if m else 10**9, p.name)

def discover_database_paths() -> list[Path]:
    paths: list[Path] = []
    if not CATEGORY_DB_DIR.exists():
        return paths

    versioned = sorted(
        [p for p in CATEGORY_DB_DIR.glob("[0-9]*chromadb") if p.is_dir()],
        key=sort_key_for_db,
    )
    paths.extend(versioned)

    fallback = CATEGORY_DB_DIR / "chroma_db"
    if fallback.exists() and fallback.is_dir():
        paths.append(fallback)

    unique_paths: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique_paths.append(p)

    return unique_paths

def safe_collection_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_-")
    return name[:63] if len(name) > 63 else name

def collection_has_docs(collection) -> bool:
    try:
        raw = collection.get(include=["documents", "metadatas"])
        docs = raw.get("documents", []) or []
        return any(doc and str(doc).strip() for doc in docs)
    except Exception:
        return False

def collection_candidates() -> list[str]:
    candidates = [
        "wiki_collection",
        safe_collection_name(CATEGORY),
        CATEGORY,
    ]
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out

def open_best_collection(client) -> tuple[Any | None, str | None]:
    candidates = collection_candidates()

    try:
        listed = client.list_collections()
        for item in listed:
            name = None
            if hasattr(item, "name"):
                name = getattr(item, "name", None)
            elif isinstance(item, str):
                name = item

            if name and name not in candidates:
                candidates.append(name)
    except Exception:
        pass

    for name in candidates:
        try:
            coll = client.get_collection(name=name)
            if collection_has_docs(coll):
                return coll, name
        except Exception:
            continue

    return None, None

# ---------------------------------------------------------
# TRACKING / LOADING
# ---------------------------------------------------------
def make_node_key(metadata: dict[str, Any], doc_id: str, db_path: Path) -> str:
    source_file = str(metadata.get("source_file", "unknown"))
    chunk_id = str(metadata.get("chunk_id", "x"))
    set_count = str(metadata.get("set_count", db_path.name))
    source_path = str(metadata.get("source_path", ""))
    if source_file == "unknown" and source_path:
        source_file = Path(source_path).name
    return f"{set_count}|{source_file}|{chunk_id}|{db_path.name}|{doc_id}"

def node_text_and_meta(node: TextNode) -> tuple[str, dict[str, Any]]:
    text = (node.text or "").strip()
    meta = dict(node.metadata or {})
    return text, meta

def load_all_nodes_and_dense_retrievers():
    db_paths = discover_database_paths()
    print(f"SYSTEM_MESSAGE_TO_ADMIN[Found {len(db_paths)} database set(s) for {CATEGORY}]")

    if not db_paths:
        print(f"SYSTEM_MESSAGE_TO_USER[No active databases found for category '{CATEGORY}']")
        sys.exit(0)

    all_nodes: list[TextNode] = []
    dense_retrievers = []
    seen_keys: set[str] = set()

    for db_path in db_paths:
        try:
            client = chromadb.PersistentClient(path=str(db_path))
            collection, collection_name = open_best_collection(client)

            if collection is None:
                print(f"SYSTEM_MESSAGE_TO_ADMINS[Skipped empty collection at {db_path.name}]")
                continue

            vector_store = ChromaVectorStore(chroma_collection=collection)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            index = VectorStoreIndex.from_vector_store(
                vector_store=vector_store,
                storage_context=storage_context,
            )

            dense_retrievers.append(
                index.as_retriever(
                    similarity_top_k=TOP_K_PER_RETRIEVER,
                    filters=MetadataFilters(
                        filters=[MetadataFilter(key="category", value=CATEGORY)]
                    ),
                )
            )

            raw = collection.get(include=["documents", "metadatas"])
            docs = raw.get("documents", []) or []
            metas = raw.get("metadatas", []) or []
            ids = raw.get("ids", []) or [f"row_{i}" for i in range(len(docs))]

            loaded_here = 0

            for doc_id, text, metadata in zip(ids, docs, metas):
                if not text or not str(text).strip():
                    continue

                md = dict(metadata or {})
                md.setdefault("category", CATEGORY)
                md.setdefault("source_file", md.get("source_file", "unknown"))
                md.setdefault("source_path", md.get("source_path", ""))
                md.setdefault("chunk_id", md.get("chunk_id", "x"))
                md.setdefault("set_count", md.get("set_count", db_path.name))
                md.setdefault("database_path", str(db_path))
                md.setdefault("collection_name", collection_name)

                key = make_node_key(md, str(doc_id), db_path)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                node = TextNode(
                    text=str(text),
                    metadata=md,
                    id_=key,
                )
                all_nodes.append(node)
                loaded_here += 1

            print(f"SYSTEM_MESSAGE_TO_ADMIN[{db_path.name} loaded with {loaded_here} chunks]")

        except Exception as e:
            print(f"SYSTEM_MESSAGE_TO_ADMINS[Error loading {db_path.name}: {type(e).__name__}: {str(e)[:120]}]")

    if not all_nodes:
        print("SYSTEM_MESSAGE_TO_USER[Databases exist, but no valid chunks were found inside.]")
        sys.exit(0)

    bm25_retriever = BM25Retriever.from_defaults(
        nodes=all_nodes,
        similarity_top_k=TOP_K_PER_RETRIEVER,
    )

    return dense_retrievers, bm25_retriever

# ---------------------------------------------------------
# HISTORY-AWARE QUERY REWRITE + MULTI QUERY
# ---------------------------------------------------------
def format_history(chat_history: list[dict[str, Any]], turns: int = HISTORY_TURNS) -> str:
    if not chat_history:
        return ""
    recent = chat_history[-(turns * 2):]
    lines: list[str] = []
    for item in recent:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        role = str(item.get("role", "user")).capitalize()
        lines.append(f"{role}: {content}")
    return "\n".join(lines)

def rewrite_standalone_query(question: str, chat_history: list[dict[str, Any]]) -> str:
    history_text = format_history(chat_history)
    if not history_text:
        return question.strip()

    prompt = (
        "Rewrite the user's question into one standalone search query.\n"
        "Use the chat history only for context.\n"
        "Do not answer the question.\n"
        "Return only the rewritten query.\n\n"
        f"Chat history:\n{history_text}\n\n"
        f"User question:\n{question}"
    )

    try:
        response = Settings.llm.complete(prompt)
        text = (response.text or "").strip().strip("`").strip()
        return text or question.strip()
    except Exception:
        return question.strip()

def parse_json_list_from_text(text: str) -> list[str]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass

    # fallback: split lines
    items = [line.strip("-• \t\r\n") for line in raw.splitlines()]
    items = [x for x in items if x]
    return items

def generate_multi_queries(question: str, chat_history: list[dict[str, Any]], standalone_query: str) -> list[str]:
    history_text = format_history(chat_history)
    prompt = (
        "Generate exactly 3 additional short search queries for hybrid retrieval.\n"
        "Use the chat history for context.\n"
        "Do not answer the question.\n"
        "Return only a JSON array of strings.\n\n"
        f"Chat history:\n{history_text or 'None'}\n\n"
        f"User question:\n{question}\n\n"
        f"Standalone query:\n{standalone_query}"
    )

    extras: list[str] = []
    try:
        response = Settings.llm.complete(prompt)
        extras = parse_json_list_from_text(response.text or "")
    except Exception:
        extras = []

    # Keep the standalone query always first
    queries = [standalone_query]
    queries.extend(extras)

    # de-duplicate while preserving order
    deduped: list[str] = []
    seen: set[str] = set()
    for q in queries:
        q = q.strip()
        if not q or q in seen:
            continue
        seen.add(q)
        deduped.append(q)

    # if model failed, use safe fallbacks
    if len(deduped) == 1:
        deduped.extend(
            [
                f"{standalone_query} details",
                f"{standalone_query} context",
                f"{standalone_query} table",
            ]
        )
        deduped = list(dict.fromkeys(deduped))

    return deduped[:4]  # 1 original + 3 extras

def build_query_variants(question: str, chat_history: list[dict[str, Any]]) -> list[str]:
    standalone = rewrite_standalone_query(question, chat_history)
    if MULTI_QUERY == 1:
        return generate_multi_queries(question, chat_history, standalone)
    return [standalone]

# ---------------------------------------------------------
# MMR
# ---------------------------------------------------------
def get_query_vector(text: str) -> np.ndarray:
    if hasattr(Settings.embed_model, "get_query_embedding"):
        vec = Settings.embed_model.get_query_embedding(text)
    else:
        vec = Settings.embed_model.get_text_embedding(text)

    arr = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    return arr / norm if norm else arr

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0

def apply_mmr_to_nodes(query: str, nodes: list[TextNode], score_map: dict[str, float], lambda_param: float = MMR_LAMBDA) -> list[TextNode]:
    if len(nodes) <= 1:
        return nodes

    qvec = get_query_vector(query)
    node_vecs: dict[str, np.ndarray] = {}
    node_by_key: dict[str, TextNode] = {}

    for node in nodes:
        key = node.node_id or make_node_key(dict(node.metadata or {}), "x", Path(dict(node.metadata or {}).get("database_path", ".")))
        text, _ = node_text_and_meta(node)
        if not text:
            continue
        node_vecs[key] = get_query_vector(text)
        node_by_key[key] = node

    if not node_by_key:
        return nodes

    selected: list[str] = []
    remaining = list(node_by_key.keys())

    # start with the most relevant
    first = max(remaining, key=lambda k: score_map.get(k, 0.0))
    selected.append(first)
    remaining.remove(first)

    while remaining:
        best_key = None
        best_score = -1e18

        for key in remaining:
            relevance = score_map.get(key, 0.0)
            diversity = 0.0
            for sel in selected:
                diversity = max(diversity, cosine_similarity(node_vecs[key], node_vecs[sel]))
            mmr_score = (lambda_param * relevance) - ((1.0 - lambda_param) * diversity)
            if mmr_score > best_score:
                best_score = mmr_score
                best_key = key

        if best_key is None:
            break

        selected.append(best_key)
        remaining.remove(best_key)
        if len(selected) >= len(nodes):
            break

    return [node_by_key[k] for k in selected if k in node_by_key]

# ---------------------------------------------------------
# RETRIEVAL + RRF
# ---------------------------------------------------------
def unique_by_key(nodes_with_scores: list[TextNode]) -> list[TextNode]:
    best: dict[str, TextNode] = {}
    best_scores: dict[str, float] = {}

    for node in nodes_with_scores:
        text, md = node_text_and_meta(node)
        key = node.node_id or make_node_key(md, "x", Path(md.get("database_path", ".")))
        score = float(getattr(node, "score", 0.0) or 0.0)
        if key not in best or score > best_scores.get(key, -1e18):
            best[key] = node
            best_scores[key] = score

    ordered = sorted(best.values(), key=lambda n: float(getattr(n, "score", 0.0) or 0.0), reverse=True)
    return ordered

def retrieve_dense_for_query(query: str, dense_retrievers) -> list[TextNode]:
    all_dense: list[TextNode] = []
    for retriever in dense_retrievers:
        try:
            all_dense.extend(retriever.retrieve(query))
        except Exception as e:
            print(f"SYSTEM_MESSAGE_TO_ADMINS[Dense retrieve error: {type(e).__name__}: {str(e)[:80]}]")
    dense = unique_by_key(all_dense)

    if MMR == 1:
        score_map = {}
        for node in dense:
            key = node.node_id
            score_map[key] = float(getattr(node, "score", 0.0) or 0.0)
        dense = apply_mmr_to_nodes(query, dense, score_map)

    return dense

def retrieve_bm25_for_query(query: str, bm25_retriever) -> list[TextNode]:
    try:
        nodes = bm25_retriever.retrieve(query)
        return unique_by_key(nodes)
    except Exception as e:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[BM25 retrieve error: {type(e).__name__}: {str(e)[:80]}]")
        return []

def base_result_from_node(node: TextNode) -> dict[str, Any]:
    text, md = node_text_and_meta(node)
    return {
        "key": node.node_id,
        "text": text,
        "metadata": md,
        "source_file": md.get("source_file", "unknown"),
        "source_path": md.get("source_path", ""),
        "chunk_id": md.get("chunk_id", "x"),
        "set_count": md.get("set_count", "?"),
        "dense_score": 0.0,
        "bm25_score": 0.0,
        "rrf_score": 0.0,
        "raw_rerank_score": None,
        "active_score": 0.0,
        "score_source": "rrf",
    }

def fuse_with_rrf(query_variants: list[str], dense_retrievers, bm25_retriever) -> list[dict[str, Any]]:
    pool: dict[str, dict[str, Any]] = {}

    for q in query_variants:
        dense_nodes = retrieve_dense_for_query(q, dense_retrievers)
        bm25_nodes = retrieve_bm25_for_query(q, bm25_retriever)

        # dense list
        for rank, node in enumerate(dense_nodes, start=1):
            key = node.node_id
            if key not in pool:
                pool[key] = base_result_from_node(node)
            pool[key]["dense_score"] = max(pool[key]["dense_score"], float(getattr(node, "score", 0.0) or 0.0))
            pool[key]["rrf_score"] += DENSE_WEIGHT * (1.0 / (RRF_K + rank))

        # bm25 list
        for rank, node in enumerate(bm25_nodes, start=1):
            key = node.node_id
            if key not in pool:
                pool[key] = base_result_from_node(node)
            pool[key]["bm25_score"] = max(pool[key]["bm25_score"], float(getattr(node, "score", 0.0) or 0.0))
            pool[key]["rrf_score"] += BM25_WEIGHT * (1.0 / (RRF_K + rank))

    results = list(pool.values())
    for item in results:
        item["active_score"] = float(item["rrf_score"])
        item["score_source"] = "rrf"

    results.sort(key=lambda x: x["active_score"], reverse=True)
    return results

# ---------------------------------------------------------
# RERANKING
# ---------------------------------------------------------
_RERANKER = None

def get_cross_encoder():
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER
    if CrossEncoder is None:
        return None

    try:
        _RERANKER = CrossEncoder(RERANK_MODEL_NAME)
    except Exception as e:
        print(f"SYSTEM_MESSAGE_TO_ADMINS[CrossEncoder unavailable: {str(e)[:80]}]")
        _RERANKER = None
    return _RERANKER

def sigmoid(x: float) -> float:
    x = max(min(float(x), 20.0), -20.0)
    return 1.0 / (1.0 + math.exp(-x))

def rerank_with_llm(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reranked = []
    for item in candidates:
        text = item["text"]
        prompt = (
            "You are reranking retrieval chunks for a question answering system.\n"
            "Return only one number from 0 to 100.\n"
            "0 means irrelevant, 100 means extremely relevant.\n\n"
            f"Query:\n{query}\n\n"
            f"Chunk:\n{text[:3500]}"
        )
        try:
            response = Settings.llm.complete(prompt)
            raw = str(response.text or "").strip()
            match = re.search(r"-?\d+(?:\.\d+)?", raw)
            score_0_100 = float(match.group(0)) if match else 0.0
        except Exception:
            score_0_100 = 0.0

        item = dict(item)
        item["raw_rerank_score"] = score_0_100
        item["active_score"] = max(0.0, min(1.0, score_0_100 / 100.0))
        item["score_source"] = "rerank"
        reranked.append(item)

    reranked.sort(key=lambda x: x["active_score"], reverse=True)
    return reranked

def rerank_candidates(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return candidates

    pool_size = min(len(candidates), RERANK_POOL_SIZE)
    pool = candidates[:pool_size]
    tail = candidates[pool_size:]

    model = get_cross_encoder()
    if model is not None:
        pairs = [(query, item["text"]) for item in pool]
        try:
            raw_scores = model.predict(pairs)
            reranked = []
            for item, raw in zip(pool, raw_scores):
                new_item = dict(item)
                new_item["raw_rerank_score"] = float(raw)
                new_item["active_score"] = sigmoid(float(raw))
                new_item["score_source"] = "rerank"
                reranked.append(new_item)
            reranked.sort(key=lambda x: x["active_score"], reverse=True)
        except Exception as e:
            print(f"SYSTEM_MESSAGE_TO_ADMINS[Reranker error, falling back to LLM: {str(e)[:80]}]")
            reranked = rerank_with_llm(query, pool)
    else:
        reranked = rerank_with_llm(query, pool)

    # keep the rest by RRF score
    for item in tail:
        new_item = dict(item)
        new_item["active_score"] = float(new_item["rrf_score"])
        new_item["score_source"] = "rrf"
        reranked.append(new_item)

    reranked.sort(key=lambda x: x["active_score"], reverse=True)
    return reranked

# ---------------------------------------------------------
# FINAL WINDOW
# ---------------------------------------------------------
def select_display_chunks(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not results:
        return []

    ordered = sorted(results, key=lambda x: x["active_score"], reverse=True)

    if len(ordered) <= MIN_CHUNKS:
        return ordered

    chosen = ordered[:MIN_CHUNKS]
    anchor_score = chosen[-1]["active_score"]

    upper = min(len(ordered), MAX_CHUNKS)
    for item in ordered[MIN_CHUNKS:upper]:
        if item["active_score"] >= (anchor_score * SCORE_WINDOW):
            chosen.append(item)
        else:
            break

    return chosen

# ---------------------------------------------------------
# PRINTING
# ---------------------------------------------------------
def print_query_variants(query_variants: list[str]) -> None:
    print("\nQuery variants used:")
    for i, q in enumerate(query_variants, start=1):
        print(f"  {i}. {q}")

def print_results(original_query: str, query_variants: list[str], results: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 100)
    print(f"CATEGORY: {CATEGORY}")
    print(f"OPTION: {OPTION}")
    print(f"MMR: {MMR}")
    print(f"MULTI_QUERY: {MULTI_QUERY}")
    print(f"RERANKING: {RERANKING}")
    print(f"QUERY: {original_query}")
    print("=" * 100)

    print_query_variants(query_variants)

    if not results:
        print("\nSYSTEM_MESSAGE_TO_USER[No highly relevant chunks found.]")
        return

    print(f"\nSYSTEM_MESSAGE_TO_USER[Retrieved {len(results)} chunks.]\n")

    for i, item in enumerate(results, start=1):
        print("-" * 100)
        print(
            f"[{i}] score={item['active_score']:.4f} | "
            f"rrf={item['rrf_score']:.4f} | "
            f"dense={item['dense_score']:.4f} | "
            f"bm25={item['bm25_score']:.4f}"
            + (
                f" | rerank_raw={float(item['raw_rerank_score']):.4f}"
                if item.get("raw_rerank_score") is not None
                else ""
            )
        )
        print(f"source_file: {item['source_file']}")
        print(f"chunk_id   : {item['chunk_id']}")
        print(f"set_count  : {item['set_count']}")
        if item["source_path"]:
            print(f"source_path: {item['source_path']}")
        print("\nCHUNK:\n")
        print(item["text"])
        print()

    print("-" * 100)

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    dense_retrievers, bm25_retriever = load_all_nodes_and_dense_retrievers()

    query_variants = build_query_variants(QUERY, CHAT_HISTORY)
    fused = fuse_with_rrf(query_variants, dense_retrievers, bm25_retriever)

    if RERANKING == 1:
        fused = rerank_candidates(query_variants[0], fused)

    final_results = select_display_chunks(fused)
    print_results(QUERY, query_variants, final_results)


if __name__ == "__main__":
    main()