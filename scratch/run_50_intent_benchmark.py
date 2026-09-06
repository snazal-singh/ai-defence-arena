"""
50-Case Intent Classification Evaluation & Benchmark Suite.
Tests QueryIntentService against 50 comprehensive scenarios including edge cases,
multi-intent queries, image context overrides, and greeting prefixes.
"""

import sys
import os
import json
import logging
import time
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("intent_benchmark")

# 50 Comprehensive Evaluation Test Cases
DATASET = [
    # --- Category 1: Greetings & Casual Conversational (8 cases) ---
    {"id": 1, "category": "Greetings", "query": "Hi", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True},
    {"id": 2, "category": "Greetings", "query": "Hello, good morning!", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True},
    {"id": 3, "category": "Greetings", "query": "Who created you?", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True},
    {"id": 4, "category": "Greetings", "query": "How are you doing today?", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True},
    {"id": 5, "category": "Greetings", "query": "Thank you so much for your help", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True},
    {"id": 6, "category": "Greetings", "query": "What can you do?", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True},
    {"id": 7, "category": "Greetings", "query": "Good night", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True},
    {"id": 8, "category": "Greetings", "query": "Okay awesome", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True},

    # --- Category 2: Document Summarization Requests (8 cases) ---
    {"id": 9, "category": "Summary", "query": "Can you summarize the uploaded document?", "expected": "SUMMARY", "has_docs": True, "has_sql": False},
    {"id": 10, "category": "Summary", "query": "Give me a brief summary of this PDF", "expected": "SUMMARY", "has_docs": True, "has_sql": False},
    {"id": 11, "category": "Summary", "query": "Summarize the key points from the report", "expected": "SUMMARY", "has_docs": True, "has_sql": False},
    {"id": 12, "category": "Summary", "query": "What is the executive summary of this file?", "expected": "SUMMARY", "has_docs": True, "has_sql": False},
    {"id": 13, "category": "Summary", "query": "Provide an overview of the main takeaways from the paper", "expected": "SUMMARY", "has_docs": True, "has_sql": False},
    {"id": 14, "category": "Summary", "query": "Summarize the document in 3 bullet points", "expected": "SUMMARY", "has_docs": True, "has_sql": False},
    {"id": 15, "category": "Summary", "query": "Can I get an abstract of the attached file?", "expected": "SUMMARY", "has_docs": True, "has_sql": False},
    {"id": 16, "category": "Summary", "query": "Give me a high-level summary of the contract document", "expected": "SUMMARY", "has_docs": True, "has_sql": False},

    # --- Category 3: Document-Specific Q&A / Vector Search (12 cases) ---
    {"id": 17, "category": "Document Q&A", "query": "What is the policy limit described in section 4?", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 18, "category": "Document Q&A", "query": "According to the contract, what is the termination notice period?", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 19, "category": "Document Q&A", "query": "Find references to NDA clauses in the agreement", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 20, "category": "Document Q&A", "query": "What are the eligibility criteria mentioned on page 12?", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 21, "category": "Document Q&A", "query": "What does section 3.2 say about indemnification?", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 22, "category": "Document Q&A", "query": "Which chapter discusses thermal efficiency ratings?", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 23, "category": "Document Q&A", "query": "Extract all security requirements from the RFP document", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 24, "category": "Document Q&A", "query": "Does the document mention any late payment penalties?", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 25, "category": "Document Q&A", "query": "Who is the primary author of the research report?", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 26, "category": "Document Q&A", "query": "What is the effective date of the service agreement?", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 27, "category": "Document Q&A", "query": "What safety guidelines are listed for high voltage equipment?", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},
    {"id": 28, "category": "Document Q&A", "query": "Explain the methodology used in chapter 2", "expected": "DOCUMENT", "has_docs": True, "has_sql": False},

    # --- Category 4: Structured Data / SQL / Mongo Queries (10 cases) ---
    {"id": 29, "category": "Structured Data", "query": "What is the total revenue for 2025?", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True},
    {"id": 30, "category": "Structured Data", "query": "Count the number of active customer accounts in the database", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True},
    {"id": 31, "category": "Structured Data", "query": "Show average order value grouped by month", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True},
    {"id": 32, "category": "Structured Data", "query": "Find top 5 highest selling products in our table", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True},
    {"id": 33, "category": "Structured Data", "query": "How many transactions were processed yesterday?", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True},
    {"id": 34, "category": "Structured Data", "query": "List all users who joined in July from the users table", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True},
    {"id": 35, "category": "Structured Data", "query": "What is the minimum balance recorded in the DB?", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True},
    {"id": 36, "category": "Structured Data", "query": "Calculate total quantity sold per product category", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True},
    {"id": 37, "category": "Structured Data", "query": "How many pending orders are in the database?", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True},
    {"id": 38, "category": "Structured Data", "query": "Find maximum transaction amount in region East", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True},

    # --- Category 5: Hybrid Queries (Document + Data) (5 cases) ---
    {"id": 39, "category": "Hybrid", "query": "Compare the policy terms in the contract PDF with the total revenue figures in the database", "expected": "HYBRID", "has_docs": True, "has_sql": True},
    {"id": 40, "category": "Hybrid", "query": "Cross reference the uploaded compliance PDF with the list of active user accounts in the database", "expected": "HYBRID", "has_docs": True, "has_sql": True},
    {"id": 41, "category": "Hybrid", "query": "Does our customer dataset in DB meet the SLA guidelines specified in the uploaded contract document?", "expected": "HYBRID", "has_docs": True, "has_sql": True},
    {"id": 42, "category": "Hybrid", "query": "Check if the revenue metrics in our database match the financial projections in the uploaded report", "expected": "HYBRID", "has_docs": True, "has_sql": True},
    {"id": 43, "category": "Hybrid", "query": "Correlate product complaint logs in the DB with the troubleshooting guidelines in the user manual document", "expected": "HYBRID", "has_docs": True, "has_sql": True},

    # --- Category 6: Edge Cases & Ambiguity (7 cases) ---
    {"id": 44, "category": "Edge Cases", "query": "Hi, can you tell me what section 4 of the document says?", "expected": "DOCUMENT", "has_docs": True, "has_sql": False, "has_mongo": False},
    {"id": 45, "category": "Edge Cases", "query": "Hello! What was the total sales count last month in our database?", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True, "has_mongo": False},
    {"id": 46, "category": "Edge Cases", "query": "Hey there, please summarize this attached paper", "expected": "SUMMARY", "has_docs": True, "has_sql": False, "has_mongo": False},
    {"id": 47, "category": "Edge Cases", "query": "What is the policy limit?\n\nImage Description: A bar chart showing quarterly policy limits", "expected": "DOCUMENT", "has_docs": True, "has_sql": False, "has_mongo": False},
    {"id": 48, "category": "Edge Cases", "query": "Write a python function to calculate Fibonacci numbers", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True, "has_mongo": False},
    {"id": 49, "category": "Edge Cases", "query": "Explain the difference between TCP and UDP networking protocols", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True, "has_mongo": False},
    {"id": 50, "category": "Edge Cases", "query": "What is 25 multiplied by 48?", "expected": "GENERAL_CHAT", "has_docs": True, "has_sql": True, "has_mongo": False},

    # --- Category 7: MongoDB-Only Queries (5 cases) ---
    {"id": 51, "category": "MongoDB Only", "query": "How many documents are in the alerts collection?", "expected": "DATA_QUERY", "has_docs": False, "has_sql": False, "has_mongo": True},
    {"id": 52, "category": "MongoDB Only", "query": "List all records where region is Goa", "expected": "DATA_QUERY", "has_docs": False, "has_sql": False, "has_mongo": True},
    {"id": 53, "category": "MongoDB Only", "query": "What is the average severity score in our JSON data?", "expected": "DATA_QUERY", "has_docs": False, "has_sql": False, "has_mongo": True},
    {"id": 54, "category": "MongoDB Only", "query": "Find all tsunami warnings issued in 2024", "expected": "DATA_QUERY", "has_docs": False, "has_sql": False, "has_mongo": True},
    {"id": 55, "category": "MongoDB Only", "query": "Group alert events by type and count them", "expected": "DATA_QUERY", "has_docs": False, "has_sql": False, "has_mongo": True},

    # --- Category 8: Dual-Source Routing (SQL + Mongo both present, 5 cases) ---
    {"id": 56, "category": "Dual-Source Routing", "query": "What is the total revenue for Q3?", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True, "has_mongo": True, "expected_source": "sql"},
    {"id": 57, "category": "Dual-Source Routing", "query": "How many alerts are in the warnings collection?", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True, "has_mongo": True, "expected_source": "mongo"},
    {"id": 58, "category": "Dual-Source Routing", "query": "Show me all records", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True, "has_mongo": True, "expected_source": "both"},
    {"id": 59, "category": "Dual-Source Routing", "query": "Compare our sales figures with the product alert frequency", "expected": "DATA_QUERY", "has_docs": False, "has_sql": True, "has_mongo": True, "expected_source": "both"},
    {"id": 60, "category": "Dual-Source Routing", "query": "Hi there", "expected": "GENERAL_CHAT", "has_docs": False, "has_sql": True, "has_mongo": True, "expected_source": None},
]

