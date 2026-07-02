from typing import List, Dict, Any, Optional
import json


class PathwayPromptTemplates:
    """
    Category-specific pathway generation prompts based on g:Profiler databases.
    
    5-Channel System - Each database has unique characteristics requiring specialized prompts:
    
    Gene Ontology (3 aspects, all use ID format GO:#######):
    - GO:BP (Biological Process): What genes do - biological goals/objectives
      Hierarchical DAG, Level 3+ specificity, avoid generic/IEA terms
    - GO:MF (Molecular Function): How genes do it - molecular-level activities  
      Binding, catalysis, transport functions, Level 3+ specificity
    - GO:CC (Cellular Component): Where genes act - cellular locations/structures
      Organelles, membranes, complexes, Level 3+ specificity
    
    Pathway Databases:
    - KEGG: Hierarchical categories (Metabolism, Signaling, Disease), ID format hsa####
      Expert-curated, 10-500 genes per pathway
    - Reactome: Expert-curated with domain specialists, ID format R-HSA-######
      Parent-child hierarchy, 10-1000+ genes, prefer specific child pathways
    """
    
    @staticmethod
    def _format_gene_list_dynamic(genes: List[str]) -> str:
        """
        Format gene list - ALWAYS show all genes (no truncation).
        
        Strategy:
        - Display ALL genes regardless of module size
        - No truncation to ensure complete information for GPT
        - Eliminates gene citation hallucination issues
        
        Rationale:
        - Complete information: GPT sees all genes, can cite accurately
        - No information loss: All genes available for pathway generation
        - Better accuracy: GPT won't hallucinate genes not in the visible list
        - Anti-hallucination: Strict enforcement of "cite only from input list"
        
        Token cost:
        - Small modules (< 100): ~200 tokens (same as before)
        - Medium modules (100-200): ~400-500 tokens (+200-300 vs old)
        - Large modules (> 200): ~500-1000 tokens (+300-800 vs old)
        
        Args:
            genes: List of gene symbols
            
        Returns:
            Formatted gene list string with all genes displayed
        """
        # Show ALL genes, no truncation
        return ", ".join(genes)
    
    # ============================================================================
    # SYSTEM PROMPTS (Define expert role and knowledge domains)
    # ============================================================================

    KEGG_SYSTEM_PROMPT = """You are an expert in discovering disease-related KEGG pathways. KEGG (Kyoto Encyclopedia of Genes and Genomes) pathways are manually curated representations of molecular interaction and reaction networks covering metabolism, genetic information processing, environmental information processing, cellular processes, and human diseases.

Your role is to identify KEGG pathways that connect the input gene list to the disease context, revealing mechanistic links between molecular networks and disease pathology.

⚠️ CRITICAL REASONING CONSTRAINT:
Your reasoning path MUST start from the INPUT GENE LIST to obtain evidence.
- First analyze what the actual input genes are and their documented pathway memberships
- Then infer pathways based on this evidence
- DO NOT start from disease knowledge and work backwards to find supporting genes

Your output MUST satisfy:

1. All KEGG pathways must be valid official KEGG pathways.
   - You may describe pathways, but DO NOT fabricate IDs.
   - If you mention a KEGG ID (hsaXXXXX format), ensure it is highly likely to exist, or omit IDs entirely.

2. All generated pathways MUST be:
   - Logically supported by the input gene list based on known gene annotations
   - Mechanistically relevant to the specified disease context
   - DO NOT infer pathway-specific processes unless the input genes contain known markers for those pathways
   - Each pathway should explain HOW the molecular network connects to disease pathology

Your goal:
Generate biologically realistic KEGG pathways that bridge the gap between gene function and disease mechanisms, consistent with what g:Profiler would return, without claiming statistical significance."""


    REACTOME_SYSTEM_PROMPT = """You are an expert in discovering disease-related Reactome pathways. Reactome is a manually curated, peer-reviewed pathway database that provides detailed, hierarchical representations of biological processes including signal transduction, metabolism, gene expression, post-translational modifications, and disease mechanisms.

Your role is to identify Reactome pathways that connect the input gene list to the disease context, revealing mechanistic links between biochemical reactions and disease pathology.

⚠️ CRITICAL REASONING CONSTRAINT:
Your reasoning path MUST start from the INPUT GENE LIST to obtain evidence.
- First analyze what the actual input genes are and their documented Reactome pathway memberships
- Then infer pathways based on this evidence
- DO NOT start from disease knowledge and work backwards to find supporting genes

Your output MUST satisfy:

1. All Reactome pathways must be valid official Reactome pathways.
   - You may describe pathways, but DO NOT fabricate IDs.
   - If you mention a Reactome ID (R-HSA-XXXXXX format), ensure it is highly likely to exist, or omit IDs entirely.

2. All generated pathways MUST be:
   - Logically supported by the input gene list based on known gene annotations
   - Mechanistically relevant to the specified disease context
   - DO NOT infer specialized pathways (e.g., immune-specific, neuron-specific) unless the input genes contain known markers for those processes
   - Each pathway should explain HOW the biochemical reactions connect to disease pathology

Your goal:
Generate biologically realistic Reactome pathways that bridge the gap between gene function and disease mechanisms, consistent with what g:Profiler would return, without claiming statistical significance."""


    GOBP_SYSTEM_PROMPT = """You are an expert in interpreting disease-related biological processes using Gene Ontology Biological Process (GO:BP) terms.
A GO:BP term represents a defined biological process—a coordinated series of molecular events carried out by gene products—that contributes to cellular function or dysfunction, rather than a curated signaling or metabolic pathway.

Your role is to identify **GO:BP terms** that plausibly connect the input gene list to the specified disease context, revealing **mechanistic biological processes** that may underlie disease pathology.

⚠️ CRITICAL REASONING CONSTRAINT:
Your reasoning path MUST start from the INPUT GENE LIST to obtain evidence.
- First analyze what the actual input genes are and their documented GO:BP annotations
- Then infer terms based on this evidence
- DO NOT start from disease knowledge and work backwards to find supporting genes

Your output MUST satisfy:

1. All GO terms must be valid official GO:BP terms.
   - You may describe terms, but DO NOT fabricate IDs.
   - If you mention a GO ID, ensure it is highly likely to exist, or omit IDs entirely.

2. All generated terms MUST be:
   - Logically supported by the input gene list based on known functional annotations
   - Mechanistically relevant to the specified disease context
   - Conservative with respect to biological interpretation
   - Explained in terms of how the biological process could contribute to disease pathology

Your goal:
Generate biologically realistic GO:BP terms that bridge gene-level functional signals and disease mechanisms, consistent with the types of terms that tools like g:Profiler could return, **without performing or implying statistical enrichment**."""


    GOMF_SYSTEM_PROMPT = """You are an expert in discovering disease-related molecular functions. Molecular function describes the biochemical activity of a gene product at the molecular level, including binding activities, catalytic activities, and transporter activities.

Your role is to identify molecular functions that explain HOW gene products contribute to disease mechanisms through their biochemical activities.

⚠️ CRITICAL REASONING CONSTRAINT:
Your reasoning path MUST start from the INPUT GENE LIST to obtain evidence.
- First analyze what the actual input genes are and their documented GO:MF annotations
- Then infer terms based on this evidence
- DO NOT start from disease knowledge and work backwards to find supporting genes

Your outputs MUST follow these constraints:

1. All GO:MF terms must be valid official GO:MF terms.
   - You may describe terms, but DO NOT fabricate IDs.
   - If you mention a GO ID, ensure it is highly likely to exist, or omit IDs entirely.

2. All generated GO:MF terms MUST be:
   - Biologically plausible based on known molecular activities of the genes
   - Mechanistically relevant to the specified disease context
   - Each term should connect molecular activities to disease-relevant cellular processes

Your goal:
Generate biologically realistic GO:MF terms that link molecular activities to disease
pathology, consistent with what g:Profiler would return, without claiming statistical
significance."""


    GOCC_SYSTEM_PROMPT = """You are an expert in discovering disease-related cellular components. Cellular component refers to the locations in the cell where a gene product is active, including cellular structures, organelles, and macromolecular complexes.

Your role is to identify cellular locations that are dysregulated or affected in disease, connecting subcellular localization to disease mechanisms.

⚠️ CRITICAL REASONING CONSTRAINT:
Your reasoning path MUST start from the INPUT GENE LIST to obtain evidence.
- First analyze what the actual input genes are and their documented GO:CC annotations
- Then infer terms based on this evidence
- DO NOT start from disease knowledge and work backwards to find supporting genes

Your outputs MUST follow these constraints:

1. All GO:CC terms must be valid official GO:CC terms.
   - You may describe terms, but DO NOT fabricate IDs.
   - If you mention a GO ID, ensure it is highly likely to exist, or omit IDs entirely.

2. All generated GO:CC terms MUST be:
   - Supported by known localization patterns of the provided genes
   - Mechanistically relevant to the specified disease context
   - Each term should explain HOW disruption of this cellular location contributes to disease pathology

Your goal:
Generate biologically realistic GO:CC terms that connect subcellular localization to disease
mechanisms, consistent with what g:Profiler would return, without claiming statistical
significance."""


    WIKIPATHWAYS_SYSTEM_PROMPT = """You are a WikiPathways database expert with knowledge of:
1. Community-curated pathway structure
2. WikiPathways ID format: "WP###" (variable digits)
3. Emerging research areas and cutting-edge pathways
4. Species-specific pathway curation (focus on Homo sapiens)
5. Integration with established databases (KEGG, Reactome, GO)
6. Typical pathway size: 20-200 genes

WikiPathways often includes newer pathways not yet in KEGG/Reactome but less standardized.
Your generations must use official WikiPathways nomenclature."""

    # ============================================================================
    # KEGG-SPECIFIC PROMPT
    # ============================================================================
    
    @staticmethod
    def get_kegg_prompt(genes: List[str], disease_name: str, top_k: int) -> Dict[str, str]:
        """
        Generate KEGG-specific pathway generation prompt.
        
        Parameters:
        -----------
        genes : List[str]
            Input gene symbols
        disease_name : str
            Disease/condition being analyzed
        top_k : int
            Number of KEGG pathways to generate
            
        Returns:
        --------
        dict : {'system_prompt': str, 'user_prompt': str}
        """
        # Dynamic gene list formatting based on module size
        gene_list_str = PathwayPromptTemplates._format_gene_list_dynamic(genes)
        
        user_prompt = f"""TASK: Analyze the provided gene list as a functionally cohesive "gene module" derived from network expansion algorithms. Identify the top {top_k} KEGG pathways that represent the biological consensus of this module and explain their mechanistic relevance to {disease_name}.

CONTEXT & PRINCIPLE:
1. Treat the Input as a Module: The input genes are not random; they form a dense subgraph in the protein-protein interaction network. Your goal is to identify the shared biological function (the "core mechanism") unifying these genes.
2. Disease Mechanism: As seen in network studies (e.g., for Inflammatory Bowel Disease), valid pathways often involve signaling cascades (like JAK-STAT or Integrin signaling) where multiple input genes act as receptors, transducers, or effectors.
3. Specificity: Prioritize pathways that provide a specific molecular explanation for {disease_name} pathology over generic cellular maintenance terms (e.g., prioritize "Th17 cell differentiation" over "Cell Cycle" if biological evidence supports it).

Note: While standard tools like g:Profiler use hypergeometric tests for enrichment, your task here is to provide the mechanistic interpretation of this pre-identified network module, focusing on both biological coherence and statistical overlap.

INPUT GENE MODULE ({len(genes)} genes):
{gene_list_str}

DISEASE CONTEXT: {disease_name}

═══════════════════════════════════════════════════════════════════════════════
GENERATION GUIDELINES
═══════════════════════════════════════════════════════════════════════════════

1. KEGG MAPPING:
   - Map the functional signals of the module to OFFICIAL KEGG pathway names (e.g., "hsa04630").
   - Use exact standard nomenclature from the KEGG database.

2. EVIDENCE-BASED RATIONALE:
   - Unlike a statistical enrichment test, you represent a "Systems Biologist" agent. 
   - You MUST cite specific genes from the input list that function as key drivers in the proposed pathway to justify your choice. (e.g., "Genes A, B, and C in the input are central kinases in the MAPK signaling cascade").

3. DISEASE RELEVANCE EXPLANATION (CRITICAL):
   - For EACH pathway, you MUST explain WHY this pathway is relevant to {disease_name}.
   - Include specific mechanistic links (e.g., "Dysregulation of this pathway leads to...").
   - If known, mention quantitative impacts (e.g., "30-50% reduction observed in disease").
   - Do NOT use generic statements like "this pathway is involved in disease".

4. OFFICIAL NAMING EXAMPLES (CRITICAL FOR MATCHING):
   Use EXACT KEGG pathway names as they appear in the official database.
   
   ✅ CORRECT Examples:
      • "SNARE interactions in vesicular transport" (NOT "SNARE-mediated transport")
      • "Ubiquitin mediated proteolysis" (NOT "Protein ubiquitination")
      • "mTOR signaling pathway" (NOT "mTOR pathway" or "mTOR signaling")
      • "Autophagy - animal" (NOT "Autophagy" or "Mammalian autophagy")
      • "Endocytosis" (NOT "Endocytic pathway")
      • "Protein processing in endoplasmic reticulum" (NOT "ER protein processing")
   
   ❌ AVOID:
      • Abbreviated names (use full official name)
      • Paraphrased descriptions (copy exact KEGG name)
      • Adding qualifiers not in official name (e.g., "pathway" if not in KEGG name)
   
   VERIFICATION: Before finalizing, check that pathway names match KEGG database exactly.

5. OUTPUT FORMAT (Strict JSON):
   - Provide EXACTLY {top_k} pathways, ordered by biological relevance/confidence.

{{
  "module_functional_summary": "A concise, high-level summary of the primary biological process represented by this gene cluster (e.g., 'This module represents a cluster of cytokine receptors and downstream JAK-STAT signal transducers').",
  "pathways": [
    {{
      "name": "Official KEGG Pathway Name",
      "pathway_id": "hsaXXXXX (or null if uncertain)",
      "key_genes": ["GENE1", "GENE2", "GENE3"],
      "mechanism_in_module": "Explain WHY this pathway is selected based on the input genes. Which input genes play a role here? (e.g., 'Input genes JAK2 and STAT3 are core components of this signaling pathway...')",
      "disease_relevance": "Specific mechanistic link to {disease_name}. (e.g., 'Dysregulation of this pathway drives mucosal inflammation and is a known therapeutic target in IBD.')"
    }}
    ... (repeat for {top_k} pathways)
  ]
}}
"""

        return {
            'system_prompt': PathwayPromptTemplates.KEGG_SYSTEM_PROMPT,
            'user_prompt': user_prompt
        }

    # ============================================================================
    # REACTOME-SPECIFIC PROMPT
    # ============================================================================
    
    @staticmethod
    def get_reactome_prompt(genes: List[str], disease_name: str, top_k: int) -> Dict[str, str]:
        """Generate Reactome-specific pathway generation prompt."""
        # Dynamic gene list formatting based on module size
        gene_list_str = PathwayPromptTemplates._format_gene_list_dynamic(genes)
        
        user_prompt = f"""TASK: Analyze the provided gene list as a functionally cohesive "gene module" derived from network expansion algorithms. Identify the top {top_k} Reactome pathways that represent the biological consensus of this module and explain their mechanistic relevance to {disease_name}.

CONTEXT & PRINCIPLE:
1. Input as a Module: The input genes are not random; they form a dense functional subgraph. Your goal is to identify the specific molecular events or reaction cascades (Reactome's core unit) that these genes collectively drive.
2. Mechanistic Evidence: As seen in network studies, valid pathways are defined by the presence of key molecular drivers (receptors, enzymes, transporters) within the module. You MUST cite specific input genes to justify your pathway selection.
3. Granularity: Reactome is hierarchical. Avoid broad top-level terms (e.g., "Signal Transduction"). Prioritize specific, actionable sub-pathways (e.g., "Interleukin-23 signaling" or "Clathrin-mediated endocytosis") that provide distinct biological insight.

INPUT GENE MODULE ({len(genes)} genes):
{gene_list_str}

DISEASE CONTEXT: {disease_name}

═══════════════════════════════════════════════════════════════════════════════
GENERATION GUIDELINES
═══════════════════════════════════════════════════════════════════════════════

1. REACTOME MAPPING:
   - Map the functional signals to OFFICIAL Reactome pathway names and IDs.
   - Standard ID format: "R-HSA-######" (e.g., R-HSA-112316).

2. EVIDENCE-BASED RATIONALE:
   - Act as a Systems Biologist. You represent the "mechanism," not just a statistical overlap.
   - You MUST cite specific genes from the input list that act as key components (catalysts, substrates, regulators) in the proposed pathway. 
   - Example: "Input genes X and Y are core kinases in this cascade, suggesting active signaling..."

3. DISEASE RELEVANCE EXPLANATION (CRITICAL):
   - For EACH pathway, you MUST explain WHY this pathway is relevant to {disease_name}.
   - Include specific mechanistic links (e.g., "Hyperactivation of this cascade leads to...").
   - If known, mention quantitative impacts (e.g., "40-60% of patients show dysregulation").
   - Do NOT use generic statements like "this pathway may be involved in disease".
   - Explain how this specific molecular event contributes to {disease_name} pathology (e.g., "Defects in this vesicle transport pathway are a known driver of protein aggregation in {disease_name}").

4. OFFICIAL NAMING EXAMPLES (CRITICAL FOR MATCHING):
   Use EXACT Reactome pathway names as they appear in the official database.
   
   ✅ CORRECT Examples:
      • "Vesicle-mediated transport" (NOT "Vesicular transport")
      • "COPI-mediated anterograde transport" (NOT "COPI transport")
      • "Golgi-to-ER retrograde transport" (NOT "ER-Golgi retrograde pathway")
      • "COPII-mediated vesicle transport" (NOT "COPII vesicle formation")
      • "RAB geranylgeranylation" (NOT "RAB protein prenylation")
      • "Interleukin-4 and Interleukin-13 signaling" (NOT "IL-4/IL-13 signaling")
   
   Common Patterns:
      • Use hyphens as in official names (e.g., "COPI-mediated" not "COPI mediated")
      • Include full hierarchical context (e.g., "Golgi-to-ER" not just "retrograde")
      • Preserve exact capitalization and spellings
   
   ❌ AVOID:
      • Shortened names
      • Casual biological descriptions
      • Synonym substitutions (e.g., "prenylation" for "geranylgeranylation")
   
   VERIFICATION: Before finalizing, ensure pathway names are exact Reactome official names.

5. OUTPUT FORMAT (Strict JSON):
   - Provide EXACTLY {top_k} pathways, ordered by biological relevance.

{{
  "module_functional_summary": "A concise summary of the primary molecular machinery represented by this gene cluster (e.g., 'A cluster of integrin receptors and downstream actin cytoskeleton regulators').",
  "pathways": [
    {{
      "name": "Official Reactome Pathway Name",
      "pathway_id": "R-HSA-###### (or null if uncertain)",
      "key_genes": ["GENE1", "GENE2", "GENE3"],
      "mechanism_in_module": "Explain WHY this pathway is selected based on the input genes. Explicitly mention key input genes and their roles (e.g., 'Input genes A and B form the active receptor complex...').",
      "disease_relevance": "Specific mechanistic link to {disease_name}. (e.g., 'Hyperactivation of this cascade leads to chronic mucosal inflammation in IBD.')"
    }}
    ... (repeat for {top_k} pathways)
  ]
}}
"""


        return {
            'system_prompt': PathwayPromptTemplates.REACTOME_SYSTEM_PROMPT,
            'user_prompt': user_prompt
        }

    # ============================================================================
    # GO:BP-SPECIFIC PROMPT
    # ============================================================================
    
    @staticmethod
    def get_gobp_prompt(genes: List[str], disease_name: str, top_k: int) -> Dict[str, str]:
        """Generate GO:BP-specific pathway generation prompt."""
        # Dynamic gene list formatting based on module size
        gene_list_str = PathwayPromptTemplates._format_gene_list_dynamic(genes)
        
        user_prompt = f"""TASK: Analyze the provided gene list as a functionally cohesive "gene module" derived from network expansion algorithms. Identify the top {top_k} GO Biological Process (GO:BP) terms that best describe the collective biological function of this module.

CONTEXT & PRINCIPLE:
1. Input as a Module: The input genes form a dense cluster in the protein interaction network. Your goal is to provide a semantic label (GO Term) that summarizes this cluster's function.
2. **Analytical Approach:** Note: While standard tools like g:Profiler use hypergeometric tests for enrichment, your task here is to provide the **mechanistic interpretation** of this pre-identified network module, focusing on both biological coherence and statistical overlap.
3. Pleiotropy vs. Specificity: 
   - Some modules represent fundamental, broadly shared cellular processes (e.g., "RNA processing" or "Protein ubiquitination") linked to multiple traits (Pleiotropic).
   - Other modules represent distinct, disease-specific pathways (e.g., "Neutrophil activation").
   - **Do not force specificity.** If the module represents a broad machinery, use the appropriate broad GO term. If it represents a specific signaling cascade, use the specific term. Match the scope of the term to the scope of the genes.

INPUT GENE MODULE ({len(genes)} genes):
{gene_list_str}

DISEASE CONTEXT: {disease_name}

═══════════════════════════════════════════════════════════════════════════════
GENERATION GUIDELINES
═══════════════════════════════════════════════════════════════════════════════

1. GO TERM SELECTION:
   - Identify OFFICIAL GO Biological Process names and IDs (Format: GO:#######).
   - Select terms that accurately reflect the **granularity** of the input module. 
   - Broad terms (e.g., "Cell cycle") are ACCEPTABLE if the module contains core machinery components common to many cell types.
   - Specific terms (e.g., "Interleukin-23-mediated signaling") are PREFERRED if the module is dense with specific receptors and ligands.

2. MECHANISTIC EVIDENCE:
   - Act as a Systems Biologist. Cite specific input genes to justify your choice. Explain *why* these genes collectively map to this GO term.
   - Example: "This module maps to 'GO:0016567 (Protein ubiquitination)' because it is enriched with E3 ligase components X, Y, and Z..."

3. DISEASE RELEVANCE EXPLANATION (CRITICAL):
   - For EACH GO:BP term, you MUST explain WHY this biological process is relevant to {disease_name}.
   - Include specific mechanistic links between the process and disease pathology.
   - For broad processes (e.g., Ubiquitination): Explain how global defects in this machinery might modulate disease mechanisms.
   - For specific processes (e.g., Cytokine signaling): Explain the direct pathogenic link.
   - If known, mention quantitative impacts (e.g., "30-50% reduction observed in disease").
   - Do NOT use generic statements like "this process is involved in disease".

4. OUTPUT FORMAT (Strict JSON):
   - Provide EXACTLY {top_k} terms.

{{
  "module_functional_summary": "A concise summary of the module's scope (e.g., 'A highly pleiotropic module involved in fundamental protein turnover' OR 'A specific immune signaling module').",
  "terms": [
    {{
      "name": "Official GO Term Name",
      "go_id": "GO:#######",
      "key_genes": ["GENE1", "GENE2", "GENE3"],
      "mechanism_in_module": "Cite specific genes and explain the module's fit to this term.",
      "disease_relevance": "Mechanistic link to {disease_name}."
    }}
    ... (repeat for {top_k} terms)
  ]
}}
"""


        return {
            'system_prompt': PathwayPromptTemplates.GOBP_SYSTEM_PROMPT,
            'user_prompt': user_prompt
        }

    # ============================================================================
    # GO:MF-SPECIFIC PROMPT
    # ============================================================================
    
    @staticmethod
    def get_gomf_prompt(genes: List[str], disease_name: str, top_k: int) -> Dict[str, str]:
        """Generate GO:MF (Molecular Function) specific pathway generation prompt."""
        # Dynamic gene list formatting based on module size
        gene_list_str = PathwayPromptTemplates._format_gene_list_dynamic(genes)
        
        user_prompt = f"""TASK: Analyze the provided gene list as a functionally cohesive "gene module" derived from network expansion algorithms. Identify the top {top_k} GO Molecular Function (GO:MF) terms that best describe the **collective biochemical activity** or **binding capabilities** of the proteins in this module.

CONTEXT & PRINCIPLE:
1. Input as a Functional Module: The input genes form a dense cluster in the protein interaction network. Your goal is to identify the molecular capabilities (enzymatic, binding, structural) enabled by this specific combination of proteins.
2. **Analytical Approach:** Note: While standard tools like g:Profiler use hypergeometric tests for enrichment, your task here is to provide the **mechanistic interpretation** of this pre-identified network module, focusing on both biological coherence and statistical overlap.
3. Activity Scope: 
   - Some modules represent broad enzymatic machinery (e.g., "Ubiquitin-protein transferase activity") relevant to many traits (Pleiotropic).
   - Other modules represent specific receptor-ligand interactions (e.g., "Cytokine receptor binding") specific to certain diseases.
   - **Do not force specificity.** Use the GO term level that best matches the consensus activity of the driver genes in the module.

INPUT GENE MODULE ({len(genes)} genes):
{gene_list_str}

DISEASE CONTEXT: {disease_name}

═══════════════════════════════════════════════════════════════════════════════
GENERATION GUIDELINES
═══════════════════════════════════════════════════════════════════════════════

1. GO TERM SELECTION:
   - Identify OFFICIAL GO Molecular Function names and IDs (Format: GO:#######).
   - Distinguish between **Activity** (doing something, e.g., Kinase activity) and **Binding** (holding something, e.g., ATP binding).
   -  (Optional internal visualization for selecting the right level).
   - Select terms that describe the *dominant* biochemical function performed by the key drivers in the list.

2. MECHANISTIC EVIDENCE (Biochemical Proof):
   - Act as a Biochemist. You MUST cite specific input genes to justify the function.
   - Explain *why* the presence of these specific proteins implies this function.
   - Example: "This module maps to 'GO:0004672 (Protein kinase activity)' because it is enriched with the catalytic kinases JAK2, TYK2, and IRAK4..."

3. DISEASE RELEVANCE EXPLANATION (CRITICAL):
   - For EACH GO:MF term, you MUST explain WHY this molecular function is relevant to {disease_name}.
   - Explain how this specific molecular activity (or its dysregulation) drives {disease_name}.
   - Include specific mechanistic links (e.g., "Hyperactive 'Kinase activity' in this module leads to constitutive phosphorylation, driving...").
   - If known, mention quantitative impacts.
   - Do NOT use generic statements like "this function is involved in disease".

4. OUTPUT FORMAT (Strict JSON):
   - Provide EXACTLY {top_k} terms.

{{
  "module_molecular_summary": "A concise summary of the module's biochemical nature (e.g., 'A cluster of receptor tyrosine kinases and their associated ligands').",
  "terms": [
    {{
      "name": "Official GO MF Term Name",
      "go_id": "GO:#######",
      "key_genes": ["GENE1", "GENE2", "GENE3"],
      "mechanism_in_module": "Cite specific genes and explain the biochemical evidence.",
      "disease_relevance": "Mechanistic link connecting this activity to {disease_name} pathology."
    }}
    ... (repeat for {top_k} terms)
  ]
}}
"""


        return {
            'system_prompt': PathwayPromptTemplates.GOMF_SYSTEM_PROMPT,
            'user_prompt': user_prompt
        }

    # ============================================================================
    # GO:CC-SPECIFIC PROMPT
    # ============================================================================
    
    @staticmethod
    def get_gocc_prompt(genes: List[str], disease_name: str, top_k: int) -> Dict[str, str]:
        """Generate GO:CC (Cellular Component) specific pathway generation prompt."""
        # Dynamic gene list formatting based on module size
        gene_list_str = PathwayPromptTemplates._format_gene_list_dynamic(genes)
        
        user_prompt = f"""TASK: Analyze the provided gene list as a functionally cohesive "gene module" derived from network expansion algorithms. Identify the top {top_k} GO Cellular Component (GO:CC) terms that best describe the **collective physical location** or **macromolecular complex** formed by this module.

CONTEXT & PRINCIPLE:
1. Input as a Physical Module: The input genes form a dense cluster in the protein-protein interaction (PPI) network. In GO:CC terms, this often implies that these proteins physically co-localize to form a complex or reside within the same specific subcellular compartment to perform their function.
2. **Analytical Approach:** Note: While standard tools like g:Profiler use hypergeometric tests for enrichment, your task here is to provide the **mechanistic interpretation** of this pre-identified network module, focusing on both biological coherence and statistical overlap.
3. Scope & Granularity: 
   - Some modules represent ubiquitous machinery (e.g., "Proteasome complex" or "Cytosol") found in many contexts (Pleiotropic).
   - Other modules represent highly specific structures (e.g., "Postsynaptic density" or "Clathrin-coated vesicle").
   - **Do not force specificity.** If the proteins are broadly distributed, use the appropriate broad term. If they form a distinct structural unit, use the specific term.

INPUT GENE MODULE ({len(genes)} genes):
{gene_list_str}

DISEASE CONTEXT: {disease_name}

═══════════════════════════════════════════════════════════════════════════════
GENERATION GUIDELINES
═══════════════════════════════════════════════════════════════════════════════

1. GO TERM SELECTION:
   - Identify OFFICIAL GO Cellular Component names and IDs (Format: GO:#######).
   - Focus on where the **core interaction** of the module occurs.
   -  (Optional internal visualization for selecting the right level).
   - Decide if the module represents a "Place" (e.g., Mitochondrion) or a "Machine" (e.g., Respiratory chain complex). Both are valid GO:CC types.

2. MECHANISTIC EVIDENCE (Physical Co-localization):
   - Act as a Cell Biologist. Cite specific input genes to justify the location.
   - You must explain *why* these genes are thought to reside together.
   - Example: "This module maps to 'GO:0005768 (Endosome)' because it contains the structural marker EEA1 and the cargo transporter Transferrin Receptor (TFRC)..."

3. DISEASE RELEVANCE EXPLANATION (CRITICAL):
   - For EACH GO:CC term, you MUST explain WHY this cellular location is relevant to {disease_name}.
   - Explain how defects in this specific structure or complex contribute to {disease_name}.
   - Include specific mechanistic links (e.g., "Accumulation of misfolded proteins in the 'Endoplasmic reticulum lumen' drives the unfolded protein response observed in...").
   - If known, mention quantitative impacts.
   - Do NOT use generic statements like "this location is involved in disease".

4. OUTPUT FORMAT (Strict JSON):
   - Provide EXACTLY {top_k} terms.

{{
  "module_structural_summary": "A concise summary of the module's physical nature (e.g., 'A transmembrane receptor complex located at the plasma membrane' OR 'A cytosolic enzymatic machinery').",
  "terms": [
    {{
      "name": "Official GO Term Name",
      "go_id": "GO:#######",
      "key_genes": ["GENE1", "GENE2", "GENE3"],
      "mechanism_in_module": "Cite specific genes and explain the evidence for their physical co-localization.",
      "disease_relevance": "Mechanistic link connecting this structure to {disease_name} pathology."
    }}
    ... (repeat for {top_k} terms)
  ]
}}
"""


        return {
            'system_prompt': PathwayPromptTemplates.GOCC_SYSTEM_PROMPT,
            'user_prompt': user_prompt
        }


    # ============================================================================
    # WIKIPATHWAYS-SPECIFIC PROMPT
    # ============================================================================
    
    @staticmethod
    def get_wikipathways_prompt(genes: List[str], disease_name: str, top_k: int) -> Dict[str, str]:
        """Generate WikiPathways-specific pathway generation prompt."""
        # Dynamic gene list formatting based on module size
        gene_list_str = PathwayPromptTemplates._format_gene_list_dynamic(genes)
        
        user_prompt = f"""TASK: Generate EXACTLY {top_k} WikiPathways that are most related to {disease_name} pathology, based on the biological processes represented in this gene set.

INPUT GENE SET ({len(genes)} genes):
{gene_list_str}

⚠️ CRITICAL: You MUST provide all {top_k} WikiPathways. Do not stop early.

═══════════════════════════════════════════════════════════════════════════════
WIKIPATHWAYS-SPECIFIC REQUIREMENTS (STRICTLY ENFORCED)
═══════════════════════════════════════════════════════════════════════════════

1. ID FORMAT (MANDATORY):
   - MUST be "WP###" (variable number of digits)
   - Examples: WP254 (Apoptosis), WP1234 (Cell cycle)
   - ❌ INVALID: "WikiPathways:WP254", "WP_254", "254"

2. COMMUNITY CURATION:
   - WikiPathways are community-curated (less standardized than KEGG/Reactome)
   - Often includes emerging research areas and novel pathways
   - Some pathways may overlap with KEGG/Reactome but have different focus

3. PATHWAY SIZE:
   - Typically 20-200 genes per pathway
   - Focus on well-populated pathways for enrichment

4. SPECIES:
   - Ensure pathways are for Homo sapiens
   - WikiPathways has species-specific versions

5. GENE CITATIONS (MANDATORY):
   - Cite ≥3 input genes for each pathway

═══════════════════════════════════════════════════════════════════════════════
ANTI-HALLUCINATION CHECKLIST
═══════════════════════════════════════════════════════════════════════════════

✓ All pathway IDs follow "WP###" format
✓ Pathway names match WikiPathways database
✓ Gene citations provided (≥3 genes per pathway)
✓ NO invented WP IDs or pathway names
✓ Pathway count = {top_k}

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT (STRICT JSON)
═══════════════════════════════════════════════════════════════════════════════

{{
  "wikipathways_analysis": "Which pathway themes are likely enriched",
  "pathways": [
    {{
      "name": "Exact WikiPathways name",
      "pathway_id": "WP###",
      "estimated_gene_overlap": <integer ≥ 3>,
      "gene_citations": ["Gene1", "Gene2", "Gene3", "..."],
      "pathway_size": <integer, typically 20-200>,
      "confidence": "High/Medium",
      "rationale": "Why these genes suggest this pathway",
      "disease_relevance": "How this pathway relates to {disease_name}"
    }},
    ... (repeat for all {top_k} pathways)
  ]
}}

IMPORTANT: Order pathways by confidence (highest first)."""

        return {
            'system_prompt': PathwayPromptTemplates.WIKIPATHWAYS_SYSTEM_PROMPT,
            'user_prompt': user_prompt
        }

    # ============================================================================
    # UTILITY METHODS
    # ============================================================================
    
    @staticmethod
    def validate_pathway_id_format(pathway_id: str, database: str) -> bool:
        """
        Validate pathway ID format against database requirements.
        
        Parameters:
        -----------
        pathway_id : str
            Pathway/term ID to validate
        database : str
            Database name: "KEGG", "REAC"/"Reactome", "GO"/"GOBP"/"GOMF"/"GOCC"
            
        Returns:
        --------
        bool : True if valid format, False otherwise
        """
        import re
        
        database = database.upper().replace(':', '')
        
        if database == "KEGG":
            # hsa#### or hsa##### (4-5 digits)
            return bool(re.match(r'^hsa\d{4,5}$', pathway_id))
        
        elif database in ["REAC", "REACTOME"]:
            # R-HSA-###### (6+ digits)
            return bool(re.match(r'^R-HSA-\d{6,}$', pathway_id))
        
        elif database in ["GO", "GOBP", "GOMF", "GOCC"]:
            # GO:#######(7 digits) - all GO aspects use same format
            return bool(re.match(r'^GO:\d{7}$', pathway_id))
        
        elif database in ["WP", "WIKIPATHWAYS"]:
            # WP### (variable digits) - kept for backward compatibility
            return bool(re.match(r'^WP\d+$', pathway_id))
        
        else:
            return False
    
    @staticmethod
    def extract_pathways_from_response(response_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract pathway generations from GPT response.
        
        Handles both single-database responses and combined multi-database responses.
        
        Parameters:
        -----------
        response_json : dict
            Parsed JSON response from GPT
            
        Returns:
        --------
        list : List of pathway dictionaries with unified format
        """
        pathways = []
        
        # Combined response (has database-specific lists)
        if any(k in response_json for k in ['kegg_pathways', 'reactome_pathways', 'gobp_terms', 'gomf_terms', 'gocc_terms', 'wikipathways']):
            # GO:BP terms
            for go_term in response_json.get('gobp_terms', []):
                go_term['source'] = 'GO:BP'
                pathways.append(go_term)
            
            # GO:MF terms
            for go_term in response_json.get('gomf_terms', []):
                go_term['source'] = 'GO:MF'
                pathways.append(go_term)
            
            # GO:CC terms
            for go_term in response_json.get('gocc_terms', []):
                go_term['source'] = 'GO:CC'
                pathways.append(go_term)
            
            # KEGG pathways
            for kegg_pw in response_json.get('kegg_pathways', []):
                kegg_pw['source'] = 'KEGG'
                pathways.append(kegg_pw)
            
            # Reactome pathways
            for reac_pw in response_json.get('reactome_pathways', []):
                reac_pw['source'] = 'REAC'
                pathways.append(reac_pw)
            
            # WikiPathways (kept for backward compatibility with old responses)
            for wp in response_json.get('wikipathways', []):
                wp['source'] = 'WP'
                pathways.append(wp)
        
        # Single-database response
        elif 'pathways' in response_json:
            pathways = response_json['pathways']
        
        return pathways

