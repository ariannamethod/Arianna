import os
import glob
import json
import hashlib
import asyncio
import logging
from functools import partial

from pinecone import Pinecone
import openai
from tenacity import retry, stop_after_attempt, wait_fixed

try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover - fallback for older versions
    AsyncOpenAI = None

logger = logging.getLogger(__name__)

VECTOR_META_PATH = "vector_store.meta.json"
EMBED_DIM = 1536  # For OpenAI ada-002

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX = os.getenv("PINECONE_INDEX")
PINECONE_ENV = os.getenv("PINECONE_ENV")

pc = None
vector_index = None


def init_pinecone():
    """Initialize Pinecone connection if it hasn't been already."""
    global pc, vector_index
    if pc is not None and vector_index is not None:
        return
    if not PINECONE_API_KEY or not PINECONE_INDEX:
        raise RuntimeError("PINECONE_API_KEY and PINECONE_INDEX must be set")
    kwargs = {"api_key": PINECONE_API_KEY}
    if PINECONE_ENV:
        kwargs["environment"] = PINECONE_ENV
    pc = Pinecone(**kwargs)
    if PINECONE_INDEX not in [x["name"] for x in pc.list_indexes()]:
        pc.create_index(name=PINECONE_INDEX, dimension=EMBED_DIM, metric="cosine")
    vector_index = pc.Index(PINECONE_INDEX)

def file_hash(fname):
    with open(fname, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def scan_files(path="config/*.md"):
    files = {}
    for fname in glob.glob(path):
        files[fname] = file_hash(fname)
    return files

def load_vector_meta():
    if os.path.isfile(VECTOR_META_PATH):
        with open(VECTOR_META_PATH, "r") as f:
            return json.load(f)
    return {}

def save_vector_meta(meta):
    with open(VECTOR_META_PATH, "w") as f:
        json.dump(meta, f)

@retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
async def safe_embed(text, openai_api_key):
    return await get_embedding(text, openai_api_key)


async def get_embedding(text, openai_api_key):
    """Return embedding for ``text`` using OpenAI."""
    if AsyncOpenAI:
        client = AsyncOpenAI(api_key=openai_api_key)
        res = await client.embeddings.create(
            model="text-embedding-ada-002",
            input=text,
        )
        return res.data[0].embedding

    def embed_sync() -> list[float]:
        openai.api_key = openai_api_key
        res = openai.embeddings.create(
            model="text-embedding-ada-002",
            input=text,
        )
        return res.data[0].embedding

    return await asyncio.to_thread(embed_sync)

def chunk_text(text, chunk_size=900, overlap=120):
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks

async def vectorize_all_files(openai_api_key, force=False, on_message=None):
    if pc is None or vector_index is None:
        init_pinecone()
    current = scan_files()
    previous = load_vector_meta()
    changed = [f for f in current if (force or current[f] != previous.get(f))]
    new = [f for f in current if f not in previous]
    removed = [f for f in previous if f not in current]

    loop = asyncio.get_running_loop()
    upserted_ids: list[str] = []
    errors: list[str] = []
    for fname in current:
        if fname not in changed and fname not in new and not force:
            continue
        with open(fname, "r", encoding="utf-8") as f:
            text = f.read()
        chunks = chunk_text(text)
        for idx, chunk in enumerate(chunks):
            meta_id = f"{fname}:{idx}"
            try:
                emb = await safe_embed(chunk, openai_api_key)
                upsert_partial = partial(
                    vector_index.upsert,
                    vectors=[
                        {
                            "id": meta_id,
                            "values": emb,
                            "metadata": {
                                "file": fname,
                                "chunk": idx,
                                "hash": current[fname],
                            },
                        }
                    ],
                )
                await loop.run_in_executor(None, upsert_partial)
                upserted_ids.append(meta_id)
            except Exception as e:
                logger.exception("Failed to upsert %s", meta_id)
                msg = f"Pinecone error: {e}"
                errors.append(msg)
                if on_message:
                    try:
                        await on_message(msg)
                    except Exception as msg_exc:  # pragma: no cover
                        logger.exception("on_message failed: %s", msg_exc)
                continue

    deleted_ids = []
    for fname in removed:
        for idx in range(50):
            meta_id = f"{fname}:{idx}"
            try:
                delete_partial = partial(vector_index.delete, ids=[meta_id])
                await loop.run_in_executor(None, delete_partial)
                deleted_ids.append(meta_id)
            except Exception as e:
                logger.exception("Failed to delete %s", meta_id)
                msg = f"Delete error: {e}"
                errors.append(msg)
                if on_message:
                    try:
                        await on_message(msg)
                    except Exception as msg_exc:  # pragma: no cover
                        logger.exception("on_message failed: %s", msg_exc)

    save_vector_meta(current)
    if on_message:
        await on_message(
            f"Vectorization complete. Added/changed: {', '.join(changed + new) if changed or new else '-'}; removed: {', '.join(removed) if removed else '-'}"
        )
    return {"upserted": upserted_ids, "deleted": deleted_ids, "errors": errors}

async def semantic_search(query, openai_api_key, top_k=5):
    if pc is None or vector_index is None:
        init_pinecone()
    emb = await safe_embed(query, openai_api_key)
    res = vector_index.query(vector=emb, top_k=top_k, include_metadata=True)
    chunks = []
    matches = getattr(res, "matches", [])
    for match in matches:
        metadata = match.get("metadata", {})
        fname = metadata.get("file")
        chunk_idx = metadata.get("chunk")
        try:
            with open(fname, "r", encoding="utf-8") as f:
                all_chunks = chunk_text(f.read())
                chunk_text_ = all_chunks[chunk_idx] if chunk_idx is not None and chunk_idx < len(all_chunks) else ""
        except Exception:
            chunk_text_ = ""
        if chunk_text_:
            chunks.append(chunk_text_)
    return chunks
