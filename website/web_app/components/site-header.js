(() => {
    'use strict';

    window.definePageFragment('site-header', String.raw`
    <header class="header">
        <div class="header-content">
            <a class="logo" href="#" aria-label="GenePathwayAI home" onclick="showAnalysisView(); return false;">
                <span class="logo-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-dna"></use></svg></span>
                <span class="logo-text">GenePathwayAI</span>
            </a>
            <nav class="nav">
                <a href="/" class="nav-link active" data-view="analysis" onclick="showAnalysisView(); return false;">Analysis</a>
                <div class="nav-featured-menu">
                    <button type="button" class="nav-link nav-featured-trigger" id="featured-examples-menu-button"
                        aria-haspopup="menu" aria-expanded="false" aria-controls="featured-examples-menu">
                        Featured examples
                        <svg class="ph ph-xs nav-featured-chevron" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg>
                    </button>
                    <div class="nav-featured-popover" id="featured-examples-menu" role="menu"
                        aria-labelledby="featured-examples-menu-button" hidden>
                        <strong class="nav-featured-heading">Completed analyses</strong>
                        <a href="/?demo=1&amp;example=AD" role="menuitem" data-example-code="AD">
                            <span>Alzheimer's disease</span>
                        </a>
                        <a href="/?demo=1&amp;example=IBD" role="menuitem" data-example-code="IBD">
                            <span>Inflammatory bowel disease</span>
                        </a>
                        <a href="/?demo=1&amp;example=MS" role="menuitem" data-example-code="MS">
                            <span>Multiple sclerosis</span>
                        </a>
                        <a href="/?demo=1&amp;example=T2D" role="menuitem" data-example-code="T2D">
                            <span>Type 2 diabetes</span>
                        </a>
                        <a href="/?demo=1&amp;example=PD" role="menuitem" data-example-code="PD">
                            <span>Parkinson disease</span>
                        </a>
                        <a href="/?demo=1&amp;example=RA" role="menuitem" data-example-code="RA">
                            <span>Rheumatoid arthritis</span>
                        </a>
                        <a href="/?demo=1&amp;example=ALS" role="menuitem" data-example-code="ALS">
                            <span>Amyotrophic lateral sclerosis</span>
                        </a>
                    </div>
                </div>
                <a href="#" class="nav-link" data-view="history" onclick="showHistoryPanel()">History</a>
                <a href="#docs/what-is" class="nav-link" data-view="docs" onclick="showDocsPanel('what-is'); return false;">Docs</a>
                <button type="button" id="tour-replay-button" class="nav-link nav-tour-button"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-compass"></use></svg> Tour</button>
                <a href="https://github.com/Grit1021/Agentic_AI_platform" class="nav-link nav-link--external" target="_blank" rel="noopener">Pipeline <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></a>
            </nav>
            <span id="header-quota-status" class="header-quota-status hidden" aria-live="polite"></span>
            <div id="auth-user-menu" class="auth-user-menu hidden">
                <span id="auth-user-email"></span>
                <a id="admin-dashboard-link" href="/admin" hidden>Admin</a>
                <a href="/auth/logout">Sign out</a>
            </div>
        </div>
    </header>
`);
})();
