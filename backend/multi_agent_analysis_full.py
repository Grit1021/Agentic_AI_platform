import os
import sys
import json
import pandas as pd
import numpy as np
from pathlib import Path
from api_cost_tracker import cost_tracker
from typing import List, Dict, Any, Tuple, Optional
import time

# Import the original multi-agent analyzer
from multi_agent_pathway_analysis import MultiAgentPathwayAnalyzer

# Import category-specific pathway prompt templates
from pathway_prompt_templates import PathwayPromptTemplates

# Import reasoning path parsing utilities
from reasoning_parser import parse_reasoning_from_response, save_reasoning_to_file, print_reasoning_summary


# OpenAI API Key check
if 'OPENAI_API_KEY' not in os.environ:
    print("⚠️  Warning: OPENAI_API_KEY not set in environment")


class GPT5PathwayGenerator:
    """
    Step 1: Use GPT-5 to generate pathways (as AI hypothesis).
    This is ONLY for generation - does not replace g:Profiler.
    """
    
    def __init__(self, model="gpt-5", reasoning_context: str = None):
        """
        Initialize GPT-5 pathway generator.
        
        Parameters:
        -----------
        model : str
            Model name (default: gpt-5)
        reasoning_context : str, optional
            Pre-formatted reasoning strategies from Memory Bank (Reasoning RAG).
            If provided, this will be injected into system prompts to guide predictions.
        """
        self.model = model
        self.reasoning_context = reasoning_context  # For Reasoning RAG
        
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
            self.available = True
            if self.reasoning_context:
                print(f"🧠 Reasoning RAG ENABLED: Expert strategies will be injected into prompts")
        except:
            print("❌ OpenAI not available")
            self.available = False
    
    def _generate_category_with_fillup(
        self,
        category_name: str,
        target_count: int,
        prompt_func,
        genes: List[str],
        disease_name: str,
        feedback: str = None,
        max_retries: int = 3,
        existing_pathways: List[str] = None,
        benchmark_config: dict = None,
        file_identifier: str = None,
        iteration: int = None,
        memory_context: str = None  # NEW: Memory Bank context for prediction
    ) -> Tuple[List[str], Dict[str, Any], Optional[Dict[str, str]]]:
        """
        Generate exactly target_count pathways for a single category with fill-up logic.
        
        If GPT returns fewer than target_count pathways, this method will retry
        with a supplementary prompt to fill up to the target.
        
        Parameters:
        -----------
        category_name : str
            Category name (e.g., 'GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC')
        target_count : int
            Target number of pathways (default 10)
        prompt_func : callable
            Function to generate prompts for this category
        genes : List[str]
            Input gene symbols
        disease_name : str
            Disease name for context
        feedback : str, optional
            Feedback from previous iteration (for iterative mode)
        max_retries : int
            Maximum retry attempts to fill up
        existing_pathways : List[str], optional
            Pathways to exclude (already generated in previous retries)
        benchmark_config : dict, optional
            Benchmark configuration for LLM evaluation
        file_identifier : str, optional
            File identifier for saving reasoning (e.g., "T2D_Module_2_iter2")
        iteration : int, optional
            Current iteration number
            
        Returns:
        --------
        tuple: (pathway_names: List[str], pathway_details: Dict[str, Any], reasoning_dict: Dict[str, str] or None)
        """
        all_pathways = []
        all_details = {}
        existing_pathways = existing_pathways or []
        reasoning_dict = None  # Generation is JSON-only; audit traces are generated after validation.
        
        # Create normalized sets for case-insensitive deduplication
        normalized_existing = {p.lower() for p in existing_pathways}
        normalized_current = {p.lower() for p in all_pathways}
        
        print(f"\n   [{category_name}] Generating {target_count} pathways...")
        
        for attempt in range(max_retries + 1):
            current_count = len(all_pathways)
            needed = target_count - current_count
            
            if needed <= 0:
                break
            
            if attempt > 0:
                print(f"      ⚠️  Have {current_count}/{target_count}, retrying for {needed} more...")
            
            try:
                # Get category-specific prompt
                prompts = prompt_func(
                    genes=genes,
                    disease_name=disease_name,
                    top_k=needed
                )
                
                system_prompt = prompts['system_prompt']
                user_prompt = prompts['user_prompt']
                
                # Inject Semantic RAG context from Memory Bank (Level 2: Embedding RAG)
                # Option B: Inject into SYSTEM PROMPT as role-level guidance.
                # Meta-guidance serves as high-level instructions that shape the
                # LLM's approach to pathway prediction.
                if self.reasoning_context:
                    system_prompt = system_prompt + f"""
{self.reasoning_context}
"""
                    if attempt == 0:
                        print(f"      🧠 Semantic RAG: Injected meta-guidance into system prompt")
                
                # For retry attempts, add exclusion instructions
                if attempt > 0 and (all_pathways or existing_pathways):
                    exclude_list = list(set(all_pathways + existing_pathways))
                    exclusion_text = f"""
IMPORTANT: You have already generated these pathways. DO NOT repeat them:
{chr(10).join(f'- {p}' for p in exclude_list[:20])}
{"..." if len(exclude_list) > 20 else ""}

Generate {needed} DIFFERENT {category_name} pathways that are NOT in the above list.
"""
                    user_prompt = exclusion_text + "\n\n" + user_prompt
                
                if feedback and attempt == 0:
                    # Iterative mode: use structured validation feedback, but keep generation JSON-only.
                    user_prompt = f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                      ITERATION FEEDBACK FOR IMPROVEMENT                       ║
╚═══════════════════════════════════════════════════════════════════════════════╝

{feedback}

═══════════════════════════════════════════════════════════════════════════════
TASK: Generate IMPROVED {category_name} pathways
═══════════════════════════════════════════════════════════════════════════════

Use the validation feedback above to retain exact FDR-supported pathways where
required and to avoid failed pathway names or weakly supported biological themes.
Return JSON only. Do not include a <REASONING> block, markdown, prose, or comments.

