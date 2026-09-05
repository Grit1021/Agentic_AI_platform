(() => {
    'use strict';

    window.definePageFragment('analysis-input', String.raw`
        <!-- Hero Section (shown initially) -->
        <section id="hero-section" class="hero">
            <div class="hero-content">
                <h1 class="hero-title">
                    Pathway analysis for disease-associated gene sets
                </h1>

                <p class="hero-subtitle">
                    Disease-aware enrichment, ranked evidence and pathway-level interpretation.
                </p>

            </div>
        </section>

        <!-- Input Section -->
        <section id="input-section" class="input-section">
            <div class="input-card">
                <div class="input-card-header">
                    <div>
                        <h2 class="input-title">Run an analysis</h2>
                    </div>
                    <div class="analysis-options" aria-label="Analysis options">
                        <div class="analysis-option analysis-option--multiple-runs">
                            <span class="analysis-setting-copy">
                                <strong>Multiple runs</strong>
                            </span>
                            <label class="settings-switch" aria-label="Use multiple analysis runs">
                                <input type="checkbox" id="iterative-checkbox" class="iterative-checkbox" checked>
                                <span aria-hidden="true"></span>
                            </label>
                        </div>
                        <label class="analysis-option analysis-option--model" for="openai-model-select">
                            <span>Model</span>
                            <select id="openai-model-select" class="settings-model-select">
                                <option value="gpt-5.1" selected>GPT-5.1</option>
                                <option value="gpt-5-mini">GPT-5 mini</option>
                                <option value="gpt-4.1">GPT-4.1</option>
                            </select>
                        </label>
                    </div>
                </div>

                <div class="analysis-context-grid">
                    <section class="input-workspace-group input-workspace-group--genes" aria-labelledby="gene-input-heading">
                        <div class="input-workspace-heading">
                            <h3 id="gene-input-heading">Input genes</h3>
                        </div>

                        <div class="gene-query-panel">
                            <div class="gene-query-heading">
                                <label for="gene-input" class="input-label">Gene list</label>
                                <div class="gene-query-actions">
                                    <button type="button" id="upload-gene-list-btn" class="gene-query-action">Upload list</button>
                                    <a class="gene-query-action gene-query-action--download" href="examples/gene_list_examples.zip" download>
                                        <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-download-simple"></use></svg> Example files
                                    </a>
                                    <button type="button" id="clear-genes-btn" class="gene-query-action gene-query-action--clear hidden">Clear</button>
                                    <input type="file" id="gene-file-input" accept=".txt,.csv,.tsv,text/plain,text/csv" hidden />
                                </div>
                            </div>
                            <div class="gene-query-editor">
                                <textarea
                                    id="gene-input"
                                    class="gene-textarea gene-query-textarea"
                                    placeholder="Start typing a gene, or paste a list&#10;APOE  TREM2  PSEN1  ENSG00000130203"
                                    autocomplete="off"
                                    aria-autocomplete="list"
                                    aria-expanded="false"
                                    aria-controls="gene-query-suggestions"
                                ></textarea>
                                <div id="gene-query-suggestions" class="gene-query-suggestions hidden" role="listbox"></div>
                            </div>
                            <div class="gene-query-formats" aria-label="Supported gene identifiers">
                                <span>HGNC symbols</span><span>Ensembl Gene IDs</span><span>Mixed identifiers</span>
                            </div>
                            <div id="selected-gene-strip" class="selected-gene-strip selected-gene-strip--query is-empty" aria-live="polite"></div>
                            <div class="input-helper-row">
                                <span id="gene-count">0 genes selected</span>
                                <span id="gene-input-quality" class="visually-hidden">Whitespace, comma or newline separated</span>
                            </div>
                        </div>

                        <div class="input-secondary-tools input-secondary-tools--single">
                            <div class="gene-list-loader">
                                <div class="gene-list-loader-header">
                                    <span class="gene-list-loader-title">
                                        <strong>Load an example</strong>
                                    </span>
                                    <button class="gene-list-toggle-btn" id="gene-list-toggle" onclick="toggleGeneListPanel()">
                                        Browse <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg>
                                    </button>
                                </div>
                                <div class="gene-list-panel hidden" id="gene-list-panel">
                                    <div class="gene-list-selectors">
                                        <div class="gene-list-select-group">
                                            <label class="input-label" for="gene-list-disease-select">Example</label>
                                            <select id="gene-list-disease-select" class="filter-select gene-list-select" onchange="onGeneListDiseaseChange()">
                                                <option value="">Select an example</option>
                                            </select>
                                        </div>
                                        <div class="gene-list-select-group" id="gene-list-module-group" style="display:none;">
                                            <label class="input-label" for="gene-list-module-select">Gene List / Module</label>
                                            <select id="gene-list-module-select" class="filter-select gene-list-select" onchange="onGeneListModuleChange()">
                                                <option value="">Select a list</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div class="gene-list-meta hidden" id="gene-list-meta">
                                        <span id="gene-list-source" hidden></span>
                                        <span id="gene-list-desc" hidden></span>
                                        <div class="gene-list-meta-row">
                                            <span class="gene-list-meta-label">Genes:</span>
                                            <span class="gene-list-meta-value" id="gene-list-count"></span>
                                        </div>
                                        <button type="button" class="gene-list-load-btn" id="gene-list-load-btn" onclick="loadSelectedGeneList()">
                                            Load example
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </section>

                    <section class="input-workspace-group input-workspace-group--disease" aria-labelledby="disease-context-heading">
                        <div class="input-workspace-heading">
                            <h3 id="disease-context-heading">Disease or phenotype</h3>
                        </div>
                        <div class="disease-search-field">
                            <div class="disease-autocomplete-wrapper disease-autocomplete-wrapper--primary">
                                <span class="disease-search-icon" aria-hidden="true"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-magnifying-glass"></use></svg></span>
                                <input
                                    type="text"
                                    id="disease-input"
                                    class="disease-custom-input"
                                    placeholder="e.g. AD, Alzheimer disease, inflammatory bowel disease"
                                    autocomplete="off"
                                    role="combobox"
                                    aria-label="Disease or phenotype"
                                    aria-autocomplete="list"
                                    aria-expanded="false"
                                    aria-controls="disease-suggestions"
                                />
                                <div id="disease-suggestions" class="disease-suggestions hidden" role="listbox"></div>
                            </div>
                            <p id="disease-input-error" class="input-validation-error hidden" role="alert"></p>
                            <select id="disease-preset-select" hidden aria-hidden="true" tabindex="-1">
                                <option value="AD">Alzheimer's Disease (AD)</option>
                                <option value="ALS">Amyotrophic Lateral Sclerosis (ALS)</option>
                                <option value="IBD">Inflammatory Bowel Disease (IBD)</option>
                                <option value="MS">Multiple Sclerosis (MS)</option>
                                <option value="PD">Parkinson's Disease (PD)</option>
                                <option value="RA">Rheumatoid Arthritis (RA)</option>
                                <option value="T2D">Type 2 Diabetes (T2D)</option>
                            </select>
                            <input type="hidden" id="disease-select" value="AD" />
                        </div>
                        <div class="open-targets-gene-import" aria-labelledby="open-targets-gene-import-title">
                            <div class="open-targets-gene-import-copy">
                                <strong id="open-targets-gene-import-title">Import by Open Targets score</strong>
                            </div>
                            <div class="open-targets-gene-import-actions" aria-label="Import Open Targets genes">
                                <button type="button" class="open-targets-gene-import-button" data-open-targets-limit="100" disabled>
                                    Import Top 100
                                </button>
                                <button type="button" class="open-targets-gene-import-button" data-open-targets-limit="200" disabled>
                                    Import Top 200
                                </button>
                            </div>
                            <div id="open-targets-gene-import-status" class="open-targets-gene-import-status hidden" aria-live="polite"></div>
                        </div>
                    </section>
                </div>

                <div class="analysis-resource-grid analysis-resource-grid--single" aria-label="Finished examples">
                    <section id="featured-examples" class="featured-examples" aria-labelledby="featured-examples-title">
                        <div class="featured-examples-copy">
                            <strong id="featured-examples-title">Completed analyses</strong>
                        </div>
                        <div class="featured-example-list">
                            <button type="button" class="featured-example-button featured-example-button--primary" data-disease="AD" onclick="openFeaturedCompletedExample('AD')">
                                <strong>Alzheimer's disease</strong>
                            </button>
                            <button type="button" class="featured-more-button" aria-expanded="false" onclick="toggleMoreFeaturedExamples(this)">More examples <svg class="ph ph-xs" aria-hidden="true"><use href="#ph-caret-down"></use></svg></button>
                            <div id="featured-more-examples" class="featured-more-examples hidden">
                                <button type="button" class="featured-example-button" data-disease="IBD" onclick="openFeaturedCompletedExample('IBD')"><strong>Inflammatory bowel disease</strong></button>
                                <button type="button" class="featured-example-button" data-disease="MS" onclick="openFeaturedCompletedExample('MS')"><strong>Multiple sclerosis</strong></button>
                                <button type="button" class="featured-example-button" data-disease="T2D" onclick="openFeaturedCompletedExample('T2D')"><strong>Type 2 diabetes</strong></button>
                                <button type="button" class="featured-example-button" data-disease="PD" onclick="openFeaturedCompletedExample('PD')"><strong>Parkinson disease</strong></button>
                                <button type="button" class="featured-example-button" data-disease="RA" onclick="openFeaturedCompletedExample('RA')"><strong>Rheumatoid arthritis</strong></button>
                                <button type="button" class="featured-example-button" data-disease="ALS" onclick="openFeaturedCompletedExample('ALS')"><strong>Amyotrophic lateral sclerosis</strong></button>
                            </div>
                        </div>
                    </section>
                </div>

                <div class="analysis-action-row">
                    <button id="start-btn" class="start-button">
                        <span class="btn-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-play"></use></svg></span>
                        <span class="btn-text">Start analysis</span>
                    </button>
                    <div class="completed-example-launcher" hidden>
                        <label for="completed-example-select">Completed result</label>
                        <div class="completed-example-controls">
                            <select id="completed-example-select" class="completed-example-select" aria-label="Choose a completed analysis result">
                                <option value="AD">Alzheimer's disease</option>
                            </select>
                            <button id="view-demo-btn" class="demo-result-button" type="button">
                                <span class="btn-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-chart-bar"></use></svg></span>
                                <span class="btn-text">View result</span>
                            </button>
                        </div>
                        <small id="completed-example-meta" class="completed-example-meta">Archived completed analysis</small>
                    </div>
                </div>
                <div id="quota-status" class="quota-status hidden" aria-live="polite"></div>
            </div>
        </section>
`);
})();
