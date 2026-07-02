from .pubmed import search_pubmed_for_pathway, get_pubmed_cache_stats
from .gprofiler_cache import GProfilerCache, gprofiler_cache

__all__ = [
    'search_pubmed_for_pathway', 'get_pubmed_cache_stats',
    'BiologicalRankingAgent', 'gpt_rank_pathways',
    'GProfilerCache', 'gprofiler_cache',
]


def __getattr__(name):
    if name in {'BiologicalRankingAgent', 'gpt_rank_pathways'}:
        from .ranking import BiologicalRankingAgent, gpt_rank_pathways

        return {
            'BiologicalRankingAgent': BiologicalRankingAgent,
            'gpt_rank_pathways': gpt_rank_pathways,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
