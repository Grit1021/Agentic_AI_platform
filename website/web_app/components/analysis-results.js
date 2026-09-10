(() => {
    'use strict';

    window.definePageFragment('analysis-results', String.raw`
        <!-- Results Section - user-facing evidence presentation -->
        <section id="results-section" class="results-section hidden">
            <!-- Results Navigation Bar -->
            <div class="results-nav">
                <button id="back-to-process" class="back-button">
                    <span><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-left"></use></svg> Back to analysis</span>
                </button>
                <div class="export-dropdown-wrapper">
                    <button id="export-btn" class="export-button">
                        <span><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-download-simple"></use></svg> Export</span>
                        <span class="export-arrow"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg></span>
                    </button>
                    <div class="report-view-toggle" role="group" aria-label="Report detail level">
                        <button type="button" class="report-view-button active" data-report-view="summary">Summary</button>
                        <button type="button" class="report-view-button" data-report-view="detailed">Full record</button>
                    </div>
                    <div id="export-dropdown" class="export-dropdown hidden">
                        <div class="pdf-export-scope">
                            <label for="pdf-export-limit">PDF pathways per database</label>
                            <select id="pdf-export-limit">
                                <option value="all" selected>All pathways</option>
                                <option value="3">Top 3</option>
                                <option value="5">Top 5</option>
                                <option value="10">Top 10</option>
                            </select>
                        </div>
                        <button class="export-option" data-format="pdf-summary">
                            <span class="export-option-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-file-text"></use></svg></span>
                            <div class="export-option-text">
                                <span class="export-option-title">Summary report (.pdf)</span>
                                <span class="export-option-desc">Concise ranked table and highlighted interpretations</span>
                            </div>
                        </button>
                        <button class="export-option" data-format="pdf">
                            <span class="export-option-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-file-text"></use></svg></span>
                            <div class="export-option-text">
                                <span class="export-option-title">Full report (.pdf)</span>
                                <span class="export-option-desc">Formatted ranked pathway evidence, interpretations and source links</span>
                            </div>
                        </button>
                        <button class="export-option" data-format="csv">
                            <span class="export-option-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-table"></use></svg></span>
                            <div class="export-option-text">
                                <span class="export-option-title">Pathway Table (.csv)</span>
                                <span class="export-option-desc">Spreadsheet-ready pathway data</span>
                            </div>
                        </button>
                        <button class="export-option" data-format="json">
                            <span class="export-option-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-brackets-curly"></use></svg></span>
                            <div class="export-option-text">
                                <span class="export-option-title">Raw Data (.json)</span>
                                <span class="export-option-desc">Full structured data for programmatic use</span>
                            </div>
                        </button>
                    </div>
                </div>
            </div>

            <!-- Results Hero -->
            <div class="results-hero-section">
                <div class="results-hero-content">
                    <h1 class="results-title">
                        <span id="disease-name-display">Alzheimer's Disease</span>
                        <span class="hero-separator">with</span>
                        <span id="gene-count-display">231 genes</span>
                    </h1>
                    <div class="results-meta">
                        <span class="meta-pill" id="analysis-date"></span>
                        <span class="meta-pill" id="model-version">GPT-5.1</span>
                        <span class="meta-pill status-success" id="analysis-status"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-check"></use></svg> Complete</span>
                    </div>
                </div>
            </div>

            <!-- Evidence-first Overview -->
            <div id="tab-overview" class="tab-content active">
                <!-- Run context, prompt-pass yield and evidence coverage -->
                <div class="summary-card" id="quick-summary">
                        <div class="summary-card-heading">
                            <div>
                                <h3>Pipeline output summary</h3>
                            </div>
                        </div>
                    <div class="summary-content" id="summary-text"></div>
                </div>

                <!-- Complete source-anchored evidence -->
                <section class="evidence-register-card">
                    <div class="evidence-register-header">
                        <div>
                            <h3>Highlighted pathways with interpretations</h3>
                        </div>
                        <label class="pathway-limit-control" for="pathways-per-database">Show per database
                            <select id="pathways-per-database" class="filter-select">
                                <option value="5" selected>Top 5</option>
                                <option value="10">Top 10</option>
                                <option value="all">All</option>
                            </select>
                        </label>
                    </div>
                    <div class="evidence-container" id="evidence-sections">
                        <!-- Rendered by JS -->
                    </div>
                </section>

            </div>
        </section>
`);
})();
