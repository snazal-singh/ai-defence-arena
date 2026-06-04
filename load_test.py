#!/usr/bin/env python3
"""
Sachet API Concurrent Load Tester
==================================
Simulates N concurrent users hitting the /ask endpoint and reports
response time, TTFB, answer length, and aggregate statistics.

Usage:
    python load_test.py                        # 10 users, default settings
    python load_test.py --users 20             # 20 concurrent users
    python load_test.py --url http://x:5001    # custom server URL
    python load_test.py --csv results.csv      # export raw results to CSV
    python load_test.py --rounds 3             # run 3 rounds of 10 users each
"""

import argparse
import csv
import json
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import List, Optional

import requests
import urllib3

# Suppress InsecureRequestWarning for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================================
# CONFIGURATION — Edit these defaults or override via CLI args
# ============================================================================

BASE_URL = "http://127.0.0.1:5001"

AUTH_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJlbWFpbCI6ImNhcm5vdF90ZXN0In0"
    ".oWlvwHt-8iTNDSOanKZqFqgyQ7aF6iheMNTEi5oU02w"
)

SESSION_ID = "20260523T173056"

CONCURRENT_USERS = 10

# Sample questions — replace these with your own
# QUESTIONS = [
#     "What is this document about?",
#     "Summarize the key findings of this document.",
#     "Who is the author of this document?",
#     "What are the main conclusions?",
#     "List the important dates mentioned in the document.",
#     "What recommendations does the document provide?",
#     "Explain the methodology described in the document.",
#     "What data sources were used?",
#     "Are there any limitations mentioned?",
#     "What is the scope of this document?",
#     "Describe the introduction section briefly.",
#     "What problem does this document address?",
#     "What are the key terms defined in the document?",
#     "Summarize section 2 of the document.",
#     "What future work is suggested?",
# ]

QUESTIONS = [
    "What is the exact timeline to complete the Transition Phase from OTSi?", # [1]
    "What is the minimum cumulative revenue required to meet the Financial Capacity condition?", # [2, 3]
    "What are the specific weights assigned to the Technical and Financial Proposals?", # [4]
    "What is the required professional experience length for the Project Director & Team Leader?", # [5]
    "What must be demonstrated for the secure sandboxed execution during the PoC?", # [6]
    "What is the maximum time allowed for synchronizing API-based datasets?", # [7]
    "What are the mandated RPO and RTO parameters for the disaster recovery site?", # [8]
    "What percentage of the Agreement Value is retained as Performance Security?", # [9]
    "What is the daily percentage rate for liquidated damages in case of delay?", # [10]
    "What percentage of the total fee is paid upon the successful Go-Live of the NDAP?" # [11]
]


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class RequestResult:
    """Stores metrics for a single API request."""
    user_id: int
    question: str
    status_code: int = 0
    total_time: float = 0.0
    ttfb: float = 0.0
    answer_length: int = 0
    answer_preview: str = ""
    error: str = ""
    success: bool = False
    est_tok_sec: float = 0.0  # Estimated tokens/sec (~4 chars per token)


# ============================================================================
# WORKER — Sends a single /ask request and captures metrics
# ============================================================================

