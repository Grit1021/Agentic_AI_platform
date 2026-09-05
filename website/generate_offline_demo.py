#!/usr/bin/env python3
"""Generate a traceable browser demo from a completed run and enrichment snapshot."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
WEB_APP_DIR = PROJECT_DIR / "web_app"
HISTORY_PATH = WEB_APP_DIR / "run_history.json"
OUTPUT_PATH = WEB_APP_DIR / "offline_demo_data.js"
JSON_OUTPUT_PATH = WEB_APP_DIR / "offline_demo_data.json"
PROFILE_SNAPSHOT_PATH = PROJECT_DIR / "demo_sources" / "gprofiler_profile.json"
PATHWAY_CONTEXT_PATH = PROJECT_DIR / "demo_sources" / "ad_module6_pathway_context.json"

# g:Profiler renamed this KEGG entry after the historical run. The stable
# native identifier is recoverable from the preserved AD_Module_6 matrix.
HISTORICAL_PATHWAY_IDS = {
    ("KEGG", "lysosome"): "KEGG:04142",
}


# Biological interpretations for the fixed, publication-facing AD demo. Each
# statement is anchored to the regenerated input–pathway intersection and the
# PubMed records already attached to that pathway; statistical enrichment is
# displayed separately in the interface.
DEMO_INTERPRETATION_POINTS = {
    "GO:0150076": [
        ("Biological context", "Neuroinflammatory responses coordinate innate immune signaling, protease activity and tissue remodeling in injured neural tissue."),
        ("Gene-level support", "GRN contributes to lysosomal and myeloid-cell homeostasis, while MMP9, MMP8, CTSC and AZU1 connect the input module to extracellular remodeling and innate immune effector activity."),
        ("Disease relevance", "In Alzheimer's disease, persistent microglial and astrocytic inflammatory signaling can amplify synaptic injury around amyloid and tau pathology. The GRN-centered lysosomal signal together with MMP8, MMP9, CTSC and AZU1 protease activity supports a neuroimmune-remodeling interpretation of this gene module."),
    ],
    "GO:0001774": [
        ("Biological context", "Microglial activation describes the transition of resident brain macrophages from homeostatic surveillance toward phagocytic, inflammatory or repair-associated states."),
        ("Gene-level support", "The intersection is anchored by GRN and the protease-related genes CTSC, MMP8 and AZU1, consistent with lysosomal remodeling and myeloid effector programs that accompany activated microglia."),
        ("Disease relevance", "Activated microglia accumulate around amyloid plaques and can contribute both protective clearance and chronic inflammatory injury in Alzheimer's disease, making activation state—not activation alone—the key biological question."),
    ],
    "GO:0006954": [
        ("Biological context", "This broad inflammatory program combines innate sensing, inflammasome-associated signaling, protease release, extracellular-matrix remodeling and acute-phase responses."),
        ("Gene-level support", "PYCARD and GSDMD support inflammasome-linked cell-death signaling; PGLYRP1, TOLLIP and LYZ support innate recognition; MMP8/MMP9, PTX3, ORM1/ORM2 and HP extend the signal to tissue remodeling and acute-phase biology."),
        ("Disease relevance", "The coordinated inflammatory signature is compatible with microglial and astrocytic responses reported in Alzheimer's disease, although the pathway is not cell-type-specific and may also capture peripheral innate immune activity."),
    ],
    "GO:0061900": [
        ("Biological context", "Glial-cell activation encompasses stimulus-induced state changes in microglia and astrocytes, including altered morphology, cytokine signaling, phagocytosis and metabolic support."),
        ("Gene-level support", "GRN links the input module to glial lysosomal homeostasis, while CTSC, MMP8 and AZU1 indicate proteolytic and innate immune effector activity associated with reactive glial states."),
        ("Disease relevance", "Spatial and imaging studies cited with this record describe glial activation during Alzheimer's disease progression, supporting a disease-relevant neuroimmune interpretation without assigning a single beneficial or harmful direction."),
    ],
    "GO:0005515": [
        ("Biological context", "Protein binding is a high-level molecular-function term that captures interaction capacity across signaling, structural, immune and proteostasis proteins rather than one discrete mechanism."),
        ("Gene-level support", "The large intersection includes MAPK1, PYCARD, VCP, multiple cathepsins and chaperone-related proteins, indicating an interaction-rich module spanning inflammatory signaling and protein quality control."),
        ("Disease relevance", "Amyloid-beta and tau toxicity depend on altered protein interactions and aggregation, but this broad GO term should be interpreted as supportive context rather than a pathway-specific Alzheimer's disease mechanism."),
    ],
    "GO:0005509": [
        ("Biological context", "Calcium-ion binding supports calcium-dependent membrane organization, cytoskeletal regulation, secretion and signal transduction."),
        ("Gene-level support", "ANXA2, THBS1, S100A7, GCA, CRACR2A and SPTAN1 connect the submitted module to calcium-responsive membrane and cytoskeletal functions."),
        ("Disease relevance", "Calcium dyshomeostasis is a recurring feature of Alzheimer's disease biology and can couple synaptic stress to mitochondrial and proteostatic dysfunction; the present term provides functional context but is not disease-specific."),
    ],
    "GO:0005764": [
        ("Biological context", "Lysosomes integrate macromolecule degradation, lipid handling, autophagic clearance and innate immune functions."),
        ("Gene-level support", "The intersection contains GRN, NPC2 and numerous lysosomal hydrolases and cathepsins, providing dense support for degradative and lipid-processing capacity in the input module."),
        ("Disease relevance", "Impaired autophagy–lysosome function can reduce clearance of amyloid, tau and damaged organelles in neurons and glia; the attached studies connect restoration of lysosomal function with Alzheimer's disease models."),
    ],
    "GO:0005783": [
        ("Biological context", "The endoplasmic reticulum coordinates secretory-protein folding, lipid synthesis, calcium storage and quality-control responses to misfolded proteins."),
        ("Gene-level support", "ERP44 and TXNDC5 support oxidative protein folding, while VCP and FAF2 connect the module to ER-associated protein quality control; MAPK1 and PRKCD provide stress-signaling links."),
        ("Disease relevance", "ER stress and the unfolded-protein response can couple amyloid/tau proteotoxicity and calcium imbalance to neuroinflammation and apoptosis in Alzheimer's disease."),
    ],
    "GO:0005788": [
        ("Biological context", "The endoplasmic-reticulum lumen is the compartment in which secreted and membrane proteins undergo folding, disulfide-bond formation and early quality control."),
        ("Gene-level support", "ERP44 and TXNDC5 directly support luminal protein-folding chemistry, while ARSA, ARSB, CTSZ and CTSC reflect secretory-pathway transit of lysosomal enzymes."),
        ("Disease relevance", "This compartment links the input module to secretory-pathway proteostasis, a process that can influence the handling of aggregation-prone proteins in Alzheimer's disease."),
    ],
    "KEGG:04142": [
        ("Biological context", "The KEGG lysosome pathway organizes acid hydrolases and lipid, glycan and protein degradation reactions required for cellular recycling."),
        ("Gene-level support", "AGA, HEXB, CTSA, ARSA, multiple cathepsins, ASAH1, NPC2, GNS, GUSB, GLB1, FUCA1, GM2A and NEU1 form a coherent lysosomal enzyme module."),
        ("Disease relevance", "The overlap spans glycan degradation, lipid handling and lysosomal proteolysis, supporting a coordinated degradative program rather than an isolated enzyme signal. In Alzheimer's disease, this map-level pattern is relevant to amyloid/tau clearance, mitophagy and microglial processing of extracellular material."),
    ],
    "KEGG:04210": [
        ("Biological context", "The apoptosis pathway integrates stress signaling with protease activation and regulated dismantling of damaged cells."),
        ("Gene-level support", "MAPK1 provides a stress-signaling node, while CTSZ, CTSH, CTSC, CTSD and CTSS connect lysosomal protease activity to cell-death regulation; SPTAN1 is a cytoskeletal substrate of proteolytic injury."),
        ("Disease relevance", "The combined MAPK1 stress-signaling, cathepsin and SPTAN1 pattern links cellular stress to proteolytic and cytoskeletal injury within the apoptosis map. This supports an apoptosis-associated contribution to neuronal vulnerability in Alzheimer's disease without implying that apoptosis is the only death program in the tissue."),
    ],
    "REAC:R-HSA-168249": [
        ("Biological context", "Reactome's Innate Immune System pathway covers pattern recognition, inflammatory signaling, antimicrobial effectors, phagocyte activation and immune-linked cell death."),
        ("Gene-level support", "The broad intersection includes TOLLIP, LYZ, MPO, PYCARD, GSDMD, PTPN6, PTX3, CHI3L1 and multiple proteases, forming a dense innate-immune and myeloid-effector signature."),
        ("Disease relevance", "Pattern-recognition, inflammasome-linked and phagocyte-effector clusters together place this module within microglial innate-immune remodeling in Alzheimer's disease, with implications for plaque handling and inflammatory injury. Because this Reactome entry is a broad parent event, its child pathways provide the appropriate level for resolving the specific reaction mechanism."),
    ],
    "GO:0006979": [
        ("Biological context", "The oxidative-stress response balances oxidant production, antioxidant defense, redox metabolism and repair of oxidatively damaged molecules."),
        ("Gene-level support", "MPO represents oxidant-generating activity, PRDX6 antioxidant defense, IDH1 and NAPRT redox-metabolic support, and HP/HBB heme-associated oxidative biology."),
        ("Disease relevance", "Oxidative stress can connect mitochondrial dysfunction, neuroinflammation and proteotoxic injury in Alzheimer's disease, consistent with the disease-focused literature attached to this pathway."),
    ],
    "GO:0043065": [
        ("Biological context", "Positive regulation of apoptosis captures upstream signals and proteolytic processes that increase commitment to regulated cell death."),
        ("Gene-level support", "PYCARD and PRKCD link inflammatory and stress signaling to cell-death control, while CTSH, CTSC and CTSD provide lysosomal protease support; GRN, MMP9 and THBS1 add injury-remodeling context."),
        ("Disease relevance", "This intersection suggests convergence between inflammatory stress and cell-death regulation in Alzheimer's disease, a relationship also reflected in the attached literature on inflammasome, MAPK and regulated-death pathways."),
    ],
    "GO:0006457": [
        ("Biological context", "Protein folding maintains proteome stability through chaperone-assisted folding, complex assembly and quality control."),
        ("Gene-level support", "CCT2 and CCT8 support cytosolic chaperonin activity, while ERP44 and TXNDC5 support oxidative folding in the secretory pathway; together they define a coherent proteostasis signal."),
        ("Disease relevance", "Failure of protein-folding and quality-control systems can promote amyloid-beta and tau misfolding in Alzheimer's disease, making proteostasis a plausible mechanistic bridge from this gene module to pathology."),
    ],
    "GO:0002526": [
        ("Biological context", "Acute inflammatory responses mobilize proteases and acute-phase proteins during rapid innate immune activation."),
        ("Gene-level support", "ELANE supplies neutrophil protease activity, while ORM1, ORM2 and HP are circulating acute-phase proteins that report systemic inflammatory and tissue-injury responses."),
        ("Disease relevance", "The signal may capture a peripheral acute-phase component relevant to systemic inflammation in Alzheimer's disease; it should not be interpreted as proof that the enriched genes originate from resident brain cells."),
    ],
}


# Structured extracts used by the result page to keep the long interpretation
# readable.  Every symbol is filtered against the audited query-term
# intersection before it is written to the demo, so this table cannot make a
# non-intersection protein look like part of the result.
DEMO_NARRATIVE_ANNOTATIONS = {
    "GO:0150076": {
        "drivers": ["GRN", "MMP9"],
        "clusters": [
            ("Lysosomal and myeloid homeostasis", ["GRN", "CTSC", "AZU1"]),
            ("Protease and matrix remodeling", ["MMP8", "MMP9"]),
        ],
    },
    "GO:0001774": {
        "drivers": ["GRN", "CTSC"],
        "clusters": [
            ("Lysosomal remodeling", ["GRN", "CTSC"]),
            ("Myeloid effector activity", ["MMP8", "AZU1"]),
        ],
    },
    "GO:0006954": {
        "drivers": ["PYCARD", "GSDMD", "MMP9"],
        "clusters": [
            ("Inflammasome-linked signaling", ["PYCARD", "GSDMD"]),
            ("Innate recognition", ["PGLYRP1", "TOLLIP", "LYZ"]),
            ("Tissue remodeling", ["MMP8", "MMP9", "PTX3"]),
            ("Acute-phase response", ["ORM1", "ORM2", "HP"]),
        ],
    },
    "GO:0061900": {
        "drivers": ["GRN", "CTSC"],
        "clusters": [
            ("Glial lysosomal homeostasis", ["GRN", "CTSC"]),
            ("Reactive effector activity", ["MMP8", "AZU1"]),
        ],
    },
    "GO:0005515": {
        "drivers": ["MAPK1", "PYCARD", "VCP"],
        "clusters": [
            ("Inflammatory signaling", ["MAPK1", "PYCARD", "GSDMD", "TOLLIP"]),
            ("Protein quality control", ["VCP", "CCT2", "CCT8", "ERP44", "TXNDC5"]),
            ("Lysosomal proteolysis", ["CTSD", "CTSS", "CTSC", "CTSH", "CTSZ"]),
        ],
    },
    "GO:0005509": {
        "drivers": ["ANXA2", "SPTAN1", "CRACR2A"],
        "clusters": [
            ("Membrane and cytoskeleton", ["ANXA2", "SPTAN1", "THBS1"]),
            ("Calcium-responsive signaling", ["CRACR2A", "GCA", "S100A7"]),
        ],
    },
    "GO:0005764": {
        "drivers": ["GRN", "NPC2"],
        "clusters": [
            ("Acid hydrolases", ["AGA", "HEXB", "GLA", "GNS", "GUSB", "GLB1"]),
            ("Cathepsin proteases", ["CTSA", "CTSG", "CTSZ", "CTSH", "CTSC", "CTSD", "CTSS"]),
            ("Lipid handling", ["ASAH1", "NPC2", "GM2A"]),
        ],
    },
    "GO:0005783": {
        "drivers": ["VCP", "ERP44", "TXNDC5"],
        "clusters": [
            ("Oxidative protein folding", ["ERP44", "TXNDC5"]),
            ("ER-associated quality control", ["VCP", "FAF2"]),
            ("Stress signaling", ["MAPK1", "PRKCD", "PYCARD"]),
        ],
    },
    "GO:0005788": {
        "drivers": ["ERP44", "TXNDC5"],
        "clusters": [
            ("Luminal protein folding", ["ERP44", "TXNDC5"]),
            ("Lysosomal-enzyme transit", ["ARSA", "ARSB", "CTSZ", "CTSC"]),
        ],
    },
    "KEGG:04142": {
        "drivers": ["NPC2", "HEXB", "ASAH1"],
        "clusters": [
            ("Glycan degradation", ["AGA", "HEXB", "GNS", "GUSB", "GLB1", "FUCA1", "NEU1"]),
            ("Lipid degradation and transport", ["ASAH1", "NPC2", "GM2A"]),
            ("Proteolysis", ["CTSA", "CTSG", "CTSZ", "CTSH", "CTSC", "CTSD", "CTSS"]),
        ],
    },
    "KEGG:04210": {
        "drivers": ["MAPK1", "CTSD", "SPTAN1"],
        "clusters": [
            ("Stress signaling", ["MAPK1"]),
            ("Lysosomal proteases", ["CTSZ", "CTSH", "CTSC", "CTSD", "CTSS"]),
            ("Cytoskeletal injury", ["SPTAN1"]),
        ],
    },
    "REAC:R-HSA-168249": {
        "drivers": ["TOLLIP", "PYCARD", "GSDMD"],
        "clusters": [
            ("Pattern recognition", ["PGLYRP1", "TOLLIP", "LYZ"]),
            ("Inflammatory cell death", ["PYCARD", "GSDMD"]),
            ("Phagocyte effectors", ["MPO", "LTF", "CTSG", "ELANE"]),
            ("Tissue remodeling", ["MMP8", "MMP9", "PTX3"]),
        ],
    },
    "GO:0006979": {
        "drivers": ["PRDX6", "MPO", "IDH1"],
        "clusters": [
            ("Oxidant generation", ["MPO", "PRKCD"]),
            ("Antioxidant defense", ["PRDX6", "HP"]),
            ("Redox metabolism", ["IDH1", "NAPRT"]),
        ],
    },
    "GO:0043065": {
        "drivers": ["PYCARD", "PRKCD", "CTSD"],
        "clusters": [
            ("Inflammatory death signaling", ["PYCARD", "PRKCD"]),
            ("Lysosomal proteases", ["CTSH", "CTSC", "CTSD"]),
            ("Injury remodeling", ["GRN", "MMP9", "THBS1"]),
        ],
    },
    "GO:0006457": {
        "drivers": ["ERP44", "CCT2", "TXNDC5"],
        "clusters": [
            ("Cytosolic chaperonin", ["CCT2", "CCT8"]),
            ("Secretory-pathway folding", ["ERP44", "TXNDC5"]),
            ("Proteostasis support", ["GRN", "B2M"]),
        ],
    },
    "GO:0002526": {
        "drivers": ["ELANE", "ORM1", "HP"],
        "clusters": [
            ("Neutrophil protease activity", ["ELANE"]),
            ("Circulating acute-phase response", ["ORM1", "ORM2", "HP"]),
        ],
    },
}


def build_demo_pathway_narrative(disease_name, profile_row, symbols, interpretation_points):
    """Create the audited offline narrative without an additional model call."""
    pathway_id = str(profile_row.get("native") or "")
    pathway_name = str(profile_row.get("name") or "this pathway")
    opening = (
        f"{len(symbols)} submitted {disease_name}-associated proteins were significantly enriched "
        f"in {pathway_name}{f' ({pathway_id})' if pathway_id else ''}."
    )
    paragraphs = [opening]
    paragraphs.extend(
        str(point.get("text") or "").strip()
        for point in interpretation_points
        if str(point.get("text") or "").strip()
    )

    allowed = {str(symbol).upper(): str(symbol) for symbol in symbols}
    annotation = DEMO_NARRATIVE_ANNOTATIONS.get(pathway_id, {})
    drivers = [
        allowed[gene.upper()]
        for gene in annotation.get("drivers", [])
        if gene.upper() in allowed
    ]
    clusters = []
    for label, members in annotation.get("clusters", []):
        genes = [allowed[gene.upper()] for gene in members if gene.upper() in allowed]
        if genes:
            clusters.append({"label": label, "genes": genes})

    return {
        "paragraphs": paragraphs,
        "driver_genes": drivers,
        "clusters": clusters,
        "discussed_genes": list(dict.fromkeys(drivers + [g for c in clusters for g in c["genes"]])),
        "generated": False,
        "provenance": "audited archived interpretation",
    }


def load_pathway_cell_context(path=PATHWAY_CONTEXT_PATH):
    """Load the audited pathway-level context pass for the final demo list."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records = payload.get("records") or {}
    if not records:
        raise RuntimeError(f"No pathway-level context records found in {path}.")

    required_metadata = {
        "interpretation_pass_id",
        "generated_at",
        "source_type",
        "evidence_contract",
        "method",
    }
    missing_metadata = required_metadata.difference(payload)
    if missing_metadata:
        raise RuntimeError(
            f"Pathway-level interpretation pass is missing: {', '.join(sorted(missing_metadata))}."
        )
    required_fields = {"pathway_name", "cell_context", "cell_context_pmids", "source_type"}
    for pathway_id, record in records.items():
        missing = required_fields.difference(record)
        if missing:
            raise RuntimeError(
                f"Cell-context record {pathway_id} is missing: {', '.join(sorted(missing))}."
            )
        if not str(record.get("cell_context") or "").strip():
            raise RuntimeError(f"Cell-context record {pathway_id} is empty.")
        if record.get("source_type") != payload.get("source_type"):
            raise RuntimeError(
                f"Cell-context record {pathway_id} does not use the unified interpretation pass."
            )
    return payload


