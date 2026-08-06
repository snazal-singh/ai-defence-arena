# 🎯 Intent Classification Evaluation & Benchmark Report

This document details the evaluation methodology, dataset schema, and benchmark results for the **Query Intent Classification Engine** (`app/services/query_intent_service.py`) in `sachet-agent-backend`.

---

## Executive Summary

- **Total Scenarios Evaluated**: 50 Test Cases
- **Passed**: 50 / 50
- **Failed**: 0 / 50
- **Overall Accuracy**: **100.0%**
- **Test Dataset Script**: `scratch/run_50_intent_benchmark.py`
- **Execution Log**: `scratch/intent_benchmark_results.json`

---

## Per-Category Performance Matrix

| Intent Category | Test Scenarios | Passed | Accuracy | Avg Latency |
| :--- | :---: | :---: | :---: | :---: |
| **Greetings & Conversational** | 8 | 8 | **100.0%** | 4.3 s |
| **Document Summarization** | 8 | 8 | **100.0%** | 7.7 s |
| **Document Vector Search (Q&A)** | 12 | 12 | **100.0%** | 4.6 s |
| **Structured Data (SQL / Mongo)** | 10 | 10 | **100.0%** | 8.8 s |
| **Hybrid (Doc + Data)** | 5 | 5 | **100.0%** | 5.8 s |
| **Edge Cases & Ambiguity** | 7 | 7 | **100.0%** | 5.0 s |
| **TOTAL / OVERALL** | **50** | **50** | **100.0%** | **6.0 s** |

---

## Benchmark Methodology & Dataset Schema

Each test scenario in the benchmark evaluates the `QueryIntentService.classify_intent()` function under realistic user query patterns, passing resource flags (`has_documents`, `has_sql_tables`, `has_mongo_tables`):

```python
intent, confidence, data_source = service.classify_intent(
    query=user_query,
    has_documents=has_docs,
    has_sql_tables=has_sql,
    has_mongo_tables=has_mongo
)
```

---

## Complete 50 Test Cases & Results Audit

### 1. Greetings & Conversational Queries (8 Cases)

| ID | User Input Query | Target Intent | Actual Intent | Conf. | Result |
| :-: | :--- | :-: | :-: | :-: | :-: |
| **01** | `"Hi"` | `GENERAL_CHAT` | `GENERAL_CHAT` | 0.99 | ✅ PASS |
| **02** | `"Hello, good morning!"` | `GENERAL_CHAT` | `GENERAL_CHAT` | 0.99 | ✅ PASS |
| **03** | `"Who created you?"` | `GENERAL_CHAT` | `GENERAL_CHAT` | 0.99 | ✅ PASS |
| **04** | `"How are you doing today?"` | `GENERAL_CHAT` | `GENERAL_CHAT` | 0.99 | ✅ PASS |
| **05** | `"Thank you so much for your help"` | `GENERAL_CHAT` | `GENERAL_CHAT` | 0.99 | ✅ PASS |
| **06** | `"What can you do?"` | `GENERAL_CHAT` | `GENERAL_CHAT` | 0.99 | ✅ PASS |
| **07** | `"Good night"` | `GENERAL_CHAT` | `GENERAL_CHAT` | 0.99 | ✅ PASS |
| **08** | `"Okay awesome"` | `GENERAL_CHAT` | `GENERAL_CHAT` | 0.99 | ✅ PASS |

---

### 2. Document Summarization Requests (8 Cases)

| ID | User Input Query | Target Intent | Actual Intent | Conf. | Result |
| :-: | :--- | :-: | :-: | :-: | :-: |
| **09** | `"Can you summarize the uploaded document?"` | `SUMMARY` | `SUMMARY` | 0.99 | ✅ PASS |
| **10** | `"Give me a brief summary of this PDF"` | `SUMMARY` | `SUMMARY` | 0.99 | ✅ PASS |
| **11** | `"Summarize the key points from the report"` | `SUMMARY` | `SUMMARY` | 0.99 | ✅ PASS |
| **12** | `"What is the executive summary of this file?"` | `SUMMARY` | `SUMMARY` | 0.99 | ✅ PASS |
| **13** | `"Provide an overview of the main takeaways from the paper"` | `SUMMARY` | `SUMMARY` | 0.99 | ✅ PASS |
| **14** | `"Summarize the document in 3 bullet points"` | `SUMMARY` | `SUMMARY` | 0.99 | ✅ PASS |
| **15** | `"Can I get an abstract of the attached file?"` | `SUMMARY` | `SUMMARY` | 0.99 | ✅ PASS |
| **16** | `"Give me a high-level summary of the contract document"` | `SUMMARY` | `SUMMARY` | 0.99 | ✅ PASS |

---

### 3. Document-Specific Vector Q&A (12 Cases)