def send_ask_request(
    user_id: int,
    question: str,
    base_url: str,
    token: str,
    session_id: str,
    timeout: int = 120,
) -> RequestResult:
    """Fire a single POST /ask request and measure response metrics."""

    result = RequestResult(user_id=user_id, question=question)

    # Each concurrent user gets a unique chatId to avoid history collisions
    chat_id = f"loadtest_{uuid.uuid4().hex[:12]}"

    payload = {
        "token": token,
        "message": question,
        "context": "files",
        "chatId": chat_id,
        "sessionId": session_id,
        "inputLanguage": 23,
        "outputLanguage": 23,
        "filenames": [],
        "hasCsvOrXlsx": False,
        "mode": "default",
    }

    headers = {"Content-Type": "application/json"}
    url = f"{base_url.rstrip('/')}/ask"

    try:
        start = time.perf_counter()

        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
            verify=False,
            stream=True,  # Enable streaming to measure TTFB accurately
        )

        # TTFB = time to receive the first chunk of data
        first_chunk = None
        chunks = []
        for chunk in resp.iter_content(chunk_size=None):
            if first_chunk is None:
                ttfb = time.perf_counter() - start
                result.ttfb = round(ttfb, 4)
            first_chunk = True
            chunks.append(chunk)

        total_time = time.perf_counter() - start

        result.status_code = resp.status_code
        result.total_time = round(total_time, 4)

        # Parse response body
        body_text = b"".join(chunks).decode("utf-8", errors="replace")
        try:
            body = json.loads(body_text)
            answer = body.get("answer", body.get("message", ""))
            result.answer_length = len(answer)
            result.answer_preview = (answer[:80] + "...") if len(answer) > 80 else answer
        except json.JSONDecodeError:
            result.answer_length = len(body_text)
            result.answer_preview = body_text[:80]

        result.success = resp.status_code == 200

        # Estimate tok/sec: ~4 chars per token is a rough LLM average
        if result.success and result.total_time > 0 and result.answer_length > 0:
            est_tokens = result.answer_length / 4.0
            result.est_tok_sec = round(est_tokens / result.total_time, 2)

    except requests.exceptions.Timeout:
        result.error = "TIMEOUT"
        result.total_time = timeout
    except requests.exceptions.ConnectionError as e:
        result.error = f"CONNECTION_ERROR: {e}"
    except Exception as e:
        result.error = f"ERROR: {e}"

    return result


# ============================================================================
# STATS — Compute aggregate statistics from results
# ============================================================================

def compute_stats(results: List[RequestResult]) -> dict:
    """Compute aggregate statistics from a list of request results."""
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    all_times = [r.total_time for r in results if r.total_time > 0]
    success_times = [r.total_time for r in successful]
    ttfbs = [r.ttfb for r in successful if r.ttfb > 0]

    def percentile(data, p):
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (p / 100)
        f = int(k)
        c = f + 1
        if c >= len(sorted_data):
            return sorted_data[-1]
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])

    total_wall_time = max(all_times) if all_times else 0

    return {
        "total_requests": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "success_rate": f"{len(successful) / len(results) * 100:.1f}%" if results else "N/A",
        # Response time stats (successful only)
        "avg_time": round(statistics.mean(success_times), 3) if success_times else 0,
        "min_time": round(min(success_times), 3) if success_times else 0,
        "max_time": round(max(success_times), 3) if success_times else 0,
        "median_time": round(statistics.median(success_times), 3) if success_times else 0,
        "p90_time": round(percentile(success_times, 90), 3),
        "p95_time": round(percentile(success_times, 95), 3),
        # TTFB stats
        "avg_ttfb": round(statistics.mean(ttfbs), 3) if ttfbs else 0,
        "min_ttfb": round(min(ttfbs), 3) if ttfbs else 0,
        "max_ttfb": round(max(ttfbs), 3) if ttfbs else 0,
        # Throughput
        "throughput": round(len(successful) / total_wall_time, 2) if total_wall_time > 0 else 0,
        "total_wall_time": round(total_wall_time, 3),
        # Answer stats
        "avg_answer_len": round(statistics.mean([r.answer_length for r in successful]), 1) if successful else 0,
        # Estimated tok/sec
        "avg_tok_sec": round(statistics.mean([r.est_tok_sec for r in successful if r.est_tok_sec > 0]), 2) if [r for r in successful if r.est_tok_sec > 0] else 0,
        "min_tok_sec": round(min([r.est_tok_sec for r in successful if r.est_tok_sec > 0]), 2) if [r for r in successful if r.est_tok_sec > 0] else 0,
        "max_tok_sec": round(max([r.est_tok_sec for r in successful if r.est_tok_sec > 0]), 2) if [r for r in successful if r.est_tok_sec > 0] else 0,
    }


