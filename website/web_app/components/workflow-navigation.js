(() => {
    'use strict';

    window.definePageFragment('workflow-navigation', String.raw`
        <aside class="workflow-rail" aria-label="Analysis workflow">
            <div class="workflow-rail-heading">
                <strong>Workflow</strong>
                <span id="workflow-navigation-status" aria-live="polite">Input is ready</span>
            </div>
            <nav class="workflow-rail-steps" aria-label="Jump to an analysis stage">
                <button type="button" class="workflow-rail-step is-active" data-workflow-step="input" aria-current="step">
                    <span class="workflow-rail-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-dna"></use></svg></span>
                    <span><strong>Input</strong></span>
                </button>
                <button type="button" class="workflow-rail-step" data-workflow-step="hypothesize">
                    <span class="workflow-rail-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-path"></use></svg></span>
                    <span><strong>Hypothesize</strong></span>
                </button>
                <button type="button" class="workflow-rail-step" data-workflow-step="validate">
                    <span class="workflow-rail-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-seal-check"></use></svg></span>
                    <span><strong>Validate</strong></span>
                </button>
                <button type="button" class="workflow-rail-step" data-workflow-step="rank">
                    <span class="workflow-rail-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-arrows-down-up"></use></svg></span>
                    <span><strong>Rank</strong></span>
                </button>
                <button type="button" class="workflow-rail-step" data-workflow-step="interpret">
                    <span class="workflow-rail-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-book-open"></use></svg></span>
                    <span><strong>Interpret</strong></span>
                </button>
            </nav>
        </aside>
`);
})();
