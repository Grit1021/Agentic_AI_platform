import json
import openai

from .config import OPENAI_API_KEY, GPT_MODEL

KNOWN_TARGETS = {
    "APOE": ("APOE modulators", "Phase 2", "Alzheimer's Disease"),
    "APP": ("Aducanumab", "FDA Approved", "Alzheimer's Disease"),
    "BACE1": ("Verubecestat", "Phase 3 (discontinued)", "Alzheimer's Disease"),
    "TREM2": ("AL002", "Phase 2", "Alzheimer's Disease"),
    "PSEN1": ("Gamma-secretase inhibitors", "Phase 2", "Alzheimer's Disease"),
    "MAPT": ("Tau aggregation inhibitors", "Phase 2", "Alzheimer's Disease"),
    "TNF": ("Infliximab/Adalimumab", "FDA Approved", "Inflammatory diseases"),
    "IL23R": ("Ustekinumab/Risankizumab", "FDA Approved", "IBD/Psoriasis"),
    "JAK2": ("Tofacitinib/Ruxolitinib", "FDA Approved", "Rheumatoid Arthritis/MPN"),
    "JAK1": ("Upadacitinib", "FDA Approved", "Rheumatoid Arthritis"),
    "IL6": ("Tocilizumab", "FDA Approved", "Rheumatoid Arthritis"),
    "NOD2": ("Experimental", "Preclinical", "IBD"),
    "PCSK9": ("Evolocumab/Alirocumab", "FDA Approved", "Hypercholesterolemia"),
    "APOB": ("Mipomersen", "FDA Approved", "Familial Hypercholesterolemia"),
    "LPA": ("Pelacarsen", "Phase 3", "Cardiovascular Disease"),
    "EGFR": ("Gefitinib/Osimertinib", "FDA Approved", "Lung Cancer"),
    "BRAF": ("Vemurafenib/Dabrafenib", "FDA Approved", "Melanoma"),
    "BCR-ABL": ("Imatinib", "FDA Approved", "CML"),
    "HER2": ("Trastuzumab", "FDA Approved", "Breast Cancer"),
    "SOD1": ("Tofersen", "FDA Approved", "ALS"),
    "HTT": ("Risdiplam", "Phase 3", "Huntington's Disease"),
}


def generate_drug_targets(genes: list, pathways: list) -> list:
    if OPENAI_API_KEY:
        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            pathway_context = "\n".join([
                f"- {p.get('name', 'Unknown')}: {p.get('genes', '')[:80]}"
                for p in pathways[:10]
            ]) if pathways else "N/A"

            gene_list = ", ".join(genes[:30])

            prompt = f"""Based on the following pathway analysis and gene list, identify the top 5 druggable targets with existing or potential therapeutic compounds.

ENRICHED PATHWAYS:
{pathway_context}

KEY GENES:
{gene_list}

For each target, provide:
1. Gene symbol
2. Drug name (approved, investigational, or repurposing candidate)
3. Development status (FDA Approved, Phase 1/2/3, Preclinical)
4. Primary indication

Return as JSON array with keys: gene, drug, status, indication
Return ONLY the JSON array, no other text."""

            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": "You are a pharmaceutical expert. Provide accurate drug target information."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_completion_tokens=600
            )

            result_text = response.choices[0].message.content.strip()
            if '[' in result_text:
                json_start = result_text.index('[')
                json_end = result_text.rindex(']') + 1
                result_text = result_text[json_start:json_end]

            targets = json.loads(result_text)
            if targets and len(targets) > 0:
                return targets[:5]

        except Exception as e:
            print(f"  GPT drug target analysis failed: {e}")

    targets = []
    for gene in genes[:20]:
        gene_upper = gene.upper()
        if gene_upper in KNOWN_TARGETS:
            drug, status, indication = KNOWN_TARGETS[gene_upper]
            targets.append({
                "gene": gene, "drug": drug,
                "status": status, "indication": indication
            })
        if len(targets) >= 5:
            break

    if len(targets) < 3:
        for gene in genes[:5]:
            if gene not in [t['gene'] for t in targets]:
                targets.append({
                    "gene": gene,
                    "drug": "Potential target (no approved drugs)",
                    "status": "Target identification",
                    "indication": "Under investigation"
                })
                if len(targets) >= 5:
                    break

    return targets[:5]
