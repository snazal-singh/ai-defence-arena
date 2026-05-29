from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError
import logging
from app.core.config import settings


class ElasticClient:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ElasticClient, cls).__new__(cls)
            cls._instance._initialize_client()
        return cls._instance
    
    def _initialize_client(self):
        # For local setup (default port: 9200)
        self.client = Elasticsearch(
            hosts=[Config.ES_BASE_URL],
            request_timeout=300
        )
        logging.info("Elasticsearch client initialized (local)")
    
    def ping(self):
        return self.client.ping()
    
    def index_exists(self, index_name):
        try:
            return self.client.indices.exists(index=index_name)
        except NotFoundError:
            return False
        except Exception as e:
            logging.error(f"Error checking index existence: {e}")
            return False