{user_prompt}
"""
                elif attempt == 0:
                    user_prompt = f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                      ITERATION 1: INITIAL PATHWAY PREDICTION                  ║
╚═══════════════════════════════════════════════════════════════════════════════╝

TASK: Generate {category_name} pathways for the input genes.

Return JSON only. Do not include a <REASONING> block, markdown, prose, or comments.

{user_prompt}
"""
                
                # Call GPT with benchmark configuration for deterministic evaluation
                api_params = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_completion_tokens": 16384,
                }
                
                # Pathway generation is JSON-only. Reasoning/audit traces are generated
                # after enrichment validation so they cannot affect same-iteration candidates.
                api_params["response_format"] = {"type": "json_object"}

                # Apply benchmark config if provided (standard LLM evaluation)
                if benchmark_config:
                    # Apply only the parameters that OpenAI API supports
                    if "temperature" in benchmark_config:
                        api_params["temperature"] = benchmark_config["temperature"]
                    if "top_p" in benchmark_config:
                        api_params["top_p"] = benchmark_config["top_p"]
                    if "presence_penalty" in benchmark_config:
                        api_params["presence_penalty"] = benchmark_config["presence_penalty"]
                    if "frequency_penalty" in benchmark_config:
                        api_params["frequency_penalty"] = benchmark_config["frequency_penalty"]
                    if "n" in benchmark_config:
                        api_params["n"] = benchmark_config["n"]
                    # Note: max_tokens from config is overridden by max_completion_tokens above
                    
                    if attempt == 0:  # Only print once per category
                        print(f"      🔬 Benchmark config: T={benchmark_config.get('temperature', 'default')}, "
                              f"top_p={benchmark_config.get('top_p', 'default')}, "
                              f"penalties={benchmark_config.get('presence_penalty', 0)}/{benchmark_config.get('frequency_penalty', 0)}")
                
                response = self.client.chat.completions.create(**api_params)
                cost_tracker.track(response)
                
                response_text = response.choices[0].message.content
                
                if not response_text or response_text.strip() == "":
                    print(f"      ❌ GPT returned empty response")
                    continue
                
                # Parse JSON (handle code blocks if present)
                import re  # Ensure re is available for all JSON extraction
                json_text = response_text
                # Defensive cleanup only; generation prompts request JSON-only.
                json_text = re.sub(r'<REASONING>.*?</REASONING>', '', json_text, flags=re.DOTALL | re.IGNORECASE)
                json_text = json_text.strip()
                
                if "```json" in json_text:
                    json_start = json_text.find("```json") + 7
                    json_end = json_text.find("```", json_start)
                    json_text = json_text[json_start:json_end].strip()
                elif "```" in json_text:
                    json_start = json_text.find("```") + 3
                    json_end = json_text.find("```", json_start)
                    json_text = json_text[json_start:json_end].strip()
                else:
                    # Try to find JSON object in the text
                    json_match = re.search(r'\{[\s\S]*\}', json_text)
                    if json_match:
                        json_text = json_match.group(0)
                
                # Parse JSON with error handling
                parsed = None
                try:
                    parsed = json.loads(json_text)
                except json.JSONDecodeError as json_err:
                    print(f"      ⚠️  JSON parsing error: {json_err}")
                    import re
                    fixed_text = re.sub(r',(\s*[}\]])', r'\1', json_text)
                    try:
                        parsed = json.loads(fixed_text)
                        print(f"      ✅ Fixed JSON")
                    except:
                        print(f"      ❌ Could not fix JSON, skipping attempt...")
                        continue
                
                if parsed is None:
                    continue
                
                # Extract pathways/terms from response
                category_pathways = []
                if 'pathways' in parsed:
                    category_pathways = parsed['pathways']
                elif 'terms' in parsed:
                    category_pathways = parsed['terms']
                
                # Add source information and collect (avoiding duplicates)
                new_count = 0
                for pw in category_pathways:
                    name = pw.get('name', '')
                    if not name:
                        continue
                    
                    # Skip if already have this pathway (case-insensitive check)
                    name_lower = name.lower()
                    if name_lower in normalized_current or name_lower in normalized_existing:
                        continue
                    
                    # Add source category
                    pw['source'] = category_name
                    
                    # Validate ID format
                    pathway_id = pw.get('pathway_id') or pw.get('go_id')
                    if pathway_id:
                        valid = PathwayPromptTemplates.validate_pathway_id_format(pathway_id, category_name)
                        if not valid:
                            print(f"      ⚠️  Invalid ID format: {pathway_id}")
                    
                    all_pathways.append(name)
                    normalized_current.add(name_lower)
                    all_details[name] = pw
                    new_count += 1
                    
                    # Stop if we've reached target
                    if len(all_pathways) >= target_count:
                        break
                
                if attempt == 0:
                    print(f"      ✅ Got {new_count} {category_name} pathways")
                else:
                    print(f"      ✅ Got {new_count} additional {category_name} pathways")
                
            except Exception as e:
                print(f"      ❌ Error: {str(e)}")
                import traceback
                traceback.print_exc()
                continue
        
        # Final status
        final_count = len(all_pathways)
        if final_count >= target_count:
            print(f"      ✅ {category_name} complete: {final_count} pathways")
        else:
            print(f"      ⚠️  {category_name} incomplete: {final_count}/{target_count} pathways (after {max_retries} retries)")
        
        return all_pathways, all_details, reasoning_dict

    def generate_posthoc_audit_trace(
        self,
        genes: List[str],
        disease_name: str,
        gpt_prediction: Dict[str, Any],
        validated_pathways_df: pd.DataFrame,
        matched_pathways_df: pd.DataFrame = None,
        feedback: str = None,
        benchmark_config: dict = None,
        file_identifier: str = None,
        iteration: int = None,
        categories: List[str] = None
    ) -> Dict[str, Dict[str, str]]:
        """
        Generate post-hoc audit traces after pathway generation and FDR validation.

        These traces summarize the generated JSON records and validation outcomes.
        They are deliberately produced after candidate generation, so they cannot
        influence the same-iteration pathway list.
        """
        if not self.available:
            return {}

        if not file_identifier or iteration is None:
            print("   ⚠️  Skipping post-hoc audit trace: file_identifier or iteration missing")
            return {}

        pathway_details = gpt_prediction.get('pathway_details', {}) or {}
        predicted_pathways = gpt_prediction.get('predicted_pathways', []) or gpt_prediction.get('generated_pathways', []) or []

        if categories is None:
            categories = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']

        def _df_records(df: pd.DataFrame, category: str, max_rows: int = 20) -> List[Dict[str, Any]]:
            if df is None or df.empty:
                return []
            sub = df[df.get('source', '') == category] if 'source' in df.columns else df
            cols = [c for c in ['native', 'name', 'p_value', 'source', 'gpt_key_genes', 'intersections'] if c in sub.columns]
            records = []
            for _, row in sub.head(max_rows).iterrows():
                rec = {}
                for col in cols:
                    val = row.get(col)
                    if isinstance(val, (list, tuple)):
                        val = ', '.join(map(str, val[:20]))
                    rec[col] = str(val)[:500]
                records.append(rec)
            return records

        def _generated_records(category: str, max_rows: int = 20) -> List[Dict[str, Any]]:
            records = []
            for name in predicted_pathways:
                detail = pathway_details.get(name, {})
                if detail.get('source') != category:
                    continue
                records.append({
                    'name': name,
                    'id': detail.get('pathway_id') or detail.get('go_id') or '',
                    'key_genes': detail.get('key_genes', []),
                    'mechanism_in_module': detail.get('mechanism_in_module') or detail.get('rationale') or detail.get('description', ''),
                    'disease_relevance': detail.get('disease_relevance', '')
                })
                if len(records) >= max_rows:
                    break
            return records

        audit_traces = {}
        gene_list_text = ', '.join(map(str, genes[:200]))
        if len(genes) > 200:
            gene_list_text += f", ... ({len(genes)} genes total)"

        for category in categories:
            generated_records = _generated_records(category)
            if not generated_records:
                continue

            validated_records = _df_records(validated_pathways_df, category)
            failed_records = []
            if matched_pathways_df is not None and not matched_pathways_df.empty and 'p_value' in matched_pathways_df.columns:
                try:
                    matched_sub = matched_pathways_df[matched_pathways_df.get('source', '') == category] if 'source' in matched_pathways_df.columns else matched_pathways_df
                    failed_df = matched_sub[matched_sub['p_value'] >= 0.05].copy()
                    failed_records = _df_records(failed_df, category, max_rows=20)
                except Exception:
                    failed_records = []

            system_prompt = (
                "You are a scientific audit assistant for pathway analysis. "
                "Summarize the evidence already produced by a pathway-generation run. "
                "Do not generate new pathway candidates. Do not claim access to hidden model reasoning."
            )

            user_prompt = f"""
Generate a post-hoc audit trace for one completed pathway-generation iteration.

Important:
- The pathway candidates have already been generated as JSON.
- g:Profiler/FDR validation has already been performed.
- This audit trace is an externalized summary of generated records and validation outcomes.
- It must not introduce new pathway candidates or change the generated pathway list.

Disease/module: {disease_name}
Iteration: {iteration}
Database category: {category}
Input genes ({len(genes)}): {gene_list_text}

Previous validation feedback used for this generation, if any:
{feedback or 'N/A'}

Generated JSON pathway records for this category:
{json.dumps(generated_records, indent=2)}

FDR-supported generated pathways for this category:
{json.dumps(validated_records, indent=2)}

Generated pathways that matched g:Profiler but did not pass FDR for this category:
{json.dumps(failed_records, indent=2)}

Return exactly one <REASONING> block using these fields:

<REASONING>
Strategy: [2-3 sentences summarizing the observed generation strategy from the JSON records, not hidden model thinking]
Gene_analysis: [2-3 sentences on module gene signals visible from key_genes and intersections]
Database_focus: [1-2 sentences explaining how {category} shaped the generated terms]
Key_gene_functions: [2-3 sentences naming dominant gene functions or protein classes supported by generated/validated records]
Pathway_selection_rationale: [2-3 sentences explaining why the generated pathway family was biologically plausible]
Biological_evidence: [1-2 sentences linking validated pathways to disease biology]
Learned_from_feedback: [2-3 sentences; use N/A for iteration 1 if no feedback]
Pathway_guidance: [2-3 sentences on what FDR-supported pathways suggest for interpretation or the next iteration]
Category_adjustments: [1-2 sentences on category-specific lessons]
Validation_reflection: [1-2 sentences comparing FDR-supported and failed generated terms]
Failure_analysis: [1-3 sentences naming failed terms and likely reasons for failure; use N/A if none]
Bottleneck_diagnosis: [1-2 sentences diagnosing specificity, annotation granularity or module-support bottlenecks]
Cell_context: [1-2 sentences on plausible disease-relevant cell/tissue context supported by validated pathways and genes; mark as interpretive if evidence is indirect]
Relevance_strength_with_disease: [High/Medium/Low] - [brief justification based on validated pathway support]
</REASONING>
"""

            api_params = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_completion_tokens": 5000,
            }

            if benchmark_config:
                for key in ["temperature", "top_p", "presence_penalty", "frequency_penalty", "n"]:
                    if key in benchmark_config:
                        api_params[key] = benchmark_config[key]

            try:
                response = self.client.chat.completions.create(**api_params)
                cost_tracker.track(response)
                response_text = response.choices[0].message.content or ""
                reasoning = parse_reasoning_from_response(response_text)
                if reasoning:
                    print_reasoning_summary(reasoning, prefix="      ")
                    reasoning_path = os.path.join(
                        os.path.dirname(file_identifier) if os.path.dirname(file_identifier) else ".",
                        f"{os.path.basename(file_identifier)}_{category.replace(':', '_')}_reasoning.md"
                    )
                    if save_reasoning_to_file(reasoning, reasoning_path, iteration, file_identifier, category):
                        print(f"      💾 Post-hoc audit trace saved: {reasoning_path}")
                    audit_traces[category] = reasoning
            except Exception as e:
                print(f"      ⚠️  Post-hoc audit trace failed for {category}: {e}")

        return audit_traces
    
    def generate_pathways(self, genes: List[str], disease_name: str, benchmark_config: dict = None, 
                          file_identifier: str = None, iteration: int = None,
                          memory_context: str = None) -> Dict[str, Any]:
        """
        Generate pathways using separate category-specific prompts for each database.
        
        This method makes 5 separate GPT calls, one for each database category:
        - GO:BP (Biological Process)
        - GO:MF (Molecular Function)  
        - GO:CC (Cellular Component)
        - KEGG
        - Reactome
        
        Each call uses the updated anti-hallucination prompts that prohibit
        gene-pathway membership claims and focus on functional themes.
        Each category independently generates 10 pathways (50 total).
        
        Parameters:
        -----------
        genes : List[str]
            Input gene symbols
        disease_name : str
            Disease/condition being analyzed
        benchmark_config : dict, optional
            LLM benchmark configuration dict with parameters:
            - temperature: 0 (deterministic)
            - top_p: 1.0 (no nucleus sampling)
            - presence_penalty: 0
            - frequency_penalty: 0
            - max_tokens: 2048
            - n: 1 (single response)
        
        Returns:
        --------
        dict : {
            'generated_pathways': list of pathway names,
            'pathway_details': dict with pathway details including 'source' category,
            'summary': empty string (no combined summary in separate mode),
            'by_category': always True
        }
        """
        if not self.available:
            return {'predicted_pathways': [], 'pathway_details': {}, 'summary': '', 'by_category': False}
        
        
        print(f"\n[GPT-5 Generation] Generating pathway hypotheses...")
        print(f"   Input: {len(genes)} genes for {disease_name}")
        print(f"   Mode: Per-category generation with fill-up (GO:BP, GO:MF, GO:CC, KEGG, Reactome)")
        
        # Fixed: 10 pathways per category (50 total)
        gobp_count = 10
        gomf_count = 10
        gocc_count = 10
        kegg_count = 10
        reac_count = 10
        
        print(f"   Target: {gobp_count} GO:BP, {gomf_count} GO:MF, {gocc_count} GO:CC, {kegg_count} KEGG, {reac_count} REAC (Total: 50)")

        
        # Define categories to process
        categories = [
            ('GO:BP', gobp_count, PathwayPromptTemplates.get_gobp_prompt),
            ('GO:MF', gomf_count, PathwayPromptTemplates.get_gomf_prompt),
            ('GO:CC', gocc_count, PathwayPromptTemplates.get_gocc_prompt),
            ('KEGG', kegg_count, PathwayPromptTemplates.get_kegg_prompt),
            ('REAC', reac_count, PathwayPromptTemplates.get_reactome_prompt)
        ]
        
        # Collect all pathways from separate category calls with fill-up
        all_pathways = []
        all_pathway_details = {}
        
        # Process each category SEPARATELY with fill-up logic
        for category_name, target_count, prompt_func in categories:
            if target_count <= 0:
                continue
            
            cat_pathways, cat_details, _ = self._generate_category_with_fillup(
                category_name=category_name,
                target_count=target_count,
                prompt_func=prompt_func,
                genes=genes,
                disease_name=disease_name,
                feedback=None,  # No feedback for initial generation
                max_retries=3,
                existing_pathways=all_pathways,  # Avoid duplicates across categories
                benchmark_config=benchmark_config,  # Pass benchmark config for deterministic evaluation
                file_identifier=file_identifier,  # Pass for reasoning path saving
                iteration=iteration,  # Pass for reasoning path saving
                memory_context=memory_context  # NEW: Pass memory context for prediction & reasoning
            )
            
            all_pathways.extend(cat_pathways)
            all_pathway_details.update(cat_details)
        
        # Compile final result
        result = {
            'generated_pathways': all_pathways,
            'predicted_pathways': all_pathways,  # Alias for backward compatibility
            'pathway_details': all_pathway_details,
            'summary': '',  # No combined summary in separate mode
            'gene_functional_themes': '',
            'by_category': True  # Always True in new separate mode
        }
        
        # Print final statistics
        total_target = gobp_count + gomf_count + gocc_count + kegg_count + reac_count
        print(f"\n✅ Total pathways generated: {len(all_pathways)} (target: {total_target})")
        
        if len(all_pathways) < total_target:
            print(f"⚠️  WARNING: Got {len(all_pathways)} pathways instead of {total_target}")
        
        # Print category distribution
        gobp_pws = [p for p in all_pathways if all_pathway_details.get(p, {}).get('source') == 'GO:BP']
        gomf_pws = [p for p in all_pathways if all_pathway_details.get(p, {}).get('source') == 'GO:MF']
        gocc_pws = [p for p in all_pathways if all_pathway_details.get(p, {}).get('source') == 'GO:CC']
        kegg_pws = [p for p in all_pathways if all_pathway_details.get(p, {}).get('source') == 'KEGG']
        reac_pws = [p for p in all_pathways if all_pathway_details.get(p, {}).get('source') == 'REAC']
        
        print(f"   Category distribution:")
        print(f"     - GO:BP: {len(gobp_pws)}/10 terms {'✅' if len(gobp_pws) >= 10 else '⚠️'}")
        print(f"     - GO:MF: {len(gomf_pws)}/10 terms {'✅' if len(gomf_pws) >= 10 else '⚠️'}")
        print(f"     - GO:CC: {len(gocc_pws)}/10 terms {'✅' if len(gocc_pws) >= 10 else '⚠️'}")
        print(f"     - KEGG: {len(kegg_pws)}/10 pathways {'✅' if len(kegg_pws) >= 10 else '⚠️'}")
        print(f"     - Reactome: {len(reac_pws)}/10 pathways {'✅' if len(reac_pws) >= 10 else '⚠️'}")
        
        return result
    
    def generate_pathways_with_feedback(self, genes: List[str], disease_name: str,
                                      feedback: str,
                                      gobp_count=10, gomf_count=10, gocc_count=10,
                                      kegg_count=10, reac_count=10,
                                      retained_pathways: List[str] = None,
                                      retained_pathway_details: Dict[str, Any] = None,
                                      retained_per_category: Dict[str, int] = None,
                                      benchmark_config: dict = None,
                                      file_identifier: str = None,
                                      iteration: int = None,
                                      memory_context: str = None) -> Dict[str, Any]:
        """
        Generate pathways incorporating previous iteration feedback using separate category calls.
        
        This is used in iterative mode to allow GPT to learn from previous results.
        Each database category gets its own GPT call with feedback prepended.
        
        CRITICAL: If retained_pathways is provided, these pathways are GUARANTEED to be
        included in the final output. GPT will only generate ADDITIONAL pathways to fill
        the remaining quota.
        
        Parameters:
        -----------
        genes : List[str]
            Input gene symbols
        disease_name : str
            Disease/condition being analyzed
        feedback : str
            Feedback from previous iteration (hindsight)
        gobp_count, gomf_count, gocc_count, kegg_count, reac_count : int
            Number of pathways to predict per category
        retained_pathways : List[str], optional
            Pathway names from previous iteration that MUST be retained
        retained_pathway_details : Dict[str, Any], optional
            Pathway details dict for retained pathways
            
        Returns:
        --------
        dict : Same format as generate_pathways()
        """
        if not self.available:
            return {'predicted_pathways': [], 'pathway_details': {}, 'summary': '', 'by_category': True}
        
        # Handle retention
        retained_pathways = retained_pathways or []
        retained_pathway_details = retained_pathway_details or {}
        n_retained = len(retained_pathways)
        
        print(f"\n[GPT{self.model}] Generating feedback-enhanced pathways...")
        print(f"   Input: {len(genes)} genes for {disease_name}")
        print(f"   Using feedback from previous iteration")
        if n_retained > 0:
            print(f"   🔒 RETENTION: {n_retained} pathways from previous iteration MUST be kept")
            print(f"   📝 GPT will generate NEW pathways to complement retained ones")
        print(f"   Distribution: {gobp_count} GO:BP, {gomf_count} GO:MF, {gocc_count} GO:CC, {kegg_count} KEGG, {reac_count} REAC")
        
        total_count = gobp_count + gomf_count + gocc_count + kegg_count + reac_count
        
        # NEW LOGIC: Each category independently targets its count (default 10)
        # Calculate retained count PER CATEGORY, then generate (target - retained) for each
        
        # Use provided retained_per_category if available, otherwise extract from retained_pathway_details
        if retained_per_category is None:
            retained_per_category = {'GO:BP': 0, 'GO:MF': 0, 'GO:CC': 0, 'KEGG': 0, 'REAC': 0}
            if n_retained > 0 and retained_pathway_details:
                # Fallback: count from retained_pathway_details (may have name mismatch issues)
                for pw_name in retained_pathways:
                    if pw_name in retained_pathway_details:
                        source = retained_pathway_details[pw_name].get('source', '')
                        if source in retained_per_category:
                            retained_per_category[source] += 1
        
        # Check if we have any retained counts
        total_retained = sum(retained_per_category.values())
        if total_retained > 0:
            
            # Calculate new needed per category: target - retained (minimum 0)
            # Each category independently aims for its target (10 by default)
            # NEW CONSTRAINT: If a category has >= 10 FDR-filtered pathways, stop generating for that category
            FDR_TARGET = 10  # Target number of FDR-filtered pathways per category
            
            # Check if each category has reached FDR saturation (>= 10 FDR-filtered)
            saturated_categories = []
            for cat, count in retained_per_category.items():
                if count >= FDR_TARGET:
                    saturated_categories.append(cat)
            
            # Calculate new counts, setting to 0 for saturated categories
            gobp_new = 0 if 'GO:BP' in saturated_categories else max(0, gobp_count - retained_per_category['GO:BP'])
            gomf_new = 0 if 'GO:MF' in saturated_categories else max(0, gomf_count - retained_per_category['GO:MF'])
            gocc_new = 0 if 'GO:CC' in saturated_categories else max(0, gocc_count - retained_per_category['GO:CC'])
            kegg_new = 0 if 'KEGG' in saturated_categories else max(0, kegg_count - retained_per_category['KEGG'])
            reac_new = 0 if 'REAC' in saturated_categories else max(0, reac_count - retained_per_category['REAC'])
            
            print(f"   📊 Per-category FDR-filtered (retained) counts (target: {FDR_TARGET}):")
            print(f"      GO:BP: {retained_per_category['GO:BP']}, GO:MF: {retained_per_category['GO:MF']}, GO:CC: {retained_per_category['GO:CC']}")
            print(f"      KEGG: {retained_per_category['KEGG']}, REAC: {retained_per_category['REAC']}")
            
            # Report saturated categories
            if saturated_categories:
                print(f"   ✅ Categories reached FDR target ({FDR_TARGET}): {', '.join(saturated_categories)}")
                print(f"      → These categories will NOT generate new pathways")
            
            print(f"   ⚙️  NEW generation counts:")
            print(f"      GO:BP: {gobp_new} new" + (f" (target {gobp_count} - {retained_per_category['GO:BP']} retained)" if gobp_new > 0 else " ✅ SATURATED"))
            print(f"      GO:MF: {gomf_new} new" + (f" (target {gomf_count} - {retained_per_category['GO:MF']} retained)" if gomf_new > 0 else " ✅ SATURATED"))
            print(f"      GO:CC: {gocc_new} new" + (f" (target {gocc_count} - {retained_per_category['GO:CC']} retained)" if gocc_new > 0 else " ✅ SATURATED"))
            print(f"      KEGG: {kegg_new} new" + (f" (target {kegg_count} - {retained_per_category['KEGG']} retained)" if kegg_new > 0 else " ✅ SATURATED"))
            print(f"      REAC: {reac_new} new" + (f" (target {reac_count} - {retained_per_category['REAC']} retained)" if reac_new > 0 else " ✅ SATURATED"))
            
            total_new = gobp_new + gomf_new + gocc_new + kegg_new + reac_new
            print(f"      Total NEW: {total_new}")
            print(f"      Total FINAL: {n_retained} retained + {total_new} new = {n_retained + total_new}")
            
            # Update counts to new values
            gobp_count = gobp_new
            gomf_count = gomf_new
            gocc_count = gocc_new
            kegg_count = kegg_new
            reac_count = reac_new
        else:
            # No retained pathways - use original counts
            print(f"   ⚙️  No retained pathways - generating full {total_count} pathways")
        
        # Define categories to process (same as predict_pathways)
        categories = [
            ('GO:BP', gobp_count, PathwayPromptTemplates.get_gobp_prompt),
            ('GO:MF', gomf_count, PathwayPromptTemplates.get_gomf_prompt),
            ('GO:CC', gocc_count, PathwayPromptTemplates.get_gocc_prompt),
            ('KEGG', kegg_count, PathwayPromptTemplates.get_kegg_prompt),
            ('REAC', reac_count, PathwayPromptTemplates.get_reactome_prompt)
        ]
        
        # Collect all pathways from separate category calls with fill-up
        all_pathways = []
        all_pathway_details = {}
        all_reasonings = {}  # Store reasoning per category
        
        # Combine retained pathways as exclusion list
        existing_pathways = list(retained_pathways) if retained_pathways else []
        
        # Process each category SEPARATELY with fill-up logic
        for category_name, target_count, prompt_func in categories:
            if target_count <= 0:
                continue
            
            cat_pathways, cat_details, cat_reasoning = self._generate_category_with_fillup(
                category_name=category_name,
                target_count=target_count,
                prompt_func=prompt_func,
                genes=genes,
                disease_name=disease_name,
                feedback=feedback,  # Pass feedback for iterative mode
                max_retries=3,
                existing_pathways=existing_pathways + all_pathways,  # Avoid duplicates
                benchmark_config=benchmark_config,  # Pass benchmark config for deterministic evaluation
                file_identifier=file_identifier,  # Pass for reasoning path saving
                iteration=iteration,  # Pass for reasoning path saving
                memory_context=memory_context  # NEW: Pass memory context for prediction & reasoning
            )
            
            all_pathways.extend(cat_pathways)
            all_pathway_details.update(cat_details)
            if cat_reasoning:
                all_reasonings[category_name] = cat_reasoning
        
        # PRE-POPULATE result with retained pathways
        final_pathways = list(retained_pathways)  # Start with retained
        final_pathway_details = dict(retained_pathway_details)  # Copy retained details
        
        # Calculate retained pathways by category FOR STATISTICS
        retained_by_category = {'GO:BP': 0, 'GO:MF': 0, 'GO:CC': 0, 'KEGG': 0, 'REAC': 0}
        for pw_name in retained_pathways:
            pw_details = retained_pathway_details.get(pw_name, {})
            source = pw_details.get('source', '')
            if source in retained_by_category:
                retained_by_category[source] += 1
        
        # Add NEW pathways from GPT
        final_pathways.extend(all_pathways)
        final_pathway_details.update(all_pathway_details)

        
        # Compile final result
        result = {
            'generated_pathways': final_pathways,
            'predicted_pathways': final_pathways,  # Alias for backward compatibility
            'pathway_details': final_pathway_details,
            'summary': '',  # No combined summary in separate mode
            'by_category': True
        }
        
        print(f"\n✅ Feedback-enhanced generation: {len(final_pathways)} total pathways")
        if n_retained > 0:
            print(f"   🔒 Retained: {n_retained} pathways from previous iteration")
            print(f"   🆕 New generation: {len(all_pathways)} pathways") 
            print(f"   📊 Total: {len(final_pathways)} = {n_retained} + {len(all_pathways)}")
        
        # Print category distribution (using FINAL pathways)
        gobp_pws = [p for p in final_pathways if final_pathway_details.get(p, {}).get('source') == 'GO:BP']
        gomf_pws = [p for p in final_pathways if final_pathway_details.get(p, {}).get('source') == 'GO:MF']
        gocc_pws = [p for p in final_pathways if final_pathway_details.get(p, {}).get('source') == 'GO:CC']
        kegg_pws = [p for p in final_pathways if final_pathway_details.get(p, {}).get('source') == 'KEGG']
        reac_pws = [p for p in final_pathways if final_pathway_details.get(p, {}).get('source') == 'REAC']
        
        print(f"   Category distribution:")
        print(f"     - GO:BP: {len(gobp_pws)} terms")
        print(f"     - GO:MF: {len(gomf_pws)} terms")
        print(f"     - GO:CC: {len(gocc_pws)} terms")
        print(f"     - KEGG: {len(kegg_pws)} pathways")
        print(f"     - Reactome: {len(reac_pws)} pathways")
        
        # Print detailed statistics table (if retention is used)
        if n_retained > 0:
            # Calculate NEW pathways by category
            gobp_new = [p for p in all_pathways if all_pathway_details.get(p, {}).get('source') == 'GO:BP']
            gomf_new = [p for p in all_pathways if all_pathway_details.get(p, {}).get('source') == 'GO:MF']
            gocc_new = [p for p in all_pathways if all_pathway_details.get(p, {}).get('source') == 'GO:CC']
            kegg_new = [p for p in all_pathways if all_pathway_details.get(p, {}).get('source') == 'KEGG']
            reac_new = [p for p in all_pathways if all_pathway_details.get(p, {}).get('source') == 'REAC']
            
            # DETAILED PATHWAY GENERATION STATISTICS table removed
            # The Step 3.5 Category Breakdown table provides sufficient statistics
        
        # Print reasoning summary if any reasoning was captured
        if all_reasonings:
            print(f"\n💭 REASONING PATH SUMMARY ({len(all_reasonings)} categories):")
            for cat_name, reasoning in all_reasonings.items():
                print(f"   [{cat_name}]")
                strategy = reasoning.get('strategy', 'N/A')[:100]
                print(f"      Strategy: {strategy}..." if len(reasoning.get('strategy', '')) > 100 else f"      Strategy: {strategy}")
                print(f"      Confidence: {reasoning.get('confidence_level', 'N/A')}")
        
        return result
    
    # Backward compatibility aliases
    predict_pathways = generate_pathways
    predict_pathways_with_feedback = generate_pathways_with_feedback


