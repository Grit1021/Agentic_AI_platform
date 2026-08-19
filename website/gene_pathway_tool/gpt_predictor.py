import json
import re
import sys
import openai

from .config import OPENAI_API_KEY, GPT_MODEL, CATEGORIES, SYSTEM_PROMPTS
from .reasoning_parser import parse_reasoning_from_response


def gpt_predict_pathways(genes: list, disease_name: str, disease_description: str, iteration: int = 1) -> tuple:
    all_pathways = []
    pathway_details = {}
    reasoning_by_category = {}

    print(f"  GPT predicting pathways for {disease_name}...")
    sys.stdout.flush()

    for category_code, category_name in CATEGORIES:
        print(f"     [{category_code}] Generating...", flush=True)

        system_prompt = SYSTEM_PROMPTS.get(category_code, f"You are an expert in {disease_name} and {category_name} pathways.")

        prompt = f"""TASK: Analyze the provided gene list as a functional module for {disease_name}.
Identify the top 10 {category_name} terms/pathways that best describe this module.

INPUT GENES: {', '.join(genes)}
DISEASE: {disease_name}
CONTEXT: {disease_description[:300] if disease_description else 'Not available'}

REQUIREMENTS:
1. Provide EXACTLY 10 terms/pathways.
2. Use EXACT OFFICIAL database names. This is CRITICAL for matching.
   - GO:BP example: "response to oxidative stress" (NOT "oxidative stress response")
   - KEGG example: "mTOR signaling pathway" (NOT "mTOR pathway")
3. Provide the official ID if possible (e.g., "GO:0006979", "KEGG:hsa04064").
4. Avoid extremely generic terms (e.g., "Signaling", "Disease", "Metabolic process") unless absolutely necessary.

RETURN FORMAT (JSON):
{{
  "pathways": [
    {{
      "name": "Official Name 1",
      "id": "ID1",
      "rationale": "Why this pathway..."
    }},
    ...
  ]
}}"""

        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt + " Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_completion_tokens=2000
            )

            response_text = response.choices[0].message.content

            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()

            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError:
                json_match = re.search(r'\{.*"pathways".*\}', response_text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                else:
                    print(f"     [{category_code}] Could not parse JSON", flush=True)
                    continue

            for pw in parsed.get('pathways', []):
                name = pw.get('name', '') if isinstance(pw, dict) else str(pw)
                pw_id = pw.get('id', '') if isinstance(pw, dict) else ''

                if name and name not in all_pathways:
                    all_pathways.append(name)
                    pathway_details[name] = {
                        'name': name,
                        'id': pw_id,
                        'source': category_code,
                        'rationale': pw.get('rationale', '') if isinstance(pw, dict) else ''
                    }

            cat_count = len([p for p in all_pathways if pathway_details.get(p, {}).get('source') == category_code])
            print(f"     [{category_code}] {cat_count} pathways", flush=True)

            reasoning = _generate_reasoning_iter1(
                client, genes, disease_name, category_code, category_name, cat_count
            )
            reasoning_by_category[category_code] = reasoning

        except Exception as e:
            print(f"     [{category_code}] Error: {str(e)}", flush=True)
            continue

    print(f"  GPT prediction complete: {len(all_pathways)} pathways", flush=True)
    return all_pathways, pathway_details, reasoning_by_category


def _generate_reasoning_iter1(client, genes, disease_name, category_code, category_name, cat_count):
    try:
        genes_str = ', '.join(genes[:30]) + ("..." if len(genes) > 30 else "")
        reasoning_prompt = f"""Provide detailed reasoning for your pathway predictions in the {category_name} ({category_code}) category.

CONTEXT:
- Disease: {disease_name}
- Input Genes ({len(genes)} total): {genes_str}
- Category: {category_code} - {category_name}
- Pathways Predicted: {cat_count}

Your response must explain HOW you analyzed the genes and WHY you predicted specific pathways.

Respond using markdown ## headers for EACH section below. Include ALL sections even if N/A for this iteration.

## Overall Strategy
[3-4 sentences explaining your analytical approach.]

## Gene Analysis
[3-4 sentences describing the dominant functional themes you observe.]

## Database Focus
[2-3 sentences on why {category_code} is appropriate.]

## Key Gene Functions
[3-4 sentences on specific genes and their annotations.]

## Pathway Selection Rationale
[3-4 sentences on which terms you selected and why.]

## Biological Evidence
[2-3 sentences on experimental or literature evidence.]

## Learned from Previous Iteration
N/A (First iteration or no feedback)

## Pathway Guidance
N/A

## Category-Specific Adjustments
N/A

## Validation Reflection
N/A (Iteration 2+ only)

## Failure Analysis
N/A (Iteration 2+ only)

## Bottleneck Diagnosis
N/A (Iteration 2+ only)

## Cell Context
[2-3 sentences identifying primary cell types and tissues.]

## Relevance Strength with Disease
[High/Medium/Low] - [2-3 sentences assessing confidence.]

IMPORTANT: Provide DETAILED, SPECIFIC analysis."""

        reasoning_response = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": f"You are a bioinformatics expert explaining your reasoning for {category_name} pathway predictions. Use ## markdown headers for each section."},
                {"role": "user", "content": reasoning_prompt}
            ],
            temperature=0,
            max_completion_tokens=16000
        )

        reasoning_text = reasoning_response.choices[0].message.content or ""
        category_reasoning = parse_reasoning_from_response(reasoning_text)

        if category_reasoning:
            return category_reasoning

    except Exception as e:
        print(f"     [{category_code}] Reasoning error: {str(e)[:50]}", flush=True)

    return {
        'overall_strategy': f"Generated {cat_count} {category_name} predictions for {disease_name}",
        'relevance_strength_with_disease': 'Medium'
    }


