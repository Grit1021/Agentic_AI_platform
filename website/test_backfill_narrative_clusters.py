import copy
import unittest

from backfill_narrative_clusters import backfill_pathway


class NarrativeClusterBackfillTests(unittest.TestCase):
    def test_restores_ad_driver_memberships_and_missing_driver_only_cluster(self):
        pathway = {
            'intersection_genes': ['GRN', 'MMP9', 'CTSC', 'MMP8', 'AZU1'],
            'pathway_narrative': {
                'paragraphs': [
                    'A microglial and lysosomal immune-regulatory cluster is exemplified by '
                    'GRN and CTSC, which regulate lysosomal signaling. A proteolytic '
                    'extracellular matrix remodeling cluster is formed by MMP8 and MMP9, '
                    'both metalloproteinases. Finally, AZU1 anchors a myeloid chemoattractant '
                    'and vascular activation cluster, in which azurocidin promotes recruitment.'
                ],
                'driver_genes': ['GRN', 'MMP9', 'CTSC'],
                'clusters': [
                    {
                        'label': 'proteolytic extracellular matrix remodeling cluster',
                        'genes': ['MMP8'],
                    },
                    {
                        'label': 'myeloid chemoattractant and vascular activation cluster',
                        'genes': ['AZU1'],
                    },
                ],
            },
        }

        report = backfill_pathway(pathway)
        clusters = pathway['pathway_narrative']['clusters']

        self.assertEqual(clusters[0]['genes'], ['MMP8', 'MMP9'])
        self.assertEqual(clusters[1]['genes'], ['AZU1'])
        self.assertEqual(
            clusters[2],
            {
                'label': 'microglial and lysosomal immune-regulatory cluster',
                'genes': ['GRN', 'CTSC'],
            },
        )
        self.assertEqual(len(report['created']), 1)
        self.assertEqual(len(report['restored']), 1)

    def test_does_not_assign_drivers_merely_discussed_near_remaining_clusters(self):
        pathway = {
            'intersection_genes': ['CD28', 'CTLA4', 'IL2RA', 'CD3E', 'LCK', 'ZAP70'],
            'pathway_narrative': {
                'paragraphs': [
                    'CD28, CTLA4 and IL2RA appear to drive the association. Beyond these '
                    'individually highlighted proteins, the remaining proteins segregate into '
                    'functional clusters. A T cell receptor signalling machinery cluster, '
                    'including CD3E, LCK and ZAP70, comprises early signaling proteins.'
                ],
                'driver_genes': ['CD28', 'CTLA4', 'IL2RA'],
                'clusters': [
                    {
                        'label': 'T cell receptor signalling machinery',
                        'genes': ['CD3E', 'LCK', 'ZAP70'],
                    }
                ],
            },
        }
        original = copy.deepcopy(pathway)

        report = backfill_pathway(pathway)

        self.assertEqual(pathway, original)
        self.assertEqual(report['restored'], [])
        self.assertEqual(report['created'], [])
        self.assertEqual(report['unresolved'], ['CD28', 'CTLA4', 'IL2RA'])

    def test_does_not_treat_recruited_driver_as_cluster_member(self):
        pathway = {
            'intersection_genes': ['XRCC5', 'XRCC6', 'PRKDC'],
            'pathway_narrative': {
                'paragraphs': [
                    'A non-homologous end joining cluster formed by XRCC5 and XRCC6 encodes '
                    'the Ku heterodimer, which binds telomeric DNA ends and recruits PRKDC.'
                ],
                'driver_genes': ['PRKDC'],
                'clusters': [
                    {'label': 'Telomeric non-homologous end joining module', 'genes': ['XRCC5', 'XRCC6']}
                ],
            },
        }

        report = backfill_pathway(pathway)

        self.assertEqual(pathway['pathway_narrative']['clusters'][0]['genes'], ['XRCC5', 'XRCC6'])
        self.assertEqual(report['unresolved'], ['PRKDC'])

    def test_uses_non_driver_overlap_to_map_an_ordinal_cluster_label(self):
        pathway = {
            'intersection_genes': ['HDAC5', 'HDAC9', 'MTA2'],
            'pathway_narrative': {
                'paragraphs': [
                    'A second, closely allied cluster contains HDAC5, HDAC9, and MTA2, '
                    'which provides a chromatin-remodeling scaffold.'
                ],
                'driver_genes': ['HDAC9'],
                'clusters': [
                    {'label': 'Class IIa HDACs and NuRD-associated scaffold', 'genes': ['HDAC5', 'MTA2']}
                ],
            },
        }

        report = backfill_pathway(pathway)

        self.assertEqual(
            pathway['pathway_narrative']['clusters'][0]['genes'],
            ['HDAC5', 'MTA2', 'HDAC9'],
        )
        self.assertEqual(len(report['restored']), 1)

    def test_does_not_capture_a_driver_after_the_member_list_action(self):
        pathway = {
            'intersection_genes': ['ACD', 'TERF2IP', 'TINF2', 'TERF2'],
            'pathway_narrative': {
                'paragraphs': [
                    'A shelterin accessory cluster comprising ACD, TERF2IP and TINF2 supports '
                    'TERF2 at chromosome ends.'
                ],
                'driver_genes': ['TERF2'],
                'clusters': [
                    {'label': 'Shelterin accessory telomere-capping complex', 'genes': ['ACD', 'TERF2IP', 'TINF2']}
                ],
            },
        }

        report = backfill_pathway(pathway)

        self.assertEqual(report['restored'], [])
        self.assertEqual(report['created'], [])
        self.assertEqual(report['unresolved'], ['TERF2'])

    def test_reaction_products_are_not_mistaken_for_a_functional_group(self):
        pathway = {
            'intersection_genes': ['SUMO1', 'SUMO2', 'SUMO3'],
            'pathway_narrative': {
                'paragraphs': [
                    'SUMO1, SUMO2 and SUMO3 form transient conjugates with transcription factors.'
                ],
                'driver_genes': ['SUMO1'],
                'clusters': [
                    {'label': 'SUMO-paralog modifiers', 'genes': ['SUMO2', 'SUMO3']}
                ],
            },
        }

        report = backfill_pathway(pathway)

        self.assertEqual(pathway['pathway_narrative']['clusters'][0]['genes'], ['SUMO2', 'SUMO3'])
        self.assertEqual(report['unresolved'], ['SUMO1'])

    def test_named_cluster_enumeration_wins_over_general_notable_prose(self):
        pathway = {
            'intersection_genes': ['STK11', 'CAB39', 'CAB39L', 'TSC1', 'TSC2', 'RPTOR'],
            'pathway_narrative': {
                'paragraphs': [
                    'STK11, TSC1, TSC2 and RPTOR form a second set of notable hits. '
                    'An upstream kinase-activation module comprises STK11 together with its '
                    'scaffold partners CAB39 and CAB39L, which stabilize the complex.'
                ],
                'driver_genes': ['STK11'],
                'clusters': [
                    {'label': 'Upstream STK11 activation complex', 'genes': ['CAB39', 'CAB39L']},
                    {'label': 'mTOR branch and growth control', 'genes': ['TSC1', 'TSC2', 'RPTOR']},
                ],
            },
        }

        report = backfill_pathway(pathway)

        self.assertEqual(pathway['pathway_narrative']['clusters'][0]['genes'], ['CAB39', 'CAB39L', 'STK11'])
        self.assertEqual(pathway['pathway_narrative']['clusters'][1]['genes'], ['TSC1', 'TSC2', 'RPTOR'])
        self.assertEqual(len(report['restored']), 1)

    def test_multiple_shared_members_map_a_safety_rephrased_module_label(self):
        pathway = {
            'intersection_genes': ['JAK1', 'JAK2', 'JAK3', 'STAT5A', 'STAT5B'],
            'pathway_narrative': {
                'paragraphs': [
                    'JAK1, JAK2, JAK3 and the transcription factors STAT5A and STAT5B form a canonical '
                    'cytokine-associated kinase–transcription factor module.'
                ],
                'driver_genes': ['STAT5B'],
                'clusters': [
                    {
                        'label': 'Common gamma-chain cytokine receptor and JAK kinase module',
                        'genes': ['JAK1', 'JAK2', 'JAK3', 'STAT5A'],
                    }
                ],
            },
        }

        report = backfill_pathway(pathway)

        self.assertEqual(
            pathway['pathway_narrative']['clusters'][0]['genes'],
            ['JAK1', 'JAK2', 'JAK3', 'STAT5A', 'STAT5B'],
        )
        self.assertEqual(len(report['restored']), 1)


if __name__ == '__main__':
    unittest.main()
