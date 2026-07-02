import os
import sys

# ============================================================================
# DISEASE CONFIGURATION
# ============================================================================

# Set the disease to analyze (can be abbreviation or full name)
CURRENT_DISEASE = os.environ.get("CURRENT_DISEASE", "AD")

# Common abbreviation expansion
ABBREVIATION_EXPANSION = {
    "AD": "Alzheimer's Disease",
    "PD": "Parkinson's Disease",
    "IBD": "Inflammatory Bowel Disease",
    "MS": "Multiple Sclerosis",
    "ALS": "Amyotrophic Lateral Sclerosis",
    "RA": "Rheumatoid Arthritis",
    "T2D": "Type 2 Diabetes",
    "SLE": "Systemic Lupus Erythematosus",
    "CD": "Crohn's Disease",
    "UC": "Ulcerative Colitis",
    "HD": "Huntington's Disease",
    "CF": "Cystic Fibrosis",
    "CKD": "Chronic Kidney Disease",
    "HF": "Heart Failure",
    "AST": "Asthma",
    "EP": "Epilepsy",
    "MDD": "Major Depressive Disorder",
    "PS": "Psoriasis",
    "HTN": "Hypertension",
    "OA": "Osteoarthritis",
    "COPD": "Chronic Obstructive Pulmonary Disease",
    "MI": "Myocardial Infarction",
    "ATH": "Atherosclerosis",
    "NAFLD": "Non-Alcoholic Fatty Liver Disease",
    # 6 new benchmark diseases (30-disease expansion)
    "SCZ": "Schizophrenia",
    "OBS": "Obesity",
    "BC":  "Breast Cancer",
    "LC":  "Lung Cancer",
    "IPF": "Idiopathic Pulmonary Fibrosis",
    "COVID": "COVID-19",
}

# ============================================================================
# FEEDBACK MODE
# ============================================================================

# 'full'        : GPT biological reasoning + p-value feedback (default)
# 'pvalue_only' : Statistical p-value feedback only (no biological reasoning)
FEEDBACK_MODE = "full"

# ============================================================================
# TEST MODE
# ============================================================================

TEST_MODE = False  # Set to False to process all modules (non-interactive mode)
TEST_MODULES = [5, 14]  # Only process these modules in TEST_MODE

# Disease keywords placeholder (will be set dynamically in main)
DISEASE_KEYWORDS = []


def get_disease_config():
    """
    Dynamically get disease configuration using mesh_utils.

    Retrieves MeSH ID and description from NCBI for any disease name.
    No hardcoded configuration needed.
    """
    from .module_loading import ensure_backend_paths

    ensure_backend_paths()

    from mesh_utils import get_mesh_id, get_disease_description_from_ncbi

    # Expand abbreviation if needed
    disease_name = ABBREVIATION_EXPANSION.get(
        CURRENT_DISEASE.upper(), CURRENT_DISEASE
    )

    # Determine disease code
    disease_code = CURRENT_DISEASE.upper()
    if disease_code not in ABBREVIATION_EXPANSION:
        # Generate a short code from the full name
        words = disease_name.split()
        if len(words) == 1:
            disease_code = disease_name[:3].upper()
        else:
            disease_code = "".join(w[0] for w in words).upper()

    print(f"\n🔍 Looking up disease: {disease_name} (code: {disease_code})")

    # Get MeSH ID
    mesh_id = get_mesh_id(disease_name)
    if not mesh_id:
        print(f"⚠️  Could not find MeSH ID for '{disease_name}'")
        print("   Using fallback MeSH ID: D000544 (Alzheimer's Disease)")
        mesh_id = "D000544"

    # Get disease description from NCBI
    description = get_disease_description_from_ncbi(mesh_id)
    if not description:
        description = f"{disease_name} is a complex disease requiring further description."

    # Generate disease-specific keywords
    keywords = []
    for word in disease_name.lower().split():
        if len(word) > 3 and word not in ['disease', 'syndrome', 'disorder']:
            keywords.append(word)
    # Add full name as keyword
    keywords.insert(0, disease_name.lower())

    config = {
        "disease_code": disease_code,
        "full_name": disease_name,
        "mesh_id": mesh_id,
        "description": description,
        "keywords": keywords,
    }

    print(f"   ✅ Disease config loaded: {disease_code} [{mesh_id}]")
    return config


def get_pubmed_disease_name(disease_name: str) -> str:
    """
    Convert module-style disease names to proper PubMed-searchable names.
    e.g., "AD_Module_5_iter1" -> "Alzheimer's Disease"
    """
    # Try to extract disease code from module-style names
    for code, full_name in ABBREVIATION_EXPANSION.items():
        if disease_name.upper().startswith(code + "_") or disease_name.upper() == code:
            return full_name

    # If already a full name, return as-is
    if any(disease_name.lower().startswith(name.lower()[:5])
           for name in ABBREVIATION_EXPANSION.values()):
        return disease_name

    # Fallback: return original
    return disease_name
