from .client import ElasticClient
import logging
import time

class ElasticIndexManager:
    def __init__(self):
        self.client = ElasticClient().client
        # Enhanced mapping with better Unicode support
        self.default_mapping = {
            "settings": {
                "analysis": {
                    "analyzer": {
                        "hindi_analyzer": {
                            "tokenizer": "standard",
                            "filter": [
                                "lowercase",
                                "stop",
                                "hindi_normalization"
                            ]
                        },
                        "multilingual_analyzer": {
                            "tokenizer": "standard",
                            "filter": [
                                "lowercase",
                                "asciifolding"
                            ]
                        }
                    }
                },
                "index": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0
                }
            },
            "mappings": {
                "properties": {
                    "vector": {"type": "dense_vector", "dims": 1024},
                    "text": {
                        "type": "text",
                        "fields": {
                            "hindi": {
                                "type": "text",
                                "analyzer": "hindi_analyzer"
                            }
                        }
                    },
                    "keyword_content": {"type": "keyword"},
                    "metadata": {
                        "properties": {
                            "filename": {"type": "keyword"},
                            "source": {"type": "keyword"},
                            "page": {"type": "integer"},
                            "header": {
                                "type": "text",
                                "analyzer": "multilingual_analyzer"
                            },
                            "content_type": {"type": "keyword"},
                            "table_id": {"type": "keyword"},
                            "table_index": {"type": "integer"}
                        }
                    }
                }
            }
        }

    def create_index(self, index_name, mapping=None):
        try:
            if not self.client.indices.exists(index=index_name):
                # Use enhanced mapping with Unicode support
                mapping_to_use = mapping or self.default_mapping
                
                self.client.indices.create(
                    index=index_name,
                    body=mapping_to_use
                )
                logging.info(f"✅ Index '{index_name}' created")

                # Wait and verify index readiness
                for i in range(5):
                    if self.client.indices.exists(index=index_name):
                        logging.info(f"✅ Index '{index_name}' confirmed ready")
                        break
                    logging.warning(f"⏳ Waiting for index '{index_name}' to be ready...")
                    time.sleep(1)
                else:
                    raise RuntimeError(f"⛔ Index '{index_name}' not ready after retries")

                return True
            logging.info(f"ℹ️ Index '{index_name}' already exists")
            return False
        except Exception as e:
            logging.error(f"❌ Error creating index: {e}")
            raise
        
    def delete_index(self, index_name):
        try:
            if self.client.indices.exists(index=index_name):
                self.client.indices.delete(index=index_name)
                logging.info(f"Index '{index_name}' deleted")
                return True
            return False
        except Exception as e:
            logging.error(f"Error deleting index: {e}")
            raise

    def refresh_index(self, index_name):
        try:
            self.client.indices.refresh(index=index_name)
            return True
        except Exception as e:
            logging.error(f"Error refreshing index: {e}")
            raise
    
    def index_exists(self, index_name):
        """Check if index exists using the ElasticClient's verification"""
        try:
            return self.client.indices.exists(index=index_name)
        except Exception as e:
            logging.error(f"Index existence check failed: {e}")
            return False