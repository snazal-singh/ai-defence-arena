"""
MongoDB Database Operations Module.
Translates natural language questions into safe PyMongo queries,
executes them, and returns formatted contexts.
"""

import logging
import json
import re
from datetime import datetime
from typing import Tuple, Optional, Any, Dict, List
from bson import ObjectId, json_util
import pymongo

from app.core.config import settings
from app.services.llm_service import get_standard_llm

logger = logging.getLogger(__name__)

# System prompt for MongoDB structured query translation
SYSTEM_PROMPT = """You are a MongoDB expert. Given a user's natural language question and a MongoDB database schema, you must translate the question into a valid MongoDB query JSON document.

Database Name: disaster_alerts
Collection Name: alerts

Schema details for 'alerts' collection:
- `_id`: ObjectId
- `StateList`: List of documents, each with `stateId` (integer)
- `DistrictList`: List of documents, each with `districtId` (integer)
- `identifier`: Long integer unique identifier
- `alert_id_sdma_autoinc`: Long integer auto-increment ID
- `effective_start_time`: Date/time when alert becomes active (stored as datetime)
- `effective_end_time`: Date/time when alert expires (stored as datetime)
- `entry_time`: Date/time when alert was entered into the database (stored as datetime)
- `warning_message`: String containing warning description (e.g. "Sample ALERT for Heavy Rainfall. Coastal regions may be affected.")
- `disaster_type`: String representing type of disaster. Common values: "Heavy Rainfall", "Tsunami", "Cyclone", "Ocean Currents", "Storm Surge"
- `certainty`: String. Common values: "Likely", "Very Likely", "Observed"
- `severity`: String. Common values: "ALERT", "WARNING", "WATCH"
- `area_covered`: String representation of decimal area size in sq km (e.g., "4183.403")
- `alert_source`: String. Example: "INCOIS"
- `area_description`: String description of the area, e.g. "Sample Zone of GOA"
- `centroid`: String coordinates e.g., "73.32115279027985,15.666116235567308"
- `centroidPoint`: GeoJSON Point with `type` (String) and `coordinates` list [longitude, latitude]
- `max_lat`, `min_lat`, `min_long`, `max_long`: Strings containing bounding coordinates

Guidelines:
1. ONLY return a valid JSON object. Do not wrap it in markdown code blocks or add any explanations.
2. The JSON object must strictly conform to this structure:
   {
     "collection": "alerts",
     "operation": "find" | "aggregate" | "count_documents" | "distinct",
     "query": <dict for query filters, or distinct format {"key": "<field_name>", "filter": <query_dict>}>,
     "projection": <dict of fields to return, optional>,
     "pipeline": <list of aggregate pipeline stages, required if operation is aggregate>,
     "sort": <list of [field_name, direction] lists (e.g. [["entry_time", -1]]), optional>,
     "limit": <integer limit, optional, default to 10 for safety>
   }
3. Use case-insensitive regex for string searches when appropriate: e.g., {"area_description": {"$regex": "GOA", "$options": "i"}}
4. For date-based filters, write ISO format strings like "2026-05-26T00:00:00Z" (our query runner will parse them to python datetime).
5. For calculations on `area_covered` (stored as string), use aggregation with `{"$toDouble": "$area_covered"}`:
   e.g., {"$group": {"_id": null, "total_area": {"$sum": {"$toDouble": "$area_covered"}}}}
"""


def get_mongo_db() -> pymongo.database.Database:
    """Connect to MongoDB and get the disaster_alerts database."""
    mongo_url = getattr(settings, "MONGO_URL", "mongodb://localhost:27017/")
    client = pymongo.MongoClient(mongo_url)
    return client["disaster_alerts"]


def parse_mongodb_types(data: Any) -> Any:
    """Recursively parse JSON strings, OIDs, and Dates into MongoDB native formats.
    Transforms simple string filters on categorical fields (disaster_type, severity, certainty)
    into case-insensitive regex matches automatically.
    """
    if isinstance(data, dict):
        if "$oid" in data:
            return ObjectId(data["$oid"])
        if "$date" in data:
            try:
                # Parse date-string into a datetime object
                date_str = data["$date"]
                if isinstance(date_str, str):
                    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except Exception:
                pass
        
        # Build processed dict, dynamically converting exact matches on key categories to case-insensitive regex
        processed = {}
        for k, v in data.items():
            if k in ["disaster_type", "severity", "certainty"] and isinstance(v, str):
                processed[k] = {"$regex": f"^{re.escape(v)}$", "$options": "i"}
            else:
                processed[k] = parse_mongodb_types(v)
        return processed
    elif isinstance(data, list):
        return [parse_mongodb_types(item) for item in data]
    elif isinstance(data, str):
        # Attempt to parse ISO datetime strings automatically
        if len(data) >= 19 and data[4] == '-' and data[7] == '-' and data[10] == 'T':
            try:
                return datetime.fromisoformat(data.replace("Z", "+00:00"))
            except Exception:
                pass
    return data



