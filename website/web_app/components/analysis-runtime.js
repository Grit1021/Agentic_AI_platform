(() => {
    'use strict';

    window.definePageFragment('analysis-runtime', String.raw`
        <!-- Chat Section (shown after analysis starts) -->
        <section id="chat-section" class="chat-section hidden">
            <div id="analysis-progress" class="analysis-progress" aria-live="polite">
                <div class="analysis-progress-inner">
                    <div class="analysis-progress-heading">
                        <div>
                            <span class="analysis-progress-label">Live analysis progress</span>
                            <strong id="analysis-progress-stage">Starting analysis</strong>
                        </div>
                        <div class="analysis-progress-heading-actions">
                            <span id="analysis-progress-percent" class="analysis-progress-percent">0%</span>
                            <button type="button" id="analysis-background-btn" class="analysis-background-btn">Back to homepage</button>
                        </div>
                    </div>
                    <progress id="analysis-progress-bar" class="analysis-progress-bar" max="100" value="0">0%</progress>
                    <div class="analysis-progress-meta">
                        <span id="analysis-progress-detail">Submitting the analysis request.</span>
                        <time id="analysis-progress-elapsed">Elapsed 0:00</time>
                        <span id="analysis-progress-remaining">Estimating time remaining</span>
                    </div>
                    <p id="analysis-progress-email" class="analysis-progress-email">You may leave this view while the analysis continues.</p>
                    <p id="analysis-progress-mode" class="analysis-progress-mode">Running automatically. Optional questions are off.</p>
                </div>
            </div>
            <div class="chat-container">
                <!-- Messages will be dynamically added here -->
                <div id="chat-messages" class="chat-messages"></div>

                <!-- Typing indicator -->
                <div id="typing-indicator" class="typing-indicator hidden">
                    <div class="typing-dots">
                        <span></span><span></span><span></span>
                    </div>
                    <span class="typing-text">Analysis in progress...</span>
                </div>
            </div>

            <!-- Query Input (shown at checkpoints) -->
            <div id="query-panel" class="query-panel hidden">
                <input type="text" id="query-input" class="query-input"
                    placeholder="Ask a question about the analysis...">
                <button id="query-submit" class="query-submit">
                    <span>Ask</span>
                </button>
                <p id="query-input-error" class="input-validation-error hidden" role="alert"></p>
            </div>
        </section>
`);
})();
