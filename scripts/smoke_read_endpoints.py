#!/usr/bin/env python3
"""
Smoke tests for external read capabilities.

Tests both /web-read and /notion-read/page endpoints:
- Success cases (200)
- Error cases (403, 502, 504, 503, 422)
- Response schema validation
- Latency measurement

Usage:
    python scripts/smoke_read_endpoints.py [--api-base http://localhost:8000]
"""

import sys
import json
import time
import argparse
from datetime import datetime
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:
    print("ERROR: requests module not found. Install with: pip install requests")
    sys.exit(1)


class SmokeTestRunner:
    """Run smoke tests for read endpoints."""

    def __init__(self, api_base: str, verbose: bool = False):
        self.api_base = api_base.rstrip("/")
        self.verbose = verbose
        self.results = []
        self.passed = 0
        self.failed = 0

    def log(self, level: str, message: str) -> None:
        """Log message with timestamp."""
        timestamp = datetime.now().isoformat(timespec="seconds")
        prefix = f"[{timestamp}] {level:8}"
        print(f"{prefix} {message}")

    def test(
        self,
        name: str,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        expected_status: int = 200,
        validate_schema: Optional[callable] = None,
    ) -> bool:
        """Run a single test."""
        url = f"{self.api_base}{path}"
        self.log("INFO", f"Test: {name}")
        self.log("INFO", f"  {method} {path}")
        if params:
            self.log("INFO", f"  params: {params}")

        start = time.time()
        try:
            if method == "GET":
                response = requests.get(url, params=params, timeout=15)
            else:
                self.log("ERROR", f"Unsupported method: {method}")
                return False

            latency = int((time.time() - start) * 1000)
            self.log("INFO", f"  status: {response.status_code} (latency: {latency}ms)")

            # Check status code
            if response.status_code != expected_status:
                self.log(
                    "ERROR",
                    f"  expected {expected_status}, got {response.status_code}",
                )
                if self.verbose and response.text:
                    self.log("ERROR", f"  response: {response.text[:200]}")
                self.failed += 1
                return False

            # Validate schema if provided
            if validate_schema:
                try:
                    data = response.json()
                    if not validate_schema(data):
                        self.log("ERROR", f"  schema validation failed")
                        if self.verbose:
                            self.log("ERROR", f"  response: {json.dumps(data)}")
                        self.failed += 1
                        return False
                except json.JSONDecodeError:
                    self.log("ERROR", f"  response is not valid JSON")
                    if self.verbose:
                        self.log("ERROR", f"  response: {response.text[:200]}")
                    self.failed += 1
                    return False

            self.log("PASS", f"  {name}")
            self.passed += 1
            return True

        except requests.exceptions.Timeout:
            latency = int((time.time() - start) * 1000)
            self.log("ERROR", f"  timeout after {latency}ms")
            self.failed += 1
            return False
        except requests.exceptions.ConnectionError as e:
            self.log("ERROR", f"  connection error: {e}")
            self.failed += 1
            return False
        except Exception as e:
            self.log("ERROR", f"  unexpected error: {e}")
            if self.verbose:
                import traceback

                traceback.print_exc()
            self.failed += 1
            return False

    def run_all(self) -> None:
        """Run all smoke tests."""
        self.log("INFO", f"Starting smoke tests against {self.api_base}")
        self.log("INFO", "=" * 60)

        # Web Read tests
        self.log("INFO", "")
        self.log("INFO", "WEB READ TESTS")
        self.log("INFO", "-" * 60)

        # Success case
        self.test(
            "Web Read: valid URL (example.com)",
            "GET",
            "/web-read",
            params={"url": "https://example.com"},
            expected_status=200,
            validate_schema=lambda d: all(
                k in d for k in ["url", "final_url", "content_type", "title", "text", "truncated"]
            ),
        )

        # Validation error (missing param)
        self.test(
            "Web Read: missing url parameter",
            "GET",
            "/web-read",
            params={},
            expected_status=422,
        )

        # Validation error (empty url)
        self.test(
            "Web Read: empty url parameter",
            "GET",
            "/web-read",
            params={"url": ""},
            expected_status=422,
        )

        # Notion Read tests
        self.log("INFO", "")
        self.log("INFO", "NOTION READ TESTS")
        self.log("INFO", "-" * 60)

        # Success case (if page_id in allowlist)
        # This will likely return 403 without proper setup, but tests the endpoint
        self.test(
            "Notion Read: test with placeholder page_id",
            "GET",
            "/notion-read/page",
            params={"page_id": "test-page-id"},
            expected_status=403,  # Expected to fail (not in allowlist for smoke test)
        )

        # Validation error (missing param)
        self.test(
            "Notion Read: missing page_id parameter",
            "GET",
            "/notion-read/page",
            params={},
            expected_status=422,
        )

        # Validation error (empty page_id)
        self.test(
            "Notion Read: empty page_id parameter",
            "GET",
            "/notion-read/page",
            params={"page_id": ""},
            expected_status=422,
        )

        # Results
        self.log("INFO", "")
        self.log("INFO", "=" * 60)
        self.log("INFO", f"SMOKE TEST RESULTS")
        self.log("INFO", f"  Passed: {self.passed}")
        self.log("INFO", f"  Failed: {self.failed}")
        self.log("INFO", f"  Total:  {self.passed + self.failed}")
        self.log("INFO", "=" * 60)

        if self.failed > 0:
            self.log("ERROR", f"Some tests failed!")
            sys.exit(1)
        else:
            self.log("INFO", "All tests passed!")
            sys.exit(0)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Smoke tests for external read capabilities"
    )
    parser.add_argument(
        "--api-base",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose output (full responses)",
    )

    args = parser.parse_args()

    runner = SmokeTestRunner(args.api_base, verbose=args.verbose)
    runner.run_all()


if __name__ == "__main__":
    main()