def gpt_predict_pathways_with_context(genes: list, disease_name: str, disease_description: str,
                                       retained_pathways: list, iteration: int = 2) -> tuple:
    all_pathways = []
    pathway_details = {}
    reasoning_by_category = {}

    print(f"  GPT predicting with context ({len(retained_pathways)} retained pathways)...", flush=True)

    retained_names = []
    for p in retained_pathways:
        if isinstance(p, dict):
            name = p.get('name', p.get('pathway_name', ''))
            if name:
                retained_names.append(name)

    context_pathways = retained_names[:20]
    context_str = "\n".join([f"  - {name}" for name in context_pathways]) if context_pathways else "No retained pathways yet."

    categories = {
        'GO:BP': 'Gene Ontology Biological Processes',
        'GO:MF': 'Gene Ontology Molecular Functions',
        'GO:CC': 'Gene Ontology Cellular Components',
        'KEGG': 'KEGG Pathways',
        'REAC': 'Reactome Pathways'
    }

    system_prompt = f"""You are an expert bioinformatician with deep knowledge of {disease_name} pathology.

Your task: Generate NEW pathway predictions that are DIFFERENT from the already validated pathways provided.

CONTEXT - Previously Validated Pathways (DO NOT REPEAT):
{context_str}

Strategy:
1. Analyze new biological themes not covered by retained pathways
2. Explore complementary mechanisms in {disease_name}
3. Predict pathways that work synergistically with validated ones
4. Focus on statistically likely pathways based on gene set

CRITICAL: Avoid predicting pathways that overlap significantly with the retained list."""

    for category_code, category_name in categories.items():
        prompt = f"""For the disease {disease_name} and input genes, predict 10 NEW {category_name} pathways.

Disease Description: {disease_description[:300] if disease_description else 'Not available'}

INPUT GENES: {', '.join(genes[:50])}{'...' if len(genes) > 50 else ''}

PREVIOUSLY VALIDATED (DO NOT REPEAT):
{context_str}

Return EXACTLY in this JSON format:
{{
  "pathways": [
    {{"name": "exact pathway name", "id": "GO:XXXXX or pathway ID"}},
    ...
  ]
}}"""

        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt + " Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_completion_tokens=2000
            )

            response_text = response.choices[0].message.content

            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()

            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError:
                json_match = re.search(r'\{.*"pathways".*\}', response_text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                else:
                    continue

            for pw in parsed.get('pathways', []):
                name = pw.get('name', '') if isinstance(pw, dict) else str(pw)
                pw_id = pw.get('id', '') if isinstance(pw, dict) else ''

                name_lower = name.lower().strip()
                if any(name_lower == r.lower().strip() for r in retained_names):
                    continue

                if name and name not in all_pathways:
                    all_pathways.append(name)
                    pathway_details[name] = {
                        'name': name,
                        'id': pw_id,
                        'source': category_code,
                        'iteration_type': 'new_prediction'
                    }

            cat_count = len([p for p in all_pathways if pathway_details.get(p, {}).get('source') == category_code])
            print(f"     [{category_code}] {cat_count} NEW pathways", flush=True)

            cat_retained = [p.get('name', '') for p in retained_pathways if p.get('source') == category_code]
            reasoning = _generate_reasoning_iter2(
                client, genes, disease_name, category_code, category_name,
                cat_count, cat_retained, context_str
            )
            reasoning_by_category[category_code] = reasoning

        except Exception as e:
            print(f"     [{category_code}] Error: {str(e)[:50]}", flush=True)
            continue

    print(f"  GPT context prediction complete: {len(all_pathways)} NEW pathways", flush=True)
    return all_pathways, pathway_details, reasoning_by_category


def _generate_reasoning_iter2(client, genes, disease_name, category_code, category_name,
                               cat_count, cat_retained, context_str):
    cat_retained_str = "\n".join([f"  - {name}" for name in cat_retained[:10]]) if cat_retained else "None"
    try:
        reasoning_prompt = f"""Provide detailed reasoning for iteration 2 pathway predictions in {category_name} ({category_code}).

CONTEXT:
- Disease: {disease_name}
- Iteration: 2 (building on iteration 1 validated results)
- Category: {category_code}
- Retained {category_code} pathways from iteration 1 ({len(cat_retained)}):
{cat_retained_str}
- NEW predictions generated: {cat_count}

Respond using markdown ## headers for EACH section below. Include ALL sections with substantive content.

## Overall Strategy
[3-4 sentences on your approach for generating NEW predictions.]

## Gene Analysis
[3-4 sentences re-examining genes in light of iteration 1 results.]

## Database Focus
[2-3 sentences on why {category_code} is appropriate.]

## Key Gene Functions
[3-4 sentences on which genes drove successful predictions.]

## Pathway Selection Rationale
[3-4 sentences on which NEW terms you selected and why.]

## Biological Evidence
[2-3 sentences on evidence for NEW predictions.]

## Learned from Previous Iteration
[3-4 sentences on patterns from retained terms.]

## Pathway Guidance
[3-4 sentences on how retained pathways inform NEW predictions.]

## Category-Specific Adjustments
[3-4 sentences on specific adjustments for {category_code}.]

## Validation Reflection
[2-3 sentences on validated vs non-validated pathways.]

## Failure Analysis
[2-3 sentences on why certain predictions failed.]

## Bottleneck Diagnosis
[2-3 sentences on underperformance diagnosis.]

## Cell Context
[2-3 sentences identifying primary cell types and tissues.]

## Relevance Strength with Disease
[High/Medium/Low] - [2-3 sentences assessing confidence.]

IMPORTANT: Provide DETAILED, MECHANISTIC analysis."""

        reasoning_response = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": f"You are a bioinformatics expert explaining detailed iterative reasoning for {category_name} pathway predictions. Use ## markdown headers for each section."},
                {"role": "user", "content": reasoning_prompt}
            ],
            temperature=0,
            max_completion_tokens=16000
        )

        reasoning_text = reasoning_response.choices[0].message.content or ""
        if reasoning_text.strip():
            category_reasoning = parse_reasoning_from_response(reasoning_text)
            if category_reasoning:
                return category_reasoning

    except Exception as e:
        print(f"     [{category_code}] Reasoning error: {str(e)[:50]}", flush=True)

    return {
        'overall_strategy': f"Generated {cat_count} NEW {category_name} predictions based on {len(cat_retained)} retained pathways",
        'learned_from_previous_iteration': f"Retained pathways ({', '.join(cat_retained[:3])}) indicate core biological themes",
        'pathway_guidance': f"Built on validated {category_code} themes to explore related mechanisms",
        'category_specific_adjustments': f'Focused on pathways mechanistically linked to retained terms',
        'relevance_strength_with_disease': 'Medium - predictions built on validated iteration 1 patterns'
    }