def sanitize_public_result(value):
    """Remove implementation-only fields that are not manuscript outputs."""
    excluded_fields = {
        "score",
        "gpt_score",
        "evidence_score",
        "relevance_score",
        "drug_targets",
        "evidence_assessment",
        "report",
        "top_pathway",
        "top_pathway_score",
        "top_pathway_database",
        "strongest_database",
    }
    if isinstance(value, dict):
        return {
            key: sanitize_public_result(item)
            for key, item in value.items()
            if key not in excluded_fields
        }
    if isinstance(value, list):
        return [sanitize_public_result(item) for item in value]
    return value


def select_demo_entry(history):
    """Return the most recently completed historical run."""
    completed = [entry for entry in history if entry.get("status") == "completed"]
    if not completed:
        raise RuntimeError("No completed analysis is available for the offline demo.")
    return max(completed, key=lambda entry: str(entry.get("completed_at") or ""))


def input_sha256(genes):
    canonical = "\n".join(str(gene).strip() for gene in genes) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_name(value):
    return " ".join(str(value or "").casefold().split())


def _clean_definition(value):
    """Remove database quotation wrappers while retaining citation brackets."""
    text = str(value or "").strip()
    if text.startswith(('"', '“', '”')):
        text = text[1:].lstrip()
    bracket_index = text.rfind(" [")
    if bracket_index > 0 and text[bracket_index - 1:bracket_index] in ('"', '“', '”'):
        text = text[:bracket_index - 1] + text[bracket_index:]
    return text.rstrip('"“”').strip()