| ID | User Input Query | Target Intent | Actual Intent | Conf. | Result |
| :-: | :--- | :-: | :-: | :-: | :-: |
| **17** | `"What is the policy limit described in section 4?"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **18** | `"According to the contract, what is the termination notice period?"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **19** | `"Find references to NDA clauses in the agreement"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **20** | `"What are the eligibility criteria mentioned on page 12?"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **21** | `"What does section 3.2 say about indemnification?"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **22** | `"Which chapter discusses thermal efficiency ratings?"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **23** | `"Extract all security requirements from the RFP document"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **24** | `"Does the document mention any late payment penalties?"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **25** | `"Who is the primary author of the research report?"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **26** | `"What is the effective date of the service agreement?"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **27** | `"What safety guidelines are listed for high voltage equipment?"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |
| **28** | `"Explain the methodology used in chapter 2"` | `DOCUMENT` | `DOCUMENT` | 0.95 | ✅ PASS |

---

### 4. Structured Data / SQL / MongoDB Queries (10 Cases)

| ID | User Input Query | Target Intent | Actual Intent | Conf. | Result |
| :-: | :--- | :-: | :-: | :-: | :-: |
| **29** | `"What is the total revenue for 2025?"` | `DATA_QUERY` | `DATA_QUERY` | 0.95 | ✅ PASS |
| **30** | `"Count the number of active customer accounts in the database"` | `DATA_QUERY` | `DATA_QUERY` | 0.95 | ✅ PASS |
| **31** | `"Show average order value grouped by month"` | `DATA_QUERY` | `DATA_QUERY` | 0.95 | ✅ PASS |
| **32** | `"Find top 5 highest selling products in our table"` | `DATA_QUERY` | `DATA_QUERY` | 0.95 | ✅ PASS |
| **33** | `"How many transactions were processed yesterday?"` | `DATA_QUERY` | `DATA_QUERY` | 0.95 | ✅ PASS |
| **34** | `"List all users who joined in July from the users table"` | `DATA_QUERY` | `DATA_QUERY` | 0.95 | ✅ PASS |
| **35** | `"What is the minimum balance recorded in the DB?"` | `DATA_QUERY` | `DATA_QUERY` | 0.95 | ✅ PASS |
| **36** | `"Calculate total quantity sold per product category"` | `DATA_QUERY` | `DATA_QUERY` | 0.95 | ✅ PASS |
| **37** | `"How many pending orders are in the database?"` | `DATA_QUERY` | `DATA_QUERY` | 0.95 | ✅ PASS |
| **38** | `"Find maximum transaction amount in region East"` | `DATA_QUERY` | `DATA_QUERY` | 0.95 | ✅ PASS |

---

### 5. Hybrid Queries (Document + Database) (5 Cases)

| ID | User Input Query | Target Intent | Actual Intent | Conf. | Result |
| :-: | :--- | :-: | :-: | :-: | :-: |
| **39** | `"Compare policy terms in contract PDF with total revenue figures in DB"` | `HYBRID` | `HYBRID` | 0.90 | ✅ PASS |
| **40** | `"Cross reference compliance PDF with active user accounts in database"` | `HYBRID` | `HYBRID` | 0.90 | ✅ PASS |
| **41** | `"Does customer dataset in DB meet SLA guidelines in contract document?"` | `HYBRID` | `HYBRID` | 0.90 | ✅ PASS |
| **42** | `"Check if revenue metrics in DB match financial projections in report"` | `HYBRID` | `HYBRID` | 0.90 | ✅ PASS |
| **43** | `"Correlate product complaint logs in DB with troubleshooting guidelines in manual"` | `HYBRID` | `HYBRID` | 0.90 | ✅ PASS |

---

### 6. Edge Cases & Complex Scenarios (7 Cases)

| ID | Edge Case Description | Query Input | Expected | Actual | Result |
| :-: | :--- | :--- | :-: | :-: | :-: |
| **44** | **Greeting Prefix + Doc Question** | `"Hi, can you tell me what section 4 of the document says?"` | `DOCUMENT` | `DOCUMENT` | ✅ PASS |
| **45** | **Greeting Prefix + Data Question** | `"Hello! What was the total sales count last month in our database?"` | `DATA_QUERY` | `DATA_QUERY` | ✅ PASS |
| **46** | **Greeting Prefix + Summary** | `"Hey there, please summarize this attached paper"` | `SUMMARY` | `SUMMARY` | ✅ PASS |
| **47** | **Image Attachment Override** | `"What is policy limit?\n\nImage Description: A bar chart of policy limits"` | `DOCUMENT` | `DOCUMENT` | ✅ PASS |
| **48** | **Python Coding Question** | `"Write a python function to calculate Fibonacci numbers"` | `GENERAL_CHAT` | `GENERAL_CHAT` | ✅ PASS |
| **49** | **Networking Concepts** | `"Explain the difference between TCP and UDP networking protocols"` | `GENERAL_CHAT` | `GENERAL_CHAT` | `GENERAL_CHAT` | ✅ PASS |
| **50** | **Arithmetic Query** | `"What is 25 multiplied by 48?"` | `GENERAL_CHAT` | `GENERAL_CHAT` | ✅ PASS |

---

## Key Takeaways & Deployment Safety

1. **Greeting Prefix Handling**: Prefixing a question with greetings (`"Hi, can you tell me..."`) does NOT short-circuit to general chat. The classifier correctly isolates the intent of the main clause (`DOCUMENT` or `DATA_QUERY`).
2. **Multi-Source Routing**: `HYBRID` queries correctly flag both vector search and SQL/Mongo query engines.
3. **Image Attachment Security**: Visual attachment payloads automatically enforce `DOCUMENT` intent, preventing missing context errors during image Q&A.
4. **General Knowledge & Code Bypass**: Technical/general coding questions bypass vector store searches, saving GPU compute and lowering latency.
