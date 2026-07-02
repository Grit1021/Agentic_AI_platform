import os
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional, Tuple, Dict
from pathlib import Path


# Cache configuration
CACHE_DIR = Path(__file__).parent
CACHE_FILE = CACHE_DIR / ".mesh_cache.json"
CACHE_VERSION = "1.0"

# In-memory cache (loaded from file on first use)
_mesh_id_cache: Dict[str, str] = {}
_description_cache: Dict[str, str] = {}
_cache_loaded = False

# NCBI API configuration
NCBI_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
NCBI_API_DELAY = 0.34  # NCBI requires max 3 requests/second without API key

# Abbreviation expansion dictionary
# Expands common disease abbreviations to full names for better NCBI E-Search results
# This avoids ambiguity when searching for short abbreviations like "AD", "PD"
ABBREVIATION_EXPANSION = {
    "AD": "Alzheimer disease",
    "PD": "Parkinson disease",
    "ALS": "Amyotrophic Lateral Sclerosis",
    "HD": "Huntington disease",
    "MS": "Multiple Sclerosis",
}


def _load_cache():
    """Load cache from file if it exists."""
    global _mesh_id_cache, _description_cache, _cache_loaded
    
    if _cache_loaded:
        return
    
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
                _mesh_id_cache = cache_data.get('mesh_id_cache', {})
                _description_cache = cache_data.get('description_cache', {})
                print(f"  💾 Loaded MeSH cache: {len(_mesh_id_cache)} IDs, {len(_description_cache)} descriptions")
    except Exception as e:
        print(f"  ⚠️  Failed to load MeSH cache: {e}")
        _mesh_id_cache = {}
        _description_cache = {}
    
    _cache_loaded = True


def _save_cache():
    """Save cache to file."""
    try:
        cache_data = {
            'mesh_id_cache': _mesh_id_cache,
            'description_cache': _description_cache,
            'metadata': {
                'version': CACHE_VERSION,
                'last_updated': time.strftime('%Y-%m-%dT%H:%M:%S')
            }
        }
        
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, indent=2)
            
    except Exception as e:
        print(f"  ⚠️  Failed to save MeSH cache: {e}")