def run_benchmark():
    from app.services.query_intent_service import get_query_intent_service
    service = get_query_intent_service()

    # Mock schemas for dual-source routing tests.
    # These simulate a session that has:
    #   - SQL tables with revenue/sales data (like a CSV upload)
    #   - MongoDB collections with alerts/warnings data (like a JSON upload)
    MOCK_SQL_SCHEMA = (
        "Table: sales_data\n"
        "Columns: id (INT), quarter (VARCHAR), revenue (DECIMAL), "
        "product (VARCHAR), region (VARCHAR), sales_count (INT)\n\n"
        "Table: customers\n"
        "Columns: id (INT), name (VARCHAR), joined_date (DATE), status (VARCHAR)"
    )
    MOCK_MONGO_SCHEMA = (
        "Collection: alerts\n"
        "Fields: _id (ObjectId), type (String), severity (Number), "
        "region (String), timestamp (Date), status (String)\n\n"
        "Collection: warnings\n"
        "Fields: _id (ObjectId), event_type (String), location (String), "
        "issued_at (Date), alert_level (String)"
    )

    original_fetch = service._fetch_dual_source_schemas

    def mock_fetch_dual_source_schemas(user_session):
        # Return mock schemas for dual-source routing test cases
        return MOCK_SQL_SCHEMA, MOCK_MONGO_SCHEMA

    results = []
    correct_count = 0
    total_count = len(DATASET)
    start_time = time.time()

    print("==================================================================")
    print("🎯 STARTING 60-CASE INTENT CLASSIFICATION EVALUATION BENCHMARK")
    print("==================================================================\n")

    category_stats = {}

    for item in DATASET:
        t0 = time.time()
        cat = item["category"]
        if cat not in category_stats:
            category_stats[cat] = {"total": 0, "correct": 0}
        category_stats[cat]["total"] += 1

        try:
            # For dual-source routing tests, inject mock schemas so the
            # classifier has real field names to route SQL vs Mongo against.
            if cat == "Dual-Source Routing":
                service._fetch_dual_source_schemas = mock_fetch_dual_source_schemas
            else:
                service._fetch_dual_source_schemas = original_fetch

            intent, conf, src = service.classify_intent(
                item["query"],
                has_documents=item["has_docs"],
                has_sql_tables=item["has_sql"],
                has_mongo_tables=item.get("has_mongo", False)
            )
            actual_name = intent.name
            latency_ms = round((time.time() - t0) * 1000, 2)

            # Intent must match
            intent_ok = (actual_name == item["expected"])
            # For dual-source routing cases, also check data_source if expected_source is set
            expected_source = item.get("expected_source", None)
            source_ok = True
            if expected_source is not None and intent_ok:
                source_ok = (src == expected_source)

            passed = intent_ok and source_ok

            if passed:
                correct_count += 1
                category_stats[cat]["correct"] += 1

            status_mark = "✅ PASS" if passed else "❌ FAIL"
            source_note = f" | Source: {src}" if item.get("expected_source") is not None else ""
            print(f"[{item['id']:02d}/{total_count}] {status_mark} | Cat: {cat:<18} | Expected: {item['expected']:<12} | Got: {actual_name:<12} ({latency_ms}ms){source_note}")
            if not passed:
                print(f"       Query: \"{item['query']}\"")
                if not intent_ok:
                    print(f"       Intent mismatch: expected {item['expected']}, got {actual_name}")
                if not source_ok:
                    print(f"       Source mismatch: expected '{expected_source}', got '{src}'")

            results.append({
                "id": item["id"],
                "category": cat,
                "query": item["query"],
                "expected": item["expected"],
                "actual": actual_name,
                "confidence": conf,
                "data_source": src,
                "passed": passed,
                "latency_ms": latency_ms
            })
        except Exception as e:
            print(f"[{item['id']:02d}/50] ❌ ERROR | {e}")
            results.append({
                "id": item["id"],
                "category": cat,
                "query": item["query"],
                "expected": item["expected"],
                "actual": "ERROR",
                "confidence": 0.0,
                "data_source": None,
                "passed": False,
                "latency_ms": 0.0,
                "error": str(e)
            })

    total_time = round(time.time() - start_time, 2)
    accuracy = round((correct_count / total_count) * 100, 2)

    print("\n==================================================================")
    print("📊 BENCHMARK SUMMARY RESULTS")
    print("==================================================================")
    print(f"Total Test Cases : {total_count}")
    print(f"Passed           : {correct_count}")
    print(f"Failed           : {total_count - correct_count}")
    print(f"Accuracy Rate    : {accuracy}%")
    print(f"Total Execution  : {total_time} seconds\n")

    print("--- Per-Category Breakdown ---")
    for cat, stats in category_stats.items():
        cat_acc = round((stats["correct"] / stats["total"]) * 100, 1)
        print(f"• {cat:<18}: {stats['correct']}/{stats['total']} ({cat_acc}%)")

    # Write detailed JSON results for documentation generator
    with open("scratch/intent_benchmark_results.json", "w") as f:
        json.dump({
            "total_count": total_count,
            "correct_count": correct_count,
            "accuracy": accuracy,
            "total_time_sec": total_time,
            "category_stats": category_stats,
            "results": results
        }, f, indent=2)

    print("\nDetailed results saved to scratch/intent_benchmark_results.json")

if __name__ == "__main__":
    run_benchmark()
