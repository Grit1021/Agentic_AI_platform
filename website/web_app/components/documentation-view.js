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
                        <button type="button" class="docs-nav-link" data-doc="checkpoints" onclick="switchDoc('checkpoints', this)">Optional Questions</button>
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
                        <p class="doc-intro">GenePathwayAI tests pathway hypotheses for a submitted gene list in a selected disease context. The result connects input mapping, corrected enrichment, within-database ranking, pathway interpretation and supporting literature.</p>

                        <h3>Key Capabilities</h3>
                        <div class="doc-feature-grid">
                            <div class="doc-feature">
                                <span class="doc-feature-icon">01</span>
                                <div>
                                    <strong>Identifier-Aware Input</strong>
                                    <p>Accepts HGNC symbols and Ensembl Gene IDs, removes duplicates, resolves human genes and reports mapping coverage before pathway interpretation.</p>
                                </div>
                            </div>
                            <div class="doc-feature">
                                <span class="doc-feature-icon">02</span>
                                <div>
                                    <strong>Pathway Hypothesis Generation</strong>
                                    <p>The selected model proposes candidate pathways across GO:BP, GO:MF, GO:CC, KEGG and Reactome. Every proposal is treated as a hypothesis to be tested.</p>
                                </div>
                            </div>
                            <div class="doc-feature">
                                <span class="doc-feature-icon">03</span>
                                <div>
                                    <strong>Statistical Validation</strong>
                                    <p>Each pathway hypothesis is tested against the submitted gene list with multiple-testing correction. Only statistically supported hypotheses advance to biological ranking.</p>
                                </div>
                            </div>
                            <div class="doc-feature">
                                <span class="doc-feature-icon">04</span>
                                <div>
                                    <strong>Evidence-Based Ranking</strong>
                                    <p>Validated pathways are ranked independently within each database using pathway definitions, disease context, enrichment evidence, input-pathway intersection genes and retrieved PubMed literature.</p>
                                </div>
                            </div>
                            <div class="doc-feature doc-feature--wide">
                                <span class="doc-feature-icon">05</span>
                                <div>
                                    <strong>Interpretation and traceable output</strong>
                                    <p>Each pathway can show a concise interpretation, driving genes, functional clusters, cell or tissue context, literature and database-level reasoning details.</p>
                                </div>
                            </div>
                            <div class="doc-feature doc-feature--wide">
                                <span class="doc-feature-icon">06</span>
                                <div>
                                    <strong>Visible progress and background running</strong>
                                    <p>The analysis page shows the current stage, percentage, elapsed time and an estimated remaining time. You can return to the homepage and follow the same job from the floating status panel.</p>
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
                        <p class="doc-intro">Start a new analysis from the homepage or open a finished example without submitting a job.</p>

                        <div class="doc-steps">
                            <div class="doc-step">
                                <div class="doc-step-number">1</div>
                                <div class="doc-step-content">
                                    <h3>Select a Disease or Phenotype</h3>
                                    <p>Search by name, abbreviation or ontology term, then select the intended Open Targets match. The selected canonical label and MONDO or EFO identifier provide the disease context for ranking and interpretation.</p>
                                </div>
                            </div>
                            <div class="doc-step">
                                <div class="doc-step-number">2</div>
                                <div class="doc-step-content">
                                    <h3>Add the Gene List</h3>
                                    <p>Paste or upload HGNC symbols and Ensembl Gene IDs, download a tested input file, or import disease-associated genes from Open Targets. Open Targets presets provide 100, 150 or 200 genes; any whole number of at least 25 can also be entered.</p>
                                </div>
                            </div>
                            <div class="doc-step">
                                <div class="doc-step-number">3</div>
                                <div class="doc-step-content">
                                    <h3>Choose Settings and Start</h3>
                                    <p>Feedback is enabled by default for a two-pass analysis, while optional questions are off so the workflow runs automatically. Choose the model and the number of highlighted pathways per database, then select <strong>Start analysis</strong>. Progress remains available if you return to the homepage.</p>
                                </div>
                            </div>
                        </div>

                        <div class="doc-callout">
                            <strong>Examples:</strong> <strong>Load disease and genes</strong> fills both inputs for an editable new run. <strong>View finished results</strong> opens an archived analysis and does not consume a live-analysis job.
                        </div>

                        <h3>Feedback and output settings</h3>
                        <table class="doc-table">
                            <thead>
                                <tr><th>Setting</th><th>Default</th><th>What it changes</th></tr>
                            </thead>
                            <tbody>
                                <tr><td><strong>Feedback</strong></td><td>On</td><td>Runs a second hypothesis pass informed by first-pass validation. It does not train or update the selected model. Turn it off for one pass.</td></tr>
                                <tr><td><strong>Questions during analysis</strong></td><td>Off</td><td>Keeps the job running automatically. When enabled, the analysis pauses at two optional points where you can ask a focused question or select Skip.</td></tr>
                                <tr><td><strong>Model</strong></td><td>GPT-5.1</td><td>Selects the model used for hypothesis generation, feedback and interpretation. GPT-5 mini and GPT-4.1 are also available in the current deployment.</td></tr>
                                <tr><td><strong>Highlighted pathways per database</strong></td><td>Top 5</td><td>Controls the initial number shown in each database section: Top 3, Top 5, Top 10 or All. It does not alter validation or ranking. PDF scope is selected separately during export.</td></tr>
                            </tbody>
                        </table>
                    </div>

                    <!-- Genes and Disease Input -->
                    <div class="doc-page" id="doc-inputs">
                        <h1>Genes &amp; Disease Input</h1>
                        <p class="doc-intro">Each new analysis requires a disease or phenotype and a gene list. The homepage presents these two inputs together.</p>

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

                        <h3>Disease or phenotype</h3>
                        <p>Search by disease name, abbreviation or partial term. Suggestions include local examples and disease or phenotype concepts from Open Targets. Selecting a match preserves its canonical name and MONDO or EFO identifier; a MeSH cross-reference is retained when available. Pressing Tab accepts the active suggestion.</p>

                        <h3>Import disease-associated genes</h3>
                        <p>After selecting an ontology-backed disease, Open Targets can replace the current gene list with the highest-ranked associated genes. The presets are 100, 150 and 200, and a custom whole number of at least 25 is accepted without a fixed upper limit. The overall association score combines weighted evidence across Open Targets data sources. It is a ranking score from 0 to 1, not a disease probability.</p>

                        <div class="doc-callout">
                            <strong>Examples:</strong> <strong>Load disease and genes</strong> fills an editable disease-gene pair. <strong>View finished results</strong> opens an archived result. The downloadable HGNC, Ensembl and mixed-identifier files are tested input templates with at least 100 genes each.
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
                        <p class="doc-intro">The running analysis and the result sidebar use the same five stages: Input, Hypothesize, Validate, Rank and Interpret. Candidate pathways do not enter the result until they pass statistical validation.</p>

                        <div class="doc-pipeline">
                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Input</span>
                                    <h3>Genes and Disease</h3>
                                </div>
                                <p>The service normalizes the submitted identifiers, resolves human genes and preserves the selected disease concept before generating pathway hypotheses.</p>
                                <div class="doc-detail-list">
                                    <div class="doc-detail-item"><span class="doc-tag">Input</span> Gene list and selected disease or phenotype</div>
                                    <div class="doc-detail-item"><span class="doc-tag">QC</span> Normalize, deduplicate, resolve and report unmapped identifiers</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Output</span> Recognized human genes and a canonical disease context</div>
                                </div>
                            </div>

                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Hypothesize</span>
                                    <h3>Pathway Hypothesis Generation</h3>
                                </div>
                                <p>The selected model proposes 10 candidate pathways for each of five databases: GO:BP, GO:MF, GO:CC, KEGG and Reactome. If feedback is enabled, validation results from the first pass guide a refined second pass without changing model parameters.</p>
                                <div class="doc-detail-list">
                                    <div class="doc-detail-item"><span class="doc-tag">Budget</span> 50 hypotheses per pass, 10 per database</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Feedback</span> Enabled by default; uses retained and unsupported hypotheses to guide pass 2</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Output</span> Candidate database terms for statistical testing</div>
                                </div>
                            </div>

                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Validate</span>
                                    <h3>Statistical Validation</h3>
                                </div>
                                <p>Each proposed term is tested for over-representation in the same submitted gene list. Multiple-testing correction is applied before a pathway can advance.</p>
                                <div class="doc-detail-list">
                                    <div class="doc-detail-item"><span class="doc-tag">Method</span> Functional over-representation analysis with multiple-testing correction</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Gate</span> Only statistically supported terms become validated pathways</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Output</span> Adjusted P-values, pathway sizes and input-pathway intersection genes</div>
                                </div>
                            </div>

                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Rank</span>
                                    <h3>Evidence-Based Ranking</h3>
                                </div>
                                <p>Validated pathways are ordered independently within each database using pathway definitions, disease pathology from NCBI MeSH, input-pathway intersection genes, enrichment strength and retrieved PubMed literature. The rank is an evidence ordering, not a numerical disease-relevance probability.</p>
                                <div class="doc-detail-list">
                                    <div class="doc-detail-item"><span class="doc-tag">Evidence</span> Pathway definition, disease context, overlap genes, enrichment and PubMed</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Scope</span> Ranks restart within GO:BP, GO:MF, GO:CC, KEGG and Reactome</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Output</span> A validated pathway ranking for each database</div>
                                </div>
                            </div>

                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Interpret</span>
                                    <h3>Interpretation and Report</h3>
                                </div>
                                <p>The final report presents the pipeline summary, validated pathway table and selected pathway interpretations. Each database follows the same order: Validated pathways, Interpretation, then database-level Reasoning details in Full record view.</p>
                                <div class="doc-detail-list">
                                    <div class="doc-detail-item"><span class="doc-tag">Summary</span> Ranked table and highlighted pathway interpretations</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Full record</span> Adds database-level reasoning details</div>
                                    <div class="doc-detail-item"><span class="doc-tag">Sources</span> Official pathway records, gene links and PubMed literature when available</div>
                                </div>
                            </div>
                        </div>

                        <div class="doc-callout">
                            <strong>Progress:</strong> The running page reports the current stage, percentage, elapsed time and estimated time remaining. Returning to the homepage does not stop the job; the floating analysis panel continues to show its status.
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

                    <!-- Optional Questions -->
                    <div class="doc-page" id="doc-checkpoints">
                        <h1>Optional Questions</h1>
                        <p class="doc-intro">Questions during analysis are off by default, so a submitted job runs without waiting for interaction. Turn them on under Feedback and output if you want to ask about intermediate results.</p>

                        <h3>Question points</h3>
                        <div class="doc-pipeline">
                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Genes</span>
                                    <h3>Gene List Question</h3>
                                </div>
                                <p>Before pathway validation, ask a focused question about gene functions, interactions or shared biological themes in the submitted list.</p>
                            </div>
                            <div class="doc-phase">
                                <div class="doc-phase-header">
                                    <span class="doc-phase-badge">Pathway</span>
                                    <h3>Leading Pathway Question</h3>
                                </div>
                                <p>After initial validation, ask about the leading pathway's mechanism, intersection genes, cell or tissue context, or relationship to the selected disease.</p>
                            </div>
                        </div>

                        <div class="doc-callout">
                            <strong>What happens next:</strong> Select <strong>Ask question</strong> to receive a model response or <strong>Skip</strong> to continue immediately. After an answer is returned, the analysis advances automatically; a second Skip is not required.
                        </div>
                    </div>

                    <!-- Reading the Results -->
                    <div class="doc-page" id="doc-results">
                        <h1>Reading the Results</h1>
                        <p class="doc-intro">Results open in Summary view. Use Full record when you need the database-level reasoning behind the displayed pathway order.</p>

                        <h3>Pipeline Output Summary</h3>
                        <p>The first section reports the matched disease, recognized and unresolved identifiers, initial hypotheses, validated pathways, pathways with cell context, validated pathways by database and a complete ranked table. The table uses the order <strong>Database, ID, Rank, Pathway, Adjusted P-value</strong>.</p>

                        <h3>Highlighted Pathways with Interpretations</h3>
                        <p>Below the summary, pathways are grouped by database. The input setting controls whether the first 3, 5, 10 or all pathways per database are highlighted. The result page also lets you switch among Top 5, Top 10 and All.</p>

                        <h3>Reading a pathway</h3>
                        <table class="doc-table">
                            <thead>
                                <tr><th>Field</th><th>How to interpret it</th></tr>
                            </thead>
                            <tbody>
                                <tr><td><strong>Database rank</strong></td><td>The evidence ordering within GO:BP, GO:MF, GO:CC, KEGG or Reactome. Ranks restart in each database and are not compared across databases.</td></tr>
                                <tr><td><strong>Pathway ID and definition</strong></td><td>The source-database identifier links to the official term when available. Definition states what the database term represents.</td></tr>
                                <tr><td><strong>Adjusted P-value</strong></td><td>The enrichment probability after correction for testing many database terms. Values below the configured threshold pass the statistical-validation stage.</td></tr>
                                <tr><td><strong>Input overlap / pathway size</strong></td><td>The number of submitted genes annotated to the term and the total annotated size of that term.</td></tr>
                                <tr><td><strong>Intersection genes</strong></td><td>The submitted genes contributing to the enrichment result. Gene symbols link to the corresponding gene record.</td></tr>
                                <tr><td><strong>Interpretation</strong></td><td>A concise disease-aware narrative followed by driving genes, functional clusters and cell or tissue context when those fields are available.</td></tr>
                                <tr><td><strong>Cell / tissue context</strong></td><td>Pathway-level labels for relevant cells, tissues or anatomical regions. Tags link to Cell Ontology, UBERON or Gene Ontology records when available.</td></tr>
                                <tr><td><strong>Literature</strong></td><td>PubMed records linked to specific supporting statements when available. Citation count is not a statistical score.</td></tr>
                                <tr><td><strong>Reasoning details</strong></td><td>A database-level record shown after its validated pathways in Full record view. It describes the ranking rationale without creating another set of pathway results.</td></tr>
                            </tbody>
                        </table>

                        <h3>Result order</h3>
                        <p>Every database uses the same reading order: <strong>Validated pathways</strong>, each selected pathway's <strong>Interpretation</strong>, then <strong>Reasoning details</strong>. Reasoning details are hidden in Summary view and shown in Full record.</p>

                        <h3>Cell and tissue context</h3>
                        <p>Cell and tissue labels are extracted from each pathway's dedicated interpretation and displayed with that pathway. Database-level reasoning is not used to populate them. A PubMed record is linked only to the statement it supports; one PMID is not assumed to validate every displayed context label. The labels organize biological context but do not establish cell-type causality.</p>

                        <div class="doc-callout">
                            <strong>Interpretation boundary:</strong> Enrichment supports over-representation of a term in the submitted gene list. It does not by itself establish disease causality, direction of effect or cell-type specificity.
                        </div>
                    </div>

                    <!-- Export & History -->
                    <div class="doc-page" id="doc-export-history">
                        <h1>Export & History</h1>
                        <p class="doc-intro">Exports are generated from the saved analysis data, not from the pathways currently expanded in the browser. Completed live jobs are available from History.</p>

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
                                    <td><strong>Summary Report (.pdf)</strong></td>
                                    <td>Pipeline output summary, ranked pathway table and concise highlighted interpretations</td>
                                    <td>Main-text review and rapid sharing</td>
                                </tr>
                                <tr>
                                    <td><strong>Full Report (.pdf)</strong></td>
                                    <td>Pipeline output summary, validated pathway evidence, interpretations, literature, source links, reasoning details and input appendix</td>
                                    <td>Supplementary records and collaboration</td>
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

                        <h3>PDF pathway scope</h3>
                        <p>Before exporting either PDF, choose All pathways or Top 3, Top 5 or Top 10 per database. This selection is independent of which pathway cards are open on the page. PDF ranking tables use Database, ID and Rank as separate columns, and pathway headings use the form <strong>1. GO:0098773: skin epidermis development</strong>. Database term descriptions are labeled <strong>Pathway definition</strong>.</p>

                        <h3>Run History</h3>
                        <p>Completed live analyses are saved to the signed-in user's server-side run history. From <strong>History</strong>, you can:</p>
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
                                <p>Provides disease and phenotype matching plus ranked disease-associated genes. The website retains the selected canonical label and MONDO or EFO identifier. Imported genes are ordered by the overall association score, a 0-to-1 evidence ranking that combines weighted data sources and is not a disease probability.</p>
                                <a href="https://platform.opentargets.org/" target="_blank" rel="noopener" class="doc-source-link">platform.opentargets.org</a>
                            </div>
                            <div class="doc-source">
                                <h3>g:Profiler</h3>
                                <p>The current enrichment implementation used to test pathway hypotheses across Gene Ontology, KEGG and Reactome. It returns multiple-testing-adjusted P-values, pathway sizes and query-term intersection genes; this component can be replaced without changing the user-facing evidence model.</p>
                                <a href="https://biit.cs.ut.ee/gprofiler/" target="_blank" class="doc-source-link">biit.cs.ut.ee/gprofiler</a>
                            </div>
                            <div class="doc-source">
                                <h3>OpenAI models</h3>
                                <p>The selected model is used for pathway hypothesis generation, validation feedback and database-specific biological interpretation. GPT-5.1 is the current default; GPT-5 mini and GPT-4.1 are also available in Feedback and output settings.</p>
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
                                <summary>What does Open Targets import do?</summary>
                                <p>After you select an ontology-backed disease, it replaces the current gene list with the requested number of highest-ranked associated genes. Use 100, 150, 200 or any whole number of at least 25. The overall association score ranks evidence strength from 0 to 1 and is not a probability.</p>
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
                                <p>Yes. Cell and tissue tags summarize one pathway's interpretation. They organize relevant context but do not establish cell-type causality. Literature is linked to individual supporting statements when available; the website does not treat one PMID as support for every tag.</p>
                            </details>
                            <details>
                                <summary>What changes when Feedback is enabled?</summary>
                                <p>Feedback is on by default. The system summarizes validation successes and failures from the first pass and uses them to generate a refined second set of hypotheses. The final validated pathway register is consolidated; Full record adds database-level Reasoning details.</p>
                            </details>
                            <details>
                                <summary>Will the analysis wait for me to answer questions?</summary>
                                <p>Not by default. Questions during analysis are off, so the job runs automatically. If you turn them on, you may ask at the gene-list and leading-pathway points or select Skip. The workflow advances automatically after the model answers.</p>
                            </details>
                            <details>
                                <summary>Can I leave the running analysis page?</summary>
                                <p>Yes. Return to the homepage while the job continues. A floating status panel shows progress and opens the active analysis again. If completion email is configured for the deployment, the service also sends a notification when the job finishes.</p>
                            </details>
                            <details>
                                <summary>Does PDF export depend on open pathway cards?</summary>
                                <p>No. PDF export uses the saved analysis data and includes the selected scope of All, Top 3, Top 5 or Top 10 pathways per database, regardless of which cards are expanded in the browser.</p>
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