# Backward compatibility: class name alias
GPT5PathwayPredictor = GPT5PathwayGenerator


class EnhancedMultiAgentAnalyzer:
    """
    Enhanced analyzer that combines GPT-5 generation with original multi-agent workflow.
    
    Workflow:
    1. GPT-5 predicts pathways (hypothesis)
    2. Run original MultiAgentPathwayAnalyzer.analyze_disease() 
       (includes g:Profiler + ranking + report generation)
    3. Annotate which GPT predictions were validated
    """
    
    def __init__(self, output_dir: str, model: str = "gpt-5.1"):
        self.output_dir = output_dir
        self.model = model
        
        # Use the SAME directory as original analyzer (multi_agent_analysis)
        # All results will be saved together in one place
        self.results_dir = os.path.join(output_dir, 'multi_agent_analysis')
        os.makedirs(self.results_dir, exist_ok=True)
        
        # Initialize GPT generator
        self.gpt_generator = GPT5PathwayGenerator(model=model)
        # Backward compatibility
        self.gpt_predictor = self.gpt_generator
        
        # Initialize original analyzer (will handle all agent loading)
        self.original_analyzer = MultiAgentPathwayAnalyzer(
            output_dir=self.output_dir,
            model=model
        )
    
    def analyze_disease_with_gpt_prediction(self, genes: List[str], 
                                           disease_name: str) -> Dict[str, Any]:
        """
        Complete analysis with GPT prediction + original multi-agent workflow.
        
        Step 1: GPT-5 prediction (hypothesis)
        Step 2: Original multi-agent analysis (g:Profiler + ranking + report)
        Step 3: Annotate GPT predictions in results
        """
        print("\n" + "="*80)
        print(f"ENHANCED MULTI-AGENT ANALYSIS: {disease_name}")
        print("="*80)
        
        results = {
            'disease_name': disease_name,
            'gene_count': len(genes),
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # =================================================================
        # STEP 1: GPT-5 Pathway Prediction (Hypothesis Generation)
        # =================================================================
        print("\n" + "="*80)
        print("STEP 1: GPT-5 PATHWAY PREDICTION (Hypothesis)")
        print("="*80)
        
        gpt_prediction = self.gpt_predictor.predict_pathways(
            genes=genes,
            disease_name=disease_name
        )
        
        results['gpt_prediction'] = gpt_prediction
        
        # Save GPT prediction
        gpt_file = os.path.join(self.results_dir, f'{disease_name}_gpt_prediction.json')
        with open(gpt_file, 'w') as f:
            json.dump(gpt_prediction, f, indent=2)
        print(f"✅ Saved GPT prediction: {gpt_file}")
        
        # =================================================================
        # STEP 2: Original Multi-Agent Analysis
        # =================================================================
        print("\n" + "="*80)
        print("STEP 2: MULTI-AGENT ANALYSIS (Original Workflow)")
        print("="*80)
        print("This includes:")
        print("  - PlanningAgent.act(): g:Profiler + 7-stage ranking")
        print("  - ReasoningAgent: Pathway overview + PPI analysis")
        print("  - WritingAgent: Scientific report generation")
        
        # Call the original analyzer's analyze_disease method
        # This does EVERYTHING: g:Profiler, ranking, PPI, report
        analysis_results = self.original_analyzer.analyze_disease(
            genes=genes,
            disease_name=disease_name
        )
        
        if analysis_results is None:
            print("❌ Multi-agent analysis failed")
            return results
        
        results['multi_agent_analysis'] = analysis_results
        
        # =================================================================
        # STEP 3: Annotate GPT Predictions in Results
        # =================================================================
        print("\n" + "="*80)
        print("STEP 3: ANNOTATING GPT PREDICTIONS")
        print("="*80)
        
        validation_stats = self._annotate_gpt_predictions(
            gpt_prediction=gpt_prediction,
            analysis_results=analysis_results,
            disease_name=disease_name
        )
        
        results['validation_stats'] = validation_stats
        
        # =================================================================
        # Generate Enhanced Summary
        # =================================================================
        self._generate_enhanced_summary(results)
        
        return results
    
    def _annotate_gpt_predictions(self, gpt_prediction: Dict, 
                                  analysis_results: Dict,
                                  disease_name: str) -> Dict[str, Any]:
        """
        Annotate which GPT predictions were validated by g:Profiler.
        """
        if 'ranked_pathways' not in analysis_results:
            print("⚠️  No ranked pathways to compare")
            return {}
        
        ranked_pathways = analysis_results['ranked_pathways']
        gpt_predicted = gpt_prediction.get('predicted_pathways', [])
        
        # Match GPT predictions with actual results
        validated = []
        not_found = []
        
        for gpt_pathway in gpt_predicted:
            matched = False
            for idx, row in ranked_pathways.iterrows():
                pathway_name = row.get('name', '').lower()
                pathway_id = row.get('native', '').lower()
                
                if (gpt_pathway.lower() in pathway_name or 
                    pathway_name in gpt_pathway.lower() or
                    gpt_pathway.lower() in pathway_id):
                    validated.append({
                        'gpt_predicted': gpt_pathway,
                        'actual_name': row['name'],
                        'p_value': row['p_value'],
                        'score': row.get('score', None)
                    })
                    matched = True
                    break
            
            if not matched:
                not_found.append(gpt_pathway)
        
        # Add GPT validation flag to ranked pathways
        if len(gpt_predicted) > 0:
            gpt_predicted_lower = [p.lower() for p in gpt_predicted]
            
            def is_gpt_validated(row):
                name_lower = row['name'].lower()
                id_lower = row['native'].lower() if 'native' in row.index else ''
                
                for gpt_p in gpt_predicted_lower:
                    if gpt_p in name_lower or name_lower in gpt_p or gpt_p in id_lower:
                        return True
                return False
            
            ranked_pathways['gpt_validated'] = ranked_pathways.apply(is_gpt_validated, axis=1)
            
            # Save annotated pathways (all pathways with gpt_validated flag)
            annotated_file = os.path.join(self.results_dir, 
                                         f'{disease_name}_annotated_pathways.csv')
            ranked_pathways.to_csv(annotated_file, index=False)
            print(f"✅ Saved annotated pathways: {annotated_file}")
            
            # Save GPT-validated pathways only (filtered and ranked)
            gpt_validated_pathways = ranked_pathways[ranked_pathways['gpt_validated'] == True].copy()
            
            if len(gpt_validated_pathways) > 0:
                # Sort by composite score (combine p-value and PubMed score)
                # Primary: PubMed score (descending), Secondary: p-value (ascending)
                if 'score' in gpt_validated_pathways.columns:
                    gpt_validated_pathways = gpt_validated_pathways.sort_values(
                        by=['score', 'p_value'], 
                        ascending=[False, True]
                    )
                else:
                    gpt_validated_pathways = gpt_validated_pathways.sort_values(
                        by='p_value', 
                        ascending=True
                    )
                
                # Save GPT-validated pathways
                gpt_validated_file = os.path.join(self.results_dir, 
                                                 f'{disease_name}_gpt_validated_pathways.csv')
                gpt_validated_pathways.to_csv(gpt_validated_file, index=False)
                print(f"✅ Saved GPT-validated pathways: {gpt_validated_file}")
                print(f"   Total GPT-validated pathways: {len(gpt_validated_pathways)}")
                
                # Print ranking summary
                print("\n📊 Top 5 GPT-Validated Pathways (ranked by PubMed score):")
                for i, (_, row) in enumerate(gpt_validated_pathways.head(5).iterrows(), 1):
                    score_str = f"score={row['score']:.3f}" if 'score' in row and pd.notna(row['score']) else "score=N/A"
                    print(f"   {i}. {row['name'][:60]}...")
                    print(f"      p-value={row['p_value']:.2e}, {score_str}, source={row['source']}")
        
        stats = {
            'total_gpt_predictions': len(gpt_predicted),
            'validated_by_gprofiler': len(validated),
            'not_found_in_gprofiler': len(not_found),
            'validated_pathways': validated,
            'not_found_pathways': not_found
        }
        
        print(f"\nGPT Prediction Validation:")
        print(f"  Total GPT predictions: {stats['total_gpt_predictions']}")
        print(f"  Validated by g:Profiler: {stats['validated_by_gprofiler']}")
        print(f"  Not found: {stats['not_found_in_gprofiler']}")
        
        return stats
    
    def _generate_enhanced_summary(self, results: Dict[str, Any]):
        """Generate comprehensive summary with GPT prediction validation."""
        disease_name = results['disease_name']
        summary_file = os.path.join(self.results_dir, f'{disease_name}_ENHANCED_SUMMARY.md')
        
        summary = f"""# Enhanced Multi-Agent Pathway Analysis Summary

## Disease: {results['disease_name']}
## Analysis Date: {results['timestamp']}
## Input: {results['gene_count']} genes

---

## Analysis Pipeline

This analysis combines:
1. **GPT-5 Prediction**: AI-powered hypothesis generation
2. **Multi-Agent Analysis**: Complete original workflow
   - PlanningAgent: g:Profiler + 7-stage ranking
   - ReasoningAgent: Pathway overview + PPI analysis
   - WritingAgent: Scientific report generation
3. **Validation**: Which GPT predictions were confirmed

---

## Step 1: GPT-5 Pathway Prediction

"""
        
        if 'gpt_prediction' in results:
            gpt = results['gpt_prediction']
            summary += f"**Predicted Pathways**: {len(gpt['predicted_pathways'])}\n\n"
            
            for i, pathway in enumerate(gpt['predicted_pathways'][:10], 1):
                details = gpt['pathway_details'].get(pathway, {})
                confidence = details.get('confidence', 'Unknown')
                summary += f"{i}. **{pathway}** (Confidence: {confidence})\n"
                summary += f"   - {details.get('description', '')}\n\n"
        
        summary += "\n---\n\n## Step 2: Multi-Agent Analysis Results\n\n"
        
        if 'multi_agent_analysis' in results and results['multi_agent_analysis']:
            ma = results['multi_agent_analysis']
            
            if 'ranked_pathways' in ma:
                ranked = ma['ranked_pathways']
                summary += f"**Total Pathways Found**: {len(ranked)}\n"
                summary += f"**Well-known Pathways**: {len(ma.get('wellknown_pathways', []))}\n"
                summary += f"**Novel Pathways**: {len(ma.get('novel_pathways', []))}\n\n"
        
        summary += "\n---\n\n## Step 3: GPT Prediction Validation\n\n"
        
        if 'validation_stats' in results:
            val = results['validation_stats']
            summary += f"**GPT Predictions**: {val.get('total_gpt_predictions', 0)}\n"
            summary += f"**Validated by g:Profiler**: {val.get('validated_by_gprofiler', 0)}\n"
            summary += f"**Not Found**: {val.get('not_found_in_gprofiler', 0)}\n\n"
            
            if val.get('validated_pathways'):
                summary += "### ✅ GPT Predictions Validated by g:Profiler (Ranked by PubMed Score):\n\n"
                
                # Sort validated pathways by score
                validated_sorted = sorted(
                    val['validated_pathways'], 
                    key=lambda x: (x.get('score') if x.get('score') is not None else -1, -x['p_value']),
                    reverse=True
                )
                
                for i, v in enumerate(validated_sorted[:10], 1):
                    summary += f"{i}. **{v['gpt_predicted']}**\n"
                    summary += f"   - Actual: {v['actual_name']}\n"
                    summary += f"   - p-value: {v['p_value']:.2e}\n"
                    if v['score'] is not None:
                        summary += f"   - PubMed score: {v['score']:.3f}\n"
                    summary += "\n"
            
            if val.get('not_found_pathways'):
                summary += "\n### ❌ GPT Predictions Not Found:\n\n"
                for pathway in val['not_found_pathways'][:5]:
                    summary += f"- {pathway}\n"
        
        summary += "\n---\n\n## Output Files (All in multi_agent_analysis/)\n\n"
        summary += f"### GPT Prediction Files:\n"
        summary += f"1. `{disease_name}_gpt_prediction.json` - GPT-5 pathway predictions\n"
        summary += f"2. `{disease_name}_ENHANCED_SUMMARY.md` - This comprehensive summary\n\n"
        summary += f"### Original Multi-Agent Analysis Files:\n"
        summary += f"3. `{disease_name}_pathways.csv` - All ranked pathways (with score)\n"
        summary += f"4. `{disease_name}_wellknown_pathways.csv` - Well-known pathways (high PubMed)\n"
        summary += f"5. `{disease_name}_novel_pathways.csv` - Novel pathways (low PubMed)\n"
        summary += f"6. `{disease_name}_report.md` - Scientific report with PPI analysis\n\n"
        summary += f"### Enhanced Files:\n"
        summary += f"7. `{disease_name}_annotated_pathways.csv` - All pathways with GPT validation flags\n"
        summary += f"8. ✨ `{disease_name}_gpt_validated_pathways.csv` - **ONLY GPT-validated pathways (ranked)**\n\n"
        summary += f"### Visualizations:\n"
        summary += f"9. `imgs/` - PPI network visualizations (*.png)\n"
        
        summary += "\n---\n\n## Interpretation\n\n"
        summary += "- ✨ **GPT-validated pathways**: Predicted by AI and confirmed by enrichment\n"
        summary += "- 📊 **Data-driven pathways**: Discovered through enrichment only\n"
        summary += "- 📚 **Well-known pathways**: High PubMed relevance (extensively studied)\n"
        summary += "- 🔬 **Novel pathways**: Lower PubMed relevance (potential new insights)\n"
        
        with open(summary_file, 'w') as f:
            f.write(summary)
        
        print(f"\n✅ Enhanced summary saved: {summary_file}")
    
    def compare_diseases(self, results_A, results_B, 
                        disease_A_name, disease_B_name,
                        genes_A, genes_B):
        """
        Compare two disease analyses.
        Uses the original analyzer's output format.
        """
        print("\n" + "="*80)
        print("DISEASE COMPARISON")
        print("="*80)
        
        # Extract analysis results
        analysis_A = results_A.get('multi_agent_analysis')
        analysis_B = results_B.get('multi_agent_analysis')
        
        if not analysis_A or not analysis_B:
            print("❌ Cannot compare: Missing analysis results")
            return None
        
        # Get pathways
        pathways_A = analysis_A.get('ranked_pathways')
        pathways_B = analysis_B.get('ranked_pathways')
        
        if pathways_A is None or pathways_B is None:
            print("❌ Cannot compare: Missing pathway data")
            return None
        
        # Extract pathway IDs
        ids_A = set(pathways_A['native'].tolist())
        ids_B = set(pathways_B['native'].tolist())
        
        common = ids_A & ids_B
        A_only = ids_A - ids_B
        B_only = ids_B - ids_A
        
        shared_genes = set(genes_A) & set(genes_B)
        
        print(f"\n{disease_A_name}: {len(ids_A)} pathways")
        print(f"{disease_B_name}: {len(ids_B)} pathways")
        print(f"Common: {len(common)} ({len(common)/max(len(ids_A), 1)*100:.1f}%)")
        
        # Save comparison
        comparison_file = os.path.join(self.results_dir, 'disease_comparison.txt')
        with open(comparison_file, 'w') as f:
            f.write("="*80 + "\n")
            f.write("DISEASE PAIR PATHWAY COMPARISON\n")
            f.write("="*80 + "\n\n")
            f.write(f"{disease_A_name} vs {disease_B_name}\n\n")
            
            # Gene stats
            f.write("GENE STATISTICS:\n")
            f.write("-"*80 + "\n")
            f.write(f"  {disease_A_name}: {len(genes_A)} genes\n")
            f.write(f"  {disease_B_name}: {len(genes_B)} genes\n")
            f.write(f"  Shared: {len(shared_genes)} genes\n\n")
            
            # Pathway stats
            f.write("PATHWAY STATISTICS:\n")
            f.write("-"*80 + "\n")
            f.write(f"  {disease_A_name}: {len(ids_A)} pathways\n")
            f.write(f"  {disease_B_name}: {len(ids_B)} pathways\n")
            f.write(f"  Common: {len(common)} pathways\n")
            f.write(f"  {disease_A_name}-specific: {len(A_only)}\n")
            f.write(f"  {disease_B_name}-specific: {len(B_only)}\n\n")
            
            # Common pathways (HIGHLIGHTING)
            if common:
                f.write("="*80 + "\n")
                f.write("*** TOP COMMON PATHWAYS (SHARED) ***\n")
                f.write("="*80 + "\n")
                f.write("These pathways are enriched in BOTH diseases.\n")
                f.write("-"*80 + "\n\n")
                
                common_df = pathways_A[pathways_A['native'].isin(common)].sort_values('p_value').head(20)
                for i, (_, row) in enumerate(common_df.iterrows(), 1):
                    f.write(f"{i}. {row['name']}\n")
                    f.write(f"   ID: {row['native']}\n")
                    f.write(f"   p-value: {row['p_value']:.2e}\n")
                    f.write(f"   Source: {row['source']}\n")
                    if 'score' in row and pd.notna(row['score']):
                        f.write(f"   PubMed Score: {row['score']:.3f}\n")
                    f.write("\n")
            
            # Summary insights
            f.write("\n" + "="*80 + "\n")
            f.write("SUMMARY INSIGHTS\n")
            f.write("="*80 + "\n\n")
            
            jaccard = len(common) / len(ids_A | ids_B) if len(ids_A | ids_B) > 0 else 0
            f.write(f"Pathway Similarity (Jaccard): {jaccard:.2%}\n")
            
            if jaccard > 0.3:
                f.write("🔹 High pathway overlap\n")
            elif jaccard > 0.1:
                f.write("🔹 Moderate pathway overlap\n")
            else:
                f.write("🔹 Low pathway overlap\n")
        
        print(f"✅ Comparison saved: {comparison_file}")
        
        return {
            'common': common,
            'A_specific': A_only,
            'B_specific': B_only,
            'comparison_file': comparison_file
        }


def main():
    """Main execution."""
    
    # Input paths
    input_dir = "/Users/liyuxin/Documents/zotero/PhD/Research/AI_agent/codes/Genetic_AI_Agent/src/utils/Network_expansion/outputs/disease_pair_expansion"
    output_dir = "/Users/liyuxin/Documents/zotero/PhD/Research/AI_agent/codes/Genetic_AI_Agent/src/utils/Pathway_analysis"
    
    # Disease files
    disease_A_file = os.path.join(input_dir, "D001289_modules.csv")  # ADHD
    disease_B_file = os.path.join(input_dir, "D010300_modules.csv")  # PD
    
    # Check files
    if not os.path.exists(disease_A_file) or not os.path.exists(disease_B_file):
        print(f"❌ Error: Module files not found")
        return
    
    # Load data
    df_A = pd.read_csv(disease_A_file)
    df_B = pd.read_csv(disease_B_file)
    
    genes_A = df_A[df_A['passes_all_filters'] == True]['node'].unique().tolist()
    genes_B = df_B[df_B['passes_all_filters'] == True]['node'].unique().tolist()
    
    disease_A_name = "ADHD_D001289"
    disease_B_name = "ParkinsonsDisease_D010300"
    
    print(f"\n{disease_A_name}: {len(genes_A)} genes")
    print(f"{disease_B_name}: {len(genes_B)} genes")
    
    # Initialize enhanced analyzer
    analyzer = EnhancedMultiAgentAnalyzer(
        output_dir=output_dir,
        model="gpt-5.1"
    )
    
    # Analyze Disease A
    print("\n" + "="*80)
    print("ANALYZING DISEASE A")
    print("="*80)
    results_A = analyzer.analyze_disease_with_gpt_prediction(genes_A, disease_A_name)
    
    # Analyze Disease B
    print("\n" + "="*80)
    print("ANALYZING DISEASE B")
    print("="*80)
    results_B = analyzer.analyze_disease_with_gpt_prediction(genes_B, disease_B_name)
    
    # Compare diseases
    comparison = analyzer.compare_diseases(
        results_A=results_A,
        results_B=results_B,
        disease_A_name=disease_A_name,
        disease_B_name=disease_B_name,
        genes_A=genes_A,
        genes_B=genes_B
    )
    
    # Final summary
    print("\n" + "="*80)
    print("✅ ANALYSIS COMPLETE")
    print("="*80)
    print(f"\n📁 All results saved in: {analyzer.results_dir}")
    print("\n📊 Key files generated:")
    print("\n  GPT Predictions:")
    print("    - *_gpt_prediction.json (AI pathway hypotheses)")
    print("    - *_ENHANCED_SUMMARY.md (comprehensive analysis summary)")
    print("\n  Multi-Agent Analysis:")
    print("    - *_pathways.csv (all ranked pathways with scores)")
    print("    - *_wellknown_pathways.csv (high PubMed relevance)")
    print("    - *_novel_pathways.csv (low PubMed relevance)")
    print("    - *_report.md (scientific report with PPI analysis)")
    print("    - imgs/*.png (PPI network visualizations)")
    print("\n  Enhanced Analysis:")
    print("    - *_annotated_pathways.csv (all pathways with GPT validation flags)")
    print("    - ✨ *_gpt_validated_pathways.csv (ONLY GPT-validated, ranked by PubMed score)")
    print("    - disease_comparison.txt (disease pair comparison)")


if __name__ == "__main__":
    main()