def _legacy_intersection_size(pathway):
    value = pathway.get("intersection_size")
    if value is None and str(pathway.get("genes") or "").strip().isdigit():
        value = pathway.get("genes")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def load_profile_snapshot(snapshot_path=PROFILE_SNAPSHOT_PATH):
    if not snapshot_path.exists():
        raise RuntimeError(
            f"Missing {snapshot_path}. Run refresh_demo_enrichment.py before generating the demo."
        )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    rows = snapshot.get("rows") or []
    if not rows:
        raise RuntimeError("The g:Profiler snapshot contains no enrichment rows.")
    if len(rows) != int(snapshot.get("matrix_row_count") or 0):
        raise RuntimeError("The g:Profiler snapshot row count is inconsistent.")
    return snapshot


def _build_profile_index(rows):
    index = {}
    for row in rows:
        key = (str(row.get("source") or ""), _normalized_name(row.get("name")))
        index.setdefault(key, []).append(row)
    return index


def _match_profile_row(pathway, profile_index):
    category = str(pathway.get("source") or pathway.get("category") or "")
    normalized_name = _normalized_name(pathway.get("name") or pathway.get("pathway_name"))
    key = (category, normalized_name)
    candidates = profile_index.get(key, [])
    pathway_id = str(
        pathway.get("pathway_id")
        or pathway.get("native")
        or pathway.get("term_id")
        or HISTORICAL_PATHWAY_IDS.get((category, normalized_name))
        or ""
    ).strip()
    if not candidates and pathway_id:
        candidates = [
            row
            for rows in profile_index.values()
            for row in rows
            if str(row.get("source") or "") == category
            and str(row.get("native") or "") == pathway_id
        ]
    if pathway_id:
        exact_id = [row for row in candidates if str(row.get("native") or "") == pathway_id]
        if exact_id:
            candidates = exact_id
    if not candidates:
        raise RuntimeError(
            f"No g:Profiler row matches {category} / {pathway.get('name', 'Unknown')}."
        )
    if len(candidates) == 1:
        return candidates[0]

    legacy_p = pathway.get("p_value", pathway.get("pvalue"))
    try:
        legacy_p = float(legacy_p)
    except (TypeError, ValueError):
        legacy_p = None
    if legacy_p is not None:
        return min(candidates, key=lambda row: abs(float(row.get("p_value") or 1) - legacy_p))
    raise RuntimeError(
        f"Ambiguous g:Profiler match for {category} / {pathway.get('name', 'Unknown')}."
    )


