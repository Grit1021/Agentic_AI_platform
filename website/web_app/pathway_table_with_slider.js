// ============================================================================
// RENDERING
// ============================================================================

function renderPathwayTable(pathways) {
    if (!pathways || pathways.length === 0) return '';

    // Generate unique table ID for multiple tables
    const tableId = `pathway-table-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    // If only 1-3 pathways, show all without slider
    if (pathways.length <= 3) {
        let html = `<table class="pathway-table">
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Pathway</th>
                    <th>p-value</th>
                    <th>Score</th>
                    <th>Category</th>
                </tr>
            </thead>
            <tbody>`;

        pathways.forEach((pw, i) => {
            const categoryClass = (pw.category || '').replace(':', '\\:');
            html += `<tr>
                <td>${i + 1}</td>
                <td>${escapeHtml(pw.name)}</td>
                <td>${formatPValue(pw.p_value)}</td>
                <td>${pw.score ? pw.score.toFixed(1) : '-'}</td>
                <td><span class="category-badge ${categoryClass}">${pw.category || '-'}</span></td>
            </tr>`;
        });

        html += `</tbody></table>`;
        return html;
    }

    // For 4+ pathways, use slider navigation  
    let html = `
        <div class="pathway-slider-container" id="${tableId}">
            <div class="pathway-slider-header">
                <strong>Found ${pathways.length} pathways</strong>
                <span class="pathway-counter">
                    Viewing: <span class="current-index">1</span> / ${pathways.length}
                </span>
            </div>
            
            <table class="pathway-table">
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Pathway</th>
                        <th>p-value</th>
                        <th>Score</th>
                        <th>Category</th>
                    </tr>
                </thead>
                <tbody class="pathway-tbody">`;

    // Initially show first pathway
    const pw = pathways[0];
    const categoryClass = (pw.category || '').replace(':', '\\:');
    html += `<tr>
        <td>1</td>
        <td>${escapeHtml(pw.name)}</td>
        <td>${formatPValue(pw.p_value)}</td>
        <td>${pw.score ? pw.score.toFixed(1) : '-'}</td>
        <td><span class="category-badge ${categoryClass}">${pw.category || '-'}</span></td>
    </tr>`;

    html += `</tbody>
            </table>
            
            <div class="pathway-slider-controls">
                <button class="slider-btn prev-btn">◀ Previous</button>
                <input type="range" 
                       class="pathway-slider" 
                       min="1" 
                       max="${pathways.length}" 
                       value="1" 
                       step="1">
                <button class="slider-btn next-btn">Next ▶</button>
            </div>
        </div>
    `;

    // Attach event listeners after DOM insertion
    setTimeout(() => {
        setupPathwaySlider(tableId, pathways);
    }, 0);

    return html;
}

function setupPathwaySlider(tableId, pathways) {
    const container = document.getElementById(tableId);
    if (!container) return;

    const slider = container.querySelector('.pathway-slider');
    const tbody = container.querySelector('.pathway-tbody');
    const prevBtn = container.querySelector('.prev-btn');
    const nextBtn = container.querySelector('.next-btn');
    const currentIndex = container.querySelector('.current-index');

    function updatePathway(index) {
        const i = index - 1; // Convert to 0-based
        const pw = pathways[i];
        const categoryClass = (pw.category || '').replace(':', '\\:');

        tbody.classList.add('updating');

        setTimeout(() => {
            tbody.innerHTML = `<tr>
                <td>${index}</td>
                <td>${escapeHtml(pw.name)}</td>
                <td>${formatPValue(pw.p_value)}</td>
                <td>${pw.score ? pw.score.toFixed(1) : '-'}</td>
                <td><span class="category-badge ${categoryClass}">${pw.category || '-'}</span></td>
            </tr>`;

            tbody.classList.remove('updating');
            currentIndex.textContent = index;
            prevBtn.disabled = index <= 1;
            nextBtn.disabled = index >= pathways.length;
        }, 100);
    }

    slider.addEventListener('input', (e) => {
        updatePathway(parseInt(e.target.value));
    });

    prevBtn.addEventListener('click', () => {
        const newValue = Math.max(1, parseInt(slider.value) - 1);
        slider.value = newValue;
        updatePathway(newValue);
    });

    nextBtn.addEventListener('click', () => {
        const newValue = Math.min(pathways.length, parseInt(slider.value) + 1);
        slider.value = newValue;
        updatePathway(newValue);
    });
}
