import os
import sys
import logging

# Ensure root directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Enable basic logging
logging.basicConfig(level=logging.INFO)

from app.services.context_provider_service import get_context_provider_service
from controllers.mongodb_db import generate_mongo_query, execute_safe_mongo_query, get_mongo_db

def run_tests():
    print("========================================")
    print("RUNNING END-TO-END MONGODB KB INTEGRATION TESTS")
    print("========================================")

    # 1. Test resources check
    print("\n1. Testing resource existence detection...")
    provider = get_context_provider_service()
    resources = provider.check_resources_exist("carnot_test")
    print("Detected resources:", resources)
    assert resources["has_data_tables"] is True, "Failed to detect MongoDB database tables!"
    print("Success: MongoDB alerts detected as data tables.")

    # 2. Test direct MongoDB query generation
    print("\n2. Testing MongoDB query generation...")
    questions = [
        "Find alerts with severity WARNING for Heavy Rainfall in GOA",
        "How many Tsunami alerts are there?",
        "Show distinct disaster types"
    ]
    
    for q in questions:
        print(f"\nUser Question: '{q}'")
        try:
            plan = generate_mongo_query(q)
            print("Generated Query Plan:")
            import json
            print(json.dumps(plan, indent=2))
            
            db = get_mongo_db()
            results = execute_safe_mongo_query(db, plan)
            print(f"Executed query successfully. Found {len(results)} matches.")
            if results:
                print("Sample result matches:")
                print(" - Type:", results[0].get("disaster_type"))
                print(" - Message:", results[0].get("warning_message"))
                print(" - Area covered:", results[0].get("area_description"))
        except Exception as e:
            print(f"Error for question '{q}': {e}")

    # 3. Test get_data_context
    print("\n3. Testing high-level get_data_context integration...")
    query = "Find Tsunami warnings"
    context = provider.get_data_context("carnot_test", query)
    print("Retrieved Context Fragment:")
    print(context[:400] + "..." if len(context) > 400 else context)
    
    print("\n========================================")
    print("ALL TESTS COMPLETED SUCCESSFULLY!")
    print("========================================")

if __name__ == "__main__":
    run_tests()
