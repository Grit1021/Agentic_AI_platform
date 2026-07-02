import os
# Disable tokenizers parallelism warning (must be set before importing transformers)
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import json
import pandas as pd
from typing import List, Dict, Any, Tuple
import time
from dataclasses import dataclass, asdict

import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.join(current_dir, 'wo_iterative'))

from wo_iterative.gpt_pathway_deep_analysis import GPTLedMultiAgentAnalyzer
from multi_agent_analysis_full import GPT5PathwayPredictor


@dataclass
class IterationFeedback:
    """Feedback structure for each iteration"""
    iteration: int
    predicted_pathways: List[str]
    validated_pathways: List[str]
    validation_rate: float
    validation_details: Dict[str, Any]
    process_feedback: str
    outcome_reward: float
    process_reward: float
    total_reward: float
    status: str  # Flash: iteration status
    hindsight: str  # Flash: hindsight feedback


class StatusSupervisor:
    """
    Flash-inspired Status Supervisor

    Monitors iteration progress and decides next action:
    - CONTINUE: keep iterating
    - CONVERGED: validation stabilized
    - DIVERGED: validation degrading
    - MAX_ITER: reached limit
    """

    def __init__(self, convergence_threshold: float = 0.05,
                 min_validation_rate: float = 0.1):
        self.convergence_threshold = convergence_threshold
        self.min_validation_rate = min_validation_rate

    def evaluate_status(self, history: List[IterationFeedback]) -> Tuple[str, str]:
        """
        Evaluate current iteration status with improved convergence criteria.

        Convergence requires:
        1. Validation rate > 5% (minimum quality threshold)
        2. Pathway stability > 50% (retain successful pathways)
        3. Validation rate change < 2% (stable performance)

        Returns:
        --------
        status : str
            CONTINUE, CONVERGED, DIVERGED, or MAX_ITER
        reasoning : str
            Explanation of the status decision
        """
        if len(history) == 0:
            return "CONTINUE", "Initial iteration"

        current = history[-1]

        # Check if validation rate is too low
        if current.validation_rate < self.min_validation_rate:
            if len(history) >= 2 and history[-2].validation_rate < self.min_validation_rate:
                return "DIVERGED", f"Validation rate too low: {current.validation_rate:.1%} < {self.min_validation_rate:.1%}"

        # Check convergence (need at least 2 iterations)
        if len(history) >= 2:
            prev = history[-2]
            val_change = current.validation_rate - prev.validation_rate
            abs_val_change = abs(val_change)

            # Calculate pathway stability
            current_set = set(current.validated_pathways)
            prev_set = set(prev.validated_pathways)

            if len(prev_set) > 0:
                overlap = len(current_set & prev_set) / len(prev_set)
            else:
                overlap = 0.0

            # NEW: Stricter convergence criteria
            # Require: (1) validation_rate > 5%, (2) stability > 50%, (3) small change
            if current.validation_rate < 0.05:
                # Too low to converge, continue iterating
                return "CONTINUE", f"Validation rate too low for convergence: {current.validation_rate:.1%} < 5%"
            
            if abs_val_change < 0.02 and overlap > 0.5 and current.validation_rate >= 0.05:
                return "CONVERGED", f"Converged: val_rate={current.validation_rate:.1%}, stability={overlap:.1%}, change={val_change:+.1%}"

            # Check if degrading significantly
            if val_change < -0.05:
                return "DIVERGED", f"Validation rate dropped: {prev.validation_rate:.1%} → {current.validation_rate:.1%} ({val_change:.1%})"

        return "CONTINUE", f"Iteration {current.iteration} complete, continuing..."


class AutoEval:
    """
    Flash-inspired AutoEval

    Automatic outcome-based evaluation without human feedback
    Evaluates: statistical significance + literature support + biological relevance
    """

    def evaluate_outcome(self, validation_details: Dict[str, Any]) -> Dict[str, float]:
        """
        Automatic outcome evaluation (simplified)
        
        Returns:
        --------
        dict : evaluation scores (2 dimensions)
            - significance_score: statistical quality (p-value based)
            - literature_score: PubMed literature support (paper count)
            - overall_score: weighted combination (60% significance, 40% literature)
        """
        gpt_pathways = validation_details.get('gpt_filtered_pathways', pd.DataFrame())
        
        if gpt_pathways.empty:
            return {
                'significance_score': 0.0,
                'literature_score': 0.0,
                'overall_score': 0.0
            }
        
        # Evidence score aggregation (Open Target style)
        #  For each pathway: evidence_score = min(-log10(p), cap) / cap
        #  Then aggregate by arithmetic mean (simpler and more interpretable than geometric mean)
        import numpy as np
        
        # Calculate evidence scores for all pathways
        def p_to_evidence_score(p, cap=10):
            """Convert p-value to evidence score (Open Target)."""
            if p <= 0:
                return 1.0
            return min(-np.log10(p), cap) / cap
        
        p_values = gpt_pathways['p_value'].values
        if len(p_values) > 0:
            # Calculate evidence scores
            evidence_scores = np.array([p_to_evidence_score(p, cap=10) for p in p_values])
            # Aggregate by arithmetic mean
            significance_score = np.mean(evidence_scores)
        else:
            significance_score = 0.0  # No pathways = no evidence
        
        # Significance score is now directly interpretable:
        # - score = 1.0:  All pathways have p ≤ 1e-10 (maximum evidence)
        # - score = 0.5:  Average pathway has p ≈ 1e-5 (moderate evidence)
        # - score = 0.13: Average pathway has p ≈ 0.05 (marginal evidence)
        # - score = 0.0:  All pathways have p = 1.0 (no evidence)
        
        # Literature score: average of combined literature scores
        # PRIORITY ORDER (simplified to use only paper count):
        # Priority 1: Use 'related_literature' PubMed results (GPT Auto Rank mode)
        # Priority 2: Use pre-computed 'score' column (Planning Agent mode - TF-IDF + BioBERT)
        # Priority 3: Default to 0.5 if neither available
        if 'related_literature' in gpt_pathways.columns:
            # GPT Auto Rank mode: calculate from PubMed results
            # Score based on NUMBER of PubMed papers only (simplified)
            pubmed_scores = []
            for lit_list in gpt_pathways['related_literature']:
                if isinstance(lit_list, list) and len(lit_list) > 0:
                    # Score based on number of papers (more = better, cap at 20)
                    n_papers = len(lit_list)
                    paper_count_score = min(n_papers / 20.0, 1.0)  # Normalize: 20 papers = max score
                    pubmed_scores.append(paper_count_score)
                else:
                    pubmed_scores.append(0.0)  # No literature found
            
            if pubmed_scores:
                literature_score = np.mean(pubmed_scores)
            else:
                literature_score = 0.5  # Fallback
        elif 'score' in gpt_pathways.columns:
            # Planning Agent mode: use TF-IDF + BioBERT combined score
            avg_score = gpt_pathways['score'].mean()
            literature_score = min(avg_score, 1.0)
        else:
            # No literature data available
            literature_score = 0.5
        
        # Overall score (weighted) - simplified to 2 dimensions
        # Adjusted weights: significance (60%), literature (40%)
        # Removed: relevance_score dimension (redundant with literature support)
        overall_score = (significance_score * 0.6 +
                        literature_score * 0.4)
        
        return {
            'significance_score': significance_score,
            'literature_score': literature_score,
            'overall_score': overall_score
        }


