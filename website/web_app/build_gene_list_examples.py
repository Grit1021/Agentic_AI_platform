"""Build the downloadable gene-list examples from archived, validated inputs."""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
EXAMPLES_DIR = APP_ROOT / "examples"
EXAMPLE_SIZE = 120
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")
ENSEMBL_PATTERN = re.compile(r"^ENSG\d{11}$")


def unique(values):
    seen = set()
    result = []
    for value in values:
        normalized = str(value or "").strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def load_example_identifiers():
    gene_lists = json.loads((APP_ROOT / "gene_lists.json").read_text(encoding="utf-8"))
    ad_lists = gene_lists["AD"]["lists"]
    symbol_source = next(item for item in ad_lists if item["id"] == "AD_top_module")
    symbols = unique(symbol_source["genes"])[:EXAMPLE_SIZE]

    archived = json.loads((APP_ROOT / "pinned_ad_example.json").read_text(encoding="utf-8"))
    ensembl_ids = unique(archived["result"]["input_genes"])[:EXAMPLE_SIZE]

    if len(symbols) != EXAMPLE_SIZE or not all(SYMBOL_PATTERN.fullmatch(item) for item in symbols):
        raise ValueError("HGNC example source does not contain 120 valid symbols")
    if len(ensembl_ids) != EXAMPLE_SIZE or not all(ENSEMBL_PATTERN.fullmatch(item) for item in ensembl_ids):
        raise ValueError("Ensembl example source does not contain 120 valid Gene IDs")
    return symbols, ensembl_ids


def build_examples():
    symbols, ensembl_ids = load_example_identifiers()
    EXAMPLES_DIR.mkdir(exist_ok=True)

    text_files = {
        "hgnc_symbols.txt": "\n".join(symbols) + "\n",
        "ensembl_gene_ids.txt": "\n".join(ensembl_ids) + "\n",
    }
    mixed_buffer = io.StringIO(newline="")
    writer = csv.writer(mixed_buffer, lineterminator="\n")
    writer.writerows(zip(symbols[: EXAMPLE_SIZE // 2], ensembl_ids[EXAMPLE_SIZE // 2 :]))
    text_files["mixed_identifiers.csv"] = mixed_buffer.getvalue()

    for filename, content in text_files.items():
        (EXAMPLES_DIR / filename).write_text(content, encoding="utf-8")

    bundle_path = EXAMPLES_DIR / "gene_list_examples.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in text_files.items():
            entry = zipfile.ZipInfo(filename, date_time=(2026, 9, 7, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, content.encode("utf-8"))
    return bundle_path


if __name__ == "__main__":
    print(build_examples())
