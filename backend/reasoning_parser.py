import re
import os
from typing import Dict, Optional
from datetime import datetime


def parse_reasoning_from_response(gpt_response: str) -> Optional[Dict[str, str]]:
    """
    Extract reasoning block from GPT response.
    
    More robust parser that:
    1. First tries to find <REASONING>...</REASONING> block
    2. If not found, tries to extract fields directly from the response text

    Expected format in GPT response:
    <REASONING>
    Strategy: [overall prediction strategy]
    Learned_from_feedback: [key insights from previous iteration]
    Pathway_guidance: [how retained pathways guide new predictions]
    Category_adjustments: [strategy per category]
    Relevance_strength_with_disease: [High/Medium/Low with explanation]
    </REASONING>

    Parameters:
    -----------
    gpt_response : str
        Raw GPT response text

    Returns:
    --------
    dict or None : Dictionary with reasoning fields if found, None otherwise
    """
    if not gpt_response:
        return None
    
    # Look for <REASONING>...</REASONING> block (case-insensitive)
    reasoning_pattern = r'<REASONING>(.*?)</REASONING>'
    match = re.search(reasoning_pattern, gpt_response, re.DOTALL | re.IGNORECASE)

    if match:
        reasoning_text = match.group(1)
        print(f"  ✓ Extracted reasoning block ({len(reasoning_text)} chars)")
    else:
        # FALLBACK: No reasoning tags found - try to extract fields directly from response
        # This handles cases where GPT doesn't wrap response in tags
        print(f"  ⚠️  No <REASONING> tags found, trying direct field extraction")
        reasoning_text = gpt_response

    # Parse individual fields
    reasoning_dict = {}
    
    # Fields that match exactly what multi_agent_analysis_full.py uses
    fields = [
        'Strategy',
        'Gene_analysis',
        'Database_focus',
        'Key_gene_functions',
        'Pathway_selection_rationale',
        'Biological_evidence',
        'Learned_from_feedback',
        'Pathway_guidance',
        'Category_adjustments',
        'Validation_reflection',
        'Failure_analysis',
        'Bottleneck_diagnosis',
        'Cell_context',
        'Relevance_strength_with_disease'
    ]
    
    # Create a regex pattern that matches any field name followed by : or -
    # This creates a list of all field positions in the text
    all_field_pattern = r'(' + '|'.join([f.replace('_', '[_\\s]?') for f in fields]) + r')\s*[:\-]'
    
    # Find all matches with their positions
    matches = list(re.finditer(all_field_pattern, reasoning_text, re.IGNORECASE))
    
    if matches:
        # Extract content between consecutive field matches
        for i, m in enumerate(matches):
            field_name = m.group(1)
            start_pos = m.end()
            
            # End position is start of next match or end of text
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                # For last field, find </REASONING> or use end of text
                end_marker = re.search(r'</REASONING>', reasoning_text[start_pos:], re.IGNORECASE)
                if end_marker:
                    end_pos = start_pos + end_marker.start()
                else:
                    end_pos = len(reasoning_text)
            
            content = reasoning_text[start_pos:end_pos].strip()
            
            # Clean up content
            content = re.sub(r'\s*</REASONING>.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'\n+', ' ', content)  # Replace newlines with spaces
            content = content.strip()
            
            if content and len(content) > 2:
                # Normalize field name to snake_case lowercase
                normalized_field = re.sub(r'[\s]+', '_', field_name.lower())
                reasoning_dict[normalized_field] = content
        
        print(f"  ✓ Found {len(matches)} field markers, extracted {len(reasoning_dict)} fields")
    
    # Fallback: try line-by-line parsing if regex approach found nothing
    if len(reasoning_dict) < 2:
        print(f"  ⚠️ Position-based extraction insufficient, trying line-by-line parsing")
        lines = reasoning_text.split('\n')
        current_field = None
        current_content = []
        
        for line in lines:
            # Check if this line starts a new field
            found_field = None
            for field in fields:
                # Build pattern for this field
                field_pattern = rf'^{field.replace("_", "[_ ]?")}[\s]*[:\-]'
                if re.match(field_pattern, line.strip(), re.IGNORECASE):
                    found_field = field
                    # Extract content after colon/dash
                    content_match = re.search(r'[:\-]\s*(.*)$', line.strip())
                    line_content = content_match.group(1).strip() if content_match else ''
                    break
            
            if found_field:
                # Save previous field
                if current_field and current_content:
                    full_content = ' '.join(current_content).strip()
                    if full_content and len(full_content) > 2:
                        reasoning_dict[current_field.lower()] = full_content
                # Start new field
                current_field = found_field
                current_content = [line_content] if line_content else []
            elif current_field:
                # Continue previous field
                clean_line = line.strip()
                if clean_line and not clean_line.startswith('</'):
                    current_content.append(clean_line)
        
        # Don't forget the last field
        if current_field and current_content:
            full_content = ' '.join(current_content).strip()
            if full_content and len(full_content) > 2:
                reasoning_dict[current_field.lower()] = full_content

    # Log which fields were successfully parsed
    if reasoning_dict:
        parsed_fields = list(reasoning_dict.keys())
        print(f"  ✓ Parsed {len(parsed_fields)} fields: {', '.join(parsed_fields)}")
        return reasoning_dict
    else:
        print(f"  ❌ No fields could be extracted from response")
        return None


def save_reasoning_to_file(reasoning_dict: Dict[str, str], 
                           output_path: str,
                           iteration: int,
                           module_id: str,
                           category: str = "ALL"):
    """
    Save reasoning to markdown file.
    
    Parameters:
    -----------
    reasoning_dict : dict
        Dictionary with reasoning fields
    output_path : str
        Full path to save reasoning file
    iteration : int
        Current iteration number
    module_id : str
        Module identifier
    category : str, optional
        Category name (GO:BP, GO:MF, etc.) or "ALL" for combined
    """
    content = f"""# Reasoning Path - {module_id} Iteration {iteration}

**Category**: {category}  
**Timestamp**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## Overall Strategy
{reasoning_dict.get('strategy', 'N/A')}

## Gene Analysis
{reasoning_dict.get('gene_analysis', 'N/A')}

## Database Focus
{reasoning_dict.get('database_focus', 'N/A')}

## Key Gene Functions
{reasoning_dict.get('key_gene_functions', 'N/A')}

## Pathway Selection Rationale
{reasoning_dict.get('pathway_selection_rationale', 'N/A')}

## Biological Evidence
{reasoning_dict.get('biological_evidence', 'N/A')}

## Learned from Previous Iteration
{reasoning_dict.get('learned_from_feedback', 'N/A (First iteration or no feedback)')}

## Pathway Guidance  
{reasoning_dict.get('pathway_guidance', 'N/A')}

## Category-Specific Adjustments
{reasoning_dict.get('category_adjustments', 'N/A')}

## Validation Reflection
{reasoning_dict.get('validation_reflection', 'N/A (Iteration 2+ only)')}

## Failure Analysis
{reasoning_dict.get('failure_analysis', 'N/A (Iteration 2+ only)')}

## Bottleneck Diagnosis
{reasoning_dict.get('bottleneck_diagnosis', 'N/A (Iteration 2+ only)')}

## Cell Context
{reasoning_dict.get('cell_context', 'N/A')}

## Relevance Strength with Disease
{reasoning_dict.get('relevance_strength_with_disease', 'N/A')}

---
*Auto-generated by reasoning path extraction system*
"""
    
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"   ⚠️  Failed to save reasoning: {e}")
        return False


def print_reasoning_summary(reasoning_dict: Dict[str, str], prefix="   "):
    """
    Print a concise summary of reasoning to console.
    
    Parameters:
    -----------
    reasoning_dict : dict
        Dictionary with reasoning fields
    prefix : str
        Prefix for each line (for indentation)
    """
    print(f"\n{prefix}💭 REASONING SUMMARY:")
    
    strategy = reasoning_dict.get('strategy', 'N/A')
    if len(strategy) > 150:
        strategy = strategy[:147] + "..."
    print(f"{prefix}   Strategy: {strategy}")
    
    learned = reasoning_dict.get('learned_from_feedback', 'N/A')
    if len(learned) > 150:
        learned = learned[:147] + "..."
    print(f"{prefix}   Learned: {learned}")
    
    confidence = reasoning_dict.get('relevance_strength_with_disease', 'N/A')
    print(f"{prefix}   Relevance: {confidence}")
