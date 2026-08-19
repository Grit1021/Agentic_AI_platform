#!/usr/bin/env python3
"""Read-only localhost server for the enhanced result interface."""

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


APP_DIR = Path(__file__).parent / "web_app"
HISTORY_FILE = APP_DIR / "run_history.json"
GENE_LISTS_FILE = APP_DIR / "gene_lists.json"


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        path = unquote(urlparse(self.path).path)

        if path == "/api/status":
            self.send_json(
                {
                    "status": "ready",
                    "mode": "read-only result preview",
                    "result_demo": "/?demo=1",
                }
            )
            return

        if path == "/api/history":
            history = json.loads(HISTORY_FILE.read_text())
            entries = []
            for item in history:
                genes = item.get("genes", [])
                entries.append(
                    {
                        "session_id": item.get("session_id"),
                        "disease": item.get("disease"),
                        "disease_name": item.get("disease_name"),
                        "gene_count": item.get("gene_count", len(genes)),
                        "genes_preview": ", ".join(genes[:5])
                        + ("..." if len(genes) > 5 else ""),
                        "model": item.get("model", "gpt-5.1"),
                        "status": item.get("status", "unknown"),
                        "created_at": item.get("created_at"),
                        "completed_at": item.get("completed_at"),
                    }
                )
            self.send_json({"history": entries, "total": len(entries)})
            return

        if path.startswith("/api/history/"):
            history = json.loads(HISTORY_FILE.read_text())
            session_id = path.rsplit("/", 1)[-1]
            item = next(
                (row for row in history if row.get("session_id") == session_id), None
            )
            if item is None:
                self.send_json({"error": "Not found"}, status=404)
            else:
                self.send_json(item)
            return

        if path == "/api/gene-lists":
            data = json.loads(GENE_LISTS_FILE.read_text())
            for disease in data.values():
                for gene_list in disease.get("lists", []):
                    gene_list["gene_count"] = len(gene_list.get("genes", []))
            self.send_json(data)
            return

        if path.startswith("/api/gene-lists/"):
            parts = path.strip("/").split("/")
            if len(parts) != 4:
                self.send_json({"error": "Not found"}, status=404)
                return

            _, _, disease_code, list_id = parts
            data = json.loads(GENE_LISTS_FILE.read_text())
            disease = data.get(disease_code.upper())
            if disease is None:
                self.send_json({"error": "Disease not found"}, status=404)
                return

            gene_list = next(
                (item for item in disease.get("lists", []) if item.get("id") == list_id),
                None,
            )
            if gene_list is None:
                self.send_json({"error": "Gene list not found"}, status=404)
                return

            self.send_json({
                **gene_list,
                "disease_code": disease_code.upper(),
                "disease_name": disease.get("name", disease_code.upper()),
                "list_id": list_id,
                "gene_count": len(gene_list.get("genes", [])),
            })
            return

        super().do_GET()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}/"
    print(f"Input preview: {base_url}", flush=True)
    print(f"Result demo:   {base_url}?demo=1", flush=True)
    ThreadingHTTPServer((args.host, args.port), PreviewHandler).serve_forever()
