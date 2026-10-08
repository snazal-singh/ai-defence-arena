import logging
from langchain.schema import Document
from langchain_elasticsearch.vectorstores import ElasticsearchStore
try:
    from langchain_ollama import OllamaEmbeddings
except ImportError:
    from langchain_community.embeddings import OllamaEmbeddings
from .index_manager import ElasticIndexManager
from .client import ElasticClient
import unicodedata
from app.core.config import settings

class ElasticDocumentManager:
    def __init__(self, index_name):
        self.index_name = index_name
        self.client = ElasticClient().client
        self.index_manager = ElasticIndexManager()
        self.embeddings = OllamaEmbeddings(
            model=settings.OLLAMA_EMBEDDING_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
        )

    def store_documents(self, documents):
        try:
            # Pre-process documents for better Unicode handling
            processed_documents = self._preprocess_documents(documents)
            
            # Create index if not exists
            self.index_manager.create_index(self.index_name)
            
            # Store documents with embeddings in local Elasticsearch
            vector_store = ElasticsearchStore.from_documents(
                processed_documents,
                es_url=settings.ES_BASE_URL,
                index_name=self.index_name,
                embedding=self.embeddings,
                vector_query_field="vector"
            )
            
            # Refresh index for immediate visibility
            self.index_manager.refresh_index(self.index_name)
            logging.info(f"Stored {len(processed_documents)} documents in {self.index_name}")
            return vector_store
        except Exception as e:
            logging.error(f"Error storing documents: {e}")
            raise
        
    def _preprocess_documents(self, documents):
        """Preprocess documents for better Unicode/Hindi handling"""
        processed = []
        
        for doc in documents:
            try:
                # Ensure proper Unicode normalization
                content = doc.page_content
                if content:
                    # Normalize Unicode
                    content = unicodedata.normalize("NFC", content)
                    
                    # Ensure UTF-8 encoding
                    if isinstance(content, bytes):
                        content = content.decode('utf-8', errors='ignore')
                    
                    # Create new document with processed content
                    processed_doc = Document(
                        page_content=content,
                        metadata=doc.metadata
                    )
                    processed.append(processed_doc)
                    
            except Exception as e:
                logging.error(f"Error preprocessing document: {e}")
                # Include original document if preprocessing fails
                processed.append(doc)
        
        return processed

    def update_documents(self, documents):
        # TODO: Implement update logic
        pass

    def delete_documents(self, document_ids):
        # TODO: Implement delete logic
        pass

    def delete_documents_by_filename(self, filename: str) -> int:
        """Delete all documents in the index whose metadata.source matches the given filename.

        Returns the number of documents deleted.
        """
        try:
            response = self.client.delete_by_query(
                index=self.index_name,
                body={"query": {"term": {"metadata.source": filename}}},
                refresh=True,
            )
            deleted = response.get("deleted", 0)
            logging.info(f"Deleted {deleted} documents with filename '{filename}' from {self.index_name}")
            return deleted
        except Exception as e:
            logging.error(f"Error deleting documents by filename '{filename}': {e}")
            raise