def execute_safe_mongo_query(db: pymongo.database.Database, query_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Safely executes read-only MongoDB operations based on generated plan."""
    collection_name = query_plan.get("collection", "alerts")
    operation = query_plan.get("operation", "find")
    
    # Parse native BSON types (ObjectIds, Datetimes) from LLM output
    query_dict = parse_mongodb_types(query_plan.get("query", {}))
    projection = query_plan.get("projection")
    pipeline = parse_mongodb_types(query_plan.get("pipeline", []))
    sort_list = query_plan.get("sort")
    limit = query_plan.get("limit", 10)
    
    col = db[collection_name]
    logger.info(f"Executing MongoDB {operation} on {collection_name}. Filter: {query_dict}, Limit: {limit}")
    
    if operation == "find":
        cursor = col.find(query_dict, projection)
        if sort_list:
            # PyMongo expects a list of tuples, e.g. [('entry_time', -1)]
            formatted_sort = [(s[0], s[1]) for s in sort_list]
            cursor = cursor.sort(formatted_sort)
        if limit:
            cursor = cursor.limit(limit)
        return list(cursor)
        
    elif operation == "aggregate":
        # Aggregate doesn't use standard limit parameter, pipeline handles it, but let's append one if missing
        if pipeline and not any("$limit" in stage for stage in pipeline):
            pipeline.append({"$limit": limit})
        cursor = col.aggregate(pipeline)
        return list(cursor)
        
    elif operation == "count_documents":
        count = col.count_documents(query_dict)
        return [{"count": count}]
        
    elif operation == "distinct":
        key = query_dict.get("key")
        filter_dict = query_dict.get("filter", {})
        if not key:
            raise ValueError("Distinct operation requires a 'key' in query dictionary")
        distinct_vals = col.distinct(key, filter_dict)
        return [{"distinct_values": distinct_vals}]
        
    else:
        raise ValueError(f"Unsupported MongoDB operation: {operation}")


def clean_llm_json(raw_text: str) -> str:
    """Cleans and extracts JSON content from raw LLM output."""
    # Strip markdown markers
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def generate_mongo_query(natural_language_query: str) -> Dict[str, Any]:
    """Uses LLM to translate natural language into a structured MongoDB query plan."""
    llm = get_standard_llm()
    
    prompt = f"{SYSTEM_PROMPT}\nUser Question: {natural_language_query}\n\nGenerated JSON:"
    
    logger.info(f"Generating MongoDB query for: {natural_language_query}")
    response = llm.invoke(prompt)
    raw_output = str(response.content)
    
    logger.info(f"Raw LLM output: {raw_output}")
    cleaned = clean_llm_json(raw_output)
    
    try:
        query_plan = json.loads(cleaned)
        return query_plan
    except Exception as e:
        logger.error(f"Failed to parse generated JSON: {cleaned}. Error: {e}")
        # Build a safe default fallback query if parsing fails
        return {
            "collection": "alerts",
            "operation": "find",
            "query": {"warning_message": {"$regex": natural_language_query, "$options": "i"}},
            "limit": 5
        }


def query_mongodb(natural_language_query: str) -> Tuple[Optional[str], Optional[str]]:
    """Runs natural language query against MongoDB and formats the context output."""
    try:
        db = get_mongo_db()
        
        # 1. Translate question to query plan
        query_plan = generate_mongo_query(natural_language_query)
        
        # 2. Execute safety query
        results = execute_safe_mongo_query(db, query_plan)
        
        # 3. Format context using json_util to serialize BSON types cleanly
        formatted_results = json.loads(json_util.dumps(results))
        
        formatted_context = (
            f"[0] \"MongoDB query: {json.dumps(query_plan)}\"  \n"
            f"(MongoDB output: {json.dumps(formatted_results)})\n\n"
        )
        return formatted_context, None
        
    except Exception as e:
        logger.error(f"MongoDB structured query failed: {e}")
        return None, str(e)
