from .config import ENTREZ_EMAIL, ABBREVIATION_EXPANSION


def search_pubmed(pathway_name: str, disease_name: str, max_results: int = 20) -> tuple:
    try:
        from Bio import Entrez, Medline
        import time

        Entrez.email = ENTREZ_EMAIL or "researcher@example.com"

        if "_Module_" in disease_name:
            disease_name = ABBREVIATION_EXPANSION.get(
                disease_name.split("_")[0].upper(),
                disease_name.split("_")[0]
            )

        query = f'("{pathway_name}") AND ("{disease_name}")'

        try:
            handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results, sort="relevance")
            record = Entrez.read(handle)
            handle.close()
        except Exception:
            time.sleep(1)
            handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results, sort="relevance")
            record = Entrez.read(handle)
            handle.close()

        ids = record.get("IdList", [])
        if not ids:
            return "No PubMed results found", []

        handle = Entrez.efetch(db="pubmed", id=ids, rettype="medline", retmode="text")
        records = list(Medline.parse(handle))
        handle.close()

        paper_list = []
        seen_titles = set()

        for i, rec in enumerate(records, 1):
            abstract = rec.get("AB", "")
            title = rec.get("TI", "No title")

            if not abstract or title.lower() in seen_titles:
                continue

            seen_titles.add(title.lower())

            paper_list.append({
                'pmid': rec.get("PMID", "N/A"),
                'title': title,
                'journal': rec.get("JT", rec.get("TA", "Unknown")),
                'year': rec.get("DP", "")[:4] if rec.get("DP") else "N/A",
                'relevance_score': 1.0 - (i / (len(records) + 1))
            })

        summary = f"Found {len(paper_list)} papers (of {len(ids)} total)"
        return summary, paper_list

    except ImportError:
        return "PubMed search unavailable (Biopython not installed)", []
    except Exception as e:
        return f"PubMed error: {str(e)[:50]}", []
