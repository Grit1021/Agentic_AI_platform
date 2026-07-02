def get_memory_bank_context(
    memory_bank,  # PathwayMemoryBank
    disease_id: str,
    disease_name: str,
    disease_description: str,
    pathways_df=None  # Optional[pd.DataFrame]
) -> str:
    """
    Retrieve relevant historical knowledge from Memory Bank for GPT prompting.
    
    Parameters:
    -----------
    memory_bank : PathwayMemoryBank
        Memory bank instance
    disease_id : str
        Current disease MeSH ID  
    disease_name : str
        Current disease name
    disease_description : str
        Current disease description
    pathways_df : DataFrame, optional
        Current pathways to check for historical matches
        
    Returns:
    --------
    str : Formatted historical context for GPT prompt
    """
    # Retrieve similar diseases
    similar_diseases = memory_bank.retrieve_similar_disease_experiences(
        disease_id=disease_id,
        disease_description=disease_description,
        top_k=3  # Top 3 similar diseases
    )
    
    if not similar_diseases:
        return "No prior disease analyses available in Memory Bank."
    
    # Format context
    context_parts = []
    context_parts.append(f"Historical Knowledge from {len(similar_diseases)} Previously Analyzed Diseases:")
    context_parts.append("")
    
    for i, disease_info in enumerate(similar_diseases, 1):
        disease_mesh = disease_info['mesh_id']
        disease_label = disease_info['name']
        num_pathways = len(disease_info.get('top_pathways', []))
        
        context_parts.append(f"{i}. {disease_label} [{disease_mesh}]")
        context_parts.append(f"   Total pathways: {disease_info.get('total_pathways', 'N/A')}")
        
        # Show top 5 pathways from this disease
        top_pathways = disease_info.get('top_pathways', [])[:5]
        if top_pathways:
            context_parts.append(f"   Top {len(top_pathways)} pathways:")
            for pw in top_pathways:
                pw_name = pw['name']
                avg_rank = pw.get('avg_rank', 'N/A')
                evidence = pw.get('evidence_count', 0)
                context_parts.append(f"     - {pw_name} (avg rank: {avg_rank}, evidence: {evidence}x)")
        
        context_parts.append("")
    
    # If we have current pathways, check for cross-disease patterns
    if pathways_df is not None and len(pathways_df) > 0:
        pathway_overlaps = []
        for _, row in pathways_df.head(20).iterrows():  # Check top 20 candidates
            pw_knowledge = memory_bank.retrieve_pathway_knowledge(
                pathway_name=row['name'],
                disease_context=disease_id
            )
            
            if pw_knowledge['num_occurrences'] > 0:
                pathway_overlaps.append({
                    'name': row['name'],
                    'occurrences': pw_knowledge['num_occurrences'],
                    'num_diseases': pw_knowledge['num_diseases'],
                    'avg_rank': pw_knowledge['avg_rank'],
                    'best_rank': pw_knowledge['best_rank']
                })
        
        if pathway_overlaps:
            context_parts.append("Cross-Disease Pathway Patterns:")
            context_parts.append(f"Found {len(pathway_overlaps)} pathways that appeared in previous analyses:")
            for pw in sorted(pathway_overlaps, key=lambda x: x['avg_rank'] or 999)[:5]:
                context_parts.append(
                    f"  - {pw['name']}: seen in {pw['num_diseases']} diseases, "
                    f"avg rank {pw['avg_rank']:.1f}, best rank {pw['best_rank']}"
                )
            context_parts.append("")
    
    return "\n".join(context_parts)


def store_module_pathways_in_memory(
    memory_bank,  # PathwayMemoryBank
    disease_id: str,
    disease_name: str,
    module_id: int,
    iteration: int,
    pathways_df,  # pd.DataFrame
    top_k: int = 50,
    global_reasoning: str = ""
):
    """
    Store top pathways from a module analysis in Memory Bank.
    
    Parameters:
    -----------
    memory_bank : PathwayMemoryBank
        Memory bank instance
    disease_id : str
        Disease MeSH ID
    disease_name : str
        Disease name
    module_id : int
        Module identifier
    iteration : int
        Iteration number
    pathways_df : DataFrame
        Ranked pathways
    top_k : int
        Number of top pathways to store
    """
    # Store top K pathways
    top_pathways = pathways_df.head(top_k)
    
    for _, pathway in top_pathways.iterrows():
        # Extract pathway data
        pathway_data = {
            'name': pathway.get('name', ''),
            'source': pathway.get('source', ''),
            'description': pathway.get('description', ''),
            'gpt_rank': pathway.get('gpt_rank', None),
            'p_value': pathway.get('p_value', None),
            'gpt_reasoning': pathway.get('reasoning', global_reasoning)
        }
        
        # Context
        iteration_context = {
            'module_id': module_id,
            'iteration': iteration,
            'disease_name': disease_name,
            'total_candidates': len(pathways_df)
        }
        
        # Store in memory
        memory_bank.store_pathway_experience(
            disease_id=disease_id,
            pathway_data=pathway_data,
            iteration_context=iteration_context
        )


