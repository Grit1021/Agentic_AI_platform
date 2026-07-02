import os
import json
import time
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any

from ..config import get_pubmed_disease_name


# ============================================================================
# PUBMED CACHE
# ============================================================================

class PubMedCache:
    """
    Disk cache for PubMed search results.

    Cache key = SHA-256(pathway_name + disease_name + max_results)
    Significantly reduces Entrez API calls for repeated or re-run analyses.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".cache" / "pathway_analysis" / "pubmed"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            project_root = Path(__file__).resolve().parents[2]
            self.cache_dir = project_root / ".cache" / "pubmed"
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    def _make_key(self, pathway: str, disease: str, max_results: int) -> str:
        content = f"{pathway.lower().strip()}|{disease.lower().strip()}|{max_results}"
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, pathway: str, disease: str, max_results: int) -> Optional[List[Dict]]:
        key = self._make_key(pathway, disease, max_results)
        cache_file = self.cache_dir / f"{key}.json"

        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                self._hits += 1
                return data.get("papers", [])
            except (json.JSONDecodeError, IOError):
                pass

        self._misses += 1
        return None

    def put(self, pathway: str, disease: str, max_results: int, papers: List[Dict]):
        key = self._make_key(pathway, disease, max_results)
        cache_file = self.cache_dir / f"{key}.json"

        try:
            with open(cache_file, 'w') as f:
                json.dump({
                    "pathway": pathway,
                    "disease": disease,
                    "max_results": max_results,
                    "papers": papers,
                    "cached_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }, f, indent=2)
        except IOError:
            pass

    @property
    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate_pct": round(self._hits / total * 100, 1) if total > 0 else 0,
        }


# Global cache instance
_pubmed_cache = PubMedCache()


# ============================================================================
# PUBMED SEARCH
# ============================================================================

def search_pubmed_for_pathway(
    pathway_name: str,
    disease_name: str,
    query_agent=None,
    max_results: int = 60,
    pathway_description: str = "",
    disease_description: str = "",
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """
    Search PubMed for papers linking pathway to disease using Biopython Entrez.

    Results are cached to disk. On subsequent runs with the same pathway+disease,
    cached results are returned without hitting the Entrez API.

    Parameters
    ----------
    pathway_name : str
        Name of the biological pathway
    disease_name : str
        Name of the disease
    query_agent : optional
        Optional compatibility parameter (not used)
    max_results : int
        Maximum number of results to fetch
    pathway_description : str
        Additional pathway context
    disease_description : str
        Additional disease context
    use_cache : bool
        Whether to use disk cache (default: True)

    Returns
    -------
    List of dicts with keys: pmid, title, relevance_score
    """
    pubmed_disease = get_pubmed_disease_name(disease_name)

    # Check cache
    if use_cache:
        cached = _pubmed_cache.get(pathway_name, pubmed_disease, max_results)
        if cached is not None:
            return cached

    # Fetch from Entrez
    papers = _fetch_from_entrez(pathway_name, pubmed_disease, max_results)

    # Store in cache
    if use_cache:
        _pubmed_cache.put(pathway_name, pubmed_disease, max_results, papers)

    return papers


def get_pubmed_cache_stats() -> Dict[str, Any]:
    """Return PubMed cache hit/miss statistics."""
    return _pubmed_cache.stats


def _fetch_from_entrez(
    pathway_name: str, disease_name: str, max_results: int
) -> List[Dict[str, Any]]:
    """Fetch papers from PubMed via Biopython Entrez."""
    try:
        from Bio import Entrez

        Entrez.email = os.environ.get('ENTREZ_EMAIL', 'researcher@example.com')

        clean_pathway = pathway_name.replace("'", "").replace('"', '')

        queries = [
            f'("{clean_pathway}"[Title/Abstract]) AND ("{disease_name}"[Title/Abstract])',
            f'({clean_pathway}[Title/Abstract]) AND ({disease_name}[Title/Abstract])',
        ]

        all_pmids = set()
        all_papers = []

        for query in queries:
            if len(all_papers) >= max_results:
                break

            try:
                handle = Entrez.esearch(
                    db="pubmed", term=query,
                    retmax=min(max_results - len(all_papers), 30),
                    sort="relevance",
                )
                results = Entrez.read(handle)
                handle.close()

                pmids = results.get("IdList", [])
                new_pmids = [p for p in pmids if p not in all_pmids]

                if not new_pmids:
                    continue

                handle = Entrez.efetch(
                    db="pubmed", id=",".join(new_pmids),
                    rettype="medline", retmode="xml",
                )
                records = Entrez.read(handle)
                handle.close()

                for article in records.get("PubmedArticle", []):
                    try:
                        medline = article.get("MedlineCitation", {})
                        pmid = str(medline.get("PMID", ""))

                        if pmid in all_pmids:
                            continue
                        all_pmids.add(pmid)

                        article_data = medline.get("Article", {})
                        title = str(article_data.get("ArticleTitle", ""))

                        relevance = _calculate_relevance(
                            title, clean_pathway, disease_name
                        )

                        all_papers.append({
                            "pmid": pmid,
                            "title": title,
                            "relevance_score": relevance,
                        })
                    except Exception:
                        continue

                time.sleep(0.34)  # NCBI rate limit

            except Exception as e:
                print(f"      ⚠️  PubMed query failed: {e}")
                continue

        all_papers.sort(key=lambda x: x["relevance_score"], reverse=True)
        return all_papers[:max_results]

    except ImportError:
        print("      ⚠️  Biopython not installed. PubMed search disabled.")
        return []
    except Exception as e:
        print(f"      ⚠️  PubMed search failed: {e}")
        return []


def _calculate_relevance(
    title: str, pathway_name: str, disease_name: str
) -> float:
    """Calculate simple relevance score based on keyword matches in title."""
    title_lower = title.lower()
    pathway_lower = pathway_name.lower()
    disease_lower = disease_name.lower()

    score = 0.0

    pathway_words = [w for w in pathway_lower.split() if len(w) > 3]
    for word in pathway_words:
        if word in title_lower:
            score += 1.0

    disease_words = [w for w in disease_lower.split() if len(w) > 3]
    for word in disease_words:
        if word in title_lower:
            score += 1.0

    total = len(pathway_words) + len(disease_words)
    return round(score / total, 3) if total > 0 else 0.0
