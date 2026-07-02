import os
import pandas as pd


class StatisticalValidationAgent:
    """
    Handles statistical validation artifacts for matched pathways.

    The upstream analyzer performs g:Profiler matching/enrichment. This refined
    agent owns the validation naming and output contract: all matched pathways,
    FDR p<0.05 pathways, and nominal p<0.05 pathways.
    """

    def save_phase1_iter1_outputs(
        self,
        module_result: dict,
        module_id,
        disease_code: str,
        phase1_dir: str,
        gpt_led_dir: str,
    ) -> dict:
        """Save the clean-script iter1 statistical-validation output contract."""
        os.makedirs(gpt_led_dir, exist_ok=True)

        base_name = f"{disease_code}_Module_{module_id}_iter1"
        all_file = os.path.join(gpt_led_dir, f"{base_name}_gpt_matched_all.csv")
        fdr_file = os.path.join(gpt_led_dir, f"{base_name}_gpt_matched_fdr_p005.csv")
        filtered_file = os.path.join(gpt_led_dir, f"{base_name}_gpt_filtered_pathways.csv")
        nominal_file = os.path.join(gpt_led_dir, f"{base_name}_gpt_matched_nominal_p005.csv")

        all_ranked = self._first_nonempty_dataframe(
            module_result.get('all_pathways'),
            module_result.get('gpt_matched_all'),
            self._read_csv_if_exists(all_file),
        )

        existing_filtered = self._first_nonempty_dataframe(
            module_result.get('filtered_pathways'),
            self._read_csv_if_exists(filtered_file),
            self._read_csv_if_exists(fdr_file),
        )

        if all_ranked.empty and not existing_filtered.empty:
            all_ranked = existing_filtered.copy()

        if all_ranked.empty:
            print(f"   ⚠️  No Phase 1 pathways available to validate for Module {module_id}")
            return module_result

        if not existing_filtered.empty:
            fdr_filtered = existing_filtered.copy()
        elif 'p_value' in all_ranked.columns:
            fdr_filtered = all_ranked[all_ranked['p_value'] < 0.05].copy()
        else:
            fdr_filtered = pd.DataFrame()
            print("   ⚠️  'p_value' column not found, using existing filtered pathways")

        if 'p_nominal' in all_ranked.columns:
            nominal_filtered = all_ranked[all_ranked['p_nominal'] < 0.05].copy()
        else:
            nominal_from_disk = self._read_csv_if_exists(nominal_file)
            if not nominal_from_disk.empty:
                nominal_filtered = nominal_from_disk
            else:
                nominal_filtered = fdr_filtered.copy()
                print("   ⚠️  'p_nominal' column not found, using FDR p-value for nominal filter")

        print("\n   📊 Statistical-Validation Agent summary:")
        print(f"      • All matched/ranked: {len(all_ranked)} pathways")
        print(f"      • FDR p<0.05: {len(fdr_filtered)} pathways")
        print(f"      • Nominal p<0.05: {len(nominal_filtered)} pathways")

        module_file = os.path.join(phase1_dir, f"Module_{module_id}_filtered_pathways.csv")
        fdr_filtered.to_csv(module_file, index=False)
        print(f"   💾 Saved to phase1: {module_file}")

        all_ranked.to_csv(all_file, index=False)
        print(f"   💾 Saved iter1 matched_all ({len(all_ranked)} pathways): {os.path.basename(all_file)}")

        fdr_filtered.to_csv(filtered_file, index=False)
        print(f"   💾 Saved iter1 FDR-filtered ({len(fdr_filtered)} pathways): {os.path.basename(filtered_file)}")

        nominal_filtered.to_csv(nominal_file, index=False)
        print(f"   💾 Saved iter1 nominal-filtered ({len(nominal_filtered)} pathways): {os.path.basename(nominal_file)}")

        module_result['all_pathways'] = all_ranked
        module_result['filtered_pathways'] = fdr_filtered
        module_result['statistical_validation'] = {
            'all_matched_count': len(all_ranked),
            'fdr_count': len(fdr_filtered),
            'nominal_count': len(nominal_filtered),
            'all_file': all_file,
            'filtered_file': filtered_file,
            'nominal_file': nominal_file,
        }
        return module_result

    @staticmethod
    def _read_csv_if_exists(path: str) -> pd.DataFrame:
        if not path or not os.path.exists(path):
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except Exception as e:
            print(f"   ⚠️  Could not read {path}: {e}")
            return pd.DataFrame()

    @staticmethod
    def _first_nonempty_dataframe(*candidates) -> pd.DataFrame:
        for candidate in candidates:
            if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                return candidate.copy()
        return pd.DataFrame()
