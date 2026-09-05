(() => {
    'use strict';

    window.definePageFragment('documentation-view', String.raw`
        <!-- Documentation Section -->
        <section id="docs-section" class="docs-section" style="display: none;">
            <div class="docs-layout">
                <!-- Sidebar Navigation -->
                <aside class="docs-sidebar">
                    <div class="docs-sidebar-title">Documentation</div>
                    <label class="docs-search" for="docs-search-input">
                        <span class="docs-search-icon" aria-hidden="true"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-magnifying-glass"></use></svg></span>
                        <input id="docs-search-input" type="search" placeholder="Search documentation" autocomplete="off" oninput="filterDocumentation(this.value)">
                    </label>
                    <p id="docs-search-empty" class="docs-search-empty" hidden>No matching sections.</p>
                    <nav class="docs-nav">
                        <span class="docs-nav-group">Getting started</span>
                        <button type="button" class="docs-nav-link active" data-doc="what-is" onclick="switchDoc('what-is', this)">What is GenePathwayAI?</button>
                        <button type="button" class="docs-nav-link" data-doc="quick-start" onclick="switchDoc('quick-start', this)">Quick Start Guide</button>
                        <span class="docs-nav-group">Input &amp; matching</span>
                        <button type="button" class="docs-nav-link" data-doc="inputs" onclick="switchDoc('inputs', this)">Genes &amp; Disease Input</button>
                        <button type="button" class="docs-nav-link" data-doc="gene-mapping" onclick="switchDoc('gene-mapping', this)">Gene Mapping &amp; QC</button>
                        <span class="docs-nav-group">Using the analysis</span>
                        <button type="button" class="docs-nav-link" data-doc="analysis-pipeline" onclick="switchDoc('analysis-pipeline', this)">Analysis Pipeline</button>
                        <button type="button" class="docs-nav-link" data-doc="pathway-categories" onclick="switchDoc('pathway-categories', this)">Pathway Categories</button>
                        <button type="button" class="docs-nav-link" data-doc="checkpoints" onclick="switchDoc('checkpoints', this)">Interactive Checkpoints</button>
                        <span class="docs-nav-group">Understanding results</span>
                        <button type="button" class="docs-nav-link" data-doc="results" onclick="switchDoc('results', this)">Reading the Results</button>
                        <button type="button" class="docs-nav-link" data-doc="export-history" onclick="switchDoc('export-history', this)">Export &amp; History</button>
                        <span class="docs-nav-group">Usage &amp; support</span>
                        <button type="button" class="docs-nav-link" data-doc="usage" onclick="switchDoc('usage', this)">Usage Limits</button>
                        <button type="button" class="docs-nav-link" data-doc="data-sources" onclick="switchDoc('data-sources', this)">Data Sources</button>
                        <button type="button" class="docs-nav-link" data-doc="faq" onclick="switchDoc('faq', this)">FAQ</button>
                        <a href="https://github.com/Grit1021/Agentic_AI_platform" class="docs-nav-link docs-nav-link--external" target="_blank" rel="noopener">Pipeline source <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></a>
                    </nav>
                </aside>

                <!-- Documentation Content -->
                <div class="docs-content">
                    <!-- What is GenePathwayAI -->
                    <div class="doc-page active" id="doc-what-is">
                        <h1>What is GenePathwayAI?</h1>
                        <p class="doc-intro">GenePathwayAI turns a submitted gene list and matched disease concept into statistically supported, database-ranked pathway evidence. Input mapping, pathway overlap, literature support and biological interpretation remain traceable in the result.</p>

                        <h3>Key Capabilities</h3>
                        <div class="doc-feature-grid">
                            <div class="doc-feature">
                                <span class="doc-feature-icon">01</span>
                                <div>
                                    <strong>Identifier-Aware Input</strong>
                                    <p>Accepts HGNC symbols and Ensembl Gene IDs, removes duplicate submissions, resolves them in the human-gene namespace, and reports mapping coverage before interpretation.</p>
                                </div>
                            </div>
                            <div class="doc-feature">
                                <span class="doc-feature-icon">02</span>
                                <div>
                                    <strong>Pathway Hypothesis Generation</strong>
                                    <p>The language-model step generates 50 candidate pathway hypotheses (10 per category) across GO:BP, GO:MF, GO:CC, KEGG and Reactome. Each candidate is treated as a testable hypothesis.</p>
                                </div>
                            </div>
                            <div class="doc-feature">
                                <span class="doc-feature-icon">03</span>
                                <div>
                                    <strong>Statistical Validation</strong>
                                    <p>Each pathway hypothesis is tested against the submitted gene set with multiple-testing correction. Only statistically supported hypotheses advance to biological ranking.</p>
                                </div>
                            </div>
                            <div class="doc-feature">
                                <span class="doc-feature-icon">04</span>
                                <div>
                                    <strong>Evidence-Based Ranking</strong>
                                    <p>Validated pathways are ranked by integrating pathway descriptions, disease pathology (NCBI MeSH), enrichment significance, intersection genes, and dynamically retrieved PubMed literature.</p>
                                </div>
                            </div>
                            <div class="doc-feature doc-feature--wide">
                                <span class="doc-feature-icon">05</span>
                                <div>
                                    <strong>Multiple-run validation feedback</strong>
                                    <p>An optional feedback step summarizes unsupported hypotheses, retained pathways and database-specific gaps for a refined second pass. Model parameters are not updated.</p>
                                </div>
                            </div>
                        </div>

                        <h3>Who Is It For?</h3>
                        <ul class="doc-list">
                            <li>Bioinformatics researchers analyzing GWAS or transcriptomics gene lists</li>
                            <li>Disease-biology researchers interpreting pathway mechanisms and cellular context</li>
                            <li>Academic researchers studying gene-disease relationships and mechanisms</li>
                            <li>Clinicians exploring genetic basis of complex diseases</li>
                        </ul>
                    </div>

                    <!-- Quick Start Guide -->
                    <div class="doc-page" id="doc-quick-start">
                        <h1>Quick Start Guide</h1>
                        <p class="doc-intro">Get started with GenePathwayAI in three simple steps.</p>

                        <div class="doc-steps">
                            <div class="doc-step">
                                <div class="doc-step-number">1</div>
                                <div class="doc-step-content">
                                    <h3>Enter Your Gene List</h3>
                                    <p>Paste HGNC gene symbols (e.g., <code>APOE, APP, PSEN1, MAPT, TREM2</code>) or Ensembl Gene IDs (e.g., <code>ENSG00000130203</code>). Commas, spaces and newlines are accepted, and the two identifier types can be mixed. The run summary reports how many submitted identifiers were recognized.</p>
                                </div>
                            </div>
                            <div class="doc-step">
                                <div class="doc-step-number">2</div>
                                <div class="doc-step-content">
                                    <h3>Select Disease Context</h3>
                                    <p>Search by disease name, abbreviation or partial term and select the intended ontology-backed match. Common project diseases are available as quick choices, while other matched disease or phenotype concepts can be used directly. The selected canonical name and database ID guide pathway ranking and interpretation.</p>
                                    <div class="doc-callout">
                                        <strong>Multiple runs:</strong> Enable the main-page switch for a two-pass analysis. Validation results, enriched gene intersections and database-specific guidance inform the second set of hypotheses. Model parameters remain unchanged.
                                    </div>
                                </div>
                            </div>
                            <div class="doc-step">
                                <div class="doc-step-number">3</div>
                                <div class="doc-step-content">
                                    <h3>Review Results</h3>
                                    <p>After the analysis completes, review the results in one evidence-first Overview:</p>
                                    <ul>
                                        <li><strong>Pipeline summary and ranked pathway evidence</strong> - Initial LLM hypotheses versus statistically validated output, followed by complete within-database pathway rankings, pathway size, input overlap, interpretations and PubMed evidence</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Genes and Disease Input -->
                    <div class="doc-page" id="doc-inputs">
                        <h1>Genes &amp; Disease Input</h1>
                        <p class="doc-intro">Each new analysis requires a gene set and a disease context. Featured examples open completed archived results; use the analysis inputs below when you want an editable gene set.</p>

                        <h3>Supported gene identifiers</h3>
                        <ul class="doc-list">
                            <li><strong>HGNC gene symbols</strong>, such as <code>APOE</code>, <code>TREM2</code> and <code>PSEN1</code></li>
                            <li><strong>Ensembl Gene IDs</strong>, such as <code>ENSG00000130203</code></li>
                            <li>Comma-, space- and newline-separated lists; mixed supported identifiers can be submitted together</li>
                            <li>Plain-text, CSV and TSV gene-list uploads</li>
                        </ul>
                        <div class="doc-code-example" aria-label="Example gene input">
                            <span>Example</span>
                            <code>APOE, TREM2, PSEN1, APP, ENSG00000130203</code>
                        </div>

                        <h3>Input checks</h3>
                        <p>At least three recognized-looking identifiers are required. The website standardizes case, removes duplicate submissions and excludes tokens that do not resemble a supported symbol or Ensembl Gene ID. Biological identifier resolution is confirmed during the analysis, so syntactically valid but unknown symbols may still be reported as unresolved.</p>

                        <div class="doc-callout">
                            <strong>How mapping works:</strong> Gene mapping is an explicit input-quality step, not a pathway result. See <button type="button" class="doc-inline-link" onclick="switchDoc('gene-mapping')">Gene Mapping &amp; QC</button> for normalization rules, mapped/unresolved definitions and the difference between recognized genes and pathway-overlap genes.
                        </div>

                        <h3>Disease context</h3>
                        <p>Search by disease name, abbreviation or partial term. The autocomplete first uses project examples, then retrieves matching disease and phenotype concepts from Open Targets. Selecting a match preserves its canonical name and MONDO/EFO identifier; a MeSH cross-reference is retained when available. For an ontology-backed selection, the Top 100 or Top 200 associated gene symbols can be imported directly, ordered by the Open Targets overall association score. A custom label can still be submitted when no ontology match is appropriate.</p>

                        <div class="doc-callout">
                            <strong>Featured examples:</strong> Selecting an example opens its completed ranked pathways, biological evidence and PubMed records. To start a new analysis, enter or load a gene set in the input controls.
                        </div>
                    </div>

                    <!-- Gene Mapping and Quality Control -->
                    <div class="doc-page" id="doc-gene-mapping">
                        <h1>Gene Mapping &amp; QC</h1>
                        <p class="doc-intro">Gene mapping converts the submitted identifiers into a consistent <em>Homo sapiens</em> gene query before pathway inference. The website reports the coverage of this step separately from pathway enrichment, ranking and interpretation.</p>

                        <div class="doc-mapping-flow" aria-label="Gene identifier mapping workflow">
                            <div><span>1</span><strong>Parse</strong><small>commas, spaces or lines</small></div>
                            <i aria-hidden="true"><svg class="ph ph-xs" focusable="false"><use href="#ph-arrow-right"></use></svg></i>
                            <div><span>2</span><strong>Normalize</strong><small>trim, uppercase and deduplicate</small></div>
                            <i aria-hidden="true"><svg class="ph ph-xs" focusable="false"><use href="#ph-arrow-right"></use></svg></i>
                            <div><span>3</span><strong>Resolve</strong><small>human symbols and Ensembl IDs</small></div>
                            <i aria-hidden="true"><svg class="ph ph-xs" focusable="false"><use href="#ph-arrow-right"></use></svg></i>
                            <div><span>4</span><strong>Report</strong><small>recognized and unresolved</small></div>
                        </div>

                        <h3>What happens to each submitted token?</h3>
                        <table class="doc-table">
                            <thead>
                                <tr><th>Step</th><th>Website behavior</th><th>Why it matters</th></tr>
                            </thead>
                            <tbody>
                                <tr><td><strong>Parsing</strong></td><td>Comma-, semicolon-, space- and newline-separated entries are read as individual tokens.</td><td>A pasted list and an uploaded text/CSV/TSV list enter the same workflow.</td></tr>
                                <tr><td><strong>Input normalization</strong></td><td>Whitespace is removed, letter case is standardized and repeated tokens are collapsed before website submission.</td><td>Repeated spellings of the same submitted token do not inflate the query count.</td></tr>
                                <tr><td><strong>Syntax check</strong></td><td>HGNC-style symbols and stable Ensembl Gene IDs are accepted. Versioned Ensembl IDs are permitted and resolved when a human-gene match is available.</td><td>Malformed tokens are excluded early; valid-looking but nonexistent identifiers still require biological resolution.</td></tr>
                                <tr><td><strong>Human-gene resolution</strong></td><td>Each token is looked up in a human-gene namespace and linked to one or more canonical Ensembl gene records. A token is <em>recognized</em> when at least one canonical mapping is returned.</td><td>The same canonical query can be used for functional sources even when the input mixes symbols and Ensembl IDs.</td></tr>
                                <tr><td><strong>Unresolved identifiers</strong></td><td>A token with no human-gene mapping is counted as unresolved. It is not silently replaced with a guessed gene.</td><td>The mapping ratio remains an auditable input-quality measure.</td></tr>
                            </tbody>
                        </table>

                        <h3>Recommended input practice</h3>
                        <div class="doc-status-grid">
                            <div class="doc-status-card doc-status-card--preferred">
                                <span>Preferred</span>
                                <strong>Approved symbol or stable ENSG ID</strong>
                                <p>Use the single-gene autocomplete to select the approved symbol when starting from an alias or partial name.</p>
                            </div>
                            <div class="doc-status-card">
                                <span>Accepted</span>
                                <strong>Mixed identifier list</strong>
                                <p>Symbols and Ensembl Gene IDs can be submitted together; each original token contributes once after deduplication.</p>
                            </div>
                            <div class="doc-status-card doc-status-card--review">
                                <span>Review</span>
                                <strong>Alias or unknown symbol</strong>
                                <p>A valid-looking alias may map to multiple genes or remain unresolved. Prefer an approved symbol when mapping is important.</p>
                            </div>
                        </div>

                        <h3>How to read mapping coverage</h3>
                        <p>The Pipeline Output Summary shows <strong>recognized genes / submitted unique identifiers</strong> and the unresolved count. This is an input-quality report. It is not an enrichment score and does not imply that every recognized gene belongs to every displayed pathway.</p>
                        <div class="doc-gene-counts" aria-label="Difference between gene mapping and pathway overlap">
                            <div><strong>Submitted identifiers</strong><span>Unique tokens after website input checks</span></div>
                            <div><strong>Recognized genes</strong><span>Tokens linked to at least one human gene</span></div>
                            <div><strong>Intersection genes</strong><span>Recognized input genes annotated to one specific pathway</span></div>
                        </div>
                        <div class="doc-callout">
                            <strong>Important:</strong> A pathway's overlap can be smaller than the recognized-gene count because intersection genes are calculated separately for each pathway. Pathway size is the total number of annotated genes in that database term, not the size of your input list.
                        </div>
                    </div>

                    <!-- Analysis Pipeline -->
                    <div class="doc-page" id="doc-analysis-pipeline">
                        <h1>Analysis Pipeline</h1>
                        <p class="doc-intro">GenePathwayAI uses four functional stages: pathway hypothesis generation, statistical validation, evidence-based ranking, and optional multiple-run feedback. Each pathway is treated as a hypothesis to be tested, not a direct generative output.</p>

                        <div class="doc-pipeline">
                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Phase 1</span>
                                    <h3>Pathway Hypothesis Generation</h3>
                                </div>
                                <p>The selected language model generates 10 candidate pathway hypotheses for each of five functional sources (GO:BP, GO:MF, GO:CC, KEGG and Reactome), for a nominal budget of 50 hypotheses per gene list and prompt pass. If a source returns too few candidates, generation is repeated with an exclusion list so retries fill missing slots without duplicating prior proposals. Each candidate is tested before it enters the result.</p>
                                <div class="doc-detail-list">
                                    <div class="doc-detail-item"><span class="doc-tag">Input</span> Gene list + disease context</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Budget</span> 50 hypotheses per prompt pass (10 per category)</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Output</span> Candidate pathway names plus one structured reasoning record per database category and prompt pass</div>
                                </div>
                            </div>

                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Phase 2</span>
                                    <h3>Statistical Validation</h3>
                                </div>
                                <p>A <strong>statistical-validation agent</strong> tests whether each proposed database term is enriched in the same submitted gene list. Multiple-testing correction is applied before a hypothesis can advance, eliminating plausible-sounding but unsupported outputs.</p>
                                <div class="doc-detail-list">
                                    <div class="doc-detail-item"><span class="doc-tag">Method</span> Functional over-representation analysis with multiple-testing correction</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Gate</span> Hypothesis accepted only if enriched in the input gene list</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Output</span> Validated pathways with adjusted P-values and intersection genes</div>
                                </div>
                            </div>

                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Phase 3</span>
                                    <h3>Evidence-Based Ranking</h3>
                                </div>
                                <p>A <strong>biological-ranking agent</strong> ranks validated pathways independently within each database by integrating pathway description, disease pathology from NCBI MeSH, intersection genes between the pathway and the gene list, enrichment significance, and dynamically retrieved PubMed literature. The output is an ordered pathway list with a documented selection rationale, not a numerical disease-relevance score.</p>
                                <div class="doc-detail-list">
                                    <div class="doc-detail-item"><span class="doc-tag">Evidence</span> Pathway description, MeSH disease pathology, intersection genes, enrichment strength and PubMed</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Ranking</span> Ordered independently within GO:BP, GO:MF, GO:CC, KEGG, and Reactome</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Method record</span> One structured record per database and prompt pass, covering gene signals, biological context and validation feedback</div>
                                </div>
                            </div>

                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Phase 4</span>
                                    <h3>Multiple-run validation feedback</h3>
                                </div>
                                <p>When Multiple runs is enabled, the system summarizes retained pathway identifiers, enriched gene intersections, unsupported pathway families and database-specific gaps. This validation feedback drives a second pass without updating model parameters.</p>
                                <div class="doc-detail-list">
                                    <div class="doc-detail-item"><span class="doc-tag">Feedback</span> Unsupported pathway families, retained intersections, database-specific adjustments and coverage gaps</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Effect</span> Failed and retained hypotheses guide the second pass</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Mode</span> Single run or Multiple runs (2 passes)</div>
                                </div>
                            </div>

                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Phase 4b</span>
                                    <h3>Biological Interpretation &amp; Output</h3>
                                </div>
                                <p>For each database channel, biological interpretation organizes the validated output into ranked pathways, driver genes and their functions, disease-relevant cell/tissue context, mechanistic themes, and an explicit disease-relevance strength. PubMed citations are dynamically retrieved per pathway.</p>
                                <div class="doc-detail-list">
                                    <div class="doc-detail-item"><span class="doc-tag">Validity</span> Determined by statistically corrected enrichment</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Context</span> Driver genes, cell and tissue labels, mechanistic themes and disease relevance</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Literature</span> PubMed PMID citations via NCBI Entrez</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Pathway Categories -->
                    <div class="doc-page" id="doc-pathway-categories">
                        <h1>Pathway Categories</h1>
                        <p class="doc-intro">GenePathwayAI evaluates pathway hypotheses against five major pathway and ontology sources to provide complementary functional views of the same gene list.</p>

                        <table class="doc-table">
                            <thead>
                                <tr>
                                    <th>Category</th>
                                    <th>Database</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><span class="doc-cat-badge" style="background: #3bb59a20; color: #3bb59a; border: 1px solid #3bb59a40">GO:BP</span></td>
                                    <td>Gene Ontology</td>
                                    <td>Biological processes - the larger biological programs accomplished by multiple molecular activities (e.g., signal transduction, apoptotic process, immune response)</td>
                                </tr>
                                <tr>
                                    <td><span class="doc-cat-badge" style="background: #4da6c920; color: #4da6c9; border: 1px solid #4da6c940">GO:MF</span></td>
                                    <td>Gene Ontology</td>
                                    <td>Molecular functions - activities at the molecular level (e.g., protein kinase activity, receptor binding, transcription factor activity)</td>
                                </tr>
                                <tr>
                                    <td><span class="doc-cat-badge" style="background: #7c8dc920; color: #7c8dc9; border: 1px solid #7c8dc940">GO:CC</span></td>
                                    <td>Gene Ontology</td>
                                    <td>Cellular components - locations relative to cellular structures where gene products perform functions (e.g., synapse, membrane, nucleus)</td>
                                </tr>
                                <tr>
                                    <td><span class="doc-cat-badge" style="background: #e67e6a20; color: #e67e6a; border: 1px solid #e67e6a40">KEGG</span></td>
                                    <td>KEGG Pathway</td>
                                    <td>Manually curated pathway maps representing molecular interaction, reaction, and relation networks for metabolism, signaling, and disease</td>
                                </tr>
                                <tr>
                                    <td><span class="doc-cat-badge" style="background: #c9a84d20; color: #c9a84d; border: 1px solid #c9a84d40">REAC</span></td>
                                    <td>Reactome</td>
                                    <td>Peer-reviewed pathway database providing curated biological reactions and pathways in human biology</td>
                                </tr>
                            </tbody>
                        </table>

                        <h3>Enrichment Method</h3>
                        <p>Enrichment analysis tests whether the overlap between the submitted gene list and a database term is larger than expected by chance. Multiple-testing correction is applied across the tested terms, and the corrected value is reported as the <strong>adjusted P-value</strong>. Implementation details are listed under Data Sources.</p>
                    </div>

                    <!-- Interactive Checkpoints -->
                    <div class="doc-page" id="doc-checkpoints">
                        <h1>Interactive Checkpoints</h1>
                        <p class="doc-intro">Interactive checkpoints let the user review intermediate outputs, ask a focused question, continue the workflow or stop the run.</p>

                        <h3>Checkpoint Types</h3>
                        <div class="doc-pipeline">
                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">A</span>
                                    <h3>Network Biology Query</h3>
                                </div>
                                <p>Before statistical validation begins. You can ask questions about gene interactions, network properties, or protein complexes formed by your gene list.</p>
                            </div>
                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">1</span>
                                    <h3>Module Review</h3>
                                </div>
                                <p>After the first prompt pass and statistical validation. Review which pathway hypotheses received corrected statistical support and decide whether to continue, ask questions, or quit.</p>
                            </div>
                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">B</span>
                                    <h3>Pathway Query</h3>
                                </div>
                                <p>Focus on the leading validated pathway. Ask questions about pathway mechanisms, gene roles, cell-type context or disease connections.</p>
                            </div>
                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">2</span>
                                    <h3>Aggregation Review</h3>
                                </div>
                                <p>After pathway aggregation across all categories. Review cross-category patterns, pathway overlap and validation feedback before optionally proceeding to the second run.</p>
                            </div>
                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">3</span>
                                    <h3>Final Review</h3>
                                </div>
                                <p>After evidence-based ranking and summary report generation. Review the full set of statistically validated, ranked pathways before exporting results.</p>
                            </div>
                        </div>

                        <div class="doc-callout">
                            <strong>Tip:</strong> At each checkpoint, type "continue" or press Continue to proceed, ask a question about the current analysis, or type "quit" to cancel.
                        </div>
                    </div>

                    <!-- Reading the Results -->
                    <div class="doc-page" id="doc-results">
                        <h1>Reading the Results</h1>
                        <p class="doc-intro">The Overview separates run-level context from pathway-level evidence. Start with the Pipeline Output Summary, then read the ranked evidence within each source database.</p>

                        <h3>Pipeline Output Summary</h3>
                        <p>The summary records recognized gene identifiers, the normalized disease name and authority identifier, and the source-database composition of the final ranked register. Prompt-pass counts appear only when matched and validated lineage was preserved for that run. Literature and cell-context counts describe interpretation coverage without being used as statistical validation criteria.</p>

                        <h3>Ranked pathway evidence</h3>
                        <table class="doc-table">
                            <thead>
                                <tr><th>Field</th><th>How to interpret it</th></tr>
                            </thead>
                            <tbody>
                                <tr><td><strong>Database rank</strong></td><td>Biological evidence ordering within GO:BP, GO:MF, GO:CC, KEGG or Reactome; ranks are not compared across databases.</td></tr>
                                <tr><td><strong>Pathway ID</strong></td><td>The source-database identifier. The pathway name links to the corresponding official database record when available.</td></tr>
                                <tr><td><strong>Adjusted P-value</strong></td><td>The enrichment probability after correction for testing many database terms. Values below the configured threshold pass the statistical-validation stage.</td></tr>
                                <tr><td><strong>Input overlap / pathway size</strong></td><td>The number of submitted genes annotated to the term and the total annotated size of that term.</td></tr>
                                <tr><td><strong>Intersection genes</strong></td><td>The submitted genes contributing to the enrichment result. Gene symbols link to the corresponding gene record.</td></tr>
                                <tr><td><strong>Five ranking evidence sources</strong></td><td>Pathway description, disease pathology, intersection genes, enrichment strength and PubMed literature are shown in the same order used by the biological-ranking agent.</td></tr>
                                <tr><td><strong>+1 Cell/tissue context</strong></td><td>A separate pathway-specific interpretation layer describing relevant cells, tissues or anatomical regions. Tags link to official Cell Ontology, UBERON or Gene Ontology records when available. It is not a sixth ranking source.</td></tr>
                                <tr><td><strong>Literature</strong></td><td>Relevant PubMed links are distributed across the pathway-description, disease, intersection-gene and cell-context evidence paragraphs when supporting records are available; citation count is not a statistical score.</td></tr>
                            </tbody>
                        </table>

                        <h3>Cell and tissue context</h3>
                        <p>Cell and tissue labels are extracted from each pathway's dedicated interpretation and displayed with that pathway. Database-level reasoning is not used to populate these annotations. The labels help organize biological context but are not evidence of cell-type causality.</p>

                        <div class="doc-callout">
                            <strong>Interpretation boundary:</strong> Enrichment supports over-representation of a term in the submitted gene list. It does not by itself establish disease causality, direction of effect or cell-type specificity.
                        </div>
                    </div>

                    <!-- Export & History -->
                    <div class="doc-page" id="doc-export-history">
                        <h1>Export & History</h1>
                        <p class="doc-intro">GenePathwayAI provides multiple export formats and maintains a history of all completed analyses.</p>

                        <h3>Export Formats</h3>
                        <table class="doc-table">
                            <thead>
                                <tr>
                                    <th>Format</th>
                                    <th>Contents</th>
                                    <th>Best For</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><strong>Full Report (.pdf)</strong></td>
                                    <td>Complete analysis: ranked statistically validated pathways, pathway sizes, input overlaps, disease interpretations, PubMed evidence, and the input appendix</td>
                                    <td>Documentation, sharing with collaborators</td>
                                </tr>
                                <tr>
                                    <td><strong>Pathway Table (.csv)</strong></td>
                                    <td>Spreadsheet-ready database ranks, pathway sizes, input-overlap counts and genes, adjusted P-values, and categories</td>
                                    <td>Further analysis in Excel/R/Python</td>
                                </tr>
                                <tr>
                                    <td><strong>Raw Data (.json)</strong></td>
                                    <td>Full structured pathway, enrichment, provenance, and run metadata for programmatic use</td>
                                    <td>Integration with downstream pipelines</td>
                                </tr>
                            </tbody>
                        </table>

                        <h3>Run History</h3>
                        <p>All completed analyses are automatically saved to your run history. From the <strong>History</strong> tab, you can:</p>
                        <ul class="doc-list">
                            <li><strong>View</strong> - Re-open full results from a past analysis</li>
                            <li><strong>Re-run</strong> - Pre-fill the input form with the same genes and disease for a new analysis</li>
                            <li><strong>Delete</strong> - Remove individual entries or clear all history</li>
                            <li><strong>Search</strong> - Filter history by disease name or gene symbols</li>
                        </ul>
                    </div>

                    <!-- Usage Limits -->
                    <div class="doc-page" id="doc-usage">
                        <h1>Usage Limits</h1>
                        <p class="doc-intro">Usage controls keep live analyses available to the team and protect external-service budgets. Your current allowance is shown in the site header and is read from the deployed environment.</p>

                        <div class="doc-feature-grid">
                            <div class="doc-feature">
                                <span class="doc-feature-icon">01</span>
                                <div>
                                    <strong>Personal daily allowance</strong>
                                    <p>A new live-analysis submission consumes one job from the signed-in user's daily allowance.</p>
                                </div>
                            </div>
                            <div class="doc-feature">
                                <span class="doc-feature-icon">02</span>
                                <div>
                                    <strong>Site-wide allowance</strong>
                                    <p>A shared daily ceiling limits the total number of live jobs submitted across all users.</p>
                                </div>
                            </div>
                            <div class="doc-feature">
                                <span class="doc-feature-icon">03</span>
                                <div>
                                    <strong>Concurrent analyses</strong>
                                    <p>The service limits simultaneous jobs. If all slots are occupied, wait for an active analysis to finish before retrying.</p>
                                </div>
                            </div>
                            <div class="doc-feature">
                                <span class="doc-feature-icon">04</span>
                                <div>
                                    <strong>Examples and saved results</strong>
                                    <p>Opening the bundled completed example or reviewing an existing history entry does not submit a new live job.</p>
                                </div>
                            </div>
                        </div>

                        <p>Daily counters reset at midnight UTC. Exact personal, global and concurrency limits are deployment settings and may change as capacity is evaluated.</p>
                    </div>

                    <!-- Data Sources -->
                    <div class="doc-page" id="doc-data-sources">
                        <h1>Data Sources</h1>
                        <p class="doc-intro">GenePathwayAI separates identifier and disease matching, statistical pathway evidence, literature retrieval and language-model interpretation across established services.</p>

                        <div class="doc-source-grid">
                            <div class="doc-source">
                                <h3>HGNC &amp; Ensembl</h3>
                                <p>Official human gene symbols and stable Ensembl Gene IDs define the preferred input nomenclature. Canonical identifier resolution is reported as input mapping coverage before pathway interpretation.</p>
                                <a href="https://www.genenames.org/" target="_blank" rel="noopener" class="doc-source-link">genenames.org</a>
                            </div>
                            <div class="doc-source">
                                <h3>Open Targets Platform</h3>
                                <p>Provides gene autocomplete and disease/phenotype concept matching. Selected disease suggestions retain the canonical label and MONDO/EFO identifier shown in the input context.</p>
                                <a href="https://platform.opentargets.org/" target="_blank" rel="noopener" class="doc-source-link">platform.opentargets.org</a>
                            </div>
                            <div class="doc-source">
                                <h3>g:Profiler</h3>
                                <p>The current enrichment implementation used to test pathway hypotheses across Gene Ontology, KEGG and Reactome. It returns multiple-testing-adjusted P-values, pathway sizes and query-term intersection genes; this component can be replaced without changing the user-facing evidence model.</p>
                                <a href="https://biit.cs.ut.ee/gprofiler/" target="_blank" class="doc-source-link">biit.cs.ut.ee/gprofiler</a>
                            </div>
                            <div class="doc-source">
                                <h3>OpenAI GPT-5.1</h3>
                                <p>Language model used for pathway hypothesis generation, structured feedback and database-specific biological interpretation.</p>
                                <a href="https://openai.com" target="_blank" class="doc-source-link">openai.com</a>
                            </div>
                            <div class="doc-source">
                                <h3>NCBI PubMed / Entrez</h3>
                                <p>Literature database from the National Center for Biotechnology Information. Provides access to biomedical literature citations for pathway-disease evidence support.</p>
                                <a href="https://pubmed.ncbi.nlm.nih.gov/" target="_blank" class="doc-source-link">pubmed.ncbi.nlm.nih.gov</a>
                            </div>
                            <div class="doc-source">
                                <h3>Gene Ontology (GO)</h3>
                                <p>The world's largest source of information on the functions of genes. Provides structured, controlled vocabulary for annotating gene products across three domains (BP, MF, CC).</p>
                                <a href="http://geneontology.org/" target="_blank" class="doc-source-link">geneontology.org</a>
                            </div>
                            <div class="doc-source">
                                <h3>KEGG Pathway</h3>
                                <p>Kyoto Encyclopedia of Genes and Genomes. Collection of manually drawn pathway maps representing knowledge on molecular interactions, reactions, and relation networks.</p>
                                <a href="https://www.genome.jp/kegg/" target="_blank" class="doc-source-link">genome.jp/kegg</a>
                            </div>
                            <div class="doc-source">
                                <h3>Reactome</h3>
                                <p>Open-source, peer-reviewed, and manually curated pathway database. Provides intuitive bioinformatics tools for pathway visualization and analysis.</p>
                                <a href="https://reactome.org/" target="_blank" class="doc-source-link">reactome.org</a>
                            </div>
                        </div>
                    </div>

                    <!-- Frequently Asked Questions -->
                    <div class="doc-page" id="doc-faq">
                        <h1>Frequently Asked Questions</h1>
                        <p class="doc-intro">Short answers to common questions about inputs, validation and interpretation.</p>

                        <div class="doc-faq-list">
                            <details>
                                <summary>Which gene identifiers can I submit?</summary>
                                <p>Use HGNC gene symbols, Ensembl Gene IDs, or a mixture of both. Separate identifiers with commas, spaces or newlines. The run summary reports mapping coverage; the <button type="button" class="doc-inline-link" onclick="switchDoc('gene-mapping')">Gene Mapping &amp; QC</button> page explains the exact recognized and unresolved definitions.</p>
                            </details>
                            <details>
                                <summary>Why are fewer pathways shown than were initially proposed?</summary>
                                <p>Initial LLM outputs are hypotheses. Only matched hypotheses with corrected statistical support proceed to the ranked evidence register.</p>
                            </details>
                            <details>
                                <summary>Why can a database category be empty?</summary>
                                <p>No hypothesis in that category may have passed the enrichment gate for the submitted gene list. An empty category should not be interpreted as proof that the biology is absent.</p>
                            </details>
                            <details>
                                <summary>Are cell-type tags pathway-level results?</summary>
                                <p>Yes. In the current output, cell and tissue tags summarize the pathway-level interpretation and are displayed as a separate +1 context layer rather than a sixth ranking source.</p>
                            </details>
                            <details>
                                <summary>What changes when Multiple runs is enabled?</summary>
                                <p>The system runs an initial pass, summarizes validation successes and failures, and uses that feedback to generate a refined second set of hypotheses. Results report the two passes separately.</p>
                            </details>
                            <details>
                                <summary>Where can I review the implementation?</summary>
                                <p>Use the <a href="https://github.com/Grit1021/Agentic_AI_platform" target="_blank" rel="noopener">Pipeline source</a> link for code and technical implementation details.</p>
                            </details>
                        </div>
                    </div>
                </div>
            </div>
        </section>
`);
})();
