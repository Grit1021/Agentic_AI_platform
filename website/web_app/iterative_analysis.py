def run_iterative_pathway_analysis(session: AnalysisSession) -> list:
    """
    ITERATIVE MODE: Run 2 iterations of pathway analysis.
    
    Each iteration:
    - Iteration 1: Cold start (no context)
    - Iteration 2: Retain ALL FDR-filtered pathways + generate NEW predictions
    
    Follows the HITL script logic from run_aggregated_disease_analysis_hitl.py
    """
    import pandas as pd
    
    disease_config = get_disease_configuration(session.disease_name)
    session.disease_config = disease_config
    disease_description = disease_config.get('description', '')
    
    all_iterations_pathways = []
    final_matched_pathways = pd.DataFrame()
    
    for iteration in range(1, 3):
        session.current_iteration = iteration
        session.add_message("system", f"🔄 **Iteration {iteration}/2** {'─' * 40}")
        
        try:
            # ================================================================
            # STEP 1: GPT-5 Pathway Prediction
            # ================================================================
            if iteration == 1:
                # Cold start: No context
                session.add_message("system", f"🧠 Step 1 (Iter {iteration}): GPT-5 generating initial predictions...")
                predicted_pathways, pathway_details, _ = gpt_predict_pathways(
                    genes=session.genes,
                    disease_name=session.disease_name,
                    disease_description=disease_description
                )
                session.add_message("system", f"✅ GPT predicted {len(predicted_pathways)} pathways")
            else:
                # Warm start: Use retained pathways as context
                retained_count = len(session.retained_pathways)
                session.add_message("system", 
                    f"🔄 Step 1 (Iter {iteration}): Using {retained_count} retained pathways as context...")
                
                # Generate NEW predictions with context
                predicted_pathways, pathway_details = gpt_predict_pathways_with_context(
                    genes=session.genes,
                    disease_name=session.disease_name,
                    disease_description=disease_description,
                    retained_pathways=session.retained_pathways
                )
                session.add_message("system", 
                    f"✅ GPT generated {len(predicted_pathways)} NEW predictions")
            
            # ================================================================
            # STEP 2: g:Profiler Enrichment
            # ================================================================
            session.add_message("system", f"🔬 Step 2 (Iter {iteration}): g:Profiler enrichment...")
            
            from gprofiler import GProfiler
            gp = GProfiler(return_dataframe=True)
            
            enrichment_results = gp.profile(
                organism='hsapiens',
                query=session.genes,
                sources=['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'],
                user_threshold=1.0,
                significance_threshold_method='fdr',
                # Preserve the genes shared by the submitted query and term so
                # downstream pathway cards can report true intersections.
                no_evidences=False
            )
            
            if enrichment_results.empty:
                session.add_message("system", "⚠️ No g:Profiler results")
                continue
            
            n_sig = (enrichment_results['p_value'] < 0.05).sum()
            session.add_message("system", 
                f"✅ g:Profiler: {len(enrichment_results)} pathways ({n_sig} significant)")
            
            # ================================================================
            # STEP 3: Match GPT with g:Profiler
            # ================================================================
            matched_pathways, category_stats = match_gpt_with_gprofiler_detailed(
                gpt_predictions=predicted_pathways,
                pathway_details=pathway_details,
                gprofiler_results=enrichment_results
            )
            
            session.add_message("system", f"🔗 Step 3 (Iter {iteration}): Matching predictions...")
            
            #  Filter by FDR < 0.05 (this is what we retain)
            fdr_filtered = matched_pathways[matched_pathways['p_value'] < 0.05].copy()
            
            # Display iteration statistics
            display_iteration_stats(session, iteration, category_stats, 
                                   len(session.retained_pathways), len(predicted_pathways),
                                   len(matched_pathways), len(fdr_filtered))
            
            # ================================================================
            # STEP 4: Retain ALL FDR-filtered pathways for next iteration
            # ================================================================
            # CRITICAL: User specified to retain ALL filtered, not just top N
            session.retained_pathways = fdr_filtered.to_dict('records')
            
            session.add_message("system", 
                f"💾 Retained {len(session.retained_pathways)} FDR-filtered pathways for next iteration")
            
            # Store for merging at end
            if not fdr_filtered.empty:
                all_iterations_pathways.append(fdr_filtered)
                final_matched_pathways = pd.concat([final_matched_pathways, fdr_filtered], 
                                                   ignore_index=True)
            
        except Exception as e:
            print(f"Iteration {iteration} error: {e}")
            import traceback
            traceback.print_exc()
            session.add_message("system", f"⚠️ Iteration {iteration} error: {str(e)[:100]}")
            continue
    
    # ================================================================
    # FINAL: Merge and rank all pathways from all iterations
    # ================================================================
    session.add_message("system", "🎯 **Final Step**: Merging and ranking all iterations...")
    
    if final_matched_pathways.empty:
        session.add_message("system", "⚠️ No pathways validated across all iterations")
        return generate_mock_pathways(session.disease)
    
    # Remove duplicates (keep first occurrence)
    final_matched_pathways = final_matched_pathways.drop_duplicates(subset=['name'], keep='first')
    
    session.add_message("system", 
        f"✅ Total unique pathways from all iterations: {len(final_matched_pathways)}")
    
    # GPT Auto-Rank the merged pathways
    try:
        ranked_pathways = gpt_rank_pathways_direct(
            final_matched_pathways,
            session.disease_name,
            disease_description,
            top_n=30
        )
    except Exception as e:
        print(f"GPT ranking error: {e}")
        ranked_pathways = final_matched_pathways.sort_values('p_value').head(30)
    
    # Convert to output format (same as single-shot mode)
    pathways_list = convert_pathways_to_output_format(ranked_pathways)
    
    # Category distribution
    cat_dist = {}
    for p in pathways_list:
        cat = p['category']
        cat_dist[cat] = cat_dist.get(cat, 0) + 1
    
    dist_str = ", ".join([f"{cat}: {count}" for cat, count in sorted(cat_dist.items())])
    session.add_message("system", 
        f"✅ **Iterative Analysis Complete**: {len(pathways_list)} pathways | {dist_str}")
    
    return pathways_list


