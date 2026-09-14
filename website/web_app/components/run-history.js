(() => {
    'use strict';

    window.definePageFragment('run-history', String.raw`
        <!-- History Section -->
        <section id="history-section" class="history-section" style="display: none;">
            <div class="history-container">
                <div class="history-header">
                    <div>
                        <h1 class="history-title">Run History</h1>
                        <p class="history-subtitle">View and manage your past analyses</p>
                    </div>
                    <button id="clear-history-btn" class="clear-history-btn" onclick="clearAllHistory()">
                        <span><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-trash"></use></svg></span> Clear History
                    </button>
                </div>
                <div class="history-filters">
                    <input type="text" id="history-search" class="history-search" placeholder="Search by disease or genes..." oninput="filterHistory()">
                    <select id="history-status-filter" class="filter-select" onchange="filterHistory()">
                        <option value="">All Statuses</option>
                        <option value="queued">Queued</option>
                        <option value="running">Running</option>
                        <option value="completed">Completed</option>
                        <option value="error">Error</option>
                    </select>
                </div>
                <div class="history-results-count"></div>
                <div id="history-table-container">
                    <table class="history-table">
                        <thead>
                            <tr>
                                <th>Session ID</th>
                                <th>Disease</th>
                                <th>Genes</th>
                                <th>Model</th>
                                <th>Created</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="history-tbody">
                        </tbody>
                    </table>
                </div>
                <div id="history-empty" class="history-empty" style="display: none;">
                    <p>No analysis history found. Run your first analysis to see it here.</p>
                </div>
            </div>
        </section>
`);
})();