def _interpretation_points(disease_name, profile_row, symbols):
    """Return biological interpretation points grounded in the demo record."""
    pathway_id = str(profile_row.get("native") or "")
    curated = DEMO_INTERPRETATION_POINTS.get(pathway_id)
    if curated:
        return [{"label": label, "text": text} for label, text in curated]

    pathway_name = str(profile_row.get("name") or "This pathway")
    pathway_definition = str(profile_row.get("description") or "").strip().strip('"“”')
    shown = symbols[:12]
    gene_text = ", ".join(shown)
    if len(symbols) > len(shown):
        gene_text += f", and {len(symbols) - len(shown)} additional intersection genes"
    return [
        {
            "label": "Biological context",
            "text": pathway_definition or f"{pathway_name} is an annotated biological pathway or function.",
        },
        {
            "label": "Gene-level support",
            "text": f"The submitted module maps to this term through {gene_text}.",
        },
        {
            "label": "Disease relevance",
            "text": (
                f"This result prioritizes {pathway_name} for biological review in {disease_name}; "
                "the attached literature should be used to evaluate mechanism, direction and cell-type context."
            ),
        },
    ]


def _grounded_interpretation(disease_name, profile_row, symbols):
    """Create a readable interpretation string for exports and legacy clients."""
    return "\n".join(
        f"{point['label']}: {point['text']}"
        for point in _interpretation_points(disease_name, profile_row, symbols)
    )


