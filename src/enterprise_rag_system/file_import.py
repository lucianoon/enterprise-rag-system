"""Bounded, isolated text extraction. Originals are temporary and never persisted."""

import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 32000


def extract(data: bytes, filename: str) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".md", ".pdf", ".docx"}:
        raise ValueError("Formato não suportado. Use TXT, MD, PDF ou DOCX.")
    if not data or len(data) > MAX_BYTES:
        raise ValueError("O arquivo deve ter entre 1 byte e 5 MB.")
    with tempfile.TemporaryDirectory(prefix="rag-import-") as folder:
        source = Path(folder) / ("source" + suffix)
        source.write_bytes(data)
        try:
            result = subprocess.run(
                [sys.executable, "-m", __name__, str(source)],
                capture_output=True,
                env={k: v for k, v in os.environ.items() if k in {"PATH", "PYTHONPATH", "LANG"}}
                | {"OMP_THREAD_LIMIT": "1", "LC_ALL": "C"},
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("A extração excedeu 90 segundos. Divida o documento.") from exc
        if result.returncode:
            raise ValueError("Não foi possível extrair. Verifique o arquivo e os limites.")
        payload = json.loads(result.stdout)
        if "error" in payload:
            raise ValueError(payload["error"])
        return payload


def command(*args):
    return subprocess.run(args, capture_output=True, check=True, timeout=20).stdout


def parse(source: Path) -> dict:
    large = os.getenv("RAG_LARGE_IMPORT") == "true"
    suffix = source.suffix
    ocr_pages = []
    if suffix in {".txt", ".md"}:
        text = source.read_text(encoding="utf-8-sig")
    elif suffix == ".docx":
        with zipfile.ZipFile(source) as archive:
            if not large and sum(i.file_size for i in archive.infolist()) > 20 * 1024 * 1024:
                raise ValueError("DOCX descompactado excede 20 MB.")
            raw = archive.read("word/document.xml")
        if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
            raise ValueError("XML não permitido.")
        root = ElementTree.fromstring(raw)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        text = "\n".join(
            "".join(node.text or "" for node in p.iter(ns + "t")) for p in root.iter(ns + "p")
        )
    else:
        with source.open("rb") as stream:
            signature = stream.read(5)
        if signature != b"%PDF-":
            raise ValueError("O arquivo não é um PDF válido.")
        info = command("pdfinfo", str(source)).decode("utf-8", errors="replace")
        match = re.search(r"^Pages:\s+(\d+)", info, re.M)
        if not match or int(match[1]) < 1 or (not large and int(match[1]) > 20):
            raise ValueError("PDF deve conter até 20 páginas. Divida o documento.")
        if re.search(r"^Encrypted:\s+yes", info, re.M):
            raise ValueError("Remova a proteção por senha do PDF antes de importar.")
        pages = []
        for page in range(1, int(match[1]) + 1):
            out = source.parent / "page.txt"
            command("pdftotext", "-f", str(page), "-l", str(page), str(source), str(out))
            value = out.read_text().strip()
            if len(value) < 30:
                image = source.parent / "scan"
                command(
                    "pdftoppm",
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-singlefile",
                    "-scale-to",
                    "2200",
                    "-png",
                    str(source),
                    str(image),
                )
                value = (
                    command("tesseract", str(image) + ".png", "stdout", "-l", "por+eng")
                    .decode("utf-8")
                    .strip()
                )
                ocr_pages.append(page)
            pages.append(value)
            if not large and sum(map(len, pages)) > MAX_TEXT:
                raise ValueError("Texto excede 32 mil caracteres. Divida o documento.")
        text = "\n\n".join(pages)
    text = text.strip()
    if not text or "\x00" in text:
        raise ValueError("Nenhum texto legível encontrado. Verifique o documento.")
    if not large and len(text) > MAX_TEXT:
        raise ValueError("Texto excede 32 mil caracteres. Divida o documento.")
    return {"text": text, "ocr_pages": ocr_pages}


if __name__ == "__main__":
    import resource

    memory = int(os.getenv("RAG_IMPORT_MEMORY_MB", "768")) * 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    if os.getenv("RAG_LARGE_IMPORT") != "true":
        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    try:
        print(json.dumps(parse(Path(sys.argv[1]))))
    except ValueError as error:
        print(json.dumps({"error": str(error)}))
    except Exception:
        print(json.dumps({"error": "Arquivo inválido ou extração indisponível."}))
