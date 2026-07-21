"""Backward-compatible shim. The embedding/AI layer now lives in app.providers."""
from app.providers import cosine_similarity, get_embedder
from app.providers.stub import StubEmbedder

__all__ = ["cosine_similarity", "get_embedder", "StubEmbedder"]