def reconcile_pathways(result, entry, snapshot):
    """Replace legacy counts with one internally consistent g:Profiler replay."""
    input_genes = [str(gene).strip() for gene in entry.get("genes", [])]
    snapshot_genes = [str(gene).strip() for gene in snapshot.get("input_genes", [])]
    expected_hash = input_sha256(input_genes)
    snapshot_hash = snapshot.get("historical_run", {}).get("input_sha256")
    if input_genes != snapshot_genes or expected_hash != snapshot_hash:
        raise RuntimeError("The enrichment snapshot does not match the selected historical input.")

    input_set = set(input_genes)
    profile_index = _build_profile_index(snapshot["rows"])
    pathway_context_payload = load_pathway_cell_context()
    pathway_cell_context = pathway_context_payload["records"]
    count_changes = []
    p_value_changes = []

    pathways = result.get("pathways") or []
    if not pathways:
        raise RuntimeError("The historical result contains no pathways.")

    for pathway in pathways:
        profile_row = _match_profile_row(pathway, profile_index)
        intersection_ids = [
            str(gene).strip() for gene in profile_row.get("intersections", []) if str(gene).strip()
        ]
        intersection_symbols = [
            str(gene).strip()
            for gene in profile_row.get("intersection_gene_symbols", [])
            if str(gene).strip()
        ]
        intersection_size = int(profile_row.get("intersection_size") or 0)
        if len(intersection_ids) != intersection_size:
            raise RuntimeError(
                f"Snapshot intersection mismatch for {profile_row.get('source')} "
                f"{profile_row.get('native')}."
            )
        if not set(intersection_ids).issubset(input_set):
            raise RuntimeError(
                f"Snapshot contains non-input genes for {profile_row.get('source')} "
                f"{profile_row.get('native')}."
            )
        if len(intersection_symbols) != intersection_size:
            raise RuntimeError(
                f"Symbol mapping is incomplete for {profile_row.get('source')} "
                f"{profile_row.get('native')}."
            )

        historical_p = pathway.get("p_value", pathway.get("pvalue"))
        historical_count = _legacy_intersection_size(pathway)
        current_p = float(profile_row.get("p_value"))
        if historical_count is not None and historical_count != intersection_size:
            count_changes.append(
                {
                    "pathway": pathway.get("name"),
                    "historical": historical_count,
                    "recomputed": intersection_size,
                }
            )
        if historical_p is not None and not math.isclose(
            float(historical_p), current_p, rel_tol=1e-12, abs_tol=0.0
        ):
            p_value_changes.append(
                {
                    "pathway": pathway.get("name"),
                    "historical": float(historical_p),
                    "recomputed": current_p,
                }
            )

        historical_name = str(pathway.get("name") or pathway.get("pathway_name") or "").strip()
        historical_description = str(pathway.get("description") or "").strip()
        current_name = str(profile_row.get("name") or historical_name).strip()
        grounded_interpretation = _grounded_interpretation(
            entry.get("disease_name") or entry.get("disease") or "historical",
            profile_row,
            intersection_symbols,
        )
        interpretation_points = _interpretation_points(
            entry.get("disease_name") or entry.get("disease") or "historical",
            profile_row,
            intersection_symbols,
        )
        pathway_id = str(profile_row.get("native") or "")
        cell_context_record = pathway_cell_context.get(pathway_id)
        if not cell_context_record:
            raise RuntimeError(
                f"No dedicated pathway-level cell context is available for {pathway_id} / {current_name}."
            )
        attached_pmids = {
            str(pmid)
            for pmid in pathway.get("pmids", [])
            if str(pmid).strip()
        }
        attached_pmids.update(
            str(record.get("pmid") or record.get("PMID"))
            for record in pathway.get("literature", [])
            if isinstance(record, dict) and (record.get("pmid") or record.get("PMID"))
        )
        unknown_context_pmids = set(cell_context_record.get("cell_context_pmids") or []) - attached_pmids
        if unknown_context_pmids:
            raise RuntimeError(
                f"Cell-context record {pathway_id} cites unattached PMIDs: "
                f"{', '.join(sorted(unknown_context_pmids))}."
            )
        pathway["historical_enrichment"] = {
            "name": historical_name,
            "p_value": float(historical_p) if historical_p is not None else None,
            "intersection_size": historical_count,
            "completed_at": entry.get("completed_at"),
            "note": "Legacy pathway-level values; intersection members were not persisted.",
        }
        pathway["historical_interpretation_unverified"] = historical_description
        pathway.update(
            {
                "name": current_name,
                "source": profile_row.get("source"),
                "category": profile_row.get("source"),
                "native": profile_row.get("native"),
                "pathway_id": profile_row.get("native"),
                "p_value": current_p,
                "significant": bool(profile_row.get("significant")),
                "score": round(min(100, max(0, -10 * math.log10(current_p + 1e-300))), 1),
                "term_size": int(profile_row.get("term_size") or 0),
                "query_size": int(profile_row.get("query_size") or 0),
                "intersection_size": intersection_size,
                "intersection_gene_ids": intersection_ids,
                "intersection_genes": intersection_symbols,
                "genes": ",".join(intersection_symbols),
                "pathway_description": _clean_definition(profile_row.get("description")),
                "disease_interpretation": grounded_interpretation,
                "interpretation_points": interpretation_points,
                "cell_context": (
                    cell_context_record.get("cell_context", "")
                    if cell_context_record else ""
                ),
                "cell_context_pmids": (
                    list(cell_context_record.get("cell_context_pmids") or [])
                    if cell_context_record else []
                ),
                "cell_context_provenance": (
                    {
                        "scope": "pathway-level",
                        "disease": pathway_context_payload.get("disease"),
                        "disease_id": pathway_context_payload.get("disease_id"),
                        "module": pathway_context_payload.get("module"),
                        "source_type": cell_context_record.get("source_type"),
                        "interpretation_pass_id": pathway_context_payload.get("interpretation_pass_id"),
                        "generated_at": pathway_context_payload.get("generated_at"),
                        "evidence_contract": pathway_context_payload.get("evidence_contract"),
                        "method": pathway_context_payload.get("method"),
                    }
                    if cell_context_record else None
                ),
                "description": grounded_interpretation,
                "enrichment_source": "g:Profiler replay snapshot",
            }
        )
        pathway["pathway_narrative"] = build_demo_pathway_narrative(
            entry.get("disease_name") or entry.get("disease") or "historical",
            profile_row,
            intersection_symbols,
            interpretation_points,
        )

    meta = snapshot.get("gprofiler_meta", {})
    result["input_genes"] = input_genes
    result["query_genes"] = input_genes
    result["enrichment_provenance"] = {
        "provider": snapshot.get("source", {}).get("provider", "g:Profiler"),
        "base_url": snapshot.get("source", {}).get("base_url"),
        "gprofiler_data_version": meta.get("version"),
        "gprofiler_timestamp": meta.get("timestamp"),
        "snapshot_generated_at": snapshot.get("snapshot_generated_at"),
        "request": snapshot.get("request"),
        "input_sha256": expected_hash,
        "matrix_sha256": snapshot.get("matrix_sha256"),
        "matrix_row_count": snapshot.get("matrix_row_count"),
        "matched_pathway_count": len(pathways),
        "symbol_mapping": snapshot.get("mapping_summary"),
        "historical_count_changes": count_changes,
        "historical_p_value_changes": p_value_changes,
        "statement": (
            "All displayed enrichment P-values, pathway identifiers and intersection genes "
            "were regenerated together from the archived input gene list. Historical model "
            "narratives are retained only as unverified audit records and are never used to "
            "derive intersection genes."
        ),
    }

    significant = [pathway for pathway in pathways if float(pathway["p_value"]) < 0.05]
    represented = sorted({pathway["category"] for pathway in pathways})
    source_mapping = snapshot.get("mapping_summary") or {}
    mapped_count = int(
        source_mapping.get("mapped_count")
        or source_mapping.get("symbol_mapped_count")
        or len(input_genes)
    )
    mapping_summary = {
        "input_count": len(input_genes),
        "mapped_count": min(mapped_count, len(input_genes)),
        "failed_count": max(len(input_genes) - mapped_count, 0),
    }
    result["run_summary"] = {
        "validation_status": (
            "Statistically validated" if significant else "No statistically validated pathways"
        ),
        "significant_pathways": len(significant),
        "total_pathways": len(pathways),
        "categories_covered": len(represented),
        "gene_count": len(input_genes),
        "mapped_gene_count": mapping_summary["mapped_count"],
        "unmapped_gene_count": mapping_summary["failed_count"],
        "disease_id": "D000544",
        "mapping_summary": mapping_summary,
    }
    result["mapping_summary"] = mapping_summary
    result["disease_context"] = {
        "name": "Alzheimer's Disease",
        "mesh_id": "D000544",
    }
    # The archive persisted the initial-pass total and the final register, but
    # not reliable per-pathway prompt-pass lineage. Do not present generated-only
    # round counts as though they explain where final pathways originated.
    validated_by_database = {
        category: sum(1 for pathway in significant if pathway["category"] == category)
        for category in ["GO:BP", "GO:MF", "GO:CC", "KEGG", "REAC"]
    }
    initial_by_database = {
        "GO:BP": 10,
        "GO:MF": 10,
        "GO:CC": 10,
        "KEGG": 10,
        "REAC": 9,
    }
    result["validation_comparison"] = {
        "initial_hypotheses": 49,
        "statistically_validated": len(significant),
        "rounds": [],
        "by_database": {
            category: {
                "initial_hypotheses": initial_by_database[category],
                "statistically_validated": validated_by_database[category],
            }
            for category in initial_by_database
        },
    }
    return result


def build_demo_result(history_path=HISTORY_PATH, snapshot_path=PROFILE_SNAPSHOT_PATH):
    history = json.loads(history_path.read_text(encoding="utf-8"))
    entry = select_demo_entry(history)
    snapshot = load_profile_snapshot(snapshot_path)
    result = sanitize_public_result(dict(entry.get("results") or {}))
    result = reconcile_pathways(result, entry, snapshot)
    result.update(
        {
            "session_id": entry.get("session_id"),
            "created_at": entry.get("created_at"),
            "completed_at": entry.get("completed_at"),
            "demo_mode": True,
            "reasoning_traces": [
                {
                    "reasoning": message["data"]["reasoning"],
                    "category": message["data"].get("category"),
                    "iteration": message["data"].get("iteration", 1),
                }
                for message in entry.get("messages", [])
                if message.get("data") and message["data"].get("reasoning")
            ],
        }
    )
    return result


def main():
    result = build_demo_result()
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    OUTPUT_PATH.write_text(
        "window.OFFLINE_DEMO_RESULT=" + payload + ";\n",
        encoding="utf-8",
    )
    JSON_OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size:,} bytes)")
    print(f"Generated {JSON_OUTPUT_PATH} ({JSON_OUTPUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
