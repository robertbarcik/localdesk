from typing import Optional

import chromadb

from app.config import VECTORSTORE_COLLECTION, VECTORSTORE_PATH
from app.rag.embeddings import embed_query

_chroma_client: Optional[chromadb.ClientAPI] = None


def _get_collection() -> chromadb.Collection:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=VECTORSTORE_PATH)
    return _chroma_client.get_collection(VECTORSTORE_COLLECTION)


def retrieve(query: str, n_results: int = 3) -> list[dict]:
    """Retrieve the top-n most relevant chunks for a query."""
    collection = _get_collection()
    query_embedding = embed_query(query)
    results = collection.query(query_embeddings=[query_embedding], n_results=n_results)
    chunks = []
    for i in range(len(results["ids"][0])):
        chunks.append(
            {
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "source": results["metadatas"][0][i].get("source", "unknown"),
                "distance": results["distances"][0][i] if results.get("distances") else None,
            }
        )
    return chunks
