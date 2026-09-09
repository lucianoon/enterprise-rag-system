"""Run user-labelled answer/abstention cases against an existing product corpus.

Does not upload documents. API queries may incur provider costs and create query logs.
The report contains answers and document excerpts; keep it with the corpus access rules.
"""

import argparse
import json
import urllib.request
from pathlib import Path
from time import perf_counter

from enterprise_rag_system.product_evaluation import AnswerCase, assess, summarize


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
    cases = [AnswerCase.model_validate(c) for c in json.loads(args.cases.read_text())]
    if not cases:
        parser.error("Cases must be nonempty")
    opener = urllib.request.build_opener(NoRedirect())
    results = []
    for case in cases:
        request = urllib.request.Request(
            args.url.rstrip("/") + "/query",
            data=json.dumps({"question": case.question, "doc_id": case.doc_id}).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        started = perf_counter()
        try:
            with opener.open(request, timeout=180) as response:
                result = json.load(response)
            verdict = assess(case, result, (perf_counter() - started) * 1000)
            results.append({"case": case.model_dump(), **verdict, "response": result})
        except Exception as exc:
            results.append(
                {
                    "case": case.model_dump(),
                    "passed": False,
                    "elapsed_ms": (perf_counter() - started) * 1000,
                    "error_type": type(exc).__name__,
                }
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"summary": summarize(results), "results": results}
    # Do not overwrite an earlier run; create private reports from the start.
    import os

    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{sum(r['passed'] for r in results)}/{len(results)} cases passed")
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()