# ============================================================================
# OUTPUT — Pretty-print results table and summary
# ============================================================================

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_header(concurrent_users: int, base_url: str, round_num: Optional[int] = None):
    """Print the test header banner."""
    round_text = f" │ Round {round_num}" if round_num else ""
    print()
    print(f"{BOLD}{CYAN}{'═' * 78}{RESET}")
    print(f"{BOLD}{CYAN}  SACHET API LOAD TEST{RESET}")
    print(f"{BOLD}{CYAN}  {concurrent_users} concurrent users │ POST /ask{round_text}{RESET}")
    print(f"{BOLD}{CYAN}  Target: {base_url}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 78}{RESET}")
    print()


def print_results_table(results: List[RequestResult]):
    """Print per-request results as a formatted table."""
    # Column widths
    id_w, q_w, st_w, time_w, ttfb_w, len_w, tok_w = 4, 40, 6, 9, 8, 7, 9

    # Header
    header = (
        f" {'#':>{id_w}} │ {'Question':<{q_w}} │ {'Status':^{st_w}} │ "
        f"{'Time(s)':>{time_w}} │ {'TTFB(s)':>{ttfb_w}} │ {'Ans Len':>{len_w}} │ {'~Tok/sec':>{tok_w}}"
    )
    separator = f"{'─' * (id_w + 1)}┼{'─' * (q_w + 2)}┼{'─' * (st_w + 2)}┼{'─' * (time_w + 2)}┼{'─' * (ttfb_w + 2)}┼{'─' * (len_w + 2)}┼{'─' * (tok_w + 2)}"

    print(f"{DIM}{separator}{RESET}")
    print(f"{BOLD}{header}{RESET}")
    print(f"{DIM}{separator}{RESET}")

    for r in results:
        # Truncate question
        q_display = (r.question[:q_w - 3] + "...") if len(r.question) > q_w else r.question

        # Color status
        if r.success:
            status_str = f"{GREEN}{r.status_code:^{st_w}}{RESET}"
        elif r.error:
            status_str = f"{RED}{'ERR':^{st_w}}{RESET}"
        else:
            status_str = f"{YELLOW}{r.status_code:^{st_w}}{RESET}"

        # Color time (green < 5s, yellow 5-10s, red > 10s)
        if r.total_time < 5:
            time_str = f"{GREEN}{r.total_time:>{time_w}.3f}{RESET}"
        elif r.total_time < 10:
            time_str = f"{YELLOW}{r.total_time:>{time_w}.3f}{RESET}"
        else:
            time_str = f"{RED}{r.total_time:>{time_w}.3f}{RESET}"

        ttfb_str = f"{r.ttfb:>{ttfb_w}.3f}" if r.ttfb > 0 else f"{'—':>{ttfb_w}}"
        len_str = f"{r.answer_length:>{len_w}}" if r.success else f"{'—':>{len_w}}"
        tok_str = f"{r.est_tok_sec:>{tok_w}.2f}" if r.est_tok_sec > 0 else f"{'—':>{tok_w}}"

        print(f" {r.user_id:>{id_w}} │ {q_display:<{q_w}} │ {status_str} │ {time_str} │ {ttfb_str} │ {len_str} │ {tok_str}")

        # Print error on next line if any
        if r.error:
            print(f"      {DIM}└─ {RED}{r.error}{RESET}")

    print(f"{DIM}{separator}{RESET}")
    print()