def display_iteration_stats(session, iteration, category_stats, retained_count, 
                           new_predictions, matched_count, fdr_count):
    """Display iteration statistics table."""
    stats_rows = []
    total_retained = 0
    total_new = 0
    total_matched = 0
    total_fdr = 0
    
    for cat in ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']:
        stat = category_stats.get(cat, {'predicted': 0, 'matched': 0, 'fdr_filtered': 0})
        
        # For iteration 1: retained = 0, For iteration 2-3: show retained
        if iteration == 1:
            cat_retained = 0
        else:
            # Count how many retained pathways are in this category
            cat_retained = sum(1 for p in session.retained_pathways 
                              if p.get('source') == cat)
        
        cat_new = stat['predicted']
        cat_total = cat_retained + cat_new
        if iteration == 1:
            cat_match = stat.get('matched', 0)
            cat_fdr = stat.get('fdr_filtered', 0)
        else:
            cat_match = stat.get('new_matched', 0)
            cat_fdr = stat.get('new_fdr', 0)
        
        # `matched` and `fdr_filtered` are unique-hypothesis counts. Retained
        # pathway records are context for round 2, not part of its rate base.
        mat_pct = (cat_match / cat_new * 100) if cat_new > 0 else 0
        fdr_pct = (cat_fdr / cat_match * 100) if cat_match > 0 else 0
        
        stats_rows.append({
            'category': cat,
            'retained': cat_retained,
            'new_gen': cat_new,
            'total': cat_total,
            'match': cat_match,
            'mat_pct': f"{mat_pct:.0f}%",
            'fdr': cat_fdr,
            'fdr_pct': f"{fdr_pct:.0f}%"
        })
        
        total_retained += cat_retained
        total_new += cat_new
        total_matched += cat_match
        total_fdr += cat_fdr
    
    # Generate HTML table
    stats_html = f'''<div class="stats-container">
    <h4>📊 Iteration {iteration} Statistics</h4>
    <table class="pathway-table stats-table">
        <thead>
            <tr>
                <th>Category</th>
                <th>Retained</th>
                <th>NewGen</th>
                <th>Total</th>
                <th>Match</th>
                <th>Mat%</th>
                <th>FDR</th>
                <th>FDR%</th>
            </tr>
        </thead>
        <tbody>'''
    
    for row in stats_rows:
        stats_html += f'''
            <tr>
                <td><span class="category-badge {row['category'].replace(':', '-')}">{row['category']}</span></td>
                <td>{row['retained']}</td>
                <td>{row['new_gen']}</td>
                <td>{row['total']}</td>
                <td><strong>{row['match']}</strong></td>
                <td>{row['mat_pct']}</td>
                <td><strong>{row['fdr']}</strong></td>
                <td>{row['fdr_pct']}</td>
            </tr>'''
    
    validation_rate = (total_fdr / max(total_matched, 1)) * 100 if total_matched > 0 else 0
    
    stats_html += f'''
        </tbody>
    </table>
    <div class="stats-summary">
        <strong>Round {iteration}/2 hypothesis-level validation: {total_fdr}/{total_matched} {'initial unique' if iteration == 1 else 'newly unique'} matched hypotheses ({validation_rate:.1f}%)</strong>
    </div>
    </div>'''
    
    session.add_message("system", stats_html)