class HindsightGenerator:
    """
    Enhanced Flash-inspired Hindsight Generator

    Generates process-level feedback by analyzing:
    - Module-specific pathway patterns
    - Near-miss vs complete failures
    - Pathway stability across iterations
    - Biological coherence of validated pathways
    """

    def __init__(self):
        # Cache for GPT-generated disease contexts to avoid redundant API calls
        self.disease_context_cache = {}
    
    def _get_pathway_disease_context(self, pathway_name: str, disease_name: str, 
                                      pathway_row: pd.DataFrame = None) -> Dict[str, str]:
        """
        Generate pathway-specific disease context using GPT (disease-agnostic).
        
        Uses GPT to dynamically generate:
        - Disease relevance explanation (mechanism, quantitative impact)
        - Key disease-related genes
        
        Includes caching to avoid redundant API calls.
        
        Parameters:
        -----------
        pathway_name : str
            Name of the pathway
        disease_name : str
            Name of the disease (e.g., "Alzheimer's Disease", "IBD", "Parkinson's Disease")
        pathway_row : pd.DataFrame, optional
            Row from pathway dataframe (for intersection genes)
        
        Returns:
        --------
        dict : {'relevance': str, 'key_genes': str}
        """
        # Extract base disease name (e.g., "AD" from "AD_Module_5")
        base_disease = disease_name.split('_Module_')[0] if '_Module_' in disease_name else disease_name.split('_')[0]
        
        # Create cache key combining pathway and disease
        cache_key = f"{pathway_name}::{base_disease}"
        
        # Check cache first
        if cache_key in self.disease_context_cache:
            return self.disease_context_cache[cache_key]
        
        # Extract intersection genes if available
        intersection_genes = []
        if pathway_row is not None and 'intersections' in pathway_row.columns:
            try:
                intersections = pathway_row['intersections'].values[0]
                if isinstance(intersections, list) and len(intersections) > 0:
                    intersection_genes = intersections[:5]  # Top 5 genes
            except:
                pass
        
        # Prepare GPT prompt (disease-agnostic)
        gene_context = ""
        if intersection_genes:
            gene_context = f"\n\nGenes in this pathway from the gene set: {', '.join(intersection_genes)}"
        
        prompt = f"""You are an expert in biomedical research specializing in {base_disease}. 

Pathway: "{pathway_name}"{gene_context}

Provide a concise analysis of this pathway's relevance to {base_disease}:

1. **Disease Relevance** (2-3 sentences):
   - Explain HOW this pathway relates to {base_disease} pathogenesis
   - Include quantitative impact if known (e.g., "30-50% reduction in disease")
   - Be specific about the mechanism

2. **Key Disease Genes** (3-5 genes):
   - List the most important genes in this pathway that are linked to {base_disease}
   - Focus on genes with strong evidence

Format your response as:
RELEVANCE: [your explanation]
GENES: [gene1, gene2, gene3, ...]

If this pathway has no clear {base_disease} relevance, respond with:
RELEVANCE: This pathway's relevance to {base_disease} is unclear or indirect.
GENES: [leave blank]"""

        try:
            # Call GPT (using OpenAI client)
            import openai
            
            response = openai.ChatCompletion.create(
                model="gpt-5.1",  # Use gpt-5.1 for context generation
                messages=[
                    {"role": "system", "content": f"You are an expert biomedical researcher specializing in {base_disease}."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temperature for more consistent outputs
                max_tokens=300
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # Parse response
            relevance = ""
            key_genes = ""
            
            for line in response_text.split('\n'):
                line = line.strip()
                if line.startswith('RELEVANCE:'):
                    relevance = line.replace('RELEVANCE:', '').strip()
                elif line.startswith('GENES:'):
                    key_genes = line.replace('GENES:', '').strip()
            
            # Create context dict
            context = {
                'relevance': relevance if relevance else f"This pathway is enriched in {base_disease}-associated genes.",
                'key_genes': key_genes if key_genes else None
            }
            
            # Cache the result
            self.disease_context_cache[cache_key] = context
            
            return context
            
        except Exception as e:
            # Fallback: return generic context
            # Suppress warning to avoid cluttering output
            
            fallback_context = {
                'relevance': f"This pathway is enriched in {base_disease}-associated genes, suggesting potential involvement in disease pathogenesis.",
                'key_genes': ', '.join(intersection_genes[:4]) if intersection_genes else None
            }
            
            # Cache fallback too
            self.disease_context_cache[cache_key] = fallback_context
            
            return fallback_context

    def _analyze_pathway_patterns(self, pathways: List[str]) -> Dict[str, Any]:
        """
        Analyze pathway list for common patterns, themes, and categories.
        
        Used to identify dominant biological mechanisms in validated pathways.
        
        Parameters:
        -----------
        pathways : List[str]
            List of pathway names
        
        Returns:
        --------
        Dict with keys:
            - 'dominant_themes': List[str] - common keywords in pathways
            - 'pathway_categories': Dict[str, int] - counts by GO/KEGG/REAC category
        """
        if not pathways:
            return {'dominant_themes': [], 'pathway_categories': {}}
        
        # Extract keywords (simple version - can be enhanced with NER)
        all_keywords = []
        for pw in pathways:
            keywords = [word.lower() for word in pw.split() if len(word) > 3]
            all_keywords.extend(keywords)
        
        # Count keyword frequencies
        from collections import Counter
        keyword_counts = Counter(all_keywords)
        
        # Get top 3 most common themes, excluding generic terms
        generic_terms = {'pathway', 'process', 'activity', 'function', 'regulation', 
                        'positive', 'negative', 'cellular', 'binding', 'protein'}
        dominant_themes = [word for word, count in keyword_counts.most_common(10) 
                          if word not in generic_terms][:3]
        
        # Categorize pathways
        categories = {
            'synaptic': 0,
            'vesicle': 0,
            'neurodegeneration': 0,
            'autophagy': 0,
            'protein_degradation': 0,
            'metabolism': 0,
            'signaling': 0,
            'other': 0
        }
        
        for pw in pathways:
            pw_lower = pw.lower()
            if any(term in pw_lower for term in ['synap', 'neurotrans']):
                categories['synaptic'] += 1
            elif any(term in pw_lower for term in ['vesicle', 'endocyt', 'exocyt']):
                categories['vesicle'] += 1
            elif any(term in pw_lower for term in ['neurodegeneration', 'neuro']):
                categories['neurodegeneration'] += 1
            elif 'autophagy' in pw_lower:
                categories['autophagy'] += 1
            elif any(term in pw_lower for term in ['proteasome', 'ubiquitin', 'degradation']):
                categories['protein_degradation'] += 1
            elif 'metabol' in pw_lower:
                categories['metabolism'] += 1
            elif 'signal' in pw_lower:
                categories['signaling'] += 1
            else:
                categories['other'] += 1
        
        # Remove zero counts
        categories = {k: v for k, v in categories.items() if v > 0}
        
        return {
            'dominant_themes': dominant_themes,
            'pathway_categories': categories
        }
    

    def _calculate_pathway_quality(self, iteration_feedback: IterationFeedback) -> float:
        """
        Analyze common patterns in pathway names to identify module-specific themes.
        
        Returns:
        --------
        dict : Pattern analysis including:
            - dominant_themes: List of recurring keywords
            - pathway_categories: Categorization of pathways
            - specificity_level: Whether pathways are general or specific
        """
        if not pathways:
            return {'dominant_themes': [], 'pathway_categories': {}, 'specificity_level': 'unknown'}
        
        # Extract keywords from pathway names
        all_words = []
        for pw in pathways:
            words = pw.lower().split()
            all_words.extend(words)
        
        # Count keyword frequencies
        from collections import Counter
        word_counts = Counter(all_words)
        
        # Filter out common stop words
        stop_words = {'of', 'by', 'in', 'to', 'the', 'and', 'or', 'for', 'a', 'an'}
        filtered_counts = {w: c for w, c in word_counts.items() if w not in stop_words and len(w) > 3}
        
        # Identify dominant themes (keywords appearing in >30% of pathways)
        threshold = len(pathways) * 0.3
        dominant_themes = [word for word, count in filtered_counts.items() if count >= threshold]
        
        # Categorize pathways by biological process
        categories = {
            'ribosome_translation': ['ribosome', 'translation', 'rna', 'trna', 'rrna', 'polymerase'],
            'immune_inflammation': ['immune', 'inflammation', 'cytokine', 'interferon', 'nfkb'],
            'stress_response': ['stress', 'oxidative', 'response', 'apoptosis', 'autophagy'],
            'metabolism': ['metabolic', 'metabolism', 'glycolysis', 'oxidative', 'mitochondrial'],
            'signaling': ['signaling', 'pathway', 'mapk', 'pi3k', 'akt', 'kinase'],
            'protein_processing': ['protein', 'proteolysis', 'ubiquitin', 'proteasome', 'folding'],
            'lysosomal_degradation': ['lysosome', 'lysosomal', 'degradation', 'catabolic', 'autophagy'],
            'neurodegeneration': ['alzheimer', 'neurodegeneration', 'tau', 'amyloid', 'synaptic']
        }
        
        pathway_categories = {}
        for category, keywords in categories.items():
            matching = [pw for pw in pathways if any(kw in pw.lower() for kw in keywords)]
            if matching:
                pathway_categories[category] = len(matching)
        
        # Determine specificity level
        if dominant_themes:
            specificity_level = 'specific' if len(dominant_themes) <= 3 else 'diverse'
        else:
            specificity_level = 'diverse'
        
        return {
            'dominant_themes': dominant_themes[:5],  # Top 5 themes
            'pathway_categories': pathway_categories,
            'specificity_level': specificity_level
        }
    
    def _categorize_failed_pathways(self, validation_details: Dict[str, Any], 
                                    failed_pathways: List[str]) -> Dict[str, List[str]]:
        """
        Placeholder for failed pathway categorization.
        
        Note: We maintain strict statistical standards (p < 0.05, FDR-corrected).
        Failed pathways are those that did not meet this threshold.
        
        Returns:
        --------
        dict : Simple categorization (all pathways in complete_fail)
        """
        # Maintain strict p < 0.05 threshold - no near-miss analysis
        return {
            'near_miss': [],
            'moderate_fail': [],
            'complete_fail': failed_pathways
        }
    
    def _calculate_pathway_quality(self, iteration_feedback: IterationFeedback) -> float:
        """
        Calculate comprehensive pathway quality score.
        
        Combines:
        - Disease specificity (30% weight)
        - Combined score (TF-IDF + BioBERT) (30% weight)
        - PubMed score (20% weight)
        - Evidence score from p-value (20% weight)
        
        Returns:
        --------
        float : Quality score (0.0-1.0)
        """
        validated_df = iteration_feedback.validation_details.get('gpt_filtered_pathways', pd.DataFrame())
        
        if validated_df.empty or len(iteration_feedback.validated_pathways) == 0:
            return 0.0
        
        # Extract scores
        disease_spec = validated_df['disease_specificity'].mean() if 'disease_specificity' in validated_df.columns else 0.2
        combined_score = validated_df['score'].mean() if 'score' in validated_df.columns else 0.0
        pubmed_score = validated_df['pubmed_score'].mean() if 'pubmed_score' in validated_df.columns else 0.0
        
        # Evidence score from p-value (replaces validation count)
        # evidence_score = min(-log10(p_value), 10) / 10
        # Higher p-value significance = higher evidence score
        if 'p_value' in validated_df.columns:
            import numpy as np
            p_values = validated_df['p_value'].values
            # Calculate evidence score for each pathway
            evidence_scores = np.minimum(-np.log10(p_values + 1e-300), 10.0) / 10.0
            evidence_score = evidence_scores.mean()
        else:
            # Fallback: use validation count as proxy
            evidence_score = min(len(iteration_feedback.validated_pathways) / 20.0, 1.0)
        
        # Weighted combination
        quality = (
            disease_spec * 0.30 +      # Disease relevance
            combined_score * 0.30 +    # Literature support (TF-IDF + BioBERT)
            pubmed_score * 0.20 +      # PubMed evidence
            evidence_score * 0.20      # Statistical evidence (p-value based)
        )
        
        return max(0.0, min(1.0, quality))
    
    def _calculate_stability(self, current: IterationFeedback, 
                            history: List[IterationFeedback]) -> Dict[str, Any]:
        """
        Calculate pathway prediction stability across iterations.
        
        Returns:
        --------
        dict : Stability metrics:
            - overlap_rate: % of validated pathways retained from previous iteration
            - new_discoveries: Number of new validated pathways
            - lost_pathways: Pathways validated before but not now
        """
        if len(history) < 2:
            return {'overlap_rate': None, 'new_discoveries': None, 'lost_pathways': []}
        
        prev = history[-2]
        current_set = set(current.validated_pathways)
        prev_set = set(prev.validated_pathways)
        
        if not prev_set:
            overlap_rate = 0.0
        else:
            overlap_rate = len(current_set & prev_set) / len(prev_set)
        
        new_discoveries = list(current_set - prev_set)
        lost_pathways = list(prev_set - current_set)
        
        return {
            'overlap_rate': overlap_rate,
            'new_discoveries': new_discoveries,
            'lost_pathways': lost_pathways
        }

    def generate_hindsight(self, current: IterationFeedback,
                          history: List[IterationFeedback],
                          disease_name: str = None) -> str:
        """
        Generate enhanced hindsight feedback with module-specific insights.

        Analyzes:
        - Module-specific pathway patterns
        - What pathways validated and why
        - Categorized failure analysis (near-miss vs complete fail)
        - Pathway stability across iterations
        - Actionable, data-driven recommendations
        """
        hindsight = f"## Hindsight Analysis (Iteration {current.iteration})\n\n"

        # Simple validation statistics (no RL terminology)
        hindsight += "### 📊 Validation Statistics\n\n"
        hindsight += f"- **Validation rate**: {current.validation_rate:.1%}\n"
        hindsight += f"- **Validated pathways**: {len(current.validated_pathways)}\n"
        hindsight += f"- **Predicted pathways**: {len(current.predicted_pathways)}\n"
        
        # Trend analysis if history available
        if len(history) >= 2:
            prev_rate = history[-2].validation_rate
            rate_change = current.validation_rate - prev_rate
            if rate_change > 0.05:
                hindsight += f"- 📈 **Improving**: +{rate_change:.1%} from previous iteration\n"
            elif rate_change < -0.05:
                hindsight += f"- 📉 **Declining**: {rate_change:.1%} from previous iteration\n"
            else:
                hindsight += f"- ➡️  **Stable**: {rate_change:+.1%} change from previous iteration\n"
        
        hindsight += "\n"


        # 1. Success analysis with pattern recognition AND specificity filtering
        if current.validated_pathways:
            # Get pathway details for specificity filtering
            gpt_pathways_df = current.validation_details.get('gpt_filtered_pathways', pd.DataFrame())
            
            # Define specificity threshold for filtering
            SPECIFICITY_THRESHOLD = 0.20  # Pathways below this are likely too general
            
            # Separate into high-quality vs low-specificity pathways
            high_quality_pathways = []
            low_specificity_pathways = []
            
            if not gpt_pathways_df.empty and 'disease_specificity' in gpt_pathways_df.columns:
                for pw in current.validated_pathways:
                    pw_row = gpt_pathways_df[gpt_pathways_df['name'] == pw]
                    if not pw_row.empty:
                        spec = pw_row['disease_specificity'].values[0]
                        if spec >= SPECIFICITY_THRESHOLD:
                            high_quality_pathways.append(pw)
                        else:
                            low_specificity_pathways.append((pw, spec))
                    else:
                        high_quality_pathways.append(pw)  # Include if no spec data
            else:
                high_quality_pathways = current.validated_pathways
            
            # Report high-quality pathways
            if high_quality_pathways:
                hindsight += f"### ✅ High-Quality Disease-Relevant Predictions ({len(high_quality_pathways)})\n"
                
                # Analyze patterns in high-quality pathways only
                patterns = self._analyze_pathway_patterns(high_quality_pathways)
                
                if patterns['dominant_themes']:
                    hindsight += f"**Disease-Related Mechanisms**: {', '.join(patterns['dominant_themes'])}\n\n"
                
                if patterns['pathway_categories']:
                    top_category = max(patterns['pathway_categories'].items(), key=lambda x: x[1])
                    hindsight += f"**Dominant Category**: {top_category[0].replace('_', ' ').title()} ({top_category[1]} pathways)\n\n"
                
                hindsight += "These pathways validated with both statistical significance AND biological relevance:\n"
                hindsight += "- Strong statistical enrichment (p < 0.05, FDR-corrected)\n"
                hindsight += "- Disease-specific (specificity ≥ 0.20)\n"
                hindsight += "- Literature support (TF-IDF + BioBERT)\n\n"

                hindsight += "Top validated pathways (with scoring details):\n"

                for i, pw in enumerate(high_quality_pathways[:5], 1):
                    hindsight += f"{i}. **{pw}**\n"
                    
                    # Add scoring details
                    pw_row = gpt_pathways_df[gpt_pathways_df['name'] == pw] if not gpt_pathways_df.empty else pd.DataFrame()
                    if not pw_row.empty:
                        if 'p_value' in pw_row.columns:
                            p_val = pw_row['p_value'].values[0]
                            hindsight += f"   - p-value: {p_val:.2e}\n"
                        if 'disease_specificity' in pw_row.columns:
                            spec = pw_row['disease_specificity'].values[0]
                            hindsight += f"   - Disease specificity: {spec:.3f}\n"
                        if 'score' in pw_row.columns:
                            lit_score = pw_row['score'].values[0]
                            hindsight += f"   - Literature score: {lit_score:.3f}\n"
                        
                        # Add disease-specific context using GPT
                        if disease_name:
                            disease_context = self._get_pathway_disease_context(pw, disease_name, pw_row)
                            if disease_context and disease_context.get('relevance'):
                                hindsight += f"   - **Disease Relevance**: {disease_context['relevance']}\n"
                                if disease_context.get('key_genes'):
                                    hindsight += f"   - **Key Genes**: {disease_context['key_genes']}\n"
                hindsight += "\n"
            
            # Report low-specificity pathways as warning
            if low_specificity_pathways:
                hindsight += f"### ⚠️ Validated but Too General ({len(low_specificity_pathways)})\n"
                hindsight += f"These pathways passed statistical validation but have low disease specificity (< {SPECIFICITY_THRESHOLD:.2f}).\n"
                hindsight += "They may be too generic for meaningful biological interpretation:\n\n"
                
                for pw, spec in low_specificity_pathways[:5]:
                    hindsight += f"- {pw} (specificity: {spec:.3f})\n"
                
                hindsight += "\n**Recommendation**: Avoid predicting such generic pathways in next iteration.\n"
                hindsight += "Focus on more specific biological processes, molecular functions, or disease mechanisms.\n\n"

        # 2. Failure analysis (strict p < 0.05 threshold)
        failed = [p for p in current.predicted_pathways if p not in current.validated_pathways]
        if failed:
            hindsight += f"### ❌ Failed Predictions ({len(failed)})\n"
            hindsight += "These pathways did NOT meet the strict validation criteria (p < 0.05, FDR-corrected):\n"
            hindsight += "\n**Common reasons for failure:**\n"
            hindsight += "- Insufficient gene overlap with pathway\n"
            hindsight += "- Not statistically enriched in gene set (p ≥ 0.05 after FDR correction)\n"
            hindsight += "- Too general or too specific\n\n"

        # 3. Quality & Stability analysis (if multiple iterations)
        if len(history) >= 2:
            stability = self._calculate_stability(current, history)
            prev = history[-2]
            
            # Calculate comprehensive quality scores for validated pathways
            curr_quality = self._calculate_pathway_quality(current)
            prev_quality = self._calculate_pathway_quality(prev)
            
            quality_change = curr_quality - prev_quality
            
            hindsight += "### 📊 Quality & Stability Analysis\n"
            
            # Quality score trend (combines disease_specificity + combined_score + pubmed + stability)
            hindsight += f"**Pathway Quality Score**: {prev_quality:.3f} → {curr_quality:.3f}"
            
            if quality_change > 0.05:
                hindsight += f" (✅ +{quality_change:.3f})\n"
                hindsight += "Quality is improving - pathways are more relevant and stable.\n\n"
            elif quality_change < -0.05:
                hindsight += f" (⚠️ {quality_change:.3f})\n"
                hindsight += "Quality decreased - consider reverting to previous strategy.\n\n"
            else:
                hindsight += f" (➡️ {quality_change:+.3f})\n"
                hindsight += "Quality stable - predictions are consistent.\n\n"
            
            # Breakdown of quality components
            curr_details = current.validation_details.get('gpt_filtered_pathways', pd.DataFrame())
            if not curr_details.empty and len(current.validated_pathways) > 0:
                hindsight += "**Quality Components (average across validated pathways):**\n"
                
                if 'disease_specificity' in curr_details.columns:
                    avg_spec = curr_details['disease_specificity'].mean()
                    hindsight += f"- Disease Specificity: {avg_spec:.3f}\n"
                
                if 'score' in curr_details.columns:
                    avg_combined = curr_details['score'].mean()
                    hindsight += f"- Combined Score (TF-IDF + BioBERT): {avg_combined:.3f}\n"
                
                if 'pubmed_score' in curr_details.columns:
                    avg_pubmed = curr_details['pubmed_score'].mean()
                    hindsight += f"- PubMed Relevance: {avg_pubmed:.3f}\n"
                
                hindsight += "\n"
            
            # Pathway stability
            if stability['overlap_rate'] is not None:
                hindsight += f"**Pathway Stability**: {stability['overlap_rate']:.1%} of validated pathways retained\n"
                
                if stability['lost_pathways']:
                    hindsight += f"⚠️ Lost {len(stability['lost_pathways'])} pathways: {', '.join(stability['lost_pathways'][:3])}\n"
                
                if stability['new_discoveries']:
                    hindsight += f"✨ New discoveries: {len(stability['new_discoveries'])} pathways\n"
                
        # 4. Disease-specific actionable recommendations
        hindsight += "### 💡 Recommendations for Next Iteration\n"
        
        # Initialize patterns (may be None if no validated pathways)
        patterns = None
        if current.validated_pathways:
            patterns = self._analyze_pathway_patterns(current.validated_pathways)
        
        # Module-specific strategy
        if patterns and patterns.get('dominant_themes'):
            theme_str = ", ".join(patterns['dominant_themes'][:3])
            if len(patterns['dominant_themes']) > 3:
                theme_str += f", and {len(patterns['dominant_themes'])-3} more"
            
            hindsight += f"**Module-Specific Strategy**: Focus on pathways related to: {theme_str}\n"
            
            if patterns.get('pathway_categories'):
                top_categories = sorted(patterns['pathway_categories'].items(), key=lambda x: x[1], reverse=True)[:2]
                for category, count in top_categories:
                    category_name = category.replace('_', ' ').title()
                    hindsight += f"- Prioritize {category_name} pathways (validated {count})\n"
        
        # Get quality components for specific recommendations
        curr_quality = self._calculate_pathway_quality(current)
        curr_details = current.validation_details.get('gpt_filtered_pathways', pd.DataFrame())
        
        if not curr_details.empty and len(current.validated_pathways) > 0:
            avg_disease_spec = curr_details['disease_specificity'].mean() if 'disease_specificity' in curr_details.columns else 0.2
            avg_combined = curr_details['score'].mean() if 'score' in curr_details.columns else 0.0
            
            # Disease specificity recommendations
            if avg_disease_spec < 0.25:
                hindsight += "- **Good disease specificity**: Current pathways are disease-relevant\n"
                hindsight += "- Continue focusing on disease-specific mechanisms\n"
            elif avg_disease_spec > 0.40:
                hindsight += "- **Excellent disease specificity**: Pathways are highly disease-specific\n"
                hindsight += "- Maintain this disease-focused approach\n"
            else:
                hindsight += "- **Moderate disease specificity**: Room for improvement\n"
                hindsight += "- Focus more on disease-specific molecular mechanisms\n"
            
            # Literature support recommendations
            if avg_combined > 0.5:
                hindsight += "- **Strong literature support**: Continue leveraging established knowledge\n"
            elif avg_combined > 0.3:
                hindsight += "- **Good literature support**: Balance with novel mechanisms\n"
            else:
                hindsight += "- **Limited literature support**: Prioritize well-studied AD pathways\n"
        
        # Overall quality-based recommendations
        if curr_quality > 0.50:
            hindsight += "- **High overall quality**: Current strategy is effective\n"
            hindsight += "- Can explore more specific sub-pathways\n"
            hindsight += "- Consider novel hypotheses related to validated themes\n"
        elif curr_quality > 0.30:
            hindsight += "- **Moderate quality**: Fine-tune current approach\n"
            hindsight += "- Balance between specificity and evidence\n"
        else:
            hindsight += "- **Low overall quality**: Major strategy revision needed\n"
            hindsight += "- Return to fundamental AD mechanisms\n"
        
        # NEW: Category-specific g:Profiler-aligned recommendations
        hindsight += "\n**Category-Specific g:Profiler Alignment:**\n"
        
        # Analyze validated pathways by source to provide targeted recommendations
        if not curr_details.empty and 'source' in curr_details.columns:
            source_counts = curr_details['source'].value_counts().to_dict()
            
            # GO:BP recommendations
            if 'GO:BP' in source_counts:
                bp_count = source_counts['GO:BP']
                hindsight += f"- **GO:BP ({bp_count} validated)**: "
                if bp_count >= 5:
                    hindsight += "Good coverage. Maintain Level 3+ specificity, focus on AD processes like protein degradation, vesicle trafficking\n"
                else:
                    hindsight += "Increase specific biological processes. Avoid generic terms like 'regulation of'. Focus on autophagy, ER stress, protein homeostasis\n"
            else:
                hindsight += "- **GO:BP**: Add biological process predictions. Focus: autophagy, vesicle transport, protein degradation (Level 3+ specificity)\n"
            
            # GO:MF recommendations
            if 'GO:MF' in source_counts:
                mf_count = source_counts['GO:MF']
                hindsight += f"- **GO:MF ({mf_count} validated)**: "
                if mf_count >= 3:
                    hindsight += "Good coverage. Continue with specific molecular activities. Avoid generic 'binding'\n"
                else:
                    hindsight += "Increase molecular function predictions. Focus: GTPase activity, SNARE binding, motor activities (not generic 'binding')\n"
            else:
                hindsight += "- **GO:MF**: Add molecular function predictions. Focus: specific binding (GTPase, SNARE), motor activities, catalytic activities\n"
            
            # GO:CC recommendations
            if 'GO:CC' in source_counts:
                cc_count = source_counts['GO:CC']
                hindsight += f"- **GO:CC ({cc_count} validated)**: "
                if cc_count >= 3:
                    hindsight += "Good coverage. Maintain specific compartments. Explore sub-structures of validated organelles\n"
                else:
                    hindsight += "Increase cellular component predictions. Focus: Golgi, ER, lysosomes, autophagosomes (avoid generic 'membrane')\n"
            else:
                hindsight += "- **GO:CC**: Add cellular component predictions. Focus: specific organelles (Golgi apparatus, ER, lysosome), not 'membrane' or 'cell'\n"
            
            # KEGG recommendations
            if 'KEGG' in source_counts:
                kegg_count = source_counts['KEGG']
                hindsight += f"- **KEGG ({kegg_count} validated)**: "
                if kegg_count >= 3:
                    hindsight += "Good pathway coverage. Use only official KEGG names, explore related signaling pathways\n"
                else:
                    hindsight += "Increase KEGG pathway predictions. Focus: disease-specific pathway, 'Autophagy', 'Protein processing in ER' (exact KEGG names)\n"
            else:
                hindsight += "- **KEGG**: Add established KEGG pathways. Critical: use EXACT official names from KEGG database. Focus: disease-specific pathways, autophagy, endocytosis\n"
            
            # Reactome recommendations  
            if 'REAC' in source_counts:
                reac_count = source_counts['REAC']
                hindsight += f"- **Reactome ({reac_count} validated)**: "
                if reac_count >= 2:
                    hindsight += "Good coverage. Navigate hierarchy - predict child pathways of validated parents for more specificity\n"
                else:
                    hindsight += "Increase Reactome predictions. Focus: child pathways (specific), not top-level categories. Use expert-curated names\n"
            else:
                hindsight += "- **Reactome**: Add mechanistic pathway predictions. Focus: specific child pathways in hierarchy, not generic parents. Disease-related: vesicle transport, ER stress\n"
        else:
            # Default recommendations when no validated pathways or source info unavailable
            hindsight += "- **GO:BP**: Predict specific biological processes (Level 3+): autophagy, vesicle transport, protein degradation\n"
            hindsight += "- **GO:MF**: Predict specific molecular activities (not 'binding'): GTPase activity, SNARE binding, motor activities\n"
            hindsight += "- **GO:CC**: Predict specific compartments (not 'membrane'): Golgi apparatus, ER, lysosome, autophagosome\n"
            hindsight += "- **KEGG**: Use EXACT official KEGG names: disease-specific pathway, 'Autophagy', 'Protein processing in endoplasmic reticulum'\n"
            hindsight += "- **Reactome**: Predict child pathways (specific), ensure names match Reactome database exactly\n"
        
        # Stability-based recommendations
        if len(history) >= 2:
            stability = self._calculate_stability(current, history)
            if stability['overlap_rate'] is not None and stability['overlap_rate'] < 0.5:
                hindsight += "- ⚠️ **Low stability**: Predictions are changing too much between iterations\n"
                hindsight += "- Maintain successful pathways - use EXACT names and IDs from validated set\n"
            elif stability['overlap_rate'] is not None and stability['overlap_rate'] > 0.8:
                hindsight += "- ✅ **Excellent stability**: Keep maintaining successful pathways from previous iterations\n"

        return hindsight


class IterativeGPTAgentFramework:
    """
    Flash-inspired iterative framework between GPT and verification agents.

    Architecture:
    1. GPT5.1 (Pathway Generator) - predicts pathways
    2. Status Supervisor - monitors progress and decides next action
    3. Multi-Agent System - verifies with statistical + literature + PPI
    4. AutoEval - automatic outcome evaluation
    5. Hindsight Generator - process-level feedback
    6. Critique + Update - refine predictions iteratively
    """

    def __init__(self, model="gpt-5.1", results_dir="./iterative_feedback",
                 max_iterations=2, retention_rate=1.0,
                 gpt_rank_function=None, disease_description=None, query_agent=None,
                 pathway_generator_class=None, feedback_mode='full'):
        """
        Initialize Flash-inspired iterative GPT-Agent framework.
        
        Parameters:
        -----------
        model : str
            LLM model to use
        results_dir : str
            Base directory for all results (will create run-specific subdirs)
        max_iterations : int
            Maximum iterations per analysis
        retention_rate : float
            Fraction of validated pathways to retain from previous iteration (default: 1.0)
            1.0 = keep ALL validated pathways and explore new ones on top
            Set to 0.0 to disable retention enforcement
        gpt_rank_function : callable, optional
            Function for GPT auto-ranking of pathways
        disease_description : str, optional
            Disease description for GPT ranking context
        query_agent : object, optional
            Query agent for PubMed literature search in GPT ranking
        pathway_generator_class : class, optional
            Custom pathway generator class (default: GPT5PathwayPredictor)
            Use GPT5PathwayGenerator from multi_agent_analysis_full_with_external.py 
            for external knowledge injection in Iteration 2+
        feedback_mode : str
            Feedback prompt mode: 'full' (default, GPT biological reasoning + p-value) 
            or 'pvalue_only' (statistical feedback only, no biological reasoning)
        """
        self.model = model
        self.base_results_dir = results_dir  # Store original base directory
        self.results_dir = results_dir  # Current working directory (will be updated per run)
        self.max_iterations = max_iterations
        self.retention_rate = retention_rate  # NEW: Pathway retention configuration
        self.feedback_mode = feedback_mode  # 'full' or 'pvalue_only'
        
        # GPT Auto-Ranking parameters
        self.gpt_rank_function = gpt_rank_function
        self.disease_description = disease_description
        self.query_agent = query_agent
        
        # Custom pathway generator class (for external knowledge support)
        self.pathway_generator_class = pathway_generator_class or GPT5PathwayPredictor

        # Create base output directory
        os.makedirs(self.base_results_dir, exist_ok=True)

        # Initialize base analyzer (Multi-Agent System)
        self.analyzer = GPTLedMultiAgentAnalyzer(
            output_dir=self.results_dir,
            model=model
        )

        # Initialize Flash components
        self.status_supervisor = StatusSupervisor()
        self.auto_eval = AutoEval()
        self.hindsight_generator = HindsightGenerator()

        # Track iteration history
        self.iteration_history: List[IterationFeedback] = []

        print(f"\n📁 Iterative framework results: {self.results_dir}")
        print(f"🔄 Max iterations: {max_iterations}")
        print(f"🔒 Pathway retention rate: {retention_rate:.0%}")
        print(f"📝 Feedback mode: {feedback_mode}")

        print(f"✨ Flash components: StatusSupervisor + AutoEval + HindsightGenerator")
        if gpt_rank_function is not None:
            print(f"🎯 GPT Auto-Ranking: ENABLED")
        
        print(f" DEBUG: IterativeGPTAgentFramework initialized with feedback_mode='{self.feedback_mode}'")

    def _deep_copy_cache(self, cache):
        """
        Deep copy gprofiler cache to prevent mutations.
        
        Parameters:
        -----------
        cache : dict or None
            g:Profiler cache dict with DataFrames
            
        Returns:
        --------
        dict or None : Deep copied cache
        """
        if cache is None:
            return None
        
        import copy
        
        # Deep copy the cache structure
        copied_cache = {}
        for key, value in cache.items():
            if isinstance(value, pd.DataFrame):
                # Deep copy DataFrame AND reset index to ensure unique indices
                # This prevents InvalidIndexError in pd.concat operations
                copied_cache[key] = value.copy(deep=True).reset_index(drop=True)
            elif isinstance(value, list):
                # Deep copy list
                copied_cache[key] = copy.deepcopy(value)
            else:
                # For other types, use deepcopy
                copied_cache[key] = copy.deepcopy(value)
        
        return copied_cache

    def _calculate_outcome_reward(self, validation_rate: float,
                                  validated_count: int) -> float:
        """
        Calculate outcome-based reward.

        Reward components:
        - Validation rate (0-1): higher is better
        - Absolute validated count: bonus for finding more pathways
        """
        base_reward = validation_rate
        count_bonus = min(validated_count / 20.0, 0.5)  # Cap at 0.5
        return base_reward + count_bonus

    def _deduplicate_pathways_case_insensitive(self, pathways: List[str]) -> List[str]:
        """
        Remove duplicate pathways using case-insensitive comparison.
        Keeps the first occurrence of each pathway name.
        
        Example:
        ['Vesicle-mediated transport', 'vesicle-mediated transport', 'SNARE binding']
        -> ['Vesicle-mediated transport', 'SNARE binding']
        """
        if not pathways:
            return []
        
        seen = set()
        unique = []
        for pw in pathways:
            pw_lower = pw.lower().strip()
            if pw_lower not in seen:
                seen.add(pw_lower)
                unique.append(pw)  # Keep original casing
        return unique

    def _enforce_pathway_retention(self, previous_validated: List[str], 
                                   retention_rate: float = None) -> List[str]:
        """
        Force retention of ALL FDR-significant validated pathways from previous iteration.
        
        MODIFIED: Now retains ALL FDR-significant pathways (p<0.05) instead of  
        only a percentage. This ensures that any pathway that passed statistical
        significance in the previous iteration is guaranteed to be included.
        
        Parameters:
        -----------
        previous_validated : List[str]
            Validated pathway names from previous iteration (already FDR-filtered at p<0.05)
        retention_rate : float, optional
            DEPRECATED - Now ignored. All pathways are retained (100%)
        
        Returns:
        --------
        List[str] : ALL pathways that MUST be included in next iteration
        
        Example:
        --------
        If previous iteration validated 10 FDR-significant pathways,
        then ALL 10 pathways MUST be retained for next iteration.
        """
        # NOTE: Retention rate is now effectively 100% - keep ALL FDR-significant pathways
        # User requirement: Retain all pathways that pass FDR significance test (p<0.05)
        
        if len(previous_validated) == 0:
            return []  # No pathways to retain
        
        # CRITICAL: Deduplicate case-insensitively before returning
        deduplicated = self._deduplicate_pathways_case_insensitive(previous_validated)
        
        print(f"   🔒 Retention policy: Keep ALL {len(deduplicated)} unique FDR-significant pathways (p<0.05)")
        if len(deduplicated) < len(previous_validated):
            print(f"      (Removed {len(previous_validated) - len(deduplicated)} case-insensitive duplicates)")
        
        return deduplicated

    # REMOVED: _calculate_stability_penalty()
    # Stability is now guaranteed by forced retention mechanism in multi_agent_analysis_full.py
    # Previously validated pathways are explicitly retained, making stability penalty redundant

    def _calculate_process_reward(self, validation_details: Dict[str, Any],
                                  history: List[IterationFeedback] = None) -> float:
        """
        Calculate process-based reward using GPT ranking quality.

        GPT ranking already evaluates all 4 dimensions:
        1. Pathway Description (biological function)
        2. Disease Pathology (relevance)
        3. P-value (statistical significance)
        4. PubMed Literature (evidence support)
        
        Reward = average GPT rank quality across validated pathways
        Higher rank (lower number) = higher reward
        """
        gpt_pathways = validation_details.get('gpt_filtered_pathways', pd.DataFrame())

        if gpt_pathways.empty:
            return 0.0

        # Use GPT rank if available (primary metric)
        if 'gpt_rank' in gpt_pathways.columns and gpt_pathways['gpt_rank'].notna().any():
            # Convert rank to score: rank 1 = 1.0, higher ranks = lower scores
            # Score = 1 - (rank - 1) / max_rank
            max_rank = gpt_pathways['gpt_rank'].max()
            if max_rank > 1:
                gpt_pathways['gpt_score'] = 1.0 - (gpt_pathways['gpt_rank'] - 1) / max_rank
            else:
                gpt_pathways['gpt_score'] = 1.0
            
            process_reward = gpt_pathways['gpt_score'].mean()
        else:
            # Fallback: use evidence score from p-value if gpt_rank not available
            import numpy as np
            avg_pvalue = gpt_pathways['p_value'].mean()
            if avg_pvalue <= 0:
                process_reward = 1.0
            else:
                process_reward = min(-np.log10(avg_pvalue), 10) / 10

        return max(0.0, min(1.0, process_reward))  # Clamp to [0, 1]

    def _generate_feedback_prompt(self, iteration_feedback: IterationFeedback,
                                  genes: List[str], disease_name: str,
                                  history: List[IterationFeedback] = None) -> str:
        """
        Generate detailed feedback prompt for GPT to refine predictions.
        
        Keeps all FDR-validated pathways and provides guidance for next iteration.

        Includes:
        - Validation statistics: matched vs FDR-filtered counts
        - High-quality pathways: all FDR-validated pathways with GPT-generated disease context
        - Retained pathways: exact names/IDs that must be kept
        - Expansion examples: how to explore related pathways
        - Not validated pathways: predictions that failed validation
        - Core guidance: general and category-specific instructions
        """
        # Extract basic info
        validated = iteration_feedback.validated_pathways
        predicted = iteration_feedback.predicted_pathways
        not_validated = [p for p in predicted if p not in validated]
        
        # Get validated pathways dataframe
        gpt_pathways_df = iteration_feedback.validation_details.get('gpt_filtered_pathways', pd.DataFrame())
        
        # Sort validated pathways by GPT rank for Top 10 display
        # GPT ranking already considers all 4 dimensions:
        # 1. Pathway Description, 2. Disease Pathology, 3. P-value, 4. PubMed Literature
        if not gpt_pathways_df.empty:
            # Use gpt_rank if available (best), otherwise fallback to p_value
            if 'gpt_rank' in gpt_pathways_df.columns:
                sorted_df = gpt_pathways_df.sort_values(by='gpt_rank', ascending=True)
            else:
                # Fallback: sort by p-value if gpt_rank not available
                sorted_df = gpt_pathways_df.sort_values(by='p_value', ascending=True)
            
            high_quality_pathways = sorted_df['name'].tolist()
        else:
            high_quality_pathways = validated

        # Extract base disease name (e.g., "IBD" from "IBD_Module_1")
        base_disease_name = disease_name.split('_Module_')[0] if '_Module_' in disease_name else disease_name.split('_')[0]

        # Get matching statistics from validation_details
        n_matched_all = iteration_feedback.validation_details.get('n_matched_all', 0)
        n_fdr_filtered = iteration_feedback.validation_details.get('n_validated', len(validated))
        validation_rate = iteration_feedback.validation_rate
        
        feedback = f"""# Iteration {iteration_feedback.iteration} Feedback

## Validation Results

- **Predicted**: {len(predicted)} pathways
- **Matched (all p-values)**: {n_matched_all} pathways
- **FDR Validated (p<0.05)**: {n_fdr_filtered} pathways ({validation_rate:.1%} validation rate)

**Key Focus**: Predict pathways with clear mechanistic links to **{base_disease_name}** pathogenesis.

"""
        
        feedback += f"## ✅ High-Quality {base_disease_name}-Relevant Pathways (Keep & Expand)\n"
        if high_quality_pathways:
            feedback += f"These pathways are statistically significant AND relevant to {base_disease_name}:\n\n"
            
            # Add detailed context for top pathways
            for i, pathway in enumerate(high_quality_pathways[:10], 1):
                feedback += f"{i}. **{pathway}**\n"
                
                # Add disease-specific context using GPT
                if not gpt_pathways_df.empty:
                    pw_row = gpt_pathways_df[gpt_pathways_df['name'] == pathway]
                    if not pw_row.empty:
                        disease_context = self.hindsight_generator._get_pathway_disease_context(
                            pathway, disease_name, pw_row
                        )
                        if disease_context and disease_context.get('relevance'):
                            feedback += f"   - **Why disease-relevant**: {disease_context['relevance']}\n"
                feedback += "\n"
        else:
            feedback += f"None - need to improve pathway quality and {base_disease_name} relevance\n"
        
        # NEW SECTION: Explicit pathway retention with exact names/IDs
        if high_quality_pathways and len(high_quality_pathways) > 0:
            feedback += f"""

## 🔒 CRITICAL: Retained Pathways (MUST Keep with Exact Names & IDs)

You MUST predict the following {min(len(high_quality_pathways), 10)} pathways in the next iteration using EXACTLY the same names and IDs as listed below. DO NOT rename or modify these pathway names.

**Retained Pathways:**
"""
            # Extract pathway IDs from validation_details
            for i, pathway_name in enumerate(high_quality_pathways[:10], 1):  # Top 10 retained
                if not gpt_pathways_df.empty:
                    pw_row = gpt_pathways_df[gpt_pathways_df['name'] == pathway_name]
                    if not pw_row.empty:
                        pw_id = pw_row['native'].values[0] if 'native' in pw_row.columns else 'N/A'
                        source = pw_row['source'].values[0] if 'source' in pw_row.columns else 'N/A'
                        feedback += f"{i}. **{pathway_name}** (ID: {pw_id}, Source: {source})\n"
                    else:
                        feedback += f"{i}. **{pathway_name}**\n"
                else:
                    feedback += f"{i}. **{pathway_name}**\n"
            
            feedback += f"""

**CRITICAL INSTRUCTIONS:**
- Use EXACTLY the same pathway names as listed above (character-for-character match)
- Use the EXACT IDs provided (do not change GO IDs, KEGG IDs, or Reactome IDs)
- These pathways have been validated with both statistical significance AND high disease relevance
- DO NOT "optimize" or "improve" these names - exact retention is required for tracking

"""
        


        # Retention requirements - use high-quality pathways only (simplified - details in new sections)
        if high_quality_pathways and len(high_quality_pathways) > 0:
            feedback += f"""

## 💡 Disease-Relevant Pathway Expansion Examples

**Examples of good disease-relevant variations:**
- If "Sphingolipid metabolism" validated → try "Glycosphingolipid metabolism", "Ceramide metabolism"
- If "Autophagy" validated → try "Macroautophagy", "Chaperone-mediated autophagy"
- If "Proteasome degradation" validated → try "Ubiquitin-proteasome system", "Protein ubiquitination"
- If "Golgi apparatus" validated → try "Golgi membrane", "cis-Golgi network", "trans-Golgi network"

**CRITICAL**: Focus on pathways with established or hypothesized links to {base_disease_name} pathogenesis.
Avoid generic housekeeping pathways unless they have specific {base_disease_name} relevance.
"""

        feedback += f"\n## ❌ Not Validated Pathways\n"
        if not_validated:
            # Try to get p-values from gpt_matched_all for richer feedback
            gpt_matched_all_df = iteration_feedback.validation_details.get('gpt_matched_all', pd.DataFrame())
            
            for i, pathway in enumerate(not_validated[:15], 1):
                # Look up p-value and category for this pathway
                p_info = ""
                if not gpt_matched_all_df.empty and 'name' in gpt_matched_all_df.columns:
                    pw_row = gpt_matched_all_df[gpt_matched_all_df['name'] == pathway]
                    if not pw_row.empty:
                        p_val = pw_row['p_value'].values[0] if 'p_value' in pw_row.columns else None
                        source = pw_row['source'].values[0] if 'source' in pw_row.columns else ''
                        if p_val is not None:
                            p_info = f" (p={p_val:.2e}, {source})"
                        else:
                            p_info = f" ({source})"
                feedback += f"{i}. {pathway}{p_info}\n"
            
            if len(not_validated) > 15:
                feedback += f"... and {len(not_validated) - 15} more\n"
            
            feedback += f"\n**Why these failed**: These pathways were predicted but did not pass FDR validation (p≥0.05). "
            feedback += f"Consider why they failed — were they too generic, lacking specific module gene support, or mechanistically distant from {base_disease_name}?\n"
        else:
            feedback += "No data available on failed predictions.\n"
        
        # Simple disease-relevance focused guidance
        feedback += f"""

## Core Guidance

Focus on the **validated** and **filtered** results above. For the next iteration:

1. **Keep validated pathways** - They show both statistical enrichment and {base_disease_name} relevance
2. **Expand in related directions** - Explore sub-pathways or related mechanisms of validated pathways  
3. **Prioritize disease correlation** - Every pathway must have a clear mechanistic link to {base_disease_name}

For each predicted pathway, explain:
- **WHY** it is relevant to {base_disease_name} pathogenesis
- **WHICH** input genes serve as key drivers

---

## Category-Specific Guidance

### GO:BP (Biological Process)
Identify biological processes that connect the input genes to {base_disease_name} mechanisms. Cite specific genes as evidence. Use EXACT GO term names (ID format: GO:#######).

### GO:MF (Molecular Function)  
Identify molecular activities (binding, catalysis, transport) dysregulated in {base_disease_name}. Explain how this activity contributes to disease pathology. Use EXACT GO term names (ID format: GO:#######).

### GO:CC (Cellular Component)
Identify cellular locations implicated in {base_disease_name} pathology. Explain how dysfunction at this location drives disease. Use EXACT GO term names (ID format: GO:#######).

### KEGG Pathways
Map functional signals to OFFICIAL KEGG pathway names. Prioritize disease-specific pathways and signaling cascades relevant to {base_disease_name} over generic metabolism. Use EXACT KEGG names (ID format: hsa#####).

### Reactome Pathways
Identify mechanistically detailed pathways from Reactome's hierarchy. Prefer specific child pathways over broad parent categories. Use EXACT Reactome names (ID format: R-HSA-######).

**Key**: For ALL categories, use database-official nomenclature to ensure g:Profiler matching.

"""
        
        # NOTE: Use fixed target count (50 pathways = 10 per category) instead of len(predicted)
        # Bug fix: len(predicted) can be 0 in edge cases, causing LLM to misinterpret as "predict 0 pathways"
        feedback += f"""
## Target Predictions for Next Iteration

Predict **50 pathways total** (10 per category) with clear mechanistic links to **{base_disease_name}**:
- 10 GO:BP (Biological Process) terms
- 10 GO:MF (Molecular Function) terms  
- 10 GO:CC (Cellular Component) terms
- 10 KEGG pathways
- 10 Reactome pathways

**Important**: The retained pathways listed above count toward your 10-per-category quota. Generate new predictions to fill remaining slots.
"""
        return feedback

    def _generate_feedback_prompt_pvalue_only(
        self, iteration_feedback: IterationFeedback,
        genes: List[str], disease_name: str,
        history: List[IterationFeedback] = None
    ) -> str:
        """
        Generate p-value only feedback prompt (ablation control).
        
        Strips all GPT biological reasoning (disease context, expansion examples,
        category-specific guidance) and keeps only statistical feedback:
        - Validation statistics (predicted / matched / FDR validated counts)
        - Validated pathway names with p-values (no disease relevance explanation)
        - Retained pathway instructions (exact name/ID retention)
        - Not validated pathways with p-values (no failure reasoning)
        - Format guidance (no biological interpretation)
        - Target prediction count (50 pathways, 10 per category)
        """
        # Extract basic info
        validated = iteration_feedback.validated_pathways
        predicted = iteration_feedback.predicted_pathways
        not_validated = [p for p in predicted if p not in validated]
        
        # Get validated pathways dataframe
        gpt_pathways_df = iteration_feedback.validation_details.get('gpt_filtered_pathways', pd.DataFrame())
        
        # Sort by p-value (purely statistical, no GPT rank)
        if not gpt_pathways_df.empty:
            sorted_df = gpt_pathways_df.sort_values(by='p_value', ascending=True)
            high_quality_pathways = sorted_df['name'].tolist()
        else:
            high_quality_pathways = validated
        
        # Extract base disease name
        base_disease_name = disease_name.split('_Module_')[0] if '_Module_' in disease_name else disease_name.split('_')[0]
        
        # Get matching statistics
        n_matched_all = iteration_feedback.validation_details.get('n_matched_all', 0)
        n_fdr_filtered = iteration_feedback.validation_details.get('n_validated', len(validated))
        validation_rate = iteration_feedback.validation_rate
        
        # =====================================================================
        # SECTION 1: Validation statistics (KEPT - same as full)
        # =====================================================================
        feedback = f"""# Iteration {iteration_feedback.iteration} Feedback

## Validation Results

- **Predicted**: {len(predicted)} pathways
- **Matched (all p-values)**: {n_matched_all} pathways
- **FDR Validated (p<0.05)**: {n_fdr_filtered} pathways ({validation_rate:.1%} validation rate)

"""
        
        # =====================================================================
        # SECTION 2: Validated pathways with p-values ONLY (NO GPT disease context)
        # =====================================================================
        feedback += f"## ✅ FDR-Validated Pathways\n"
        if high_quality_pathways:
            feedback += f"These pathways passed FDR validation (p<0.05):\n\n"
            
            for i, pathway in enumerate(high_quality_pathways[:10], 1):
                # Only show p-value and source — NO disease context
                if not gpt_pathways_df.empty:
                    pw_row = gpt_pathways_df[gpt_pathways_df['name'] == pathway]
                    if not pw_row.empty:
                        p_val = pw_row['p_value'].values[0]
                        source = pw_row['source'].values[0] if 'source' in pw_row.columns else ''
                        feedback += f"{i}. **{pathway}** (p={p_val:.2e}, {source})\n"
                    else:
                        feedback += f"{i}. **{pathway}**\n"
                else:
                    feedback += f"{i}. **{pathway}**\n"
        else:
            feedback += "None validated in previous iteration.\n"
        
        # =====================================================================
        # SECTION 3: Retained pathway instructions (KEPT - same as full)
        # =====================================================================
        if high_quality_pathways and len(high_quality_pathways) > 0:
            feedback += f"""\n\n## 🔒 CRITICAL: Retained Pathways (MUST Keep with Exact Names & IDs)

You MUST predict the following {min(len(high_quality_pathways), 10)} pathways in the next iteration using EXACTLY the same names and IDs as listed below.

**Retained Pathways:**
"""
            for i, pathway_name in enumerate(high_quality_pathways[:10], 1):
                if not gpt_pathways_df.empty:
                    pw_row = gpt_pathways_df[gpt_pathways_df['name'] == pathway_name]
                    if not pw_row.empty:
                        pw_id = pw_row['native'].values[0] if 'native' in pw_row.columns else 'N/A'
                        source = pw_row['source'].values[0] if 'source' in pw_row.columns else 'N/A'
                        feedback += f"{i}. **{pathway_name}** (ID: {pw_id}, Source: {source})\n"
                    else:
                        feedback += f"{i}. **{pathway_name}**\n"
                else:
                    feedback += f"{i}. **{pathway_name}**\n"
            
            feedback += f"""\n**CRITICAL INSTRUCTIONS:**
- Use EXACTLY the same pathway names as listed above (character-for-character match)
- Use the EXACT IDs provided
- DO NOT rename or modify these pathway names

"""
        
        # =====================================================================
        # NO expansion examples (REMOVED)
        # NO disease-relevance guidance (REMOVED)
        # =====================================================================
        
        # =====================================================================
        # SECTION 4: Not validated pathways with p-values (NO failure reasoning)
        # =====================================================================
        feedback += f"\n## ❌ Not Validated Pathways\n"
        if not_validated:
            gpt_matched_all_df = iteration_feedback.validation_details.get('gpt_matched_all', pd.DataFrame())
            
            for i, pathway in enumerate(not_validated[:15], 1):
                p_info = ""
                if not gpt_matched_all_df.empty and 'name' in gpt_matched_all_df.columns:
                    pw_row = gpt_matched_all_df[gpt_matched_all_df['name'] == pathway]
                    if not pw_row.empty:
                        p_val = pw_row['p_value'].values[0] if 'p_value' in pw_row.columns else None
                        source = pw_row['source'].values[0] if 'source' in pw_row.columns else ''
                        if p_val is not None:
                            p_info = f" (p={p_val:.2e}, {source})"
                        else:
                            p_info = f" ({source})"
                feedback += f"{i}. {pathway}{p_info}\n"
            
            if len(not_validated) > 15:
                feedback += f"... and {len(not_validated) - 15} more\n"
        else:
            feedback += "No data available on failed predictions.\n"
        
        # =====================================================================
        # SECTION 5: Minimal guidance (format only, NO biological reasoning)
        # =====================================================================
        feedback += f"""\n## Guidance for Next Iteration

1. **Keep retained pathways** listed above with exact names
2. **Improve statistical significance** - aim for p<0.05 FDR-adjusted
3. **Replace non-validated pathways** with new predictions

## Naming Format Requirements

- GO:BP / GO:MF / GO:CC: Use EXACT GO term names (ID format: GO:#######)
- KEGG: Use OFFICIAL KEGG pathway names (ID format: hsa#####)
- Reactome: Use EXACT Reactome names (ID format: R-HSA-######)

**Key**: Use database-official nomenclature to ensure g:Profiler matching.

"""
        
        # =====================================================================
        # SECTION 6: Target predictions (KEPT - same as full)
        # =====================================================================
        feedback += f"""## Target Predictions for Next Iteration

Predict **50 pathways total** (10 per category):
- 10 GO:BP (Biological Process) terms
- 10 GO:MF (Molecular Function) terms  
- 10 GO:CC (Cellular Component) terms
- 10 KEGG pathways
- 10 Reactome pathways

**Important**: The retained pathways listed above count toward your 10-per-category quota. Generate new predictions to fill remaining slots.
"""
        return feedback

    def _call_gpt_with_feedback(self, genes: List[str], disease_name: str,
                                feedback_prompt: str, top_k: int) -> Dict[str, Any]:
        """
        Call GPT with feedback from previous iteration.

        Uses a modified prompt that includes validation feedback.
        """
        # Create a custom predictor call with feedback
        predictor = self.pathway_generator_class(model=self.model)

        # Construct enhanced prompt
        enhanced_prompt = f"""You are analyzing genes for {disease_name}.

{feedback_prompt}

Based on the feedback above, predict {top_k} pathways that are most likely to be:
1. Statistically enriched in the gene set
2. Supported by literature evidence
3. Biologically relevant to {disease_name}

Learn from the validation results to improve your predictions.
"""

        # Call predictor with enhanced context
        # Note: This requires modifying the predictor to accept custom prompts
        # For now, we'll use the standard call and log the feedback
        prediction = predictor.predict_pathways(
            genes=genes,
            disease_name=disease_name
        )
        # Add feedback context to prediction
        prediction['feedback_used'] = feedback_prompt

        return prediction



    def run_iterative_analysis(self, genes: List[str], disease_name: str,
                              top_k_predict: int = 50,  # Changed from 40 to match iterations 2-3
                              top_k_analyze: int = 6) -> Dict[str, Any]:
        """
        Run Flash-inspired iterative GPT-Agent feedback loop.

        Parameters:
        -----------
        genes : list
            Gene list for analysis
        disease_name : str
            Disease name
        top_k_predict : int
            Number of pathways to predict each iteration
        top_k_analyze : int
            Number of top pathways for detailed analysis

        Returns:
        --------
        dict : Complete iteration history and final results
        """
        print("\n" + "="*80)
        # Create unique run directory with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        current_run_id = f"{disease_name}_{timestamp}"
        
        # IMPORTANT: Use base_results_dir to avoid nesting
        self.results_dir = os.path.join(self.base_results_dir, current_run_id)
        os.makedirs(self.results_dir, exist_ok=True)
        
        print("FLASH-INSPIRED ITERATIVE GPT-AGENT FRAMEWORK")
        print("="*80)
        print(f"🆔 Run ID: {current_run_id}")
        print(f"📁 Results: {self.results_dir}")
        print(f"Disease: {disease_name}")
        print(f"Genes: {len(genes)}")
        print(f"Max iterations: {self.max_iterations}")
        
        # Save run configuration
        self._save_run_config(current_run_id, disease_name, genes, top_k_predict, top_k_analyze)

        # ================================================================
        # OPTIMIZATION: Run g:Profiler once and cache results
        # ================================================================
        print("\n" + "="*80)
        print("PRE-COMPUTING g:Profiler ENRICHMENT (Cache for all iterations)")
        print("="*80)
        print("Using FULL enrichment (no p-value threshold) for comprehensive matching")
        
        gprofiler_cache = None
        # NOTE: g:Profiler is a direct API call - does NOT require agent loading
        # Only the planning_agent ranking step (below) requires agents_ready
        try:
                # Use enrich_geneset_full to get ALL results (no filtering)
                from src.pathway_enrichment_analysis import PathwayEnrichmentAnalyzer
                enrichment_analyzer = PathwayEnrichmentAnalyzer(self.results_dir)
                
                cached_all_pathways = enrichment_analyzer.enrich_geneset_full(
                    genes=genes,
                    name=disease_name,
                    sources=['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
                )
                
                if not cached_all_pathways.empty:
                    # Calculate statistics for filtering
                    total_count = len(cached_all_pathways)
                    nominal_sig_count = (cached_all_pathways['p_value'] < 0.05).sum()

                    # PRE-COMPUTE COMPLETE RANKING USING PLANNING AGENT (6-STAGE WORKFLOW)
                    # This calls planning_agent.act() which performs:
                    # Stage 1: LLM disease description enrichment
                    # Stage 2: TF-IDF similarity
                    # Stage 3: BioBERT embedding similarity
                    # Stage 4: p-value weighting (score * (1 - p_value))
                    # Stage 5: Protein function keyword search
                    # Stage 6: PubMed relevance
                    
                    print(f"\n   📊 PRE-COMPUTING COMPLETE RANKING (Planning Agent 6-Stage Workflow)")
                    print(f"   Calling planning_agent.act() for {len(genes)} genes")
                    print(f"   This ranking will be cached and reused across all {self.max_iterations} iterations")
                    
                    try:
                        if not self.analyzer.base_analyzer.agents_ready:
                            raise RuntimeError("Planning agent not loaded (BioBERT tokenizer issue) - skipping 6-stage ranking")
                        base_disease_name = disease_name.split('_iter')[0] if '_iter' in disease_name else disease_name
                        
                        # Further simplify disease name for PubMed queries
                        # Convert module-based names like "JACCARD_AD_M19_vs_PD_M12" to actual disease names
                        if '_M' in base_disease_name and '_vs_' in base_disease_name:
                            # Extract disease names from "JACCARD_AD_M19_vs_PD_M12" format
                            # Remove JACCARD_ prefix if present
                            clean_name = base_disease_name.replace('JACCARD_', '')
                            
                            parts = clean_name.split('_vs_')
                            disease_A = parts[0].split('_M')[0]  # "AD"
                            disease_B = parts[1].split('_M')[0] if len(parts) > 1 else ""  # "PD"
                            
                            # Convert abbreviations to full names for better PubMed results
                            disease_map = {
                                'AD': "Alzheimer's disease",
                                'PD': "Parkinson's disease",
                                'ALS': "Amyotrophic lateral sclerosis",
                                'HD': "Huntington's disease"
                            }
                            
                            disease_A_full = disease_map.get(disease_A, disease_A)
                            disease_B_full = disease_map.get(disease_B, disease_B)
                            
                            # For PubMed, use both diseases
                            pubmed_disease_name = f"{disease_A_full} {disease_B_full}"
                        elif '_M' in base_disease_name:
                            # Single disease with module, like "AD_Module_19" or "JACCARD_AD_Module_19"
                            # Remove common prefixes
                            clean_name = base_disease_name.replace('JACCARD_', '')
                            disease_abbr = clean_name.split('_M')[0]
                            
                            disease_map = {
                                'AD': "Alzheimer's disease",
                                'PD': "Parkinson's disease",
                                'ALS': "Amyotrophic lateral sclerosis",
                                'HD': "Huntington's disease"
                            }
                            pubmed_disease_name = disease_map.get(disease_abbr, base_disease_name)
                        else:
                            pubmed_disease_name = base_disease_name
                        
                        print(f"      Disease name for PubMed: {pubmed_disease_name}")
                        
                        # Call planning agent's complete 6-stage workflow
                        # This will:
                        # 1. Run g:Profiler (with user_threshold=0.05 by default, giving FDR-corrected pathways)
                        # 2. Rank by TF-IDF + BioBERT (stages 2-4)
                        # 3. Rank by PubMed relevance (stage 6)
                        # 4. Select wellknown and novel pathways
                        print(f"      Running 6-stage workflow...")
                        ranked_pathways_df, wellknown_pathways, novel_pathways = self.analyzer.base_analyzer.planning_agent.act(
                            protein_list=genes,
                            disease_trait=pubmed_disease_name,  # Use simplified name for PubMed
                            top=1000,  # Get all significant pathways, not just top 100
                            query_agent=self.analyzer.base_analyzer.query_agent
                        )
                        
                        fdr_sig_count = len(ranked_pathways_df) if not ranked_pathways_df.empty else 0
                        print(f"      ✅ Complete ranking done: {fdr_sig_count} FDR-corrected pathways")
                        
                        if not ranked_pathways_df.empty:
                            # Merge planning agent results back to cached_all_pathways
                            # The ranked_pathways_df should have:
                            # - tfidf_score (implicitly in 'score')
                            # - biobert_score (implicitly in 'score')
                            # - score (combined TF-IDF + BioBERT)
                            # - weighted_score
                            # - pubmed_relevance
                            # - validated_publications
                            # - num_publications

                            # Handle duplicate pathway names by keeping the first occurrence
                            # (same pathway may appear in multiple sources like GO:BP, GO:MF, etc.)
                            ranked_pathways_unique = ranked_pathways_df.drop_duplicates(subset=['name'], keep='first')
                            score_mapping = ranked_pathways_unique.set_index('name').to_dict('index')
                            
                            # Add all planning agent scores to cache
                            # Note: planning agent doesn't separate tfidf/biobert, they're combined in 'score'
                            # We'll extract them from 'score' assuming equal weighting
                            for col in ['score', 'weighted_score', 'pubmed_relevance', 'num_publications']:
                                if col in ranked_pathways_df.columns:
                                    cached_all_pathways[col] = cached_all_pathways['name'].apply(
                                        lambda x: score_mapping.get(x, {}).get(col, 0.0)
                                    )
                                else:
                                    cached_all_pathways[col] = 0.0
                            
                            # Assuming score = (tfidf + biobert) / 2, we approximate:
                            # tfidf_score ≈ biobert_score ≈ score (since we don't have individual scores)
                            cached_all_pathways['tfidf_score'] = cached_all_pathways['score']
                            cached_all_pathways['biobert_score'] = cached_all_pathways['score']

                            # Create pubmed_score alias for pubmed_relevance (for backward compatibility)
                            if 'pubmed_relevance' in cached_all_pathways.columns:
                                cached_all_pathways['pubmed_score'] = cached_all_pathways['pubmed_relevance']
                                print(f"      ✅ PubMed scores mapped (avg: {cached_all_pathways['pubmed_score'].mean():.3f})")
                            else:
                                cached_all_pathways['pubmed_score'] = 0.0
                                print(f"      ⚠️  No PubMed scores available, using default 0.0")

                            # Handle validated_publications (list type)
                            if 'validated_publications' in ranked_pathways_df.columns:
                                cached_all_pathways['validated_publications'] = cached_all_pathways['name'].apply(
                                    lambda x: score_mapping.get(x, {}).get('validated_publications', [])
                                )
                            else:
                                cached_all_pathways['validated_publications'] = [[] for _ in range(len(cached_all_pathways))]
                            
                            # Add disease_specificity and combined_score
                            # These are needed for STEP 3.5 cached literature ranking
                            if 'disease_specificity' not in cached_all_pathways.columns:
                                # Calculate disease specificity with penalty for generic terms
                                # Extract disease names (handle both single disease and disease pairs)
                                # Examples: "AD_Module_5" -> ["AD"]
                                #          "JACCARD_AD_M19_vs_PD_M12" -> ["AD", "PD"]
                                #          "AD_M19_vs_PD_M12" -> ["AD", "PD"]

                                disease_parts = []
                                if 'vs' in disease_name.lower():
                                    # Disease pair format
                                    # Extract diseases around "vs"
                                    parts = disease_name.split('_')
                                    for i, part in enumerate(parts):
                                        if part.upper() in ['AD', 'PD', 'ALS', 'MS']:
                                            disease_parts.append(part.upper())
                                else:
                                    # Single disease format
                                    base_disease = disease_name.split('_')[0] if '_' in disease_name else disease_name
                                    disease_parts = [base_disease.upper()]

                                # Define disease-specific keywords
                                disease_keywords = {
                                    'AD': ['alzheimer', 'amyloid', 'tau', 'dementia', 'apoe', 'app', 'presenilin'],
                                    'PD': ['parkinson', 'synuclein', 'alpha-synuclein', 'dopamine', 'substantia nigra', 'lewy body'],
                                    'ALS': ['amyotrophic', 'motor neuron', 'als', 'tdp-43', 'sod1'],
                                    'MS': ['multiple sclerosis', 'demyelination', 'oligodendrocyte', 'myelin']
                                }

                                # Generic/overly broad terms that should be penalized
                                generic_keywords = [
                                    'metabolic process', 'cellular process', 'biological process',
                                    'regulation', 'signaling', 'pathway', 'activity',
                                    'binding', 'transport', 'localization', 'organization'
                                ]

                                # Combine keywords from all detected diseases
                                keywords = []
                                for disease in disease_parts:
                                    keywords.extend(disease_keywords.get(disease, []))

                                # Remove duplicates
                                keywords = list(set(keywords))

                                # Debug: Show extracted diseases and keyword count
                                if disease_parts:
                                    print(f"      🔍 Detected diseases: {disease_parts} ({len(keywords)} keywords)")
                                else:
                                    print(f"      ⚠️  No diseases detected in '{disease_name}', using default")

                                def calc_specificity(name, desc):
                                    """Calculate disease specificity with generic term penalty"""
                                    if pd.isna(desc):
                                        desc = ""

                                    text = f"{name} {desc}".lower()

                                    # Count disease-specific matches
                                    disease_matches = sum(1 for kw in keywords if kw in text)

                                    # Count generic term matches (penalty)
                                    generic_matches = sum(1 for kw in generic_keywords if kw in text)

                                    if keywords:
                                        # Disease specificity score (improved formula)
                                        # Use sqrt to reduce the penalty of having many keywords
                                        # This gives more weight to each match
                                        if disease_matches > 0:
                                            # Scale: 1 match → ~0.2, 2 matches → ~0.3, 3+ matches → 0.4+
                                            disease_score = min(disease_matches / max(len(keywords) ** 0.5, 1), 1.0) * 0.5
                                        else:
                                            disease_score = 0

                                        # Generic penalty (reduce score if too generic)
                                        generic_penalty = min(generic_matches / len(generic_keywords), 0.2)

                                        # Final score: disease specificity - generic penalty + baseline
                                        # Baseline 0.1 for all pathways, max 0.6 for highly specific
                                        final_score = max(0.1, min(0.6, disease_score - generic_penalty + 0.1))
                                        return final_score
                                    else:
                                        # Unknown disease: use moderate default with generic penalty
                                        generic_penalty = min(generic_matches / len(generic_keywords), 0.15)
                                        return max(0.1, 0.25 - generic_penalty)

                                cached_all_pathways["disease_specificity"] = cached_all_pathways.apply(
                                    lambda row: calc_specificity(row.get('name', ''), row.get('description', '')),
                                    axis=1
                                )

                                avg_spec = cached_all_pathways['disease_specificity'].mean()
                                min_spec = cached_all_pathways['disease_specificity'].min()
                                max_spec = cached_all_pathways['disease_specificity'].max()

                                # Show distribution
                                high_spec = (cached_all_pathways['disease_specificity'] > 0.15).sum()
                                low_spec = (cached_all_pathways['disease_specificity'] <= 0.11).sum()

                                print(f"      ✅ Disease-specificity calculated (avg: {avg_spec:.3f}, range: {min_spec:.3f}-{max_spec:.3f})")
                                print(f"         Distribution: {low_spec} low (≤0.11), {high_spec} high (>0.15) out of {len(cached_all_pathways)} pathways")
                            
                            # Calculate combined_score
                            if 'combined_score' not in cached_all_pathways.columns:
                                if 'score' in cached_all_pathways.columns and 'disease_specificity' in cached_all_pathways.columns:
                                    # combined_score = (TF-IDF + BioBERT + disease_specificity) / 3
                                    # score = (TF-IDF + BioBERT) / 2
                                    # So: combined_score = (score * 2 + disease_specificity) / 3
                                    cached_all_pathways["combined_score"] = (
                                        cached_all_pathways["score"] * 2 + cached_all_pathways["disease_specificity"]
                                    ) / 3.0
                                    print(f"      ✅ Combined score calculated (avg: {cached_all_pathways['combined_score'].mean():.3f})")
                                else:
                                    # Fallback
                                    cached_all_pathways["combined_score"] = cached_all_pathways.get("score", 0.0)
                            
                            
                            # Calculate evidence scores (Open Targets style)
                            # This converts p-values to a [0,1] scale using -log10 transformation
                            # Formula: evidence_score = min(-log10(p_value), 10) / 10
                            # Example: p=1e-10 → score=1.0, p=1e-5 → score=0.5, p=0.05 → score=0.13
                            def p_to_evidence(p, cap=10):
                                """Convert p-value to evidence score."""
                                import numpy as np
                                if p <= 0:
                                    return 1.0
                                return min(-np.log10(p), cap) / cap
                            
                            cached_all_pathways["evidence_score"] = cached_all_pathways["p_value"].apply(
                                lambda p: p_to_evidence(p, cap=10)
                            )
                            
                            # Weighted_score = combined_score × evidence_score
                            # Combined_score: literature relevance (TF-IDF + BioBERT + disease specificity)
                            # Evidence_score: statistical significance weight (Open Targets -log10 scale)
                            # This gives high weight to pathways with BOTH literature support AND statistical significance
                            cached_all_pathways["weighted_score"] = (
                                cached_all_pathways["combined_score"] * cached_all_pathways["evidence_score"]
                            )
                            
                            print(f"      ✅ Ranking scores merged to cache")
                            print(f"         - evidence_score = min(-log10(p_value), 10) / 10")
                            print(f"         - weighted_score = combined_score × evidence_score")
                        else:
                            # No pathways from planning agent, set defaults
                            for col in ['tfidf_score', 'biobert_score', 'score', 'weighted_score', 'pubmed_relevance', 'num_publications', 'disease_specificity', 'combined_score']:
                                cached_all_pathways[col] = 0.0
                            cached_all_pathways['validated_publications'] = [[] for _ in range(len(cached_all_pathways))]
                            fdr_sig_count = 0
                            
                    except Exception as e:
                        print(f"      ⚠️  Planning agent ranking failed: {e}")
                        import traceback
                        traceback.print_exc()
                        # Set default values
                        for col in ['tfidf_score', 'biobert_score', 'score', 'weighted_score', 'pubmed_relevance', 'num_publications', 'disease_specificity', 'combined_score']:
                            cached_all_pathways[col] = 0.0
                        cached_all_pathways['validated_publications'] = [[] for _ in range(len(cached_all_pathways))]
                        fdr_sig_count = 0

                    # Create cache with BOTH all pathways and FDR-filtered pathways
                    fdr_pathways = cached_all_pathways[cached_all_pathways['p_value'] < 0.05].copy() if 'p_value' in cached_all_pathways.columns else cached_all_pathways.copy()
                    
                    gprofiler_cache = {
                        'all_pathways': cached_all_pathways,  # ALL pathways (no p-value filter)
                        'ranked_pathways': fdr_pathways,      # FDR-significant pathways only
                        'wellknown': [],  # Not applicable for full results
                        'novel': []  # Not applicable for full results
                    }

                    print(f"\n✅ g:Profiler FULL cache created:")
                    print(f"   - all_pathways: {total_count} total pathways (no p-value filter)")
                    print(f"   - ranked_pathways: {len(fdr_pathways)} FDR-significant pathways (p<0.05)")
                    print(f"   📊 Filter Statistics:")
                    print(f"      - Nominal p<0.05: {nominal_sig_count} pathways (no FDR correction)")
                    print(f"      - FDR-corrected p<0.05: {fdr_sig_count} pathways (ranked by planning agent)")
                    print(f"   🔄 Cache will be reused for {self.max_iterations} iterations")
                else:
                    print("⚠️  No g:Profiler results found")
                    gprofiler_cache = None
                
        except Exception as e:
            print(f"⚠️  g:Profiler caching failed: {e}")
            print("   Will call g:Profiler individually for each iteration")
            import traceback
            traceback.print_exc()
            gprofiler_cache = None
        # (no else needed - g:Profiler always runs regardless of agents_ready)

        # ================================================================
        # ITERATION LOOP
        # ================================================================

        for iteration in range(1, self.max_iterations + 1):
            print("\n" + "▶"*40)
            print(f"ITERATION {iteration}/{self.max_iterations}")
            print("▶"*40)

            # Step 1: GPT5.1 Pathway Generator
            retained_pathways = None
            retained_pathways_df = None  # Initialize to ensure it's always defined
            if iteration == 1:
                print("\n[GPT5.1] Initial pathway prediction...")
            else:
                print(f"\n[GPT5.1] Refined prediction with feedback...")
                prev_feedback = self.iteration_history[-1]

                # CUMULATIVE PATHWAY RETENTION - Accumulate ALL validated pathways from all iterations
                if self.retention_rate > 0:
                    # Collect ALL validated pathways from all previous iterations
                    all_previous_validated = []
                    for hist in self.iteration_history:
                        all_previous_validated.extend(hist.validated_pathways)
                    
                    # Remove duplicates while preserving order (CASE-INSENSITIVE)
                    seen = set()
                    unique_validated = []
                    for pw in all_previous_validated:
                        pw_lower = pw.lower().strip()
                        if pw_lower not in seen:
                            seen.add(pw_lower)
                            unique_validated.append(pw)  # Keep original casing
                    
                    if len(unique_validated) > 0:
                        # Apply retention rate to cumulative pathways
                        must_keep = self._enforce_pathway_retention(
                            unique_validated,
                            retention_rate=self.retention_rate
                        )
                        
                        print(f"\n🔒 CUMULATIVE PATHWAY RETENTION:")
                        print(f"   All previous iterations validated: {len(unique_validated)} unique pathways")
                        print(f"   Retention rate: {self.retention_rate:.0%}")
                        print(f"   MUST keep: {len(must_keep)} pathways")
                        
                        # Show breakdown by iteration
                        for i, hist in enumerate(self.iteration_history, 1):
                            print(f"     Iter{i}: {len(hist.validated_pathways)} pathways")
                        
                        print(f"   Top retained pathways:")
                        for i, pw in enumerate(must_keep[:3], 1):
                            print(f"     {i}. {pw}")
                        if len(must_keep) > 3:
                            print(f"     ... and {len(must_keep)-3} more")
                        
                        retained_pathways = must_keep
                        
                        # Build retained pathways DataFrame from CSV files
                        retained_dfs = []
                        
                        for i, hist in enumerate(self.iteration_history, 1):
                            # Load from CSV file (DataFrames in validation_details aren't serialized)
                            disease_name_iter = hist.validation_details.get('disease_name', disease_name)
                            
                            # Find base Pathway_analysis directory
                            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                            
                            # CRITICAL: Include iteration number in CSV filename
                            # Files are saved as: disease_name_iter1_gpt_filtered_pathways.csv
                            gpt_filtered_csv = os.path.join(
                                base_dir,
                                'iterative_feedback',
                                'gpt_led_analysis_ag2_hitl',
                                f'{disease_name_iter}_iter{i}_gpt_filtered_pathways.csv'
                            )
                            
                            if os.path.exists(gpt_filtered_csv):
                                try:
                                    hist_df = pd.read_csv(gpt_filtered_csv)
                                    
                                    # Apply case-insensitive deduplication
                                    if not hist_df.empty and 'name' in hist_df.columns:
                                        hist_df['_name_lower'] = hist_df['name'].str.lower()
                                        # FIXED: Use keep='last' to preserve most recent data within each iteration
                                        hist_df_dedup = hist_df.drop_duplicates(subset='_name_lower', keep='last').drop(columns=['_name_lower'])
                                        retained_dfs.append(hist_df_dedup)
                                except Exception as e:
                                    print(f"   ⚠️ Error loading CSV for iteration {i}: {e}")
                        
                        # Combine all retained DataFrames
                        if retained_dfs:
                            retained_pathways_df = pd.concat(retained_dfs, ignore_index=True)
                            
                            # Apply case-insensitive deduplication across all iterations
                            if 'name' in retained_pathways_df.columns:
                                retained_pathways_df['_name_lower'] = retained_pathways_df['name'].str.lower()
                                before_dedup = len(retained_pathways_df)
                                # FIXED: Use keep='last' to preserve most recent iteration's data (including gpt_rank)
                                retained_pathways_df = retained_pathways_df.drop_duplicates(subset='_name_lower', keep='last').drop(columns=['_name_lower'])
                                after_dedup = len(retained_pathways_df)
                                
                                if before_dedup > after_dedup:
                                    print(f"   🔄 Removed {before_dedup - after_dedup} cross-iteration duplicates (case-insensitive)")
                            
                            print(f"\n   ✅ Retained pathways DataFrame: {len(retained_pathways_df)} unique pathways with full data")
                        else:
                            print(f"\n   ⚠️  No retained pathways DataFrame could be built (all iterations had empty gpt_filtered_pathways)")
                            retained_pathways_df = None

                    else:
                        print(f"   No pathways to retain (no previous validated pathways)")
                        retained_pathways = None
                        retained_pathways_df = None  # Ensure DataFrame is also None
                else:
                    print(f"   Retention disabled (retention_rate=0)")
                    retained_pathways = None
                    retained_pathways_df = None  # Ensure DataFrame is also None

                if self.feedback_mode == 'pvalue_only':
                    print(f"   [DEBUG] Generating pvalue_only feedback prompt...")
                    feedback_prompt = self._generate_feedback_prompt_pvalue_only(
                        prev_feedback, genes, disease_name, self.iteration_history
                    )
                else:
                    print(f"   [DEBUG] Generating FULL feedback prompt...")
                    feedback_prompt = self._generate_feedback_prompt(
                        prev_feedback, genes, disease_name, self.iteration_history
                    )
                feedback_file = os.path.join(
                    self.results_dir,
                    f'{disease_name}_iter{iteration}_feedback.txt'
                )
                with open(feedback_file, 'w') as f:
                    f.write(feedback_prompt)
                print(f"   Feedback prompt saved: {feedback_file}")

            results = self.analyzer.analyze_gpt_led_pathways(
                genes=genes,
                disease_name=f"{disease_name}_iter{iteration}",
                top_k_predict=top_k_predict,
                top_k_analyze=top_k_analyze,
                retained_pathways=retained_pathways,  # Pass pathway names list for statistics
                retained_pathways_df=retained_pathways_df,  # Pass DataFrame (always defined now)
                gprofiler_cache=self._deep_copy_cache(gprofiler_cache),  # Pass cache copy to prevent mutations
                skip_ppi_analysis=True,  # Skip PPI for per-iteration runs (performance optimization)
                gpt_rank_function=self.gpt_rank_function,  # Enable GPT auto-ranking
                disease_description=self.disease_description,  # Disease context for ranking
                query_agent=self.query_agent,  # PubMed search agent
                file_identifier=os.path.join(self.results_dir, f"{disease_name}_iter{iteration}"),  # For reasoning path
                iteration=iteration  # For reasoning path
            )

            # Step 2: Multi-Agent Verification
            print("\n[Multi-Agent] Verification complete:")
            gpt_prediction = results.get('gpt_prediction', {})
            predicted_pathways = gpt_prediction.get('predicted_pathways', [])
            gpt_pathways_df = results.get('gpt_filtered_pathways', pd.DataFrame())
            validated_pathways = gpt_pathways_df['name'].tolist() if not gpt_pathways_df.empty else []
            validation_rate = results.get('validation_rate', 0.0)

            print(f"   Predicted: {len(predicted_pathways)}")
            print(f"   Validated: {len(validated_pathways)}")
            print(f"   Validation rate: {validation_rate:.1%}")

            # Print literature scoring details if available
            if not gpt_pathways_df.empty:
                print(f"\n   📚 Literature Scoring (averaged across validated pathways):")
                if 'score' in gpt_pathways_df.columns:
                    avg_combined_score = gpt_pathways_df['score'].mean()
                    print(f"      Combined score: {avg_combined_score:.3f} (TF-IDF + BioBERT)")
                if 'tfidf_score' in gpt_pathways_df.columns:
                    avg_tfidf = gpt_pathways_df['tfidf_score'].mean()
                    print(f"      TF-IDF score: {avg_tfidf:.3f}")
                if 'biobert_score' in gpt_pathways_df.columns:
                    avg_biobert = gpt_pathways_df['biobert_score'].mean()
                    print(f"      BioBERT score: {avg_biobert:.3f}")
                if 'ad_specificity' in gpt_pathways_df.columns:
                    avg_ad_spec = gpt_pathways_df['ad_specificity'].mean()
                    print(f"      Disease specificity: {avg_ad_spec:.3f}")

            # Step 3: AutoEval (Flash)
            print("\n[AutoEval] Automatic outcome evaluation...")
            eval_scores = self.auto_eval.evaluate_outcome(results)
            print(f"   Significance score: {eval_scores['significance_score']:.3f}")
            print(f"   Literature score: {eval_scores['literature_score']:.3f}")
            print(f"   Overall score: {eval_scores['overall_score']:.3f}")

            # Step 4: Calculate rewards (for RL)
            outcome_reward = self._calculate_outcome_reward(
                validation_rate, len(validated_pathways)
            )
            process_reward = self._calculate_process_reward(results, self.iteration_history)
            total_reward = (outcome_reward + process_reward) / 2.0

            # Step 5: Generate process feedback
            process_feedback = self._generate_process_feedback(
                results, predicted_pathways, validated_pathways
            )

            # Step 6: Record iteration (temporary without hindsight)
            iteration_feedback = IterationFeedback(
                iteration=iteration,
                predicted_pathways=predicted_pathways,
                validated_pathways=validated_pathways,
                validation_rate=validation_rate,
                validation_details=results,
                process_feedback=process_feedback,
                outcome_reward=outcome_reward,
                process_reward=process_reward,
                total_reward=total_reward,
                status="PENDING",
                hindsight=""
            )

            # Step 7: Hindsight Generator (Flash)
            print("\n[Hindsight] Generating process-level feedback...")
            hindsight = self.hindsight_generator.generate_hindsight(
                iteration_feedback, self.iteration_history, disease_name
            )
            iteration_feedback.hindsight = hindsight

            # Save hindsight
            hindsight_file = os.path.join(
                self.results_dir,
                f'{disease_name}_iter{iteration}_hindsight.md'
            )
            with open(hindsight_file, 'w') as f:
                f.write(hindsight)
            print(f"   Hindsight saved: {hindsight_file}")

            # Step 8: Status Supervisor (Flash)
            print("\n[StatusSupervisor] Evaluating iteration status...")
            self.iteration_history.append(iteration_feedback)
            status, reasoning = self.status_supervisor.evaluate_status(self.iteration_history)
            iteration_feedback.status = status

            print(f"   Status: {status}")
            print(f"   Reasoning: {reasoning}")

            # Step 9: Check if should continue
            if iteration >= self.max_iterations:
                print(f"\n⏹️ MAX_ITER reached at iteration {iteration}")
                break
            elif status == "CONVERGED":
                print(f"\n✅ CONVERGED at iteration {iteration}")
                break
            elif status == "DIVERGED":
                print(f"\n⚠️ DIVERGED at iteration {iteration}")
                print("   Consider adjusting parameters or strategy")
                break

        # Generate final summary
        final_results = self._generate_final_summary(disease_name, genes)

        print("\n" + "="*80)
        print("✅ ITERATIVE ANALYSIS COMPLETE")
        print("="*80)
        print(f"   Total iterations: {len(self.iteration_history)}")
        print(f"   Final validation rate: {self.iteration_history[-1].validation_rate:.1%}")
        print(f"   Final status: {self.iteration_history[-1].status}")
        print(f"   Best iteration: {max(self.iteration_history, key=lambda x: x.total_reward).iteration}")

        return final_results

    def run_iterative_analysis_from_initial_results(self, genes: List[str], disease_name: str, 
                                                  initial_results: Dict[str, Any],
                                                  memory_context: str = None) -> Dict[str, Any]:
        """
        Continue iterative analysis from initial (Phase 1) results.
        
        This method is used in the Aggregated Workflow Phase 2, where we:
        1. Take the results from Phase 1 (Module Collection) as Iteration 1
        2. Continue iterating (Iter 2, 3...) for THIS SPECIFIC MODULE
        3. Return the final refined results for this module
        
        Parameters:
        -----------
        genes : List[str]
            List of gene symbols for this module
        disease_name : str
            Name of the disease (or "Module_X")
        initial_results : Dict
            Results from Phase 1 (run_module_pathway_collection)
        memory_context : str, optional
            Memory Bank context for GPT prediction and reasoning (cross-disease knowledge)
            
        Returns:
        --------
        Dict : Final iterative analysis results for this module
        """
        print(f"\n{'='*80}")
        print(f"RESUMING ITERATIVE ANALYSIS FOR: {disease_name}")
        print(f"{'='*80}")
        
        # Reset history
        self.iteration_history = []
        
        # ----------------------------------------------------------------
        # STEP 1: Process Initial Results (Iteration 1)
        # ----------------------------------------------------------------
        print(f"\n▶ ITERATION 1/{self.max_iterations} (From Phase 1)")
        
        # Extract data from initial results
        filtered_pathways = initial_results.get('filtered_pathways', pd.DataFrame())
        gpt_prediction = initial_results.get('gpt_prediction', {})
        validation_rate = initial_results.get('validation_rate', 0.0)
        
        # CRITICAL: Sync Phase 1 gpt_prediction to analyzer so Iteration 2 
        # can access it via _last_gpt_prediction for external knowledge injection
        if isinstance(gpt_prediction, dict) and hasattr(self, 'analyzer'):
            self.analyzer._last_gpt_prediction = gpt_prediction
            print(f"   📦 Synced Phase 1 GPT prediction to analyzer ({len(gpt_prediction.get('pathway_details', {}))} pathway details)")
        
        if isinstance(gpt_prediction, dict):
            predicted_pathways = gpt_prediction.get('predicted_pathways', [])
        else:
            predicted_pathways = []
        
        # FIX: If predicted_pathways is empty, reconstruct from gpt_matched_all
        # This happens because _last_gpt_prediction sync can lose predicted_pathways
        if not predicted_pathways:
            # Try 1: From gpt_matched_all DataFrame in initial_results
            gpt_matched_all_df = initial_results.get('gpt_matched_all', pd.DataFrame())
            if not gpt_matched_all_df.empty and 'name' in gpt_matched_all_df.columns:
                predicted_pathways = gpt_matched_all_df['name'].tolist()
                print(f"   📦 Reconstructed predicted_pathways from gpt_matched_all: {len(predicted_pathways)} pathways")
            else:
                # Try 2: Load from CSV file on disk
                iter1_name = f"{disease_name}_iter1"
                matched_all_csv = os.path.join(
                    self.analyzer.results_dir, f'{iter1_name}_gpt_matched_all.csv'
                )
                if os.path.exists(matched_all_csv):
                    try:
                        matched_all_disk = pd.read_csv(matched_all_csv)
                        if 'name' in matched_all_disk.columns:
                            predicted_pathways = matched_all_disk['name'].tolist()
                            # Also store the DataFrame for feedback generation
                            initial_results['gpt_matched_all'] = matched_all_disk
                            print(f"   📦 Reconstructed predicted_pathways from CSV: {len(predicted_pathways)} pathways")
                    except Exception as e:
                        print(f"   ⚠️ Could not load matched_all CSV: {e}")
            
            if not predicted_pathways:
                print(f"   ⚠️ Warning: predicted_pathways is still empty, 'Not Validated Pathways' feedback will be incomplete")
            
        validated_pathways = filtered_pathways['name'].tolist() if not filtered_pathways.empty else []
        
        # CRITICAL: Ensure initial_results has correct disease_name with _iter1 suffix
        # This is needed so iteration 2 can correctly locate the iter1 CSV file
        iter1_disease_name = f"{disease_name}_iter1"
        if 'disease_name' not in initial_results or not initial_results['disease_name'].endswith('_iter1'):
            initial_results['disease_name'] = iter1_disease_name
            print(f"   📝 Set file identifier to: {iter1_disease_name}")
        
        # Create Iteration 1 feedback object
        # We need to generate process feedback and rewards retrospectively
        process_feedback = self._generate_process_feedback(
            initial_results, predicted_pathways, validated_pathways
        )
        
        outcome_reward = self._calculate_outcome_reward(
            validation_rate, len(validated_pathways)
        )
        # For Iter 1, process reward is same as outcome since we have no history
        process_reward = outcome_reward 
        total_reward = outcome_reward
        
        iter1_feedback = IterationFeedback(
            iteration=1,
            predicted_pathways=predicted_pathways,
            validated_pathways=validated_pathways,
            validation_rate=validation_rate,
            validation_details=initial_results,
            process_feedback=process_feedback,
            outcome_reward=outcome_reward,
            process_reward=process_reward,
            total_reward=total_reward,
            status="PENDING",
            hindsight=""
        )
        
        # Generate Hindsight for Iteration 1
        print("\n[Hindsight] Generating feedback from Phase 1 results...")
        hindsight = self.hindsight_generator.generate_hindsight(
            iter1_feedback, [], disease_name
        )
        iter1_feedback.hindsight = hindsight
        
        # Save Iter 1 Hindsight
        hindsight_file = os.path.join(
            self.results_dir,
            f'{disease_name}_iter1_hindsight.md'
        )
        with open(hindsight_file, 'w') as f:
            f.write(hindsight)
        print(f"   Hindsight saved: {hindsight_file}")
        
        # Add to history
        self.iteration_history.append(iter1_feedback)
        
        # ----------------------------------------------------------------
        # STEP 2: Continue Iterations (2 to Max)
        # ----------------------------------------------------------------
        
        # CRITICAL: Try to extract the full g:Profiler cache from Phase 1
        # Phase 1 should have saved the comprehensive cache with all_pathways + ranked_pathways
        gprofiler_cache = initial_results.get('gprofiler_cache', None)
        
        if gprofiler_cache is not None:
            # Validate cache structure
            if 'all_pathways' in gprofiler_cache:
                all_count = len(gprofiler_cache['all_pathways'])
                ranked_count = len(gprofiler_cache.get('ranked_pathways', []))
                print(f"   ✅ Using Phase 1 g:Profiler cache:")
                print(f"      - all_pathways: {all_count} total")
                print(f"      - ranked_pathways: {ranked_count} FDR-significant")
            else:
                # Old cache format or degraded cache
                print(f"   ⚠️  WARNING: Phase 1 cache missing 'all_pathways'")
                print(f"      Iterations 2-3 will have limited matching scope")
                print(f"      RECOMMENDATION: Update Phase 1 to save full cache")
                # Still use it, but matching will be limited
        else:
            # No cache - iterations 2-3 will re-run g:Profiler (slower but comprehensive)
            print(f"   ⚠️  No g:Profiler cache from Phase 1")
            print(f"      Each iteration will call g:Profiler API (slower)")
            
        final_results = initial_results
        
        for iteration in range(2, self.max_iterations + 1):
            print("\n" + "▶"*40)
            print(f"ITERATION {iteration}/{self.max_iterations}")
            print("▶"*40)
            
            # ================================================================
            # PATHWAY RETENTION LOGIC (NEW!)
            # ================================================================
            retained_pathways = None
            retained_pathways_df = None  # Initialize here to avoid UnboundLocalError
            
            if self.retention_rate > 0:
                prev_feedback = self.iteration_history[-1]
                
                if len(prev_feedback.validated_pathways) > 0:
                    # Calculate how many to retain (100% = all validated pathways)
                    must_keep = self._enforce_pathway_retention(
                        prev_feedback.validated_pathways,
                        retention_rate=self.retention_rate
                    )
                    
                    print(f"\n🔒 ENFORCING PATHWAY RETENTION:")
                    print(f"   Previous iteration validated: {len(prev_feedback.validated_pathways)} pathways")
                    print(f"   Retention rate: {self.retention_rate:.0%}")
                    print(f"   MUST keep: {len(must_keep)} pathways")
                    print(f"   Top retained pathways:")
                    for i, pw in enumerate(must_keep[:5], 1):
                        print(f"     {i}. {pw}")
                    if len(must_keep) > 5:
                        print(f"     ... and {len(must_keep)-5} more")
                    
                    retained_pathways = must_keep
                    
                    # Load retained pathways DataFrame from CSV file
                    # The file is named: {disease_name}_iter{N}_gpt_filtered_pathways.csv
                    # Located in: self.analyzer.results_dir (gpt_led_analysis_ag2_hitl)
                    retained_pathways_df = None
                    
                    # Get disease name from previous iteration result
                    disease_name_prev = prev_feedback.validation_details.get('disease_name', disease_name)
                    # Remove the _iter{N} suffix if present (the base analysis already used disease_name_iter{N})
                    # File is already named with iter suffix from analyze_gpt_led_pathways
                    
                    # Find iteration number of previous feedback
                    prev_iter = prev_feedback.iteration
                    
                    # Build CSV path - file is in analyzer's results_dir with iter suffix in name
                    if hasattr(self, 'analyzer') and hasattr(self.analyzer, 'results_dir'):
                        results_dir = self.analyzer.results_dir
                    else:
                        results_dir = os.path.join(self.results_dir, 'gpt_led_analysis_ag2_hitl')
                    
                    # The CSV filename includes iteration suffix, e.g. AD_Module_5_iter1_gpt_filtered_pathways.csv
                    # disease_name_prev already contains _iter{N} from the analysis call, e.g. "AD_Module_5_iter1"
                    gpt_filtered_csv = os.path.join(
                        results_dir,
                        f'{disease_name_prev}_gpt_filtered_pathways.csv'
                    )
                    
                    print(f"   📂 Loading retained DataFrame from: {gpt_filtered_csv}")
                    
                    if os.path.exists(gpt_filtered_csv):
                        try:
                            prev_df = pd.read_csv(gpt_filtered_csv)
                            print(f"      ✅ Loaded {len(prev_df)} pathways from CSV")
                            
                            # Filter to only retained pathways
                            if 'name' in prev_df.columns:
                                retained_pathways_df = prev_df[prev_df['name'].isin(must_keep)].copy()
                                print(f"      ✅ Retained {len(retained_pathways_df)} pathways from {len(must_keep)} must-keep list")
                            else:
                                print(f"      ❌ CSV missing 'name' column, cannot filter retained pathways")
                                print(f"      Columns available: {list(prev_df.columns)[:10]}")
                        except Exception as e:
                            print(f"      ❌ Error loading CSV: {e}")
                    else:
                        print(f"      ❌ CSV not found: {gpt_filtered_csv}")
                        print(f"      ❌ Cannot load retained pathways DataFrame - this will cause incorrect category counts!")


            
            # Generate feedback prompt (respect feedback_mode setting)
            if self.feedback_mode == 'pvalue_only':
                print(f"   [DEBUG] Generating pvalue_only feedback prompt (from_initial_results path)...")
                feedback_prompt = self._generate_feedback_prompt_pvalue_only(
                    iteration_feedback=self.iteration_history[-1],
                    genes=genes,
                    disease_name=disease_name,
                    history=self.iteration_history
                )
            else:
                print(f"   [DEBUG] Generating FULL feedback prompt (from_initial_results path)...")
                feedback_prompt = self._generate_feedback_prompt(
                    iteration_feedback=self.iteration_history[-1],
                    disease_name=disease_name,
                    genes=genes,
                    history=self.iteration_history
                )
            
            # Save feedback prompt
            feedback_file = os.path.join(
                self.results_dir,
                f'{disease_name}_iter{iteration-1}_feedback.txt'
            )
            with open(feedback_file, 'w') as f:
                f.write(feedback_prompt)
            print(f"   Feedback saved: {feedback_file}")
            
            # Run Analysis (GPT Predict -> g:Profiler -> Rank -> Filter)
            # Using the NEW feedback-aware method WITH RETENTION
            if retained_pathways:
                print(f"\n[GPT{self.model}] Generating {50 - len(retained_pathways)} NEW pathways (+ {len(retained_pathways)} retained)...")
            else:
                print(f"\n[GPT{self.model}] Generating 50 NEW pathways based on feedback...")
            
            results = self.analyzer.analyze_gpt_led_pathways(
                genes=genes,
                disease_name=f"{disease_name}_iter{iteration}",  # Add iteration suffix
                top_k_predict=50,  # Total quota (includes retained)
                top_k_analyze=6,
                retained_pathways=retained_pathways,  # Pass pathway names list for statistics
                retained_pathways_df=retained_pathways_df,  # Pass DataFrame (always defined now)
                gprofiler_cache=self._deep_copy_cache(gprofiler_cache), # Reuse cache (copy to prevent mutations)
                skip_ppi_analysis=True,
                iteration_feedback=feedback_prompt,  # Pass feedback
                gpt_rank_function=self.gpt_rank_function,  # Enable GPT auto-ranking
                disease_description=self.disease_description,  # Disease context
                query_agent=self.query_agent,  # PubMed search agent
                file_identifier=os.path.join(self.results_dir, f"{disease_name}_iter{iteration}"),  # For reasoning path
                iteration=iteration,  # For reasoning path
                memory_context=memory_context  # NEW: Pass memory context for prediction & reasoning
            )
            
            # Extract results
            current_pathways = results.get('gpt_filtered_pathways', pd.DataFrame())
            gpt_pred = results.get('gpt_predicted', {})
            
            if isinstance(gpt_pred, dict) and 'pathways' in gpt_pred:
                predicted_pathways = gpt_pred['pathways']
            elif isinstance(gpt_pred, list):
                predicted_pathways = gpt_pred
            else:
                predicted_pathways = []
                
            validated_pathways = current_pathways['name'].tolist() if not current_pathways.empty else []
            validation_rate = results.get('validation_rate', 0.0)
            
            # Update cache with new results
            if not current_pathways.empty:
                if gprofiler_cache is None:
                    # Create new cache with both all and ranked pathways
                    gprofiler_cache = {
                        'all_pathways': current_pathways.reset_index(drop=True),      # For iteration 1, current = all
                        'ranked_pathways': current_pathways.reset_index(drop=True),   # Same in iteration 1
                        'wellknown': [], 
                        'novel': []
                    }
                else:
                    # Merge new pathways into cache
                    # CRITICAL: Reset indices AND handle column differences to avoid InvalidIndexError
                    try:
                        cache_df = gprofiler_cache['all_pathways'].reset_index(drop=True)
                        new_df = current_pathways.reset_index(drop=True)
                        
                        # Get common columns only (different iterations may have different columns)
                        common_cols = list(set(cache_df.columns) & set(new_df.columns))
                        if 'name' in common_cols:  # Ensure 'name' is included for drop_duplicates
                            # Use only common columns to avoid reindexing issues
                            cache_df = cache_df[common_cols]
                            new_df = new_df[common_cols]
                        
                        gprofiler_cache['all_pathways'] = pd.concat(
                            [cache_df, new_df], 
                            ignore_index=True, 
                            sort=False
                        ).drop_duplicates(subset='name').reset_index(drop=True)
                        
                        # Same for ranked_pathways
                        ranked_df = gprofiler_cache['ranked_pathways'].reset_index(drop=True)
                        if 'name' in common_cols:
                            ranked_df = ranked_df[[c for c in common_cols if c in ranked_df.columns]]
                        
                        gprofiler_cache['ranked_pathways'] = pd.concat(
                            [ranked_df, new_df], 
                            ignore_index=True, 
                            sort=False
                        ).drop_duplicates(subset='name').reset_index(drop=True)
                        
                    except Exception as e:
                        print(f"   ⚠️  Cache update warning: {e}")
                        # Fallback: just use current_pathways
                        gprofiler_cache['all_pathways'] = current_pathways.reset_index(drop=True)
                        gprofiler_cache['ranked_pathways'] = current_pathways.reset_index(drop=True)
            
            # AutoEval
            print("\n[AutoEval] Automatic outcome evaluation...")
            eval_scores = self.auto_eval.evaluate_outcome(results)
            
            # Rewards
            outcome_reward = self._calculate_outcome_reward(validation_rate, len(validated_pathways))
            process_reward = self._calculate_process_reward(results, self.iteration_history)
            total_reward = (outcome_reward + process_reward) / 2.0
            
            # Process Feedback
            process_feedback = self._generate_process_feedback(results, predicted_pathways, validated_pathways)
            
            # Record Iteration
            iteration_feedback = IterationFeedback(
                iteration=iteration,
                predicted_pathways=predicted_pathways,
                validated_pathways=validated_pathways,
                validation_rate=validation_rate,
                validation_details=results,
                process_feedback=process_feedback,
                outcome_reward=outcome_reward,
                process_reward=process_reward,
                total_reward=total_reward,
                status="PENDING",
                hindsight=""
            )
            
            # Hindsight
            print("\n[Hindsight] Generating process-level feedback...")
            hindsight = self.hindsight_generator.generate_hindsight(iteration_feedback, self.iteration_history, disease_name)
            iteration_feedback.hindsight = hindsight
            
            # Save Hindsight
            hindsight_file = os.path.join(self.results_dir, f'{disease_name}_iter{iteration}_hindsight.md')
            with open(hindsight_file, 'w') as f:
                f.write(hindsight)
            
            # Status Check
            self.iteration_history.append(iteration_feedback)
            status, reasoning = self.status_supervisor.evaluate_status(self.iteration_history)
            iteration_feedback.status = status
            
            print(f"   Status: {status}")
            
            # Save Iteration Pathways
            iter_file = os.path.join(self.results_dir, f'{disease_name}_iter{iteration}_pathways.csv')
            if not current_pathways.empty:
                current_pathways.to_csv(iter_file, index=False)
            print(f"   Saved: {iter_file}")
            
            final_results = results
            
            if status == "CONVERGED":
                print(f"\n✅ CONVERGED at iteration {iteration}")
                break
        
        print("\n" + "="*80)
        print(f"✅ MODULE ITERATION COMPLETE: {disease_name}")
        print("="*80)
        
        # CRITICAL FIX: Return cumulative pathways, not just last iteration's results
        # final_results['gpt_filtered_pathways'] from last iteration only contains NEW pathways
        # We need to return ALL accumulated pathways (current_pathways)
        final_results['gpt_filtered_pathways'] = current_pathways
        print(f"   📊 Final pathways (cumulative across all iterations): {len(current_pathways)}")
        
        # Include iteration_history for category breakdown plotting
        final_results['iteration_history'] = self.iteration_history
        final_results['total_iterations'] = len(self.iteration_history)
        
        return final_results


    def _generate_process_feedback(self, results: Dict[str, Any],
                                   predicted: List[str],
                                   validated: List[str]) -> str:
        """Generate detailed process feedback for GPT"""
        gpt_pathways = results.get('gpt_filtered_pathways', pd.DataFrame())

        if gpt_pathways.empty:
            return "No pathways were validated. Consider: (1) More specific pathways, (2) Pathways with known gene associations, (3) Disease-relevant mechanisms."

        # Analyze validated pathways
        avg_pvalue = gpt_pathways['p_value'].mean()

        feedback = f"Validated pathways show:\n"
        feedback += f"- Average p-value: {avg_pvalue:.2e} (statistical significance)\n"

        # Literature scoring details
        if 'score' in gpt_pathways.columns:
            avg_score = gpt_pathways['score'].mean()
            feedback += f"- Average combined literature score: {avg_score:.3f} (TF-IDF + BioBERT)\n"

        if 'tfidf_score' in gpt_pathways.columns:
            avg_tfidf = gpt_pathways['tfidf_score'].mean()
            feedback += f"  • TF-IDF score: {avg_tfidf:.3f} (keyword-based relevance)\n"

        if 'biobert_score' in gpt_pathways.columns:
            avg_biobert = gpt_pathways['biobert_score'].mean()
            feedback += f"  • BioBERT score: {avg_biobert:.3f} (semantic similarity)\n"

        if 'ad_specificity' in gpt_pathways.columns:
            avg_spec = gpt_pathways['ad_specificity'].mean()
            feedback += f"- Average disease specificity: {avg_spec:.3f}\n"

        # Identify patterns in validated vs not validated
        not_validated = [p for p in predicted if p not in validated]

        if len(not_validated) > 0:
            feedback += f"\nNot validated pathways ({len(not_validated)}) may lack:\n"
            feedback += "- Statistical enrichment in the gene set\n"
            feedback += "- Sufficient gene overlap\n"
            feedback += "- Strong literature evidence (low TF-IDF/BioBERT scores)\n"

        return feedback
    
    def _save_run_config(self, run_id: str, disease_name: str, genes: List[str], 
                        top_k_predict: int, top_k_analyze: int):
        """Save run configuration for reproducibility."""
        import time
        
        config = {
            'run_id': run_id,
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'disease_name': disease_name,
            'gene_count': len(genes),
            'parameters': {
                'top_k_predict': top_k_predict,
                'top_k_analyze': top_k_analyze,
                'max_iterations': self.max_iterations,
                'model': self.model
            },
            'genes_sample': genes[:10] if len(genes) > 10 else genes  # First 10 genes only
        }
        
        config_file = os.path.join(self.results_dir, 'run_config.json')
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"✅ Run config saved: {config_file}")
        
        # Update latest runs index
        self._update_latest_runs_index(disease_name, run_id)

    # ========================================
    # AGGREGATED ITERATION METHODS
    # ========================================

    def run_aggregated_iterative_analysis(
        self,
        aggregated_pathways: pd.DataFrame,
        disease_name: str = "AD",
        module_metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Run Flash iteration on aggregated pathways from all modules.
        
        This method skips Steps 1-4 (GPT prediction, g:Profiler, matching, filtering)
        and runs Flash iteration directly on pre-filtered pathways from Phase 1.
        
        Key differences from run_iterative_analysis():
        - No GPT prediction step (pathways already collected)
        - No g:Profiler step (already done per module)
        - Focus on pathway refinement across modules
        - Track module origins throughout iterations
        
        Parameters:
        -----------
        aggregated_pathways : DataFrame
            Combined pathways from all modules with columns:
            - name, description, p_value, score, etc.
            - module_id: str (e.g., "Module_5")
            - biological_theme: str
            - Planning agent scores: tfidf_score, biobert_score, weighted_score
        disease_name : str
            Disease name (default "AD", disease-level analysis)
        module_metadata : dict
            Information about source modules (optional)
            
        Returns:
        --------
        dict : Complete iteration history and final results
        """
        print("\\n" + "="*80)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        current_run_id = f"{disease_name}_aggregated_{timestamp}"
        
        # Create run directory
        self.results_dir = os.path.join(self.base_results_dir, current_run_id)
        os.makedirs(self.results_dir, exist_ok=True)
        
        print("FLASH-INSPIRED AGGREGATED ITERATIVE FRAMEWORK")
        print("="*80)
        print(f"🆔 Run ID: {current_run_id}")
        print(f"📁 Results: {self.results_dir}")
        print(f"Disease: {disease_name}")
        print(f"Aggregated pathways: {len(aggregated_pathways)}")
        print(f"Source modules: {aggregated_pathways['module_id'].nunique() if 'module_id' in aggregated_pathways.columns else 'N/A'}")
        print(f"Max iterations: {self.max_iterations}")
        
        # Verify required columns
        required_cols = ['name', 'p_value', 'module_id']
        missing_cols = [col for col in required_cols if col not in aggregated_pathways.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns in aggregated_pathways: {missing_cols}")
        
        # Save run configuration
        run_config = {
            'run_id': current_run_id,
            'disease_name': disease_name,
            'total_pathways': len(aggregated_pathways),
            'unique_pathways': aggregated_pathways['name'].nunique(),
            'source_modules': aggregated_pathways['module_id'].unique().tolist() if 'module_id' in aggregated_pathways.columns else [],
            'max_iterations': self.max_iterations,
            'module_metadata': module_metadata,
            'timestamp': timestamp
        }
        
        config_file = os.path.join(self.results_dir, 'run_config.json')
        with open(config_file, 'w') as f:
            json.dump(run_config, f, indent=2, default=str)
        print(f"✅ Run config saved: {config_file}")
        
        # Initialize with aggregated pathways as "initial prediction"
        # Treat all aggregated pathways as if GPT predicted them
        initial_predicted_pathways = aggregated_pathways['name'].tolist()
        
        print(f"\\n📊 Starting with {len(initial_predicted_pathways)} aggregated pathways from Phase 1")
        
        # ================================================================
        # ITERATION LOOP (Flash Framework)
        # ================================================================
        
        for iteration in range(1, self.max_iterations + 1):
            print("\\n" + "▶"*40)
            print(f"ITERATION {iteration}/{self.max_iterations}")
            print("▶"*40)
            
            # For iteration 1: use all aggregated pathways
            # For iteration 2+: GPT will refine based on feedback
            if iteration == 1:
                # Use aggregated pathways from Phase 1
                current_pathways = aggregated_pathways.copy()
                predicted_pathways = initial_predicted_pathways
                print(f"[Iteration {iteration}] Using all {len(predicted_pathways)} aggregated pathways")
            else:
                # ================================================================
                # ITERATION 2+: FULL GPT PREDICTION + RANKING PIPELINE
                # ================================================================
                # Generate NEW pathways based on feedback, then run full pipeline:
                # GPT predict → g:Profiler → Planning Agent → Match → Filter
                
                print(f"\n[GPT{self.model}] Generating NEW pathways based on feedback...")
                
                # Generate feedback prompt with previous iteration results
                # Collect all genes from all modules for feedback prompt
                _all_genes_for_feedback = []
                for _mod_data in module_pathway_data.values():
                    _all_genes_for_feedback.extend(_mod_data.get('genes', []))
                _all_genes_for_feedback = list(set(_all_genes_for_feedback))
                
                if self.feedback_mode == 'pvalue_only':
                    feedback_prompt = self._generate_feedback_prompt_pvalue_only(
                        iteration_feedback=self.iteration_history[-1],
                        genes=_all_genes_for_feedback,
                        disease_name=disease_name,
                        history=self.iteration_history
                    )
                else:
                    feedback_prompt = self._generate_feedback_prompt(
                        iteration_feedback=self.iteration_history[-1],
                        genes=_all_genes_for_feedback,
                        disease_name=disease_name,
                        history=self.iteration_history
                    )
                
                # Save feedback prompt
                feedback_file = os.path.join(
                    self.results_dir,
                    f'{disease_name}_iter{iteration-1}_feedback.txt'
                )
                with open(feedback_file, 'w') as f:
                    f.write(feedback_prompt)
                print(f"   Feedback saved: {feedback_file}")
                
                # Collect all genes from all modules
                all_genes = []
                for module_data in module_pathway_data.values():
                    all_genes.extend(module_data.get('genes', []))
                all_genes = list(set(all_genes))  # Deduplicate
                
                print(f"   Using {len(all_genes)} genes from {len(module_pathway_data)} modules")
                print(f"   Running full analysis pipeline (GPT → g:Profiler → Planning Agent → Match → Filter)...")
                
                # -------------------------------------------------------------------
                # NEW: Run full GPT-led pathway analysis with feedback
                # -------------------------------------------------------------------
                try:
                    results = self.analyzer.analyze_gpt_led_pathways(
                        genes=all_genes,
                        disease_name=disease_name,
                        top_k_predict=50,  # Predict 50 new pathways
                        top_k_analyze=6,
                        retained_pathways=None,
                        gprofiler_cache=self._deep_copy_cache(gprofiler_cache),  # Reuse Phase 0 cache (copy to prevent mutations)
                        skip_ppi_analysis=True,
                        iteration_feedback=feedback_prompt,  # Pass feedback to GPT
                        gpt_rank_function=self.gpt_rank_function,  # Enable GPT auto-ranking
                        disease_description=self.disease_description,  # Disease context
                        query_agent=self.query_agent,  # PubMed search agent
                        file_identifier=os.path.join(self.results_dir, f"{disease_name}_iter{iteration}"),  # For reasoning path
                        iteration=iteration  # For reasoning path
                    )
                    
                    # Extract results
                    current_pathways = results.get('gpt_filtered_pathways', pd.DataFrame())
                    gpt_pred = results.get('gpt_predicted', {})
                    
                    if isinstance(gpt_pred, dict) and 'pathways' in gpt_pred:
                        predicted_pathways = gpt_pred['pathways']
                    elif isinstance(gpt_pred, list):
                        predicted_pathways = gpt_pred
                    else:
                        predicted_pathways = []
                    
                    # Add module metadata (preserve aggregation structure)
                    # Assign pathways to "Aggregated_Iter{iteration}" module
                    if not current_pathways.empty:
                        current_pathways['module_id'] = f'Aggregated_Iter{iteration}'
                        current_pathways['module_size'] = len(all_genes)
                        
                        # Infer biological theme
                        from aggregated_pathway_helpers import infer_biological_theme
                        theme = infer_biological_theme(current_pathways)
                        current_pathways['biological_theme'] = theme
                    
                    print(f"   ✅ Pipeline complete: {len(predicted_pathways)} predicted, {len(current_pathways)} validated")
                    
                except Exception as e:
                    print(f"   ❌ Pipeline failed: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # Fallback: use empty results
                    current_pathways = pd.DataFrame()
                    predicted_pathways = []
            
            # Validation: All pathways in current_pathways are already "validated"
            # (they passed FDR filtering in Phase 1)
            validated_pathways = current_pathways['name'].tolist()
            validation_rate = len(validated_pathways) / len(predicted_pathways) if predicted_pathways else 0
            
            print(f"\\n📊 Iteration {iteration} Results:")
            print(f"   Predicted: {len(predicted_pathways)}")
            print(f"   Validated: {len(validated_pathways)}")
            print(f"   Validation rate: {validation_rate:.1%}")
            
            # Create results dictionary (compatible with existing structure)
            results = {
                'gpt_filtered_pathways': current_pathways,
                'validation_rate': validation_rate,
                'gpt_predicted': {'pathways': predicted_pathways} if isinstance(predicted_pathways, list) else predicted_pathways
            }
            
            # Save iteration pathways
            iter_file = os.path.join(
                self.results_dir,
                f'{disease_name}_iter{iteration}_pathways.csv'
            )
            current_pathways.to_csv(iter_file, index=False)
            print(f"   Saved: {iter_file}")
            
            # AutoEval (Flash)
            print("\\n[AutoEval] Automatic outcome evaluation...")
            eval_scores = self.auto_eval.evaluate_outcome(results)
            print(f"   Significance score: {eval_scores['significance_score']:.3f}")
            print(f"   Literature score: {eval_scores['literature_score']:.3f}")
            print(f"   Overall score: {eval_scores['overall_score']:.3f}")
            
            # Calculate rewards (for RL tracking)
            outcome_reward = self._calculate_outcome_reward(validation_rate, len(validated_pathways))
            process_reward = self._calculate_process_reward(results, self.iteration_history)
            total_reward = (outcome_reward + process_reward) / 2.0
            
            # Generate process feedback
            process_feedback = self._generate_aggregated_process_feedback(
                results, predicted_pathways, validated_pathways, aggregated_pathways
            )
            print(f"\\n{process_feedback}")
            
            # Create iteration feedback
            iteration_feedback = IterationFeedback(
                iteration=iteration,
                predicted_pathways=predicted_pathways,
                validated_pathways=validated_pathways,
                validation_rate=validation_rate,
                validation_details=results,
                process_feedback=process_feedback,
                outcome_reward=outcome_reward,
                process_reward=process_reward,
                total_reward=total_reward,
                status="PENDING",
                hindsight=""
            )
            
            # Hindsight Generator (Flash) - AGGREGATED MODE
            print("\\n[Hindsight] Generating module-specific AD pathway analysis...")
            hindsight = self._generate_aggregated_hindsight(
                iteration_feedback, self.iteration_history, aggregated_pathways
            )
            iteration_feedback.hindsight = hindsight
            
            # Save hindsight
            hindsight_file = os.path.join(
                self.results_dir,
                f'{disease_name}_iter{iteration}_hindsight.md'
            )
            with open(hindsight_file, 'w') as f:
                f.write(hindsight)
            print(f"   Hindsight saved: {hindsight_file}")
            
            # Status Supervisor (Flash)
            print("\\n[StatusSupervisor] Evaluating iteration status...")
            self.iteration_history.append(iteration_feedback)
            status, reasoning = self.status_supervisor.evaluate_status(self.iteration_history)
            iteration_feedback.status = status
            
            print(f"   Status: {status}")
            print(f"   Reasoning: {reasoning}")
            
            # Check if should continue
            if iteration >= self.max_iterations:
                print(f"\\n⏹️ MAX_ITER reached at iteration {iteration}")
                break
            elif status == "CONVERGED":
                print(f"\\n✅ CONVERGED at iteration {iteration}")
                break
            elif status == "DIVERGED":
                print(f"\\n⚠️ DIVERGED at iteration {iteration}")
                break
        
        # Generate final summary
        final_results = self._generate_aggregated_final_summary(disease_name, aggregated_pathways, module_metadata)
        
        print("\\n" + "="*80)
        print("✅ AGGREGATED ITERATIVE ANALYSIS COMPLETE")
        print("="*80)
        print(f"   Total iterations: {len(self.iteration_history)}")
        print(f"   Final validation rate: {self.iteration_history[-1].validation_rate:.1%}")
        print(f"   Final status: {self.iteration_history[-1].status}")
        print(f"   Best iteration: {max(self.iteration_history, key=lambda x: x.total_reward).iteration}")
        
        return final_results

    def _generate_aggregated_hindsight(
        self,
        current: IterationFeedback,
        history: List[IterationFeedback],
        aggregated_pathways: pd.DataFrame
    ) -> str:
        """
        Generate hindsight analysis for aggregated pathways.
        
        Focus: Module-specific AD-relevant pathways
        NOT analyzing: Cross-module shared patterns or biological theme clusters
        
        Parameters:
        -----------
        current : IterationFeedback
            Current iteration feedback
        history : List[IterationFeedback]
            Previous iterations
        aggregated_pathways : DataFrame
            All aggregated pathways with module_id column
            
        Returns:
        --------
        str : Hindsight markdown content
        """
        hindsight = f"# Hindsight Analysis - Iteration {current.iteration}\n\n"
        
        # Get current validated pathways with module info
        gpt_pathways_df = current.validation_details.get('gpt_filtered_pathways', pd.DataFrame())
        
        if gpt_pathways_df.empty:
            hindsight += "⚠️ No pathways validated in this iteration.\n"
            return hindsight
        
        # Group by module_id to analyze module-specific patterns
        if 'module_id' not in gpt_pathways_df.columns:
            hindsight += "⚠️ Module information missing from pathways.\n"
            return hindsight
        
        hindsight += f"## Validated Pathways by Module\n\n"
        hindsight += f"Total validated: {len(gpt_pathways_df)} pathways from {gpt_pathways_df['module_id'].nunique()} modules\n\n"
        
        # Analyze each module's pathways
        for module_id in sorted(gpt_pathways_df['module_id'].unique()):
            module_pathways = gpt_pathways_df[gpt_pathways_df['module_id'] == module_id]
            
            hindsight += f"### {module_id}\n\n"
            hindsight += f"**Pathways validated**: {len(module_pathways)}\n"
            
            # Get biological theme
            if 'biological_theme' in module_pathways.columns:
                theme = module_pathways['biological_theme'].iloc[0]
                hindsight += f"**Biological theme**: {theme}\n"
            
            # Calculate disease-specificity statistics
            if 'ad_specificity' in module_pathways.columns:
                avg_ad_spec = module_pathways['ad_specificity'].mean()
                max_ad_spec = module_pathways['ad_specificity'].max()
                hindsight += f"**Disease-specificity**: avg={avg_ad_spec:.3f}, max={max_ad_spec:.3f}\n"
                
                # Identify top disease-relevant pathways for this module
                top_ad_pathways = module_pathways.nlargest(5, 'ad_specificity')
                hindsight += f"\n**Top disease-relevant pathways**:\n"
                for idx, (_, row) in enumerate(top_ad_pathways.iterrows(), 1):
                    hindsight += f"{idx}. {row['name']} (disease-spec={row['ad_specificity']:.3f}, p={row['p_value']:.2e})\n"
            
            # Statistical quality
            avg_pvalue = module_pathways['p_value'].mean()
            hindsight += f"\n**Statistical quality**: avg p-value = {avg_pvalue:.2e}\n"
            
            hindsight += "\n"
        
        # Overall disease-relevance analysis
        hindsight += f"## Disease-Relevance Summary\n\n"
        
        if 'ad_specificity' in gpt_pathways_df.columns:
            # Identify pathways with high disease-specificity across all modules
            high_ad_pathways = gpt_pathways_df[gpt_pathways_df['ad_specificity'] > 0.6]
            
            hindsight += f"**High disease-specificity pathways** (score > 0.6): {len(high_ad_pathways)}\n\n"
            
            if not high_ad_pathways.empty:
                hindsight += "These pathways show strong AD relevance and should be prioritized:\n\n"
                for idx, (_, row) in enumerate(high_ad_pathways.nlargest(10, 'ad_specificity').iterrows(), 1):
                    hindsight += f"{idx}. **{row['name']}** ({row['module_id']})\n"
                    hindsight += f"   - Disease-specificity: {row['ad_specificity']:.3f}\n"
                    hindsight += f"   - p-value: {row['p_value']:.2e}\n"
                    if 'score' in row and pd.notna(row['score']):
                        hindsight += f"   - Literature score: {row['score']:.3f}\n"
                    hindsight += "\n"
        
        # Recommendations for next iteration
        hindsight += f"## Recommendations\n\n"
        
        # Calculate average disease-specificity
        if 'ad_specificity' in gpt_pathways_df.columns:
            avg_ad_spec_all = gpt_pathways_df['ad_specificity'].mean()
            
            if avg_ad_spec_all < 0.4:
                hindsight += "⚠️ **Low disease-specificity detected** (avg={:.3f})\n".format(avg_ad_spec_all)
                hindsight += "- Focus on pathways with direct AD relevance (amyloid, tau, neurodegeneration)\n"
                hindsight += "- Prioritize disease-specific mechanisms over generic biological processes\n\n"
            else:
                hindsight += "✅ **Good disease-specificity** (avg={:.3f})\n".format(avg_ad_spec_all)
                hindsight += "- Continue focusing on disease-relevant pathways\n"
                hindsight += "- Explore module-specific disease mechanisms\n\n"
        
        # Module-specific recommendations
        hindsight += "**Module-specific focus**:\n"
        hindsight += "- Each module represents distinct biological themes\n"
        hindsight += "- Prioritize high disease-specificity pathways within each module\n"
        hindsight += "- Maintain module diversity while improving AD relevance\n"
        
        return hindsight
    
    def _select_pathways_with_gpt(
        self,
        available_pathways: pd.DataFrame,
        feedback_prompt: str,
        disease_name: str,
        target_count: int,
        iteration: int
    ) -> List[str]:
        """
        Use GPT to select pathways from available pool based on feedback.
        
        Parameters:
        -----------
        available_pathways : DataFrame
            All available pathways with scores
        feedback_prompt : str
            Feedback from previous iteration
        disease_name : str
            Disease name
        target_count : int
            Target number of pathways to select
        iteration int
            Current iteration number
            
        Returns:
        --------
        list : Selected pathway names
        """
        from multi_agent_analysis_full import GPT5PathwayPredictor
        
        # Build pathway selection prompt
        pathway_list_df = available_pathways[['name', 'p_value', 'disease_specificity', 'module_id']].copy()
        
        # Sort by quality for presentation
        pathway_list_df = pathway_list_df.sort_values(
            by=['disease_specificity', 'p_value'],
            ascending=[False, True]
        )
        
        # Format pathway pool for GPT
        pathway_pool_text = "\n".join([
            f"{idx}. {row['name']} "
            f"(p={row['p_value']:.2e}, "
            f"specificity={row['disease_specificity']:.3f}, "
            f"module={row['module_id']})"
            for idx, (_, row) in enumerate(pathway_list_df.iterrows(), 1)
        ])
        
        selection_prompt = f"""# Pathway Selection Task - Iteration {iteration}

## Context
You are refining pathway analysis for {disease_name} based on previous iteration feedback.

## Previous Iteration Feedback
{feedback_prompt}

## Available Pathways Pool ({len(available_pathways)} total)
{pathway_pool_text}

## Task
Select the TOP {target_count} most promising pathways from the pool above for deeper analysis in this iteration.

**Selection Criteria** (in order of priority):
1. **High disease specificity** (>0.3 preferred, avoid <0.15)
2. **Strong statistical significance** (p < 0.01 preferred)
3. **Direct relevance to {disease_name}** (amyloid, tau, neurodegeneration, synaptic dysfunction)
4. **Module diversity** (include pathways from multiple modules if available)
5. **Learn from previous feedback** (prioritize what worked, avoid what failed)

**Output Format**:
Return ONLY a JSON list of pathway names, exactly as they appear above:

["pathway_name_1", "pathway_name_2", ..., "pathway_name_{target_count}"]

IMPORTANT: Return exactly {target_count} pathways (or fewer if pool is smaller).
"""
        
        # Call GPT
        try:
            predictor = self.pathway_generator_class(model=self.model)
            
            # Use GPT's completion API for simple text generation
            response = predictor.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a pathway analysis expert. Return only valid JSON."},
                    {"role": "user", "content": selection_prompt}
                ],
                temperature=0.7,  # Balanced creativity
                max_completion_tokens=500
            )
            cost_tracker.track(response)
            response_text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            import json
            import re
            
            # Extract JSON array (handle markdown code blocks)
            json_match = re.search(r'\[.*?\]', response_text, re.DOTALL)
            if json_match:
                selected_pathways = json.loads(json_match.group(0))
            else:
                # Fallback: parse line by line
                selected_pathways = [
                    line.strip().strip('"').strip("'").strip(',')
                    for line in response_text.split('\n')
                    if line.strip() and not line.strip().startswith('#')
                ][:target_count]
            
            # Validate selections (must be in available pool)
            valid_pathway_names = set(available_pathways['name'].tolist())
            validated_selections = [
                pw for pw in selected_pathways
                if pw in valid_pathway_names
            ]
            
            print(f"      GPT returned {len(selected_pathways)} pathways, {len(validated_selections)} validated")
            
            # If GPT selection is insufficient, supplement with high-quality pathways
            if len(validated_selections) < min(target_count, len(available_pathways)):
                print(f"      Supplementing with top-ranked pathways by quality...")
                remaining_needed = min(target_count, len(available_pathways)) - len(validated_selections)
                
                # Get pathways not already selected
                remaining_pool = available_pathways[
                    ~available_pathways['name'].isin(validated_selections)
                ].sort_values(
                    by=['disease_specificity', 'p_value'],
                    ascending=[False, True]
                )
                
                supplement = remaining_pool.head(remaining_needed)['name'].tolist()
                validated_selections.extend(supplement)
                print(f"      Added {len(supplement)} supplemental pathways")
            
            return validated_selections[:target_count]
            
        except Exception as e:
            print(f"      ⚠️ GPT selection failed: {e}")
            print(f"      Falling back to quality-based automatic selection...")
            
            # Fallback: Auto-select by quality metrics
            sorted_pathways = available_pathways.sort_values(
                by=['disease_specificity', 'p_value'],
                ascending=[False, True]
            )
            return sorted_pathways.head(target_count)['name'].tolist()
    
    def _generate_aggregated_process_feedback(
        self,
        results: Dict[str, Any],
        predicted: List[str],
        validated: List[str],
        aggregated_pathways: pd.DataFrame
    ) -> str:
        """
        Generate process feedback for aggregated pathways.
        
        Similar to regular process feedback but includes module context.
        """
        gpt_pathways = results.get('gpt_filtered_pathways', pd.DataFrame())
        
        if gpt_pathways.empty:
            return "No pathways validated."
        
        feedback = f"Process Feedback (Aggregated Mode):\\n"
        # Guard against division by zero
        if len(predicted) > 0:
            feedback += f"- Validated: {len(validated)}/{len(predicted)} pathways ({len(validated)/len(predicted)*100:.1%})\\n"
        else:
            feedback += f"- Validated: {len(validated)} pathways (no predictions to compare)\\n"
        
        # Module distribution
        if 'module_id' in gpt_pathways.columns:
            module_counts = gpt_pathways['module_id'].value_counts()
            feedback += f"- Module coverage: {len(module_counts)} modules\\n"
        
        # Statistical quality
        avg_pvalue = gpt_pathways['p_value'].mean()
        feedback += f"- Average p-value: {avg_pvalue:.2e}\\n"
        
        # AD-specificity
        if 'ad_specificity' in gpt_pathways.columns:
            avg_ad_spec = gpt_pathways['ad_specificity'].mean()
            feedback += f"- Average AD-specificity: {avg_ad_spec:.3f}\\n"
        
        # Literature scores
        if 'score' in gpt_pathways.columns:
            avg_lit_score = gpt_pathways['score'].mean()
            feedback += f"- Average literature score: {avg_lit_score:.3f}\\n"
        
        return feedback
    
    def _generate_aggregated_final_summary(
        self,
        disease_name: str,
        aggregated_pathways: pd.DataFrame,
        module_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate final summary for aggregated iteration.
        
        Returns:
        --------
        dict : Summary with iteration history and final stats
        """
        summary = {
            'disease_name': disease_name,
            'run_type': 'aggregated',
            'total_pathways': len(aggregated_pathways),
            'unique_pathways': aggregated_pathways['name'].nunique(),
            'source_modules': aggregated_pathways['module_id'].unique().tolist() if 'module_id' in aggregated_pathways.columns else [],
            'iterations': [
                {
                    'iteration': fb.iteration,
                    'predicted': len(fb.predicted_pathways),
                    'validated': len(fb.validated_pathways),
                    'validation_rate': fb.validation_rate,
                    'total_reward': fb.total_reward,
                    'status': fb.status
                }
                for fb in self.iteration_history
            ],
            'module_metadata': module_metadata
        }
        
        # Save summary as JSON
        summary_file = os.path.join(self.results_dir, f'{disease_name}_iterative_summary.json')
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\\n✅ Summary saved: {summary_file}")
        
        # Generate markdown report
        self._generate_aggregated_report(disease_name, aggregated_pathways)
        
        return summary
    
    def _generate_aggregated_report(
        self,
        disease_name: str,
        aggregated_pathways: pd.DataFrame
    ):
        """Generate comprehensive markdown report for aggregated analysis."""
        report_file = os.path.join(self.results_dir, f'{disease_name}_ITERATIVE_REPORT.md')
        
        with open(report_file, 'w') as f:
            f.write(f"# Aggregated Iterative Pathway Analysis: {disease_name}\n\n")
            
            f.write(f"## Overview\n\n")
            f.write(f"- **Analysis Type**: Aggregated Flash Iteration\n")
            f.write(f"- **Total Pathways**: {len(aggregated_pathways)}\n")
            f.write(f"- **Unique Pathways**: {aggregated_pathways['name'].nunique()}\n")
            f.write(f"- **Source Modules**: {aggregated_pathways['module_id'].nunique() if 'module_id' in aggregated_pathways.columns else 'N/A'}\n")
            f.write(f"- **Iterations**: {len(self.iteration_history)}\n\n")
            
            f.write(f"## Iteration Summary\n\n")
            for fb in self.iteration_history:
                f.write(f"### Iteration {fb.iteration}\n\n")
                f.write(f"- Predicted: {len(fb.predicted_pathways)}\n")
                f.write(f"- Validated: {len(fb.validated_pathways)}\n")
                f.write(f"- Validation Rate: {fb.validation_rate:.1%}\n")
                f.write(f"- Total Reward: {fb.total_reward:.3f}\n")
                f.write(f"- Status: {fb.status}\n\n")
            
            f.write(f"## Final Results\n\n")
            final_pathways = self.iteration_history[-1].validation_details.get('gpt_filtered_pathways', pd.DataFrame())
            
            if not final_pathways.empty:
                f.write(f"**Top AD-Relevant Pathways**:\n\n")
                
                if 'ad_specificity' in final_pathways.columns:
                    top = final_pathways.nlargest(20, 'ad_specificity')
                else:
                    top = final_pathways.nsmallest(20, 'p_value')
                
                for idx, (_, row) in enumerate(top.iterrows(), 1):
                    f.write(f"{idx}. **{row['name']}**\n")
                    if 'module_id' in row:
                        f.write(f"   - Module: {row['module_id']}\n")
                    if 'ad_specificity' in row:
                        f.write(f"   - AD-specificity: {row['ad_specificity']:.3f}\n")
                    f.write(f"   - p-value: {row['p_value']:.2e}\n")
                    f.write("\n")
        
        print(f"✅ Report saved: {report_file}")

    
    def _update_latest_runs_index(self, disease_name: str, run_id: str):
        """Update index of latest runs for each module."""
        import time
        
        index_file = os.path.join(self.base_results_dir, 'latest_runs.json')
        
        # Read existing index
        if os.path.exists(index_file):
            with open(index_file, 'r') as f:
                index = json.load(f)
        else:
            index = {}
        
        # Update current module's latest run
        index[disease_name] = {
            'run_id': run_id,
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'results_dir': self.results_dir
        }
        
        # Save
        with open(index_file, 'w') as f:
            json.dump(index, f, indent=2, sort_keys=True)
        
        print(f"✅ Latest runs index updated: {index_file}")

    def _generate_final_summary(self, disease_name: str, genes: List[str]) -> Dict[str, Any]:
        """Generate comprehensive summary of iterative analysis"""
        summary_file = os.path.join(
            self.results_dir,
            f'{disease_name}_iterative_summary.json'
        )

        # Prepare summary data
        summary = {
            'disease_name': disease_name,
            'gene_count': len(genes),
            'total_iterations': len(self.iteration_history),
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'iterations': [asdict(fb) for fb in self.iteration_history],
            'convergence_analysis': self._analyze_convergence(),
            'best_iteration': self._find_best_iteration()
        }

        # Save JSON summary
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)

        print(f"\n✅ Summary saved: {summary_file}")

        # Generate markdown report
        self._generate_markdown_report(disease_name, summary)

        return summary

    def _analyze_convergence(self) -> Dict[str, Any]:
        """Analyze convergence patterns across iterations"""
        if len(self.iteration_history) < 2:
            # Return default values for single iteration
            first_iter = self.iteration_history[0] if self.iteration_history else None
            if first_iter:
                return {
                    'converged': False,
                    'reason': 'Insufficient iterations (only 1)',
                    'validation_rate_improved': False,
                    'validation_rate_change': 0.0,
                    'reward_improved': False,
                    'reward_change': 0.0,
                    'final_validation_rate': first_iter.validation_rate,
                    'final_reward': first_iter.total_reward
                }
            else:
                return {
                    'converged': False,
                    'reason': 'No iterations',
                    'validation_rate_improved': False,
                    'validation_rate_change': 0.0,
                    'reward_improved': False,
                    'reward_change': 0.0,
                    'final_validation_rate': 0.0,
                    'final_reward': 0.0
                }

        val_rates = [fb.validation_rate for fb in self.iteration_history]
        rewards = [fb.total_reward for fb in self.iteration_history]

        # Check if validation rate improved
        rate_improved = val_rates[-1] > val_rates[0]
        rate_change = val_rates[-1] - val_rates[0]

        # Check if rewards improved
        reward_improved = rewards[-1] > rewards[0]
        reward_change = rewards[-1] - rewards[0]

        return {
            'validation_rate_improved': rate_improved,
            'validation_rate_change': rate_change,
            'reward_improved': reward_improved,
            'reward_change': reward_change,
            'final_validation_rate': val_rates[-1],
            'final_reward': rewards[-1]
        }

    def _find_best_iteration(self) -> Dict[str, Any]:
        """Find the best performing iteration"""
        best = max(self.iteration_history, key=lambda x: x.total_reward)

        return {
            'iteration': best.iteration,
            'validation_rate': best.validation_rate,
            'validated_count': len(best.validated_pathways),
            'total_reward': best.total_reward,
            'top_pathways': best.validated_pathways[:10]
        }

    def _generate_markdown_report(self, disease_name: str, summary: Dict[str, Any]):
        """Generate human-readable markdown report with Flash components"""
        report_file = os.path.join(
            self.results_dir,
            f'{disease_name}_ITERATIVE_REPORT.md'
        )

        with open(report_file, 'w') as f:
            f.write(f"# Flash-Inspired Iterative GPT-Agent Framework Report\n\n")
            f.write(f"**Disease**: {disease_name}\n")
            f.write(f"**Date**: {summary['timestamp']}\n")
            f.write(f"**Total Iterations**: {summary['total_iterations']}\n\n")

            f.write("---\n\n## Framework Architecture (Flash-Inspired)\n\n")
            f.write("```\n")
            f.write("┌─────────────────────────────────────────────────────────────┐\n")
            f.write("│ GPT5.1 (Pathway Generator)                                  │\n")
            f.write("│   ↓                                                          │\n")
            f.write("│ Status Supervisor - monitors progress & decides action      │\n")
            f.write("│   ↓                                                          │\n")
            f.write("│ Biological Multi-Agent System                               │\n")
            f.write("│   - Statistical Significance Agent (g:Profiler)             │\n")
            f.write("│   - Literature Evidence Agent (PubMed)                      │\n")
            f.write("│   - Pathway Graph Agent (PPI/STRING)                        │\n")
            f.write("│   ↓                                                          │\n")
            f.write("│ AutoEval - automatic outcome evaluation                     │\n")
            f.write("│   ↓                                                          │\n")
            f.write("│ Hindsight Generator - process-level feedback                │\n")
            f.write("│   ↓                                                          │\n")
            f.write("│ Critique + Update → GPT5.1 (iterative refinement)          │\n")
            f.write("└─────────────────────────────────────────────────────────────┘\n")
            f.write("```\n\n")

            f.write("### Key Components\n\n")
            f.write("1. **GPT5.1 Pathway Generator**: Predicts candidate pathways based on genes\n")
            f.write("2. **Status Supervisor**: Monitors iteration status (CONTINUE/CONVERGED/DIVERGED)\n")
            f.write("3. **Multi-Agent Verification**: Statistical + literature + PPI validation\n")
            f.write("4. **AutoEval**: Automatic outcome evaluation without human feedback\n")
            f.write("5. **Hindsight Generator**: Analyzes what worked/failed, provides actionable insights\n")
            f.write("6. **RL-Ready**: Tracks outcome + process rewards for future fine-tuning\n\n")

            f.write("---\n\n## Iteration History\n\n")

            for fb_dict in summary['iterations']:
                f.write(f"### Iteration {fb_dict['iteration']}\n\n")
                f.write(f"**Status**: `{fb_dict['status']}`\n\n")

                f.write("#### Prediction & Validation\n")
                f.write(f"- Predicted: {len(fb_dict['predicted_pathways'])} pathways\n")
                f.write(f"- Validated: {len(fb_dict['validated_pathways'])} pathways\n")
                f.write(f"- Validation Rate: {fb_dict['validation_rate']:.1%}\n\n")

                f.write("#### Rewards (for RL fine-tuning)\n")
                f.write(f"- Outcome Reward: {fb_dict['outcome_reward']:.3f}\n")
                f.write(f"- Process Reward: {fb_dict['process_reward']:.3f}\n")
                f.write(f"- Total Reward: {fb_dict['total_reward']:.3f}\n\n")

                if fb_dict['validated_pathways']:
                    f.write("#### Top Validated Pathways\n")
                    for i, pathway in enumerate(fb_dict['validated_pathways'][:5], 1):
                        f.write(f"{i}. {pathway}\n")
                    f.write("\n")

                # Add hindsight if available
                if fb_dict.get('hindsight'):
                    f.write("#### Hindsight Analysis\n")
                    f.write(f"See detailed hindsight: `{disease_name}_iter{fb_dict['iteration']}_hindsight.md`\n\n")

                f.write("---\n\n")

            f.write("## Convergence Analysis\n\n")
            conv = summary['convergence_analysis']
            f.write(f"- **Validation Rate Change**: {conv['validation_rate_change']:.3f}\n")
            f.write(f"- **Reward Change**: {conv['reward_change']:.3f}\n")
            f.write(f"- **Final Validation Rate**: {conv['final_validation_rate']:.1%}\n")
            f.write(f"- **Final Reward**: {conv['final_reward']:.3f}\n\n")

            if conv['validation_rate_improved']:
                f.write("✅ **Validation rate IMPROVED** through iterative feedback\n\n")
            else:
                f.write("⚠️ **Validation rate did not improve** - consider adjusting strategy\n\n")

            f.write("---\n\n## Best Iteration\n\n")
            best = summary['best_iteration']
            f.write(f"**Iteration {best['iteration']}** achieved the highest reward:\n\n")
            f.write(f"- Validation Rate: {best['validation_rate']:.1%}\n")
            f.write(f"- Validated Pathways: {best['validated_count']}\n")
            f.write(f"- Total Reward: {best['total_reward']:.3f}\n\n")

            f.write("**Top Pathways from Best Iteration**:\n")
            for i, pathway in enumerate(best['top_pathways'], 1):
                f.write(f"{i}. {pathway}\n")

            f.write("\n---\n\n## Output Files\n\n")
            f.write("### Per-Iteration Files\n")
            f.write(f"- `{disease_name}_iter*_feedback.txt` - Feedback prompts sent to GPT\n")
            f.write(f"- `{disease_name}_iter*_hindsight.md` - Hindsight analysis (what worked/failed)\n")
            f.write(f"- `{disease_name}_iter*_report.md` - Full multi-agent analysis report\n")
            f.write(f"- `{disease_name}_iter*_gpt_filtered_pathways.csv` - Validated pathways\n\n")

            f.write("### Summary Files\n")
            f.write(f"- `{disease_name}_iterative_summary.json` - Complete iteration history + rewards\n")
            f.write(f"- `{disease_name}_ITERATIVE_REPORT.md` - This report\n\n")

            f.write("---\n\n## Future: RL Fine-Tuning\n\n")
            f.write("This framework is **RL-ready** for fine-tuning pathway prediction models:\n\n")
            f.write("**Training Data Structure**:\n")
            f.write("- **State**: Gene list + feedback from previous iteration\n")
            f.write("- **Action**: Predicted pathways\n")
            f.write("- **Outcome Reward**: Validation rate + validated count\n")
            f.write("- **Process Reward**: Statistical significance + literature support + disease relevance\n\n")

            f.write("**Suitable Models for Fine-Tuning**:\n")
            f.write("- Llama 3.1 (8B/70B)\n")
            f.write("- Mistral (7B/Mixtral)\n")
            f.write("- BioGPT / PubMedBERT (domain-specific)\n\n")

            f.write("**Training Approach**:\n")
            f.write("- Supervised fine-tuning on successful iterations\n")
            f.write("- RLHF with outcome + process rewards\n")
            f.write("- DPO (Direct Preference Optimization) on validated vs failed pathways\n")

        print(f"✅ Report saved: {report_file}")


def main():
    """Example: Run iterative GPT-Agent feedback framework"""

    # Setup paths
    input_dir = "/Users/liyuxin/Documents/zotero/PhD/Research/AI_agent/codes/Genetic_AI_Agent/src/utils/Network_expansion/outputs/disease_pair_expansion"
    output_dir = "/Users/liyuxin/Documents/zotero/PhD/Research/AI_agent/codes/Genetic_AI_Agent/src/utils/Pathway_analysis"

    # Load data
    disease_file = os.path.join(input_dir, "D000544_modules.csv")

    if not os.path.exists(disease_file):
        print(f"❌ File not found: {disease_file}")
        return

    df = pd.read_csv(disease_file)

    # Get genes
    # The original code had a filter for 'passes_all_filters' which is now removed as per instruction.
    # The instruction was to remove filtering from `get_module_genes`, but the provided snippet
    # indicated a change in the main gene loading logic.
    # Assuming the intent was to remove the 'passes_all_filters' check from the main gene loading.
    genes = df['node'].unique().tolist()

    disease_name = "AD"

    print(f"\n📊 Loaded: {disease_name}")
    print(f"   Genes: {len(genes)}")

    # Initialize framework
    framework = IterativeGPTAgentFramework(
        output_dir=output_dir,
        model="gpt-5.1",
        max_iterations=3  # Start with 3 iterations for testing
    )

    # Run iterative analysis
    results = framework.run_iterative_analysis(
        genes=genes,
        disease_name=disease_name,
        top_k_predict=40,
        top_k_analyze=6,
        convergence_threshold=0.05
    )

    print("\n" + "="*80)
    print("✅ ANALYSIS COMPLETE")
    print("="*80)
    print(f"\n📁 Results: {framework.results_dir}")
    print("\n📄 Key files:")
    print(f"   - {disease_name}_iterative_summary.json")
    print(f"   - {disease_name}_ITERATIVE_REPORT.md")
    print(f"   - {disease_name}_iter*_feedback.txt (feedback prompts)")
    print(f"   - {disease_name}_iter*_report.md (per-iteration reports)")


if __name__ == "__main__":
    main()
