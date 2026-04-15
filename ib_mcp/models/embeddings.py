"""Text embedding models for RAG and similarity search.

Supports: BAAI/bge-large-en-v1.5, sentence-transformers/all-MiniLM-L6-v2
Used by strategies: S36 (Contrastive Fingerprints), S40 (RAG Pattern Lookup)
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from ib_mcp.models import MODEL_CACHE_DIR, registry

logger = logging.getLogger(__name__)

# ChromaDB storage path
VECTOR_DB_PATH = MODEL_CACHE_DIR / "chroma_db"
VECTOR_DB_PATH.mkdir(exist_ok=True)


@dataclass
class EmbeddingResult:
    """Result from embedding computation."""
    text: str
    embedding: list[float]
    model: str
    dimension: int


def embed_texts(
    texts: list[str],
    model_key: str = "bge_large",
    normalize: bool = True,
) -> list[EmbeddingResult]:
    """Compute embeddings for a list of texts.

    Args:
        texts: List of text strings to embed
        model_key: "bge_large" (1024-dim, high quality) or
                   "minilm" (384-dim, fast)
        normalize: Whether to L2-normalize embeddings (recommended for cosine sim)

    Returns:
        List of EmbeddingResult with embedding vectors
    """
    model = registry.get_model(model_key)
    embeddings = model.encode(
        texts, normalize_embeddings=normalize, show_progress_bar=False,
    )

    return [
        EmbeddingResult(
            text=text,
            embedding=emb.tolist(),
            model=model_key,
            dimension=len(emb),
        )
        for text, emb in zip(texts, embeddings)
    ]


def compute_similarity(
    query_embedding: list[float],
    candidate_embeddings: list[list[float]],
) -> list[float]:
    """Compute cosine similarities between a query and candidates."""
    query = np.array(query_embedding)
    candidates = np.array(candidate_embeddings)

    # Cosine similarity (assumes normalized embeddings)
    similarities = candidates @ query
    return similarities.tolist()


def build_scanner_day_summary(
    date: str,
    scanner_data: dict,
    outcome: dict | None = None,
) -> str:
    """Build a natural language summary of a scanner day for embedding.

    Args:
        date: Date string YYYYMMDD
        scanner_data: Scanner results dict (from get_scanner_results)
        outcome: Optional dict with end-of-day outcomes (top gainer returns, etc.)

    Returns:
        Text summary suitable for embedding
    """
    parts = [f"Date: {date}"]

    # Extract dominant themes
    gainer_symbols = set()
    loser_symbols = set()
    volume_symbols = set()

    if isinstance(scanner_data, list):
        for scanner in scanner_data:
            name = scanner.get("scanner", "")
            symbols = [s["symbol"] for s in scanner.get("symbols", [])[:10]]
            if "Gain" in name or "PctGain" in name:
                gainer_symbols.update(symbols)
                parts.append(f"Gainers ({name}): {', '.join(symbols[:5])}")
            elif "Loss" in name or "PctLoss" in name:
                loser_symbols.update(symbols)
                parts.append(f"Losers ({name}): {', '.join(symbols[:5])}")
            elif "Volume" in name:
                volume_symbols.update(symbols)
                parts.append(f"Volume leaders ({name}): {', '.join(symbols[:5])}")

    # Overlap analysis
    volume_gainers = volume_symbols & gainer_symbols
    volume_losers = volume_symbols & loser_symbols
    if volume_gainers:
        parts.append(f"Volume + Gain overlap: {', '.join(list(volume_gainers)[:5])}")
    if volume_losers:
        parts.append(f"Volume + Loss overlap: {', '.join(list(volume_losers)[:5])}")

    # Bull/bear ratio
    if gainer_symbols or loser_symbols:
        ratio = len(gainer_symbols) / max(len(loser_symbols), 1)
        parts.append(f"Bull/bear ratio: {ratio:.2f}")

    if outcome:
        parts.append(f"Outcome: {json.dumps(outcome)}")

    return " | ".join(parts)


class ScannerDayIndex:
    """Vector index of historical scanner days for similarity search.

    Used by Strategy 36 (Contrastive Fingerprints) and Strategy 40 (RAG).
    """

    def __init__(self, model_key: str = "bge_large"):
        self.model_key = model_key
        self.index_path = VECTOR_DB_PATH / f"scanner_days_{model_key}.json"
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        if self.index_path.exists():
            with open(self.index_path) as f:
                self._entries = json.load(f)
            logger.info(f"Loaded {len(self._entries)} scanner day entries")

    def _save(self):
        with open(self.index_path, "w") as f:
            json.dump(self._entries, f)

    def add_day(
        self,
        date: str,
        summary: str,
        scanner_data: dict | None = None,
        outcome: dict | None = None,
    ):
        """Add a scanner day to the index.

        Args:
            date: Date string YYYYMMDD
            summary: Natural language summary of the day
            scanner_data: Raw scanner data (stored for retrieval)
            outcome: End-of-day outcome data
        """
        # Check if date already exists
        for entry in self._entries:
            if entry["date"] == date:
                logger.info(f"Date {date} already in index, updating")
                self._entries.remove(entry)
                break

        # Compute embedding
        results = embed_texts([summary], model_key=self.model_key)
        embedding = results[0].embedding

        self._entries.append({
            "date": date,
            "summary": summary,
            "embedding": embedding,
            "outcome": outcome or {},
            "indexed_at": datetime.now().isoformat(),
        })
        self._save()

    def find_similar_days(
        self,
        query_summary: str,
        top_k: int = 3,
        min_similarity: float = 0.5,
    ) -> list[dict]:
        """Find historical days most similar to the query.

        Args:
            query_summary: Today's scanner state summary
            top_k: Number of similar days to return
            min_similarity: Minimum cosine similarity threshold

        Returns:
            List of dicts with date, summary, similarity, outcome
        """
        if not self._entries:
            return []

        query_emb = embed_texts([query_summary], model_key=self.model_key)[0].embedding
        candidate_embs = [e["embedding"] for e in self._entries]

        similarities = compute_similarity(query_emb, candidate_embs)

        # Rank by similarity
        scored = list(zip(self._entries, similarities))
        scored.sort(key=lambda x: x[1], reverse=True)

        results = []
        for entry, sim in scored[:top_k]:
            if sim >= min_similarity:
                results.append({
                    "date": entry["date"],
                    "summary": entry["summary"],
                    "similarity": round(float(sim), 4),
                    "outcome": entry.get("outcome", {}),
                })

        return results

    def count(self) -> int:
        return len(self._entries)
