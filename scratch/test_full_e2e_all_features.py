"""
Comprehensive Full End-to-End Test Suite for sachet-agent-backend.
Tests all 12 major system components:
 1. Core Config & Settings
 2. API Schemas & Request Parsing
 3. Vision & NuMarkdown Ingestion Pipeline
 4. File Classification & Ingestion Splitter Pipeline
 5. Elasticsearch Client & BGE Reranker
 6. Internal SQL / Tabular Engine (sql_db)
 7. Internal MongoDB JSON Engine (mongodb_db)
 8. Query Intent Classification & Multi-Target Routing
 9. Context Provider & Augmentation
10. Chat History & Chat Context Manager
11. STT / TTS & Translation Language Matrix
12. FastAPI Application Router & Endpoint Integrity
"""

import os
import sys
import json
import io
import time
import logging
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("full_e2e_suite")

passed = 0
failed = 0
skipped = 0

def assert_test(name: str, condition: bool, msg: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ [PASS] {name}")
    else:
        failed += 1
        print(f"  ❌ [FAIL] {name}: {msg}")

def skip_test(name: str, reason: str = ""):
    global skipped
    skipped += 1
    print(f"  ⚠️ [SKIP] {name}: {reason}")

def run_all_e2e_tests():
    start_time = time.time()
    print("==================================================================")
    print("🚀 SACHET AGENT BACKEND - FULL END-TO-END VERIFICATION SUITE")
    print("==================================================================\n")

    # ------------------------------------------------------------------
    # MODULE 1: Core Config & Settings
    # ------------------------------------------------------------------
    print("🔧 1. Testing Core Config & Settings...")
    try:
        from app.core.config import settings
        assert_test("Settings Instance Initialized", settings is not None)
        assert_test("USE_NUMARKDOWN_PARSER is True", getattr(settings, "USE_NUMARKDOWN_PARSER", False) is True)
        assert_test("NuMarkdown Model Declared", bool(getattr(settings, "NUMARKDOWN_MODEL", "")))
        assert_test("ES Base URL Declared", bool(getattr(settings, "ES_BASE_URL", "")))
        assert_test("Reranker Model Configured", bool(getattr(settings, "RERANKER_MODEL", "")))
    except Exception as e:
        assert_test("Core Config Load", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 2: API Schemas & Request Parsing (CamelCase + Snake_Case)
    # ------------------------------------------------------------------
    print("\n📦 2. Testing API Schemas & Request Parsing...")
    try:
        from app.schemas.query import QueryRequest, TrialQueryRequest, ToggleNoteRequest, RenameChatRequest
        from app.schemas.document import MongoServerConnectRequest, MongoCollectionSelectRequest, RenameContainerBody

        # Case 1: CamelCase payload
        q1 = QueryRequest(message="Test 1", chatId="c1", sessionId="s1", context=True, inputLanguage="en", outputLanguage="hi")
        assert_test("QueryRequest CamelCase parsing", q1.chatId == "c1" and q1.sessionId == "s1" and q1.context is True)

        # Case 2: snake_case payload
        q2 = QueryRequest(**{"message": "Test 2", "chat_id": "c2", "session_id": "s2", "input_language": "en", "output_language": "hi"})
        assert_test("QueryRequest snake_case alias resolution", q2.chatId == "c2" and q2.sessionId == "s2")

        # Case 3: ToggleNoteRequest
        tn = ToggleNoteRequest(session_id="sess_1", chat_id="chat_1", message_id="msg_1")
        assert_test("ToggleNoteRequest alias resolution", tn.sessionId == "sess_1" and tn.messageId == "msg_1")

        # Case 4: Mongo Schemas
        mc = MongoServerConnectRequest(connectionUri="mongodb://localhost:27017/test", serverName="Test Server")
        assert_test("MongoServerConnectRequest schema", mc.connectionUri == "mongodb://localhost:27017/test" and mc.serverName == "Test Server")
    except Exception as e:
        assert_test("API Schemas Parsing", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 3: Vision & NuMarkdown Ingestion Pipeline
    # ------------------------------------------------------------------
    print("\n👁️ 3. Testing Vision & NuMarkdown Parser Pipeline...")
    try:
        from app.services.vision_service import get_vision_service, VisionService
        vision_svc = get_vision_service()
        assert_test("VisionService Singleton Initialized", vision_svc is not None)
        assert_test("NuMarkdown Parser Model Configured", bool(vision_svc.numarkdown_model))
        
        # Test clean_text safety on NuMarkdown table
        from utils.extractText import clean_text
        markdown_table = "| Name | Role | Location |\n|---|---|---|\n| Alice | Lead | Delhi |\n| Bob | Dev | Mumbai |"
        cleaned_table = clean_text(markdown_table)
        assert_test("clean_text preserves Markdown pipe tables", "| Alice | Lead | Delhi |" in cleaned_table)
        assert_test("clean_text preserves Markdown headers", clean_text("## Section Header") == "## Section Header")
    except Exception as e:
        assert_test("Vision Service Pipeline", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 4: File Classification & Ingestion Splitter Pipeline
    # ------------------------------------------------------------------
    print("\n📂 4. Testing File Classification & Ingestion Pipeline...")
    try:
        from app.services.document_service import classify_files
        from controllers.upload import get_hierarchical_chunks
        from langchain.schema import Document

        class MockFile:
            def __init__(self, filename):
                self.filename = filename

        test_files = [
            MockFile("annual_report.pdf"),
            MockFile("guidelines.docx"),
            MockFile("notes.txt"),
            MockFile("sales_data.csv"),
            MockFile("inventory.xlsx"),
            MockFile("alerts.json"),
            MockFile("unknown.bin")
        ]
        doc_files, data_files, mongo_files, unsupported = classify_files(test_files)
        assert_test("Classify doc_files (pdf, docx, txt)", len(doc_files) == 3)
        assert_test("Classify data_files (csv, xlsx)", len(data_files) == 2)
        assert_test("Classify mongo_files (json)", len(mongo_files) == 1)
        assert_test("Classify unsupported", len(unsupported) == 1)

        # Test Markdown-aware Hierarchical Chunking
        sample_markdown = (
            "# Main Title\n\n"
            "This is introduction text.\n\n"
            "## Financial Overview\n\n"
            "Here is the financial summary.\n"
        )
        sample_doc = Document(page_content=sample_markdown, metadata={"source": "report.pdf", "page": 1, "content_type": "text"})
        table_doc = Document(page_content="| Quarter | Revenue |\n|---|---|\n| Q1 | $10M |\n| Q2 | $12M |", metadata={"source": "report.pdf", "page": 1, "content_type": "table"})
        chunks = get_hierarchical_chunks([sample_doc, table_doc], "report.pdf")
        assert_test("Hierarchical Chunking splits document", len(chunks) > 0)
        table_chunks = [c for c in chunks if c.metadata.get("content_type") == "table"]
        assert_test("Hierarchical Chunking detects table chunks", len(table_chunks) >= 1)
    except Exception as e:
        assert_test("File Classification & Chunking", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 5: Elasticsearch Client & BGE Reranker
    # ------------------------------------------------------------------
    print("\n⚡ 5. Testing Elasticsearch Client & BGE Reranker...")
    try:
        from elastic.client import ElasticClient
        from elastic.reranker import get_reranker
        from langchain.schema import Document

        es_client = ElasticClient()
        assert_test("ElasticClient Singleton Initialized", es_client is not None)
        
        # Test index_exists method handles non-existent index safely
        exists = es_client.index_exists("non_existent_dummy_session_12345")
        assert_test("ElasticClient index_exists check executes safely", isinstance(exists, bool))

        # Test BGE Cross-Encoder Reranker
        reranker = get_reranker()
        assert_test("BGE Reranker Initialized", reranker is not None)
        if reranker:
            sample_docs = [
                Document(page_content="Elasticsearch provides vector search capabilities.", metadata={"id": 1}),
                Document(page_content="FastAPI is a Python web framework for asynchronous APIs.", metadata={"id": 2}),
                Document(page_content="PyTorch is a machine learning framework for deep learning.", metadata={"id": 3})
            ]
            reranked = reranker.rerank("Python asynchronous API framework", sample_docs, top_n=1)
            assert_test("BGE Reranker correctly ranks relevant document first", len(reranked) == 1 and "FastAPI" in reranked[0].page_content)
    except Exception as e:
        assert_test("ES & Reranker Pipeline", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 6: Internal SQL / Tabular Engine (sql_db)
    # ------------------------------------------------------------------
    print("\n🗄️ 6. Testing Internal SQL / Tabular Engine (sql_db)...")
    try:
        from controllers.sql_db import sanitize_identifier, MYSQL_CONFIG
        assert_test("SQL identifier sanitizer alphanumeric", sanitize_identifier("valid_table_123") == "valid_table_123")
        assert_test("SQL identifier sanitizer removes special chars", sanitize_identifier("my table! @#$ 2024") == "my_table_2024")
        assert_test("SQL identifier sanitizer truncates to 64 chars", len(sanitize_identifier("a" * 100)) <= 64)
        assert_test("MySQL configuration dictionary populated", MYSQL_CONFIG["drivername"] == "mysql+mysqlconnector")
    except Exception as e:
        assert_test("SQL Engine Verification", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 7: Internal MongoDB JSON Engine (mongodb_db)
    # ------------------------------------------------------------------
    print("\n🍃 7. Testing Internal MongoDB JSON Engine (mongodb_db)...")
    try:
        from controllers.sql_db import sanitize_identifier
        from controllers.mongodb_db import (
            has_mongo_data,
            _normalize_json_payload,
            _assert_no_forbidden_operators,
            _clamp_limit,
            parse_mongodb_types
        )
        assert_test("Collection name sanitizer replaces invalid characters", sanitize_identifier("my.alert$collection") == "my_alert_collection")
        
        # Test JSON payload normalization (dict -> list of dict, list -> list)
        normalized = _normalize_json_payload({"id": 1, "alert": "High"})
        assert_test("JSON payload normalizer converts dict to list", isinstance(normalized, list) and len(normalized) == 1)

        # Test limit clamp
        assert_test("MongoDB query limit clamp lower bound", _clamp_limit(-5) == 1)
        assert_test("MongoDB query limit clamp upper bound", _clamp_limit(500) == 100)
        assert_test("MongoDB query limit clamp valid range", _clamp_limit(25) == 25)

        # Test forbidden operator security assertion
        forbidden_detected = False
        try:
            _assert_no_forbidden_operators({"$where": "this.password == 'secret'"})
        except ValueError:
            forbidden_detected = True
        assert_test("Forbidden operator assertion blocks $where injection", forbidden_detected)
        
        # Test has_mongo_data on non-existent session
        has_mongo = has_mongo_data("dummy_non_existent_session_9999")
        assert_test("has_mongo_data handles non-existent session safely", isinstance(has_mongo, bool))
    except Exception as e:
        assert_test("MongoDB Engine Verification", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 8: Query Intent Classification & Multi-Target Routing
    # ------------------------------------------------------------------
    print("\n🎯 8. Testing Query Intent Classification & Multi-Target Routing...")
    try:
        from app.services.query_intent_service import get_query_intent_service, QueryIntent
        intent_svc = get_query_intent_service()
        assert_test("QueryIntentService Initialized", intent_svc is not None)

        # Fast-Path 1: Greeting
        i1, c1, s1 = intent_svc.classify_intent("Hi there!", has_documents=True, has_sql_tables=True, has_mongo_tables=True)
        assert_test("Intent Fast-Path: Greeting -> GENERAL_CHAT", i1 == QueryIntent.GENERAL_CHAT)

        # Fast-Path 2: Summary request regex
        i2, c2, s2 = intent_svc.classify_intent("Please summarize the uploaded document", has_documents=True, has_sql_tables=False)
        assert_test("Intent Fast-Path: Summary regex -> SUMMARY", i2 == QueryIntent.SUMMARY)

        # Guard 1: No data tables -> cannot be DATA_QUERY (downgrades to DOCUMENT if has_documents=True)
        i3, c3, s3 = intent_svc.classify_intent("What was the total revenue in the table?", has_documents=True, has_sql_tables=False, has_mongo_tables=False)
        assert_test("Intent Guard 1: Missing data tables routes to DOCUMENT", i3 in (QueryIntent.DOCUMENT, QueryIntent.GENERAL_CHAT), f"Got {i3.name}")

        # Guard 2: No documents -> HYBRID downgraded to DATA_QUERY
        i4, c4, s4 = intent_svc.classify_intent("Compare sales numbers with customer counts", has_documents=False, has_sql_tables=True, has_mongo_tables=False)
        assert_test("Intent Guard 2: Missing docs routes to DATA_QUERY", i4 == QueryIntent.DATA_QUERY, f"Got {i4.name}")

        # Guard 3: Zero context
        i5, c5, s5 = intent_svc.classify_intent("What is the speed of light?", has_documents=False, has_sql_tables=False, has_mongo_tables=False)
        assert_test("Intent Guard 3: Zero context -> GENERAL_CHAT", i5 == QueryIntent.GENERAL_CHAT, f"Got {i5.name}")
    except Exception as e:
        assert_test("Intent Classification Pipeline", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 9: Context Provider & Augmentation
    # ------------------------------------------------------------------
    print("\n📑 9. Testing Context Provider & Resource Checks...")
    try:
        from app.services.context_provider_service import get_context_provider_service
        ctx_svc = get_context_provider_service()
        assert_test("ContextProviderService Singleton Initialized", ctx_svc is not None)

        res = ctx_svc.check_resources_exist("test_session_dummy_9999")
        assert_test("check_resources_exist returns all required resource keys", 
                    all(k in res for k in ["has_documents", "has_data_tables", "has_sql_tables", "has_mongo_tables", "has_summaries"]))
        assert_test("check_resources_exist non-existent session has_sql_tables is False", res["has_sql_tables"] is False)
        assert_test("check_resources_exist non-existent session has_mongo_tables is False", res["has_mongo_tables"] is False)
    except Exception as e:
        assert_test("Context Provider Verification", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 10: Chat History & Chat Context Manager
    # ------------------------------------------------------------------
    print("\n💬 10. Testing Chat History & Context Services...")
    try:
        from app.services.chat_history_manager import get_chat_history_manager
        from app.services.chat_context_service import get_chat_context_service
        
        chat_mgr = get_chat_history_manager()
        assert_test("ChatHistoryManager Singleton Initialized", chat_mgr is not None)
        
        chat_ctx = get_chat_context_service()
        assert_test("ChatContextService Singleton Initialized", chat_ctx is not None)
        
        # Test reference extraction & prompt enhancement
        enhanced = ctx_svc._create_enhanced_search_query(
            "What about the policy limit?", 
            {"context_used": True, "context": "Assistant: We discussed the Insurance Agreement Section 4 yesterday.", "context_type": "clarification"}
        )
        assert_test("Chat Context Query Enhancement", len(enhanced) >= len("What about the policy limit?"))
    except Exception as e:
        assert_test("Chat History & Context Services", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 11: STT / TTS & Translation Language Matrix
    # ------------------------------------------------------------------
    print("\n🌐 11. Testing STT, TTS & Translation Language Matrix...")
    try:
        from utils.translation import LANGUAGE_TO_FLORES
        from utils.language_codes import ISO_TO_BCP47
        from app.services.tts_service import get_tts_service
        from app.services.stt_service import get_stt_service

        assert_test("FloRes Language Matrix contains Hindi (hin_Deva)", LANGUAGE_TO_FLORES.get("Hindi") == "hin_Deva")
        assert_test("FloRes Language Matrix contains English (eng_Latn)", LANGUAGE_TO_FLORES.get("English") == "eng_Latn")
        assert_test("FloRes Language Matrix contains Bengali (ben_Beng)", LANGUAGE_TO_FLORES.get("Bengali") == "ben_Beng")
        assert_test("FloRes Language Matrix contains Tamil (tam_Taml)", LANGUAGE_TO_FLORES.get("Tamil") == "tam_Taml")
        assert_test("ISO to BCP47 contains standard mappings", ISO_TO_BCP47.get("hi") == "hi-IN" and ISO_TO_BCP47.get("en") == "en-IN")

        tts_svc = get_tts_service()
        assert_test("TTSService Singleton Initialized", tts_svc is not None)

        stt_svc = get_stt_service()
        assert_test("STTService Singleton Initialized", stt_svc is not None)
    except Exception as e:
        assert_test("STT/TTS/Translation Matrix", False, str(e))

    # ------------------------------------------------------------------
    # MODULE 12: FastAPI Application Router & Endpoint Integrity
    # ------------------------------------------------------------------
    print("\n🚀 12. Testing FastAPI App Router & Endpoint Integrity...")
    try:
        from main import app
        assert_test("FastAPI Application Instance Loaded", app is not None)

        # Verify all core routes exist in app
        routes = [route.path for route in app.routes]
        expected_routes = [
            "/ask",
            "/trial-ask",
            "/upload",
            "/free-trial",
            "/containers",
            "/synthesize",
            "/stt-transcribe",
            "/stt-health",
            "/health",
            "/containers/{session_id}/mongodb/connect",
            "/containers/{session_id}/mongodb/servers",
            "/containers/{session_id}"
        ]
        for route_pattern in expected_routes:
            matched = any(route_pattern in r for r in routes)
            assert_test(f"API Route Registered: {route_pattern}", matched)

        # Test OpenAPI schema generation without runtime errors
        openapi_schema = app.openapi()
        assert_test("OpenAPI Schema Generated Successfully", openapi_schema is not None and "paths" in openapi_schema)
    except Exception as e:
        assert_test("FastAPI App Router Integrity", False, str(e))

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------
    total_time = round(time.time() - start_time, 2)
    total_tests = passed + failed

    print("\n==================================================================")
    print("📊 FULL END-TO-END SUITE EXECUTION SUMMARY")
    print("==================================================================")
    print(f"Total Tests Executed : {total_tests}")
    print(f"Passed               : {passed}")
    print(f"Failed               : {failed}")
    print(f"Skipped              : {skipped}")
    if total_tests > 0:
        accuracy = round((passed / total_tests) * 100, 2)
        print(f"Success Rate         : {accuracy}%")
    print(f"Execution Time       : {total_time}s\n")

    return failed == 0

if __name__ == "__main__":
    success = run_all_e2e_tests()
    sys.exit(0 if success else 1)
