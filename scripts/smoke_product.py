"""Exercise the built product container with disposable data and credentials."""

import json
import subprocess
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8001"


def wait_ready():
    for _ in range(30):
        try:
            with urllib.request.urlopen(URL + "/ready", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.5)
    raise RuntimeError("Product container did not become ready")


def command(*args):
    return subprocess.check_output(
        [
            "docker",
            "exec",
            "rag-product",
            "python",
            "-m",
            "enterprise_rag_system.product_admin",
            "--database",
            "/app/state/registry.sqlite3",
            *args,
        ],
        text=True,
    ).strip()


wait_ready()
token = command("issue-user", "--tenant", "smoke", "--user", "operator", "--role", "admin")


def request(path, method="GET", body=None):
    req = urllib.request.Request(
        URL + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


with urllib.request.urlopen(URL, timeout=5) as response:
    assert b"Arquivo de conhecimento" in response.read()
request(
    "/documents/policy",
    "PUT",
    {"title": "Viagens", "text": "Reembolso no portal.", "expected_revision": 0},
)
assert request("/query", "POST", {"question": "reembolso"})["citations"][0]["doc_id"] == "policy"
command("backup", "/app/state/backup.sqlite3")
subprocess.run(["docker", "restart", "--time", "2", "rag-product"], check=True, capture_output=True)
wait_ready()
assert request("/documents/policy")["revision"] == 1
command("revoke-user", "--tenant", "smoke", "--user", "operator")
try:
    request("/documents")
except urllib.error.HTTPError as exc:
    assert exc.code == 401
else:
    raise AssertionError("Revoked credential still works")
print("Product smoke passed: UI, persistence, query, backup, restart and revocation.")