def print_summary(stats: dict):
    """Print aggregate statistics."""
    s = stats
    w = 52

    print(f"{BOLD}┌─ AGGREGATE STATS {'─' * (w - 19)}┐{RESET}")
    print(f"│  Total Requests:    {s['total_requests']:<{w - 22}}│")
    print(f"│  {GREEN}Success:           {s['successful']} ({s['success_rate']}){RESET}{' ' * max(0, w - 28 - len(str(s['successful'])) - len(s['success_rate']))}│")
    if s['failed'] > 0:
        print(f"│  {RED}Failed:            {s['failed']}{RESET}{' ' * max(0, w - 22 - len(str(s['failed'])))}│")
    else:
        print(f"│  Failed:            {s['failed']}{' ' * max(0, w - 22 - len(str(s['failed'])))}│")
    print(f"│{'':─<{w}}│")
    print(f"│  {BOLD}Response Time:{RESET}{' ' * (w - 16)}│")
    print(f"│    Avg: {s['avg_time']:.3f}s  │  Min: {s['min_time']:.3f}s  │  Max: {s['max_time']:.3f}s{' ' * max(0, w - 47)}│")
    print(f"│    P50: {s['median_time']:.3f}s  │  P90: {s['p90_time']:.3f}s  │  P95: {s['p95_time']:.3f}s{' ' * max(0, w - 47)}│")
    print(f"│{'':─<{w}}│")
    print(f"│  {BOLD}TTFB (Time to First Byte):{RESET}{' ' * (w - 27)}│")
    print(f"│    Avg: {s['avg_ttfb']:.3f}s  │  Min: {s['min_ttfb']:.3f}s  │  Max: {s['max_ttfb']:.3f}s{' ' * max(0, w - 47)}│")
    print(f"│{'':─<{w}}│")
    print(f"│  {BOLD}Throughput:{RESET}  {s['throughput']:.2f} req/sec{' ' * max(0, w - 27 - len(str(s['throughput'])))}│")
    print(f"│  {BOLD}Wall Clock:{RESET}  {s['total_wall_time']:.3f}s{' ' * max(0, w - 24 - len(str(s['total_wall_time'])))}│")
    print(f"│  {BOLD}Avg Answer Length:{RESET}  {s['avg_answer_len']:.0f} chars{' ' * max(0, w - 33 - len(str(int(s['avg_answer_len']))))}│")
    print(f"│{'':─<{w}}│")
    print(f"│  {BOLD}Est. Token Speed (~4 chars/tok):{RESET}{' ' * (w - 33)}│")
    print(f"│    Avg: {s['avg_tok_sec']:.2f}  │  Min: {s['min_tok_sec']:.2f}  │  Max: {s['max_tok_sec']:.2f} tok/s{' ' * max(0, w - 49)}│")
    print(f"└{'─' * w}┘")
    print()


def export_csv(results: List[RequestResult], stats: dict, filepath: str):
    """Export results to a CSV file."""
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            "User ID", "Question", "Status Code", "Total Time (s)",
            "TTFB (s)", "Answer Length", "Est Tok/sec", "Answer Preview", "Error", "Success"
        ])

        # Per-request rows
        for r in results:
            writer.writerow([
                r.user_id, r.question, r.status_code, r.total_time,
                r.ttfb, r.answer_length, r.est_tok_sec, r.answer_preview, r.error, r.success
            ])

        # Blank row + stats
        writer.writerow([])
        writer.writerow(["--- AGGREGATE STATS ---"])
        for key, val in stats.items():
            writer.writerow([key, val])

    print(f"{GREEN}✓ Results exported to {filepath}{RESET}")


# ============================================================================
# ORCHESTRATOR — Run the concurrent load test
# ============================================================================

