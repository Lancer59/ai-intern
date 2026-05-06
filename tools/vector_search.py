"""
Semantic code search tool using ChromaDB + local embeddings.

Indexes the target workspace on first use and answers queries like
"Where is the authentication logic?" by returning the most relevant
code chunks — no grep pattern needed.

Embedding priority:
  1. OllamaEmbeddings (nomic-embed-text) — fully local, no API key
  2. OpenAIEmbeddings                    — fallback if Ollama unavailable

Index is persisted in agent_data/chroma/<workspace_hash>/ and rebuilt
automatically when the workspace path changes between sessions.
"""

import asyncio
import hashlib
import logging
import os
import pathlib

from langchain_core.tools import tool

logger = logging.getLogger("vector_search")

# Source file extensions to index (mirrors _MAP_EXTENSIONS in coding_assistant.py)
_INDEX_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".cs",
    ".cpp", ".c", ".h", ".rb", ".php", ".swift", ".kt", ".scala",
    ".html", ".css", ".scss", ".json", ".yaml", ".yml", ".toml",
    ".md", ".sh",
}
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", "coverage",
}
_CHROMA_BASE = os.path.join("agent_data", "chroma")
_MAX_FILE_BYTES = 200_000   # skip files larger than 200 KB
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 100
_TOP_K = 5


def _workspace_id(workspace_path: str) -> str:
    """Short stable ID for a workspace path used as the Chroma collection name."""
    return "ws_" + hashlib.md5(workspace_path.encode()).hexdigest()[:12]


def _get_embeddings():
    """Return the best available embedding model."""
    try:
        from langchain_ollama import OllamaEmbeddings
        emb = OllamaEmbeddings(
            model="nomic-embed-text",
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
        # Quick connectivity check
        emb.embed_query("ping")
        logger.info("Vector search: using OllamaEmbeddings (nomic-embed-text)")
        return emb
    except Exception:
        pass

    try:
        from langchain_openai import OpenAIEmbeddings
        emb = OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        logger.info("Vector search: using OpenAIEmbeddings (text-embedding-3-small)")
        return emb
    except Exception:
        pass

    raise RuntimeError(
        "No embedding backend available. "
        "Either start Ollama with 'ollama pull nomic-embed-text' "
        "or set OPENAI_API_KEY."
    )


def _collect_documents(workspace_path: str):
    """Walk workspace and return LangChain Documents for all source files."""
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
    )
    docs = []
    for root, dirs, files in os.walk(workspace_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            ext = pathlib.Path(fname).suffix.lower()
            if ext not in _INDEX_EXTENSIONS:
                continue
            fpath = os.path.join(root, fname)
            if os.path.getsize(fpath) > _MAX_FILE_BYTES:
                continue
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                rel = os.path.relpath(fpath, workspace_path)
                chunks = splitter.create_documents(
                    [content],
                    metadatas=[{"source": rel, "workspace": workspace_path}],
                )
                docs.extend(chunks)
            except Exception as e:
                logger.debug(f"Skipping {fpath}: {e}")
    return docs


def _build_or_load_index(workspace_path: str):
    """Return a Chroma vectorstore for the workspace, building it if needed."""
    from langchain_chroma import Chroma

    collection_name = _workspace_id(workspace_path)
    persist_dir = os.path.join(_CHROMA_BASE, collection_name)
    embeddings = _get_embeddings()

    # If persisted index exists, load it
    if os.path.isdir(persist_dir):
        logger.info(f"Vector search: loading existing index from {persist_dir}")
        return Chroma(
            collection_name=collection_name,
            persist_directory=persist_dir,
            embedding_function=embeddings,
        )

    # Build fresh index
    logger.info(f"Vector search: indexing {workspace_path} ...")
    os.makedirs(persist_dir, exist_ok=True)
    docs = _collect_documents(workspace_path)
    if not docs:
        raise ValueError(f"No indexable source files found in {workspace_path}")

    store = Chroma.from_documents(
        documents=docs,
        embedding=embeddings,
        collection_name=collection_name,
        persist_directory=persist_dir,
    )
    logger.info(f"Vector search: indexed {len(docs)} chunks into {persist_dir}")
    return store


# Module-level cache: workspace_path -> Chroma instance
_index_cache: dict = {}


@tool
async def semantic_code_search(query: str, workspace_path: str, top_k: int = 5) -> str:
    """Search the codebase semantically — find relevant code by meaning, not exact keywords.

    Use this instead of grep when you need to locate logic by concept, e.g.:
      "Where is the authentication logic?"
      "Find the database connection setup"
      "Which file handles payment processing?"

    The index is built automatically on first use and cached for the session.
    Requires either Ollama (nomic-embed-text) or OPENAI_API_KEY for embeddings.

    :param query: Natural language description of what you're looking for.
    :param workspace_path: Absolute path to the target repository root.
    :param top_k: Number of results to return (default 5, max 10).
    :return: Formatted list of matching code chunks with file paths and line context.
    """
    def _run():
        k = min(max(1, top_k), 10)

        if workspace_path not in _index_cache:
            _index_cache[workspace_path] = _build_or_load_index(workspace_path)

        store = _index_cache[workspace_path]
        results = store.similarity_search(query, k=k)

        if not results:
            return "No relevant code found for that query."

        lines = [f"Semantic search results for: '{query}'\n"]
        for i, doc in enumerate(results, 1):
            source = doc.metadata.get("source", "unknown")
            lines.append(f"--- [{i}] {source} ---")
            lines.append(doc.page_content.strip())
            lines.append("")
        return "\n".join(lines)

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        logger.error(f"semantic_code_search failed: {e}")
        return f"Error: {e}"


@tool
async def rebuild_code_index(workspace_path: str) -> str:
    """Force a full rebuild of the semantic search index for the workspace.

    Use this after large refactors or when the index feels stale.

    :param workspace_path: Absolute path to the target repository root.
    :return: Confirmation with the number of chunks indexed.
    """
    def _run():
        import shutil
        collection_name = _workspace_id(workspace_path)
        persist_dir = os.path.join(_CHROMA_BASE, collection_name)

        # Remove existing index
        if os.path.isdir(persist_dir):
            shutil.rmtree(persist_dir)
        _index_cache.pop(workspace_path, None)

        # Rebuild
        store = _build_or_load_index(workspace_path)
        _index_cache[workspace_path] = store
        count = store._collection.count()
        return f"Index rebuilt: {count} chunks indexed for {workspace_path}"

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        logger.error(f"rebuild_code_index failed: {e}")
        return f"Error: {e}"
