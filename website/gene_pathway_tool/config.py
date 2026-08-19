import os

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
ENTREZ_EMAIL = os.environ.get('ENTREZ_EMAIL', '')
GPT_MODEL = os.environ.get('GPT_MODEL', 'gpt-5.1')

ABBREVIATION_EXPANSION = {
    "AD": "Alzheimer's Disease",
    "PD": "Parkinson's Disease",
    "IBD": "Inflammatory Bowel Disease",
    "MS": "Multiple Sclerosis",
    "ALS": "Amyotrophic Lateral Sclerosis",
    "RA": "Rheumatoid Arthritis",
    "T2D": "Type 2 Diabetes",
    "COPD": "Chronic Obstructive Pulmonary Disease",
}

CATEGORIES = [
    ('GO:BP', 'Biological Process'),
    ('GO:MF', 'Molecular Function'),
    ('GO:CC', 'Cellular Component'),
    ('KEGG', 'KEGG Pathway'),
    ('REAC', 'Reactome Pathway')
]

CATEGORY_CODES = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']

SYSTEM_PROMPTS = {
    'GO:BP': """You are an expert in interpreting disease-related biological processes using Gene Ontology Biological Process (GO:BP) terms.
Your role is to identify GO:BP terms that plausibly connect the input gene list to the specified disease context.
Constraints:
1. Use OFFICIAL GO:BP term names (e.g., "response to oxidative stress").
2. Do NOT fabricate IDs. If you provide an ID (GO:#######), ensure it is correct.
3. Select terms that accurately reflect the granularity of the input module.
4. Do NOT use generic terms like "Biological process" or "Cellular process" unless the module is extremely broad.
5. Prioritize specific terms (e.g., "Interleukin-23-mediated signaling") if supported by the genes.""",

    'GO:MF': """You are an expert in discovering disease-related molecular functions (GO:MF).
Your role is to identify molecular functions that explain HOW gene products contribute to disease mechanisms.
Constraints:
1. Use OFFICIAL GO:MF term names.
2. Distinguish between Activity (e.g., Kinase activity) and Binding (e.g., ATP binding).
3. Select terms that describe the dominant biochemical function of the key drivers.""",

    'GO:CC': """You are an expert in discovering disease-related cellular components (GO:CC).
Your role is to identify cellular locations or complexes relevant to the disease.
Constraints:
1. Use OFFICIAL GO:CC term names.
2. Focus on where the core interaction of the module occurs.""",

    'KEGG': """You are an expert in KEGG pathways.
Your role is to identify KEGG pathways that connect the input genes to the disease.
Constraints:
1. Use OFFICIAL KEGG pathway names (e.g., "mTOR signaling pathway").
2. Do NOT use abbreviated names or qualifiers not in the official name.
3. Ensure the pathway is biologically supported by the input genes.""",

    'REAC': """You are an expert in Reactome pathways.
Your role is to identify Reactome pathways that represent the biological consensus of the module.
Constraints:
1. Use OFFICIAL Reactome pathway names.
2. Avoid broad top-level terms (e.g., "Signal Transduction") if a specific sub-pathway applies.
3. Use exact capitalization and spelling."""
}

MESH_MAP = {
    "alzheimer's disease": "D000544",
    "inflammatory bowel disease": "D015212",
    "parkinson's disease": "D010300",
    "multiple sclerosis": "D009103",
    "amyotrophic lateral sclerosis": "D000690",
    "rheumatoid arthritis": "D001172",
    "type 2 diabetes": "D003924",
}

DISEASE_DESCRIPTIONS = {
    "alzheimer's disease": "A progressive neurodegenerative disorder characterized by cognitive decline and memory loss.",
    "inflammatory bowel disease": "Chronic inflammatory conditions of the gastrointestinal tract including Crohn's disease and ulcerative colitis.",
    "parkinson's disease": "A neurodegenerative disorder characterized by motor symptoms including tremor, rigidity, and bradykinesia.",
    "multiple sclerosis": "An autoimmune demyelinating disease of the central nervous system.",
    "amyotrophic lateral sclerosis": "A progressive neurodegenerative disease affecting motor neurons.",
    "rheumatoid arthritis": "A chronic autoimmune inflammatory disorder primarily affecting joints.",
    "type 2 diabetes": "A metabolic disorder characterized by insulin resistance and high blood sugar levels.",
}


def get_disease_configuration(disease_name: str) -> dict:
    mesh_id = MESH_MAP.get(disease_name.lower(), "D000544")
    description = DISEASE_DESCRIPTIONS.get(
        disease_name.lower(),
        f"Analysis of {disease_name}-related pathways and mechanisms."
    )
    disease_code = disease_name.split()[0].upper()[:5]
    for abbr, full in ABBREVIATION_EXPANSION.items():
        if full.lower() == disease_name.lower():
            disease_code = abbr
            break
    return {
        "mesh_id": mesh_id,
        "full_name": disease_name,
        "disease_code": disease_code,
        "description": description
    }