def run_load_test(
    base_url: str,
    token: str,
    session_id: str,
    concurrent_users: int,
    questions: List[str],
    timeout: int = 120,
    round_num: Optional[int] = None,
) -> List[RequestResult]:
    """Execute the load test with N concurrent users."""

    print_header(concurrent_users, base_url, round_num)

    # Cycle questions to fill all user slots
    assigned_questions = [
        questions[i % len(questions)] for i in range(concurrent_users)
    ]

    results: List[RequestResult] = []

    print(f"  {DIM}Launching {concurrent_users} concurrent requests...{RESET}")
    print()

    wall_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrent_users) as executor:
        future_to_id = {}
        for i, question in enumerate(assigned_questions, start=1):
            future = executor.submit(
                send_ask_request,
                user_id=i,
                question=question,
                base_url=base_url,
                token=token,
                session_id=session_id,
                timeout=timeout,
            )
            future_to_id[future] = i

        for future in as_completed(future_to_id):
            result = future.result()
            results.append(result)

            # Live progress indicator
            status_icon = f"{GREEN}✓{RESET}" if result.success else f"{RED}✗{RESET}"
            print(f"  {status_icon} User {result.user_id:>3} done in {result.total_time:.2f}s — {result.answer_preview[:50]}")

    wall_time = time.perf_counter() - wall_start
    print(f"\n  {DIM}All {concurrent_users} requests completed in {wall_time:.2f}s{RESET}\n")

    # Sort by user ID for display
    results.sort(key=lambda r: r.user_id)

    return results


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Sachet API Concurrent Load Tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python load_test.py                     # 10 concurrent users
  python load_test.py --users 20          # 20 concurrent users
  python load_test.py --rounds 3          # 3 rounds of 10 users
  python load_test.py --csv results.csv   # export to CSV
  python load_test.py --url http://x:5001 # custom server
        """,
    )
    parser.add_argument("--users", type=int, default=CONCURRENT_USERS, help=f"Number of concurrent users (default: {CONCURRENT_USERS})")
    parser.add_argument("--url", type=str, default=BASE_URL, help=f"Base URL of the API server (default: {BASE_URL})")
    parser.add_argument("--token", type=str, default=AUTH_TOKEN, help="Auth token (default: hardcoded test token)")
    parser.add_argument("--session-id", type=str, default=SESSION_ID, help=f"Session ID (default: {SESSION_ID})")
    parser.add_argument("--timeout", type=int, default=120, help="Request timeout in seconds (default: 120)")
    parser.add_argument("--csv", type=str, default=None, metavar="FILE", help="Export results to CSV file")
    parser.add_argument("--rounds", type=int, default=1, help="Number of test rounds to run (default: 1)")

    args = parser.parse_args()

    # ---- Pre-flight health check ----
    print(f"\n{DIM}  Checking server health at {args.url}...{RESET}")
    try:
        hc = requests.get(f"{args.url.rstrip('/')}/healthcheck", timeout=5, verify=False)
        if hc.status_code == 200:
            print(f"  {GREEN}✓ Server is up{RESET}\n")
        else:
            print(f"  {YELLOW}⚠ Healthcheck returned {hc.status_code}{RESET}\n")
    except Exception as e:
        print(f"  {RED}✗ Cannot reach server: {e}{RESET}")
        print(f"  {RED}  Make sure the backend is running (python run.py){RESET}\n")
        sys.exit(1)

    # ---- Run test rounds ----
    all_results: List[RequestResult] = []

    for round_num in range(1, args.rounds + 1):
        round_label = round_num if args.rounds > 1 else None

        results = run_load_test(
            base_url=args.url,
            token=args.token,
            session_id=args.session_id,
            concurrent_users=args.users,
            questions=QUESTIONS,
            timeout=args.timeout,
            round_num=round_label,
        )

        print_results_table(results)
        stats = compute_stats(results)
        print_summary(stats)

        all_results.extend(results)

        # Pause between rounds to let the server recover
        if round_num < args.rounds:
            print(f"  {DIM}Pausing 3s before next round...{RESET}\n")
            time.sleep(3)

    # ---- Multi-round aggregate ----
    if args.rounds > 1:
        print(f"{BOLD}{CYAN}{'═' * 78}{RESET}")
        print(f"{BOLD}{CYAN}  OVERALL SUMMARY — {args.rounds} rounds × {args.users} users = {len(all_results)} total requests{RESET}")
        print(f"{BOLD}{CYAN}{'═' * 78}{RESET}\n")
        overall_stats = compute_stats(all_results)
        print_summary(overall_stats)

    # ---- CSV export ----
    if args.csv:
        final_stats = compute_stats(all_results) if args.rounds > 1 else stats
        export_csv(all_results, final_stats, args.csv)


if __name__ == "__main__":
    main()
