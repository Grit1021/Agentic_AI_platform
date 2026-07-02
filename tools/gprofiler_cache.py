import json
import time
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd


class GProfilerCache:
    """
    Disk cache for g:Profiler enrichment results.

    Cache key = SHA-256(sorted gene list + organism + significance threshold)
    Stores results as CSV for seamless DataFrame round-tripping.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".cache" / "pathway_analysis" / "gprofiler"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            project_root = Path(__file__).resolve().parents[2]
            self.cache_dir = project_root / ".cache" / "gprofiler"
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    def _make_key(self, genes: List[str], organism: str = "hsapiens") -> str:
        """Create cache key from sorted gene list."""
        gene_str = "|".join(sorted(g.upper() for g in genes))
        content = f"{gene_str}|{organism}"
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, genes: List[str], organism: str = "hsapiens") -> Optional[pd.DataFrame]:
        """Retrieve cached g:Profiler results if available."""
        key = self._make_key(genes, organism)
        csv_file = self.cache_dir / f"{key}.csv"
        meta_file = self.cache_dir / f"{key}.meta.json"

        if csv_file.exists():
            try:
                df = pd.read_csv(csv_file)
                self._hits += 1
                return df
            except Exception:
                pass

        self._misses += 1
        return None

    def put(self, genes: List[str], results_df: pd.DataFrame, organism: str = "hsapiens"):
        """Store g:Profiler results in cache."""
        key = self._make_key(genes, organism)
        csv_file = self.cache_dir / f"{key}.csv"
        meta_file = self.cache_dir / f"{key}.meta.json"

        try:
            results_df.to_csv(csv_file, index=False)
            with open(meta_file, 'w') as f:
                json.dump({
                    "num_genes": len(genes),
                    "num_results": len(results_df),
                    "organism": organism,
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


# Global instance
gprofiler_cache = GProfilerCache()
