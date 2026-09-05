# Pathway interpretation — narrative rewrite

Reference specification: `Alzheimer_disease_bxz.docx` (writing rules + two GO:BP worked examples).

## 1. What changed

The per-pathway **Overall interpretation** card previously restated statistics the page
already displayed:

> *neuroinflammatory response ranks #1 within GO:BP for Alzheimer's Disease. 5 input genes
> overlap the 77-gene pathway annotation, with 5 linked publications.*

It now carries prose written to the docx structure, with the statistics demoted to a muted
footnote line at the bottom of the card:

1. **Opening** — one or two sentences: how many disease-associated proteins were enriched,
   the pathway name and accession. Nothing else. (docx rule 1)
2. **Notable proteins** — one or two paragraphs, two or three proteins each, giving
   molecular function + documented disease link + a concrete quantitative or clinical fact
   where one is well established. (docx rules 2–3)
3. **Functional clusters** — remaining related proteins grouped and introduced by shared
   function (neuroinflammatory, synaptic, neurotrophic, …). (docx rule 3)
4. **Closing** — two to four sentences naming the driving protein(s) and any well-documented
   interaction between intersection proteins. (docx rule 4)

**Cross-pathway continuity** (docx rule 7) is implemented as state, not as a prompt hint:
narratives are generated sequentially in the order the reader encounters them, and the set of
already-introduced proteins is carried forward into the next pathway's prompt. A protein
explained under pathway 1 is referenced only from the new pathway's angle under pathway 3.

The card also surfaces two structured extracts from the narrative: **Driving proteins** and
**Functional clusters**, rendered as linked gene chips. Both are filtered against the actual
intersection gene list server-side, so the model cannot promote a gene that is not in the
intersection.

## 2. Two deviations from the docx, and why

**Figure references are off.** The docx opens each pathway with "…significantly enriched in
X (GO:…; Figure 2)" and later reasons from the figure ("Figure 2 also suggests strong
high-confidence interactions between SNAP25 and SYT1"). The web result page renders no
per-pathway protein–protein interaction figure, so a figure cross-reference would be
unresolvable. The flag `NARRATIVE_FIGURE_REFERENCES` (default `False`) turns it back on if a
PPI figure is ever added. Interaction claims are still permitted in the closing paragraph, but
they must stand on the literature rather than on a figure.

**Per-database organizing principles.** The docx examples are both GO:BP. GO:MF, GO:CC, KEGG
and Reactome do not carry the same kind of information, so applying the "group by function"
rule to all five would produce confident prose about structure that the source database does
not encode. Each database gets its own reading instruction instead.

## 3. Per-database reading (answers the KEGG / REAC question)

| Database | What the term actually asserts | Organizing principle for the narrative |
|---|---|---|
| **GO:BP** | A coordinated series of molecular events. No reaction order. | Functional clusters, as in the docx. Explicitly forbidden from inventing an order between proteins. |
| **GO:MF** | A biochemical activity carried by individual gene products. | Which shared activity (catalysis / binding / transport / receptor); which proteins are the principal effectors. If the term is broad (*protein binding*, *ion binding*), say so — the enrichment constrains an activity class, not a mechanism. |
| **GO:CC** | Where gene products reside. Not what they do. | Which compartment or complex is shared; whether that compartment is itself a site of pathology; structural constituents vs transient residents. Must state that co-localization is not evidence of shared mechanism. |
| **KEGG** | A manually drawn wiring diagram of molecular interactions, reactions and relations. | Interpret map coverage. Use branch position, direction or contiguity only when map coordinates/topology hits are preserved; otherwise group the flat intersection into functional modules without inventing an order. |
| **REAC** | A **hierarchy of events**: parent pathway → sub-pathway → reaction. | Distinguish broad parent events from reaction-level hits. Assign catalyst/input/output/complex roles and successive-step relationships only when the result preserves those reaction annotations. |

The practical difference: for GO:BP a good narrative answers *"what do these proteins do
together?"*; for KEGG and Reactome it answers *"where in the mechanism do these proteins sit,
and is the hit concentrated or diffuse?"* — a scattered KEGG hit across unrelated branches is
a materially weaker result than five hits on one branch, and the old template could not say so.

## 4. Where it lives

**`web_app/server.py`**

| Symbol | Role |
|---|---|
| `NARRATIVE_FIGURE_REFERENCES` | Off. Enable only when a PPI figure exists. |
| `NARRATIVE_MAX_PATHWAYS` | Default 12, override via env. Narrative generation is one model call per pathway. |
| `NARRATIVE_DATABASE_GUIDANCE` | The table in §3. |
| `NARRATIVE_STRUCTURE_RULES` | The docx structure + hard constraints. |
| `build_pathway_narrative_prompt()` | One pathway → prompt, including the continuity clause. |
| `generate_pathway_narratives()` | Sequential generation, carries discussed proteins forward, filters driver/cluster genes against the intersection. |
| `fallback_pathway_narrative()` | No API key or a failed call → states only what the record proves, asserts no per-protein mechanism. |
| `attach_pathway_narratives()` | Writes `pathway_narrative` onto each record, in display order. Called from both output builders. |

**`web_app/app.js`** — `getPathwayNarrative()`, `buildStructuredNarrativeFallback()`,
`renderNarrativeEvidenceStrip()`, `renderNarrativeDriverGenes()`,
`renderNarrativeClusters()`, `renderOverallInterpretation()`. The first view now shows the
overlap/pathway size, database-specific reading lens and the pathway-level conclusion. Detailed
gene/mechanism prose is available through one disclosure, keeping the record readable without
removing content. Literature links are selected per paragraph from that pathway's attached PubMed
records. Older history entries are upgraded from their persisted structured fields rather than
falling back to one generic sentence.

**`web_app/styles.css`** — `.overall-interpretation-card--narrative`, `.narrative-meta-row`,
`.narrative-cluster`, `.narrative-record-line`, `.evidence-gene-chip--driver`.

## 5. Cost and latency

One model call per pathway, capped at `NARRATIVE_MAX_PATHWAYS` (12), issued sequentially
because each prompt depends on the previous result. At ~1.4k completion tokens per call this
adds roughly 12 calls to a run. The analysis thread emits a progress message before the step,
so the pipeline panel shows why it is waiting. Lower `NARRATIVE_MAX_PATHWAYS` to trade
coverage for latency.

## 6. Not done

- **PDF / report export** still emits the four labeled statements, not the narrative.
- **The bundled offline AD demo** carries an audited deterministic narrative for all 16 retained
  pathways, including KEGG and Reactome. It is regenerated from the preserved intersections and
  the curated biological/disease interpretation fields, without an additional model call.
- **The YouTube references** were available as the GO interpretation video and its related KEGG
  interpretation video, but neither exposed captions. Their visible framing was therefore used
  only as presentation inspiration; biological claims and database-specific rules come from the
  supplied docx, the archived pathway records and official GO/KEGG/Reactome documentation.
