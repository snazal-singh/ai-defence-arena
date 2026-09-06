import io
import json
import logging
import os
import sys

# Ensure root directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Enable basic logging
logging.basicConfig(level=logging.INFO)

from app.services.context_provider_service import get_context_provider_service
from controllers.mongodb_db import (
    create_mongo_collections,
    describe_collections_schema,
    execute_safe_mongo_query,
    generate_mongo_query,
    get_mongo_db_for_session,
    has_mongo_data,
    query_mongodb,
)

TEST_SESSION = "carnot_test_mongo_kb"

SAMPLE_ALERTS = [
    {"disaster_type": "Tsunami", "severity": "WARNING", "area_description": "Sample Zone of GOA"},
    {"disaster_type": "Tsunami", "severity": "ALERT", "area_description": "Coastal Odisha"},
    {"disaster_type": "Heavy Rainfall", "severity": "WATCH", "area_description": "Kerala Coast"},
]


class _FakeUploadFile:
    """Minimal stand-in for a Flask/FastAPI UploadFile, matching the .filename
    + .seek()/.read() interface process_json_file expects."""

    def __init__(self, filename: str, payload) -> None:
        self.filename = filename
        self._buffer = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def seek(self, pos):
        return self._buffer.seek(pos)

    def read(self, *args, **kwargs):
        return self._buffer.read(*args, **kwargs)


def run_tests():
    print("========================================")
    print("RUNNING END-TO-END MONGODB KB INTEGRATION TESTS (per-session)")
    print("========================================")

    # 0. Ingest a sample JSON dataset into this session's own Mongo database,
    # mirroring how a real file upload would populate it.
    print(f"\n0. Seeding per-session Mongo data for '{TEST_SESSION}'...")
    fake_file = _FakeUploadFile("alerts.json", SAMPLE_ALERTS)
    success, message = create_mongo_collections(TEST_SESSION, [fake_file])
    assert success, f"Failed to seed test data: {message}"
    print("Seeded 'alerts' collection with", len(SAMPLE_ALERTS), "sample documents")

    # 1. Test resources check
    print("\n1. Testing resource existence detection...")
    provider = get_context_provider_service()
    resources = provider.check_resources_exist(TEST_SESSION)
    print("Detected resources:", resources)
    assert resources["has_data_tables"] is True, "Failed to detect this session's Mongo data!"
    assert has_mongo_data(TEST_SESSION) is True
    print("Success: session-scoped Mongo data detected as a data table.")

    # 1b. A different, unrelated session must NOT see this session's data.
    other_session_resources = provider.check_resources_exist("some_other_unrelated_session")
    assert has_mongo_data("some_other_unrelated_session") is False, (
        "Isolation violated: another session sees this session's Mongo data!"
    )
    print("Success: an unrelated session correctly has no Mongo data (isolation holds).")

    # 2. Test schema introspection + direct MongoDB query generation
    print("\n2. Testing dynamic schema introspection + MongoDB query generation...")
    db = get_mongo_db_for_session(TEST_SESSION)
    collection_names = db.list_collection_names()
    schema_description = describe_collections_schema(db, collection_names)
    print("Introspected schema:\n", schema_description)

    questions = [
        "Find alerts with severity WARNING in GOA",
        "How many Tsunami alerts are there?",
        "Show distinct disaster types",
    ]

    targets = [(None, None, name) for name in collection_names]
    for q in questions:
        print(f"\nUser Question: '{q}'")
        try:
            plans = generate_mongo_query(q, schema_description, targets)
            print(f"Generated {len(plans)} query plan(s):")
            print(json.dumps(plans, indent=2))

            for plan in plans:
                results = execute_safe_mongo_query(TEST_SESSION, plan, allowed_targets=targets)
                print(f"Executed query successfully. Found {len(results)} matches.")
        except Exception as e:
            print(f"Error for question '{q}': {e}")

    # 3. Test get_data_context (full integration through the context provider)
    print("\n3. Testing high-level get_data_context integration...")
    query = "Find Tsunami warnings"
    context = provider.get_data_context(TEST_SESSION, query)
    print("Retrieved Context Fragment:")
    print(context[:400] + "..." if len(context) > 400 else context)
    assert context, "Expected non-empty context for a session with seeded Mongo data"

    # 3b. query_mongodb must refuse to run for a session with no data.
    res, err = query_mongodb("some_other_unrelated_session", query)
    assert res is None and err, "Expected an error for a session with no Mongo data"
    print("Success: query_mongodb correctly refuses sessions without their own data.")

    print("\n========================================")
    print("ALL TESTS COMPLETED SUCCESSFULLY!")
    print("========================================")


if __name__ == "__main__":
    run_tests()