def disease_name_to_mesh_id(disease_name: str, use_cache: bool = True) -> Optional[str]:
    """
    Dynamically map disease name to MeSH ID using NCBI E-Search.
    
    This function searches the NCBI MeSH database for the best matching
    MeSH term for the given disease name.
    
    Parameters:
    -----------
    disease_name : str
        Disease name to search (e.g., "Alzheimer's disease", "AD")
    use_cache : bool
        Whether to use cached results (default: True)
    
    Returns:
    --------
    str or None
        MeSH ID (e.g., "D000544") if found, None otherwise
    
    Examples:
    ---------
    >>> disease_name_to_mesh_id("Alzheimer's disease")
    'D000544'
    >>> disease_name_to_mesh_id("AD")
    'D000544'
    >>> disease_name_to_mesh_id("Unknown Disease XYZ")
    None
    """
    _load_cache()
    
    # Check cache first
    if use_cache and disease_name in _mesh_id_cache:
        cached_id = _mesh_id_cache[disease_name]
        # Verify cached ID is a descriptor (D-prefix), not qualifier (Q-prefix)
        if cached_id.startswith('D'):
            return cached_id
        else:
            print(f"  ⚠️  Removing invalid cached ID: {cached_id} for '{disease_name}'")
            del _mesh_id_cache[disease_name]
            _save_cache()
    
    # Expand abbreviations to full names for better NCBI E-Search results
    search_term = disease_name
    if disease_name in ABBREVIATION_EXPANSION:
        search_term = ABBREVIATION_EXPANSION[disease_name]
        print(f"  🔄 Expanding abbreviation '{disease_name}' → '{search_term}'")
    
    # Try dynamic NCBI E-Search with the search term
    print(f"  🔍 Searching NCBI E-Search for '{search_term}'...")
    
    try:
        import requests
        
        # Construct E-Search query
        # Search in MeSH database without field restriction for better matching
        query = search_term  # Use expanded term if available
        
        params = {
            'db': 'mesh',
            'term': query,
            'retmode': 'json',
            'retmax': '5',  # Get top 5 results to check
            'sort': 'relevance'
        }
        
        # Rate limiting
        time.sleep(NCBI_API_DELAY)
        
        # Make API request using requests library (more reliable than urllib)
        response = requests.get(NCBI_ESEARCH_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Extract MeSH UID
        id_list = data.get('esearchresult', {}).get('idlist', [])
        
        if not id_list:
            print(f"  ⚠️  No MeSH ID found for '{disease_name}'")
            return None
        
        # Try each UID until we find a valid D-prefixed MeSH ID
        for mesh_uid in id_list:
            mesh_id = _fetch_mesh_id_from_uid(mesh_uid)
            if mesh_id:
                # Cache the result
                _mesh_id_cache[disease_name] = mesh_id
                _save_cache()
                print(f"  🔍 Resolved '{disease_name}' → MeSH ID: {mesh_id}")
                return mesh_id
        
        print(f"  ⚠️  No valid MeSH ID found in results for '{disease_name}'")
        return None
        
    except requests.RequestException as e:
        print(f"  ❌ Network error resolving MeSH ID for '{disease_name}': {e}")
        return None
    except Exception as e:
        print(f"  ❌ Error resolving MeSH ID for '{disease_name}': {e}")
        return None


def _fetch_mesh_id_from_uid(mesh_uid: str) -> Optional[str]:
    """
    Fetch actual MeSH ID (D-prefixed) from MeSH UID using E-Summary.
    
    Uses the same proven approach as get_official_mesh_description:
    E-Summary returns JSON with the MeSH UI directly.
    
    IMPORTANT: Only returns Descriptor IDs (D-prefix), not Qualifiers (Q-prefix).
    
    Parameters:
    -----------
    mesh_uid : str
        MeSH UID from E-Search (e.g., "68000544")
    
    Returns:
    --------
    str or None
        MeSH Descriptor ID (e.g., "D000544") if found, None for qualifiers
    """
    try:
        import requests
        
        # Use E-Summary (JSON) instead of E-Fetch (XML) to avoid SSL issues
        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        params = {
            'db': 'mesh',
            'id': mesh_uid,
            'retmode': 'json'
        }
        
        # Rate limiting
        time.sleep(NCBI_API_DELAY)
        
        # Use requests library
        response = requests.get(summary_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Extract MeSH ID from JSON
        # Path: result -> UID -> ds_meshui
        result_block = data.get('result', {}).get(str(mesh_uid), {})
        mesh_id = result_block.get('ds_meshui')
        
        if mesh_id:
            # Only accept Descriptor IDs (D-prefix), reject Qualifiers (Q-prefix)
            if mesh_id.startswith('D'):
                return mesh_id
            else:
                print(f"  ⚠️  Skipping non-descriptor MeSH ID: {mesh_id} (UID: {mesh_uid})")
                return None
        
        return None
        
    except Exception as e:
        print(f"  ⚠️  Error fetching MeSH ID from UID {mesh_uid}: {e}")
        return None


def get_mesh_description(mesh_id: str, use_cache: bool = True) -> Optional[str]:
    """
    Fetch MeSH term description using proven implementation from planning_utils.
    
    This function uses the existing get_official_mesh_description from the 
    PlanningAgent's utils, which has been verified to work correctly.
    
    Parameters:
    -----------
    mesh_id : str
        MeSH ID (e.g., "D000544")
    use_cache : bool
        Whether to use cached results (default: True)
    
    Returns:
    --------
    str or None
        MeSH term description/summary if found
    
    Examples:
    ---------
    >>> desc = get_mesh_description("D000544")
    >>> "degenerative" in desc.lower()
    True
    """
    _load_cache()
    
    # Check cache first
    if use_cache and mesh_id in _description_cache:
        return _description_cache[mesh_id]
    
    try:
        import requests
        
        # Direct NCBI E-Utilities call (same logic as planning_utils.get_official_mesh_description
        # but without importing planning_utils which triggers BioBERT tokenizer loading)
        clean_id = mesh_id.replace("MESH:", "").strip()
        
        # Step 1: E-Search to get internal UID
        search_params = {
            'db': 'mesh',
            'term': f'{clean_id}[ui]',
            'retmode': 'json'
        }
        time.sleep(NCBI_API_DELAY)
        r1 = requests.get(NCBI_ESEARCH_URL, params=search_params, timeout=10)
        r1.raise_for_status()
        search_data = r1.json()
        
        id_list = search_data.get('esearchresult', {}).get('idlist', [])
        if not id_list:
            print(f"  ⚠️  MeSH ID {clean_id} not found in E-Search")
            return None
        
        uid = id_list[0]
        
        # Step 2: E-Summary to get scope note
        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        summary_params = {
            'db': 'mesh',
            'id': uid,
            'retmode': 'json'
        }
        time.sleep(NCBI_API_DELAY)
        r2 = requests.get(summary_url, params=summary_params, timeout=10)
        r2.raise_for_status()
        summary_data = r2.json()
        
        result_block = summary_data.get('result', {}).get(str(uid), {})
        description = result_block.get('ds_scopenote') or result_block.get('ds_scope')
        
        if description:
            # Cache the result
            _description_cache[mesh_id] = description
            _save_cache()
            return description
        
        return None
        
    except Exception as e:
        print(f"  ❌ Error fetching description for MeSH ID {mesh_id}: {e}")
        return None


def get_disease_description_by_name(disease_name: str) -> Optional[str]:
    """
    Try to get disease description directly from NCBI by searching disease name.
    
    This function searches NCBI MeSH database for the disease name and retrieves
    the description from the first result, even if it's not a standard Descriptor.
    
    This is used as an intermediate fallback when:
    - No standard MeSH Descriptor ID (D-prefix) is found
    - But we still want to try NCBI before falling back to LLM
    
    Parameters:
    -----------
    disease_name : str
        Disease name to search
    
    Returns:
    --------
    str or None
        Disease description if found in NCBI
    
    Examples:
    ---------
    >>> desc = get_disease_description_by_name("Rare Disease XYZ")
    >>> desc is not None
    True  # If NCBI has any information about it
    """
    print(f"  🔍 Searching NCBI for description of '{disease_name}'...")
    
    try:
        import requests
        
        # Step 1: E-Search to find UIDs
        params = {
            'db': 'mesh',
            'term': disease_name,
            'retmode': 'json',
            'retmax': '1',  # Just get the top result
            'sort': 'relevance'
        }
        
        time.sleep(NCBI_API_DELAY)
        
        response = requests.get(NCBI_ESEARCH_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        id_list = data.get('esearchresult', {}).get('idlist', [])
        
        if not id_list:
            print(f"  ⚠️  No NCBI results for '{disease_name}'")
            return None
        
        mesh_uid = id_list[0]
        
        # Step 2: E-Summary to get description
        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        params = {
            'db': 'mesh',
            'id': mesh_uid,
            'retmode': 'json'
        }
        
        time.sleep(NCBI_API_DELAY)
        
        response = requests.get(summary_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        result_block = data.get('result', {}).get(str(mesh_uid), {})
        
        # Try to get scope note (detailed description)
        description = result_block.get('ds_scopenote')
        
        if description:
            print(f"  ✅ Found NCBI description ({len(description)} chars)")
            return description
        
        # Fallback: get term name as minimal description
        term_name = result_block.get('ds_meshterms')
        if term_name and isinstance(term_name, list) and len(term_name) > 0:
            description = term_name[0]
            print(f"  ⚠️  Using MeSH term name: {description}")
            return description
        
        print(f"  ⚠️  No description available in NCBI for '{disease_name}'")
        return None
        
    except requests.RequestException as e:
        print(f"  ❌ Network error searching NCBI: {e}")
        return None
    except Exception as e:
        print(f"  ❌ Error searching NCBI: {e}")
        return None


def get_disease_description_with_fallback(disease_name: str) -> Tuple[str, str]:
    """
    Get disease description with multi-layer fallback strategy.
    
    Fallback Strategy:
    1. Try to map disease_name → MeSH ID → fetch description from NCBI
    2. If no MeSH ID found, try searching NCBI directly by disease name
    3. If NCBI has no information, return None (caller should use LLM)
    
    Parameters:
    -----------
    disease_name : str
        Disease name to get description for
    
    Returns:
    --------
    tuple : (description: str or None, source: str)
        - description: Disease description text, or None if NCBI has no info
        - source: "mesh" | "ncbi_search" | "fallback"
    
    Examples:
    ---------
    >>> desc, source = get_disease_description_with_fallback("Alzheimer's disease")
    >>> source
    'mesh'
    >>> len(desc) > 100
    True
    
    >>> desc, source = get_disease_description_with_fallback("Unknown XYZ")
    >>> source
    'fallback'
    >>> desc is None
    True  # Caller should use LLM to generate description
    """
    print(f"  📚 Getting description for: {disease_name}")
    
    # Layer 1: Try MeSH ID resolution
    mesh_id = disease_name_to_mesh_id(disease_name)
    
    if mesh_id:
        print(f"  ✅ Resolved MeSH ID: {mesh_id}")
        
        # Layer 1.5: Fetch description from MeSH
        description = get_mesh_description(mesh_id)
        
        if description:
            print(f"  ✅ Fetched MeSH description ({len(description)} chars)")
            return description, "mesh"
        else:
            print(f"  ⚠️  Failed to fetch MeSH description for {mesh_id}")
    else:
        print(f"  ⚠️  No MeSH ID found for '{disease_name}'")
    
    # Layer 2: Try searching NCBI directly by disease name
    print(f"  🔄 Trying direct NCBI search...")
    ncbi_desc = get_disease_description_by_name(disease_name)
    
    if ncbi_desc:
        return ncbi_desc, "ncbi_search"
    
    # Layer 3: Return None - caller should use LLM
    print(f"  ⚠️  No NCBI information available for '{disease_name}'")
    return None, "fallback"


# Convenience function for backward compatibility
def get_enriched_disease_description(disease_name: str) -> str:
    """
    Get enriched disease description (backward compatible wrapper).
    
    This function maintains backward compatibility with existing code
    that expects just the description string.
    
    Parameters:
    -----------
    disease_name : str
        Disease name
    
    Returns:
    --------
    str
        Disease description
    """
    description, _ = get_disease_description_with_fallback(disease_name)
    return description
