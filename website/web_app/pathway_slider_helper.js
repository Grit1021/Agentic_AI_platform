// Insert this function AFTER renderPathwayTable (around line 465)
// And BEFORE renderDrugTable (around line 467)

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
