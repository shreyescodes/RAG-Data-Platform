import os
from typing import List

import openai

from ..config import settings


class EmbeddingService:
    def __init__(self, model: str = None):
        self.model = model or settings.EMBEDDING_MODEL
        # Use instance-scoped client — avoid mutating the global openai module state
        self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def get_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text"""
        try:
            response = self.client.embeddings.create(input=text, model=self.model)
            return response.data[0].embedding
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return []

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        try:
            response = self.client.embeddings.create(input=texts, model=self.model)
            return [item.embedding for item in response.data]
        except Exception as e:
            print(f"Error generating batch embeddings: {e}")
            return []
