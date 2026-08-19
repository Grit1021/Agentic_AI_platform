import re

KNOWN_KEYS = [
    'overall_strategy', 'strategy', 'gene_analysis', 'database_focus',
    'key_gene_functions', 'pathway_selection_rationale', 'biological_evidence',
    'cell_context', 'relevance_strength_with_disease',
    'learned_from_previous_iteration', 'learned_from_feedback',
    'pathway_guidance',
    'category_specific_adjustments', 'category_adjustments',
    'validation_reflection', 'failure_analysis', 'bottleneck_diagnosis'
]


def normalize_key(k):
    return k.strip().lower().replace(' ', '_').replace('-', '_')


def parse_reasoning_from_response(text):
    if not text:
        return None

    reasoning_match = re.search(r'<REASONING>(.*?)</REASONING>', text, re.DOTALL | re.IGNORECASE)
    content = reasoning_match.group(1).strip() if reasoning_match else text.strip()

    key_pattern = '|'.join(re.escape(k) for k in KNOWN_KEYS)
    pattern = re.compile(
        r'(?:^|\n)\s*(?:\*\*)?(' + key_pattern + r')(?:\*\*)?[:\s]+(.+?)(?=\n\s*(?:\*\*)?(?:' + key_pattern + r')(?:\*\*)?[:\s]|\Z)',
        re.DOTALL | re.IGNORECASE
    )

    sections = {}
    for match in pattern.finditer(content):
        key = normalize_key(match.group(1))
        value = match.group(2).strip()
        if value and value not in ('N/A', 'Not provided', ''):
            sections[key] = value

    def is_na_value(val):
        cleaned = val.strip().rstrip('-').strip()
        if not cleaned:
            return True
        na_patterns = ['N/A', 'Not provided', 'N/A (First iteration or no feedback)',
                       'N/A (Iteration 2+ only)', 'N/A (first iteration)', 'N/A (iteration 2+ only)']
        return cleaned in na_patterns or cleaned.upper().startswith('N/A')

    def clean_value(val):
        return val.strip().rstrip('-').strip()

    if not sections:
        lines = content.split('\n')
        current_section = None
        current_content = []
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith('##') or (line_stripped.startswith('**') and line_stripped.endswith('**')):
                if current_section and current_content:
                    val = '\n'.join(current_content).strip()
                    if val and not is_na_value(val):
                        sections[normalize_key(current_section)] = clean_value(val)
                current_section = line_stripped.strip('#* ')
                current_content = []
            elif current_section:
                if not (line_stripped == '---' or line_stripped == '***' or line_stripped == '___'):
                    current_content.append(line)
        if current_section and current_content:
            val = '\n'.join(current_content).strip()
            if val and not is_na_value(val):
                sections[normalize_key(current_section)] = clean_value(val)

    return sections if sections else None
