import pandas as pd

from .config import CATEGORY_CODES


def matches_gpt_prediction_enhanced(gpt_pred_name, gpt_pred_id, gprofiler_name, gprofiler_id):
    gpt_name_norm = str(gpt_pred_name).lower().strip()
    gp_name_norm = str(gprofiler_name).lower().strip()

    if gpt_pred_id and gprofiler_id:
        gpt_id_norm = str(gpt_pred_id).upper().strip()
        gp_id_norm = str(gprofiler_id).upper().strip()
        if gpt_id_norm == gp_id_norm:
            return True

    if gpt_name_norm == gp_name_norm:
        return True

    if gpt_name_norm in gp_name_norm or gp_name_norm in gpt_name_norm:
        len_gpt = len(gpt_name_norm)
        len_gp = len(gp_name_norm)
        if len_gpt > 0 and len_gp > 0:
            ratio = max(len_gpt, len_gp) / min(len_gpt, len_gp)
            if ratio <= 1.3:
                return True

    return False


def match_gpt_with_gprofiler_detailed(gpt_predictions: list, pathway_details: dict,
                                       gprofiler_results: pd.DataFrame,
                                       retained_pathway_names: set = None) -> tuple:
    if retained_pathway_names is None:
        retained_pathway_names = set()

    category_stats = {cat: {
        'predicted': 0,
        'matched': 0,
        'fdr_filtered': 0,
        'new_matched': 0,
        'new_fdr': 0
    } for cat in CATEGORY_CODES}

    for pw_name, details in pathway_details.items():
        source = details.get('source', '')
        if source in category_stats:
            category_stats[source]['predicted'] += 1

    if not gpt_predictions or gprofiler_results.empty:
        return gprofiler_results.head(30), category_stats

    gpt_preds_lookup = []
    for gpt_pred, details in pathway_details.items():
        gpt_id = details.get('id', '')
        is_new_pred = gpt_pred not in retained_pathway_names

        gpt_preds_lookup.append({
            'name': gpt_pred,
            'id': gpt_id,
            'source': details.get('source', ''),
            'is_new': is_new_pred
        })

    gpt_matched_rows = []
    for idx, row in gprofiler_results.iterrows():
        gprofiler_name = str(row.get('name', ''))
        gprofiler_id = str(row.get('native', ''))
        gprofiler_source = row.get('source', '')

        if gprofiler_source not in category_stats:
            continue

        is_match = False
        matched_is_new = False

        for gpt_item in gpt_preds_lookup:
            if matches_gpt_prediction_enhanced(
                gpt_item['name'], gpt_item['id'],
                gprofiler_name, gprofiler_id
            ):
                is_match = True
                matched_is_new = gpt_item['is_new']
                break

        if is_match:
            row_copy = row.copy()
            row_copy['gpt_validated'] = True
            row_copy['is_new_prediction'] = matched_is_new
            gpt_matched_rows.append(row_copy)

            category_stats[gprofiler_source]['matched'] += 1
            if matched_is_new:
                category_stats[gprofiler_source]['new_matched'] += 1

            if row.get('p_value', 1.0) < 0.05:
                category_stats[gprofiler_source]['fdr_filtered'] += 1
                if matched_is_new:
                    category_stats[gprofiler_source]['new_fdr'] += 1

    if gpt_matched_rows:
        matched_df = pd.DataFrame(gpt_matched_rows)
        matched_df = matched_df.sort_values('p_value')
        return matched_df, category_stats
    else:
        top_df = gprofiler_results.sort_values('p_value').head(30).copy()
        top_df['gpt_validated'] = False
        return top_df, category_stats
