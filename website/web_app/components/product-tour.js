(() => {
    'use strict';

    window.definePageFragment('product-tour', String.raw`
    <div id="product-tour" class="product-tour hidden" role="dialog" aria-modal="true" aria-labelledby="product-tour-title" aria-describedby="product-tour-copy">
        <div class="product-tour-backdrop"></div>
        <section class="product-tour-card">
            <div class="product-tour-progress">
                <span id="product-tour-count" aria-live="polite">1 of 4</span>
                <div class="product-tour-dismiss">
                    <button type="button" id="product-tour-skip-all" class="product-tour-skip-all">Skip all</button>
                    <button type="button" id="product-tour-close" aria-label="Close tour"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-x"></use></svg></button>
                </div>
            </div>
            <h2 id="product-tour-title">Choose the disease context</h2>
            <p id="product-tour-copy">Start with a disease or phenotype. Matching an ontology term enables Open Targets gene import.</p>
            <div class="product-tour-actions">
                <button type="button" id="product-tour-skip" class="product-tour-skip" aria-label="Skip this tour step">Skip</button>
                <div><button type="button" id="product-tour-back" class="product-tour-back">Back</button><button type="button" id="product-tour-next" class="product-tour-next">Next</button></div>
            </div>
        </section>
    </div>
`);
})();