def convert_pathways_to_output_format(pathways_df):
    """Convert DataFrame to output list format."""
    import math
    
    pathways_list = []
    
    # Select balanced pathways across categories
    categories_order = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
    per_category = {}
    
    for cat in categories_order:
        cat_df = pathways_df[pathways_df['source'] == cat] if 'source' in pathways_df.columns else pd.DataFrame()
        per_category[cat] = cat_df
    
    # Select top pathways from each category (balanced)
    pathways_per_cat = 4  # 4 per category = 20 total
    selected_rows = []
    
    for cat in categories_order:
        cat_df = per_category.get(cat, pd.DataFrame())
        if not cat_df.empty:
            selected_rows.extend(cat_df.head(pathways_per_cat).to_dict('records'))
    
    # If not enough, add more from any category
    remaining = 20 - len(selected_rows)
    if remaining > 0 and not pathways_df.empty:
        already_selected = set(r.get('name', '') for r in selected_rows)
        for _, row in pathways_df.iterrows():
            if row.get('name', '') not in already_selected:
                selected_rows.append(row.to_dict())
                if len(selected_rows) >= 20:
                    break
    
    # Convert to output format
    rank = 1
    for row in selected_rows[:20]:
        p_val = row.get('p_value', 0.05)
        # Inverted formula: lower p-values give higher scores (0-100 scale)
        # -log10(p_val) gives the significance, scaled to 0-100
        score = min(100, max(0, -10 * math.log10(float(p_val) + 1e-300)))

        pathways_list.append({
            "name": row.get('name', 'Unknown'),
            "p_value": float(p_val),
            "score": round(score, 1),
            "category": row.get('source', 'GO:BP'),
            "genes": ','.join(row.get('intersections', [])[:5]) if isinstance(row.get('intersections'), list) else str(row.get('intersection_size', 0)),
            "description": str(row.get('description', ''))[:200],
            "gpt_rank": rank,
            "gpt_predicted": row.get('gpt_validated', False),
            "literature": row.get('related_literature', []) if isinstance(row.get('related_literature'), list) else []
        })
        rank += 1
    
    return pathways_list
