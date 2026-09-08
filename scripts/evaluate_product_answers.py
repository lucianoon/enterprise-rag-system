"""Run user-labelled answer/abstention cases against an existing product corpus.

Does not upload documents. API queries may incur provider costs and create query logs.
The report contains answers and document excerpts; keep it with the corpus access rules.
"""

import argparse
import json
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8002")
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    token = args.token_file.read_text().strip()
    cases = json.loads(args.cases.read_text())
    if not cases or any(type(c.get("expected_abstention")) is not bool for c in cases):
        parser.error("Cases must be nonempty and specify expected_abstention as a boolean")
    opener = urllib.request.build_opener(NoRedirect())
    results = []
    for case in cases:
        request = urllib.request.Request(
            args.url.rstrip("/") + "/query",
            data=json.dumps({"question": case["question"], "doc_id": case["doc_id"]}).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with opener.open(request, timeout=180) as response:
                result = json.load(response)
            passed = result["abstained"] == case["expected_abstention"]
            if case["expected_abstention"]:
                passed &= result["metadata"]["verification"] == "insufficient"
                passed &= not result["citations"]
            else:
                passed &= result["metadata"]["verification"] == "supported"
                passed &= bool(result["citations"])
            results.append({**case, "passed": passed, "response": result})
        except Exception as exc:
            results.append({**case, "passed": False, "error_type": type(exc).__name__})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(f"{sum(r['passed'] for r in results)}/{len(results)} cases passed")
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()
