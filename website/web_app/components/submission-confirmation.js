(() => {
    'use strict';

    window.definePageFragment('submission-confirmation', String.raw`
        <section
            id="submission-section"
            class="submission-section hidden"
            aria-labelledby="submission-title"
            tabindex="-1"
        >
            <div class="submission-receipt">
                <div class="submission-success-mark" aria-hidden="true">
                    <svg class="ph"><use href="#ph-check"></use></svg>
                </div>

                <p class="submission-kicker">Analysis submitted</p>
                <h1 id="submission-title">Your pathway analysis is underway</h1>
                <p class="submission-intro">
                    GenePathwayAI will continue in the background. You can return to the homepage or follow this run in Job Center.
                </p>

                <dl class="submission-job-summary" aria-label="Submitted analysis details">
                    <div>
                        <dt>Status</dt>
                        <dd>
                            <span id="submission-job-status" class="submission-status" data-state="queued" role="status" aria-live="polite">
                                <span aria-hidden="true"></span>
                                <span id="submission-job-status-label">Queued</span>
                            </span>
                        </dd>
                    </div>
                    <div>
                        <dt>Analysis</dt>
                        <dd id="submission-job-label">Pathway analysis</dd>
                    </div>
                    <div>
                        <dt>Genes</dt>
                        <dd id="submission-gene-count">0 genes</dd>
                    </div>
                    <div>
                        <dt>Run ID</dt>
                        <dd><code id="submission-run-id">Pending</code></dd>
                    </div>
                </dl>

                <p class="submission-next-label">Where would you like to go next?</p>
                <div class="submission-actions">
                    <button type="button" id="submission-home-button" class="submission-action submission-action--home">
                        <span class="submission-action-icon" aria-hidden="true">
                            <svg class="ph"><use href="#ph-house"></use></svg>
                        </span>
                        <span class="submission-action-copy">
                            <strong>Back to homepage</strong>
                            <small>Return to the input page. Your active job stays visible.</small>
                        </span>
                        <svg class="ph submission-action-arrow" aria-hidden="true"><use href="#ph-arrow-right"></use></svg>
                    </button>

                    <a href="#history" id="submission-job-center-link" class="submission-action submission-action--jobs">
                        <span class="submission-action-icon" aria-hidden="true">
                            <svg class="ph"><use href="#ph-clipboard-text"></use></svg>
                        </span>
                        <span class="submission-action-copy">
                            <strong>Open Job Center</strong>
                            <small>Track progress, open results, or return to this run later.</small>
                        </span>
                        <svg class="ph submission-action-arrow" aria-hidden="true"><use href="#ph-arrow-right"></use></svg>
                    </a>
                </div>

                <p class="submission-note">
                    You do not need to keep this page open. Completion email is sent when notifications are available.
                </p>
            </div>
        </section>
`);
})();
