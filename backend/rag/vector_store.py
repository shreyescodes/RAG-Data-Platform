import faiss
import numpy as np
import pickle
import os
from typing import List, Tuple, Dict
from .embeddings import EmbeddingService


class FAISSVectorStore:
    def __init__(self, dimension: int = 1536, index_path: str = "data/faiss_index"):
        self.dimension = dimension
        self.index_path = index_path
        self.index = faiss.IndexFlatL2(dimension)
        self.metadata = []
        self.embedding_service = EmbeddingService()

        os.makedirs(os.path.dirname(index_path) if os.path.dirname(index_path) else "data", exist_ok=True)

        if os.path.exists(f"{index_path}.index"):
            self.load_index()

    def add_documents(self, texts: List[str], metadata: List[Dict]):
        """Add documents with their embeddings to the vector store"""
        embeddings = self.embedding_service.get_embeddings_batch(texts)

        if embeddings:
            embeddings_array = np.array(embeddings).astype('float32')
            self.index.add(embeddings_array)
            self.metadata.extend(metadata)
            self.save_index()

    def search(self, query: str, k: int = 5) -> List[Tuple[Dict, float]]:
        """Search for similar documents"""
        query_embedding = self.embedding_service.get_embedding(query)

        if not query_embedding:
            return []

        query_vector = np.array([query_embedding]).astype('float32')
        distances, indices = self.index.search(query_vector, min(k, self.index.ntotal))

        results = []
        for idx, distance in zip(indices[0], distances[0]):
            if idx < len(self.metadata):
                results.append((self.metadata[idx], float(distance)))

        return results

    def save_index(self):
        """Save FAISS index and metadata to disk"""
        faiss.write_index(self.index, f"{self.index_path}.index")
        with open(f"{self.index_path}.metadata", 'wb') as f:
            pickle.dump(self.metadata, f)

    def load_index(self):
        """Load FAISS index and metadata from disk"""
        try:
            self.index = faiss.read_index(f"{self.index_path}.index")
            with open(f"{self.index_path}.metadata", 'rb') as f:
                self.metadata = pickle.load(f)
        except Exception as e:
            print(f"Error loading index: {e}")

    def get_stats(self) -> Dict:
        """Get statistics about the vector store"""
        return {
            "total_documents": self.index.ntotal,
            "dimension": self.dimension,
            "metadata_count": len(self.metadata)
        }
