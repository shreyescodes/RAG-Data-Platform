import os
from typing import List

from sentence_transformers import SentenceTransformer
from config import settings


class EmbeddingService:
    def __init__(self, model: str = None):
        self.model_name = model or settings.EMBEDDING_MODEL
        # Load the local sentence transformer model
        self.model = SentenceTransformer(self.model_name)

    def get_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text"""
        try:
            # Output is a numpy array, convert to list of floats
            embedding = self.model.encode(text)
            return embedding.tolist()
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return []

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        try:
            embeddings = self.model.encode(texts)
            return embeddings.tolist()
        except Exception as e:
            print(f"Error generating batch embeddings: {e}")
            return []
