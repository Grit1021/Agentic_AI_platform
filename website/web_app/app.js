/**
 * Gene Pathway Analysis - Frontend Application
 * =============================================
 * Handles the conversational UI and API communication
 */

// ============================================================================
// STATE
// ============================================================================

const state = {
    sessionId: null,
    isAnalyzing: false,
    pollingInterval: null,
    lastMessageCount: 0,
    quota: null,
    analysisStartedAt: null,
    backgrounded: false,
    backgroundResults: null,
    userEmail: '',
    emailNotificationsAvailable: false
};

const frontendDataState = {
    geneLists: {},
    completedExamples: null,
    resultCache: new Map(),
    ready: false,
};

const HOSTED_APP_URL = String(
    document.querySelector('meta[name="hosted-app-url"]')?.content || ''
).replace(/\/$/, '');

// Collected reasoning traces from messages (populated during analysis)
const collectedReasoning = [];

// Gene list state
const geneListState = {
    allLists: {},       // full metadata from /api/gene-lists
    selectedDisease: null,
    selectedListId: null,
    selectedMeta: null
};

const GENE_SEARCH_SEEDS = [
    'APOE', 'APP', 'PSEN1', 'PSEN2', 'MAPT', 'TREM2', 'CD33', 'CLU', 'BIN1',
    'ABCA7', 'SORL1', 'PICALM', 'CR1', 'CASS4', 'INPP5D', 'MEF2C', 'PTK2B',
    'SPI1', 'MS4A6A', 'IL1B', 'TNF', 'TYROBP', 'C1QA', 'C1QB', 'C1QC', 'C3',
    'BACE1', 'GSK3B', 'SQSTM1', 'LAMP1', 'CTSD', 'SOD2', 'GPX1', 'CAMK2A'
];

const geneSearchState = {
    index: new Set(GENE_SEARCH_SEEDS),
    suggestions: [],
    activeIndex: -1,
    expandedSelection: false
};

const geneQueryAutocompleteState = {
    activeIndex: -1,
    searchTimer: null,
    searchController: null,
    tokenStart: 0,
    tokenEnd: 0,
    query: '',
};

// ============================================================================
// DOM ELEMENTS
// ============================================================================

const elements = {
    heroSection: document.getElementById('hero-section'),
    inputSection: document.getElementById('input-section'),
    chatSection: document.getElementById('chat-section'),
    resultsSection: document.getElementById('results-section'),

    geneInput: document.getElementById('gene-input'),
    geneQuerySuggestions: document.getElementById('gene-query-suggestions'),
    geneFileInput: document.getElementById('gene-file-input'),
    uploadGeneListBtn: document.getElementById('upload-gene-list-btn'),
    geneInputQuality: document.getElementById('gene-input-quality'),
    geneSearchInput: document.getElementById('gene-search-input'),
    geneSuggestions: document.getElementById('gene-suggestions'),
    selectedGeneStrip: document.getElementById('selected-gene-strip'),
    clearGenesBtn: document.getElementById('clear-genes-btn'),
    diseaseSelect: document.getElementById('disease-select'),
    geneCount: document.getElementById('gene-count'),
    startBtn: document.getElementById('start-btn'),
    quotaStatus: document.getElementById('quota-status'),
    headerQuotaStatus: document.getElementById('header-quota-status'),

    chatMessages: document.getElementById('chat-messages'),
    typingIndicator: document.getElementById('typing-indicator'),
    queryPanel: document.getElementById('query-panel'),
    queryInput: document.getElementById('query-input'),
    querySubmit: document.getElementById('query-submit'),
    analysisProgress: document.getElementById('analysis-progress'),
    analysisProgressBar: document.getElementById('analysis-progress-bar'),
    analysisProgressStage: document.getElementById('analysis-progress-stage'),
    analysisProgressPercent: document.getElementById('analysis-progress-percent'),
    analysisProgressDetail: document.getElementById('analysis-progress-detail'),
    analysisProgressElapsed: document.getElementById('analysis-progress-elapsed'),
    analysisProgressRemaining: document.getElementById('analysis-progress-remaining'),
    analysisProgressEmail: document.getElementById('analysis-progress-email'),
    analysisBackgroundBtn: document.getElementById('analysis-background-btn'),
    activeJobBanner: document.getElementById('active-job-banner'),
    activeJobBannerText: document.getElementById('active-job-banner-text'),
    viewActiveJob: document.getElementById('view-active-job'),

    // Results View Elements
    backToProcess: document.getElementById('back-to-process'),
    retryNarrativesBtn: document.getElementById('retry-narratives-btn'),
    exportBtn: document.getElementById('export-btn'),
    diseaseNameDisplay: document.getElementById('disease-name-display'),
    geneCountDisplay: document.getElementById('gene-count-display'),
    analysisDate: document.getElementById('analysis-date'),
    modelVersion: document.getElementById('model-version'),
    metricCards: document.getElementById('metric-cards'),
    summaryText: document.getElementById('summary-text'),
    evidenceSections: document.getElementById('evidence-sections')
};

// Store current results data
let currentResults = null;
let pathwayDisplayLimit = 5;


// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    initAuthUserMenu();
    initAnalysisSettings();
    initWorkflowNavigation();
    initProductTour();
    initFeaturedExamplesMenu();

    // Disease context is the first, equally weighted input.
    const contextGrid = document.querySelector('.analysis-context-grid');
    const diseaseGroup = contextGrid?.querySelector('.input-workspace-group--disease');
    const geneGroup = contextGrid?.querySelector('.input-workspace-group--genes');
    if (contextGrid && diseaseGroup && geneGroup) contextGrid.insertBefore(diseaseGroup, geneGroup);

    // Gene count tracking
    elements.geneInput.addEventListener('input', updateGeneCount);
    elements.geneInput.addEventListener('input', clearOpenTargetsGeneImportState);
    initGeneQueryAutocomplete();
    initGeneSearch();
    initGeneFileUpload();
    updateGeneCount();

    // Load all homepage reference data from the backend-owned data contract.
    initializeFrontendData();
    loadQuotaStatus();

    // Start analysis
    elements.startBtn.addEventListener('click', startAnalysis);
    document.getElementById('view-demo-btn')?.addEventListener('click', showBundledDemoResult);

    // Query submission
    elements.querySubmit.addEventListener('click', submitQuery);
    elements.queryInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') submitQuery();
    });

    // Export dropdown
    elements.exportBtn.addEventListener('click', toggleExportDropdown);
    document.querySelectorAll('.export-option').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const format = e.currentTarget.dataset.format;
            exportData(format);
            closeExportDropdown();
        });
    });
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.export-dropdown-wrapper')) {
            closeExportDropdown();
        }
    });

    // Results View Navigation
    elements.backToProcess?.addEventListener('click', hideResultsView);
    elements.retryNarrativesBtn?.addEventListener('click', retryFallbackNarratives);
    document.getElementById('pathways-per-database')?.addEventListener('change', event => {
        pathwayDisplayLimit = event.target.value === 'all' ? Infinity : Number(event.target.value) || 5;
        const homeLimit = document.getElementById('input-pathways-per-database');
        if (homeLimit) homeLimit.value = event.target.value;
        if (currentResults?.pathways) renderEvidenceSectionsView(currentResults.pathways);
    });
    elements.analysisBackgroundBtn?.addEventListener('click', backgroundAnalysis);
    elements.viewActiveJob?.addEventListener('click', showActiveJob);
    document.querySelectorAll('[data-report-view]').forEach(button => {
        button.addEventListener('click', () => setReportView(button.dataset.reportView));
    });

});

function getFeaturedExamplesMenuItems() {
    return [...document.querySelectorAll('#featured-examples-menu [role="menuitem"]')];
}

function setFeaturedExamplesMenuOpen(open, { focusItem = null } = {}) {
    const trigger = document.getElementById('featured-examples-menu-button');
    const menu = document.getElementById('featured-examples-menu');
    if (!trigger || !menu) return;
    trigger.setAttribute('aria-expanded', String(open));
    menu.hidden = !open;
    if (!open) return;

    const items = getFeaturedExamplesMenuItems();
    const target = focusItem === 'last' ? items.at(-1) : focusItem === 'first' ? items[0] : null;
    target?.focus({ preventScroll: true });
}

function openNavigationCompletedExample(event, diseaseCode) {
    event?.preventDefault();
    setFeaturedExamplesMenuOpen(false);

    const baseUrl = window.location.protocol === 'file:'
        ? HOSTED_APP_URL
        : window.location.origin;
    if (!baseUrl) {
        alert('The hosted completed examples are not configured for this preview.');
        return false;
    }

    const targetUrl = new URL('/', baseUrl);
    targetUrl.searchParams.set('demo', '1');
    targetUrl.searchParams.set('example', diseaseCode);
    window.location.assign(targetUrl.toString());
    return false;
}

function initFeaturedExamplesMenu() {
    const wrapper = document.querySelector('.nav-featured-menu');
    const trigger = document.getElementById('featured-examples-menu-button');
    const menu = document.getElementById('featured-examples-menu');
    if (!wrapper || !trigger || !menu) return;

    const params = new URLSearchParams(window.location.search);
    const currentCode = String(params.get('example') || '').toUpperCase();
    getFeaturedExamplesMenuItems().forEach(item => {
        const selected = item.dataset.exampleCode === currentCode;
        item.classList.toggle('is-current', selected);
        if (selected) item.setAttribute('aria-current', 'page');
        item.addEventListener('click', event => {
            openNavigationCompletedExample(event, item.dataset.exampleCode);
        });
    });

    trigger.addEventListener('click', event => {
        event.stopPropagation();
        setFeaturedExamplesMenuOpen(trigger.getAttribute('aria-expanded') !== 'true');
    });
    trigger.addEventListener('keydown', event => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            setFeaturedExamplesMenuOpen(true, {
                focusItem: event.key === 'ArrowUp' ? 'last' : 'first',
            });
        }
    });
    menu.addEventListener('keydown', event => {
        const items = getFeaturedExamplesMenuItems();
        const currentIndex = items.indexOf(document.activeElement);
        let nextIndex = null;
        if (event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % items.length;
        if (event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + items.length) % items.length;
        if (event.key === 'Home') nextIndex = 0;
        if (event.key === 'End') nextIndex = items.length - 1;
        if (nextIndex !== null) {
            event.preventDefault();
            items[nextIndex]?.focus();
        }
        if (event.key === 'Escape') {
            event.preventDefault();
            setFeaturedExamplesMenuOpen(false);
            trigger.focus();
        }
        if (event.key === 'Tab') setFeaturedExamplesMenuOpen(false);
    });
    document.addEventListener('click', event => {
        if (!wrapper.contains(event.target)) setFeaturedExamplesMenuOpen(false);
    });
}

function getModelOptionLabel(model) {
    return ({
        'gpt-5.1': 'GPT-5.1 (default)',
        'gpt-5-mini': 'GPT-5 mini (faster)',
        'gpt-4.1': 'GPT-4.1 (non-reasoning)',
    })[model] || model;
}

async function loadAnalysisSettingsConfig() {
    if (window.location.protocol === 'file:') return;
    try {
        const response = await fetch('/api/status', {
            headers: { 'Accept': 'application/json' },
            cache: 'no-store',
        });
        if (!response.ok) return;
        const payload = await response.json();
        state.emailNotificationsAvailable = Boolean(payload.email_notifications_configured);
        updateProgressNotificationCopy();
        const select = document.getElementById('openai-model-select');
        const allowedModels = Array.isArray(payload.allowed_gpt_models)
            ? payload.allowed_gpt_models.filter(Boolean)
            : [];
        if (!select || !allowedModels.length) return;
        select.replaceChildren(...allowedModels.map(model => {
            const option = document.createElement('option');
            option.value = model;
            option.textContent = getModelOptionLabel(model);
            return option;
        }));
        select.value = allowedModels.includes(payload.gpt_model)
            ? payload.gpt_model
            : allowedModels[0];
    } catch (_) {
        // Static previews intentionally keep the bundled model choices.
    }
}

function initAnalysisSettings() {
    loadAnalysisSettingsConfig();
    document.getElementById('input-pathways-per-database')?.addEventListener('change', event => {
        pathwayDisplayLimit = event.target.value === 'all' ? Infinity : Number(event.target.value) || 5;
        const resultsLimit = document.getElementById('pathways-per-database');
        if (resultsLimit) resultsLimit.value = event.target.value;
        if (currentResults?.pathways) renderEvidenceSectionsView(currentResults.pathways);
    });
}

const WORKFLOW_STEP_LABELS = {
    input: 'Input is ready',
    hypothesize: 'Candidate pathway generation',
    validate: 'Statistical validation',
    rank: 'Evidence-based ranking',
    interpret: 'Biological interpretation',
};

function setActiveWorkflowStep(step) {
    document.querySelectorAll('.workflow-rail-step').forEach(button => {
        const active = button.dataset.workflowStep === step;
        button.classList.toggle('is-active', active);
        if (active) button.setAttribute('aria-current', 'step');
        else button.removeAttribute('aria-current');
    });
    const status = document.getElementById('workflow-navigation-status');
    if (status) status.textContent = WORKFLOW_STEP_LABELS[step] || '';
}

function getWorkflowScrollTarget(step) {
    const resultsVisible = elements.resultsSection && !elements.resultsSection.classList.contains('hidden');
    const chatVisible = elements.chatSection && !elements.chatSection.classList.contains('hidden');

    if (step === 'input') return document.querySelector('.analysis-context-grid');
    if (chatVisible) {
        const stageMap = { hypothesize: 1, validate: 2, rank: 3, interpret: 4 };
        const stage = stageMap[step];
        return document.querySelector(`[data-pipeline-stage="${stage}"]`) || elements.analysisProgress;
    }
    if (resultsVisible) {
        return {
            hypothesize: document.querySelector('.database-reasoning-details'),
            validate: document.querySelector('.summary-ranked-table-wrap') || document.querySelector('.summary-card'),
            rank: document.querySelector('.evidence-register-card'),
            interpret: document.querySelector('.overall-interpretation-card'),
        }[step];
    }
    return document.querySelector('.analysis-context-grid');
}

function navigateToWorkflowStep(step) {
    if (step === 'input') showAnalysisView();
    const target = getWorkflowScrollTarget(step);
    setActiveWorkflowStep(step);
    if (!target) return;
    let ancestor = target.parentElement;
    while (ancestor) {
        if (ancestor.tagName === 'DETAILS') ancestor.open = true;
        ancestor = ancestor.parentElement;
    }
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    window.requestAnimationFrame(() => {
        target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
    });
}

function initWorkflowNavigation() {
    document.querySelectorAll('.workflow-rail-step').forEach(button => {
        button.addEventListener('click', () => navigateToWorkflowStep(button.dataset.workflowStep));
    });
    setActiveWorkflowStep('input');
}

const PRODUCT_TOUR_STEPS = [
    {
        target: '.input-workspace-group--disease',
        title: 'Choose the disease context',
        copy: 'Search for a disease or phenotype, or load a complete disease and gene example.',
    },
    {
        target: '.input-workspace-group--genes',
        title: 'Add the gene list',
        copy: 'Paste or upload identifiers, download a tested file, or import ranked disease-associated genes from Open Targets.',
    },
    {
        target: '.analysis-options',
        title: 'Control the analysis',
        copy: 'Feedback is enabled by default. Open this panel to choose the model and highlighted pathway count.',
    },
    {
        target: '#featured-examples',
        title: 'Review a finished example',
        copy: 'Open a completed disease analysis before starting a new run.',
    },
];

let productTourIndex = 0;
let productTourReturnFocus = null;
let productTourContinuation = '';

function hideProductTour({ followContinuation = true } = {}) {
    const tour = document.getElementById('product-tour');
    document.querySelectorAll('.tour-highlight').forEach(element => element.classList.remove('tour-highlight'));
    tour?.classList.add('hidden');
    if (productTourReturnFocus instanceof HTMLElement && document.contains(productTourReturnFocus)) {
        productTourReturnFocus.focus();
    }
    productTourReturnFocus = null;
    const continuation = productTourContinuation;
    productTourContinuation = '';
    if (followContinuation && continuation) {
        window.location.assign(continuation);
    }
}

function renderProductTourStep() {
    const tour = document.getElementById('product-tour');
    const step = PRODUCT_TOUR_STEPS[productTourIndex];
    if (!tour || !step) return;
    document.querySelectorAll('.tour-highlight').forEach(element => element.classList.remove('tour-highlight'));
    const target = document.querySelector(step.target);
    target?.classList.add('tour-highlight');
    target?.scrollIntoView({ behavior: 'auto', block: 'center' });
    document.getElementById('product-tour-count').textContent = `${productTourIndex + 1} of ${PRODUCT_TOUR_STEPS.length}`;
    document.getElementById('product-tour-title').textContent = step.title;
    document.getElementById('product-tour-copy').textContent = step.copy;
    const back = document.getElementById('product-tour-back');
    const next = document.getElementById('product-tour-next');
    if (back) back.disabled = productTourIndex === 0;
    if (next) next.textContent = productTourIndex === PRODUCT_TOUR_STEPS.length - 1 ? 'Finish' : 'Next';
}

function showProductTour({ force = false } = {}) {
    const tour = document.getElementById('product-tour');
    if (!tour) return;
    const params = new URLSearchParams(window.location.search);
    const isPostLoginTour = params.get('tour') === '1';
    if (!force && !isPostLoginTour && (params.get('demo') === '1' || window.location.hash.startsWith('#docs/'))) return;
    productTourContinuation = '';
    if (isPostLoginTour) {
        const continuation = String(params.get('after_tour') || '').trim();
        if (continuation.startsWith('/') && !continuation.startsWith('//') && continuation !== '/') {
            productTourContinuation = continuation;
        }
        params.delete('tour');
        params.delete('after_tour');
        const remainingQuery = params.toString();
        const cleanUrl = `${window.location.pathname}${remainingQuery ? `?${remainingQuery}` : ''}${window.location.hash}`;
        window.history.replaceState(window.history.state, '', cleanUrl);
    }
    productTourReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    productTourIndex = 0;
    tour.classList.remove('hidden');
    renderProductTourStep();
    document.getElementById('product-tour-next')?.focus();
}

function skipCurrentProductTourStep() {
    if (productTourIndex >= PRODUCT_TOUR_STEPS.length - 1) {
        hideProductTour();
        return;
    }
    productTourIndex += 1;
    renderProductTourStep();
    document.getElementById('product-tour-skip')?.focus();
}

function trapProductTourFocus(event) {
    if (event.key !== 'Tab') return;
    const tour = document.getElementById('product-tour');
    if (!tour || tour.classList.contains('hidden')) return;
    const controls = Array.from(tour.querySelectorAll('button:not([disabled])'));
    if (!controls.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}

function initProductTour() {
    document.getElementById('tour-replay-button')?.addEventListener('click', () => {
        showAnalysisView();
        showProductTour({ force: true });
    });
    document.getElementById('product-tour-close')?.addEventListener('click', hideProductTour);
    document.getElementById('product-tour-skip-all')?.addEventListener('click', hideProductTour);
    document.getElementById('product-tour-skip')?.addEventListener('click', skipCurrentProductTourStep);
    document.getElementById('product-tour-back')?.addEventListener('click', () => {
        productTourIndex = Math.max(0, productTourIndex - 1);
        renderProductTourStep();
    });
    document.getElementById('product-tour-next')?.addEventListener('click', () => {
        if (productTourIndex >= PRODUCT_TOUR_STEPS.length - 1) {
            hideProductTour();
            return;
        }
        productTourIndex += 1;
        renderProductTourStep();
    });
    document.getElementById('product-tour')?.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            event.preventDefault();
            hideProductTour();
            return;
        }
        trapProductTourFocus(event);
    });
    window.setTimeout(() => showProductTour(), 250);
}

const UNSAFE_BIOMEDICAL_TEXT_PATTERNS = [
    /\b(?:how\s+to|steps?\s+to|instructions?\s+(?:for|to)|help\s+me)\b.{0,80}\b(?:kill|murder|shoot|stab|bomb|explosive|poison|weapon|attack)\b/is,
    /\b(?:i\s+will|we\s+will|i(?:'m|\s+am)\s+going\s+to)\s+(?:kill|murder|shoot|stab|bomb|attack|hurt)\b/i,
    /\b(?:kill\s+myself|suicide\s+method|how\s+to\s+die)\b/i,
    /\b(?:ignore|override)\s+(?:all\s+)?(?:previous|system|developer)\s+instructions?\b/i,
    /\b(?:reveal|print|return)\b.{0,40}\b(?:api\s*key|secret|environment\s+variables?|system\s+prompt)\b/i,
];

function getBiomedicalTextError(value, fieldName = 'This field') {
    const text = String(value || '').trim();
    if (!text) return '';
    if (/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/.test(text)) {
        return `${fieldName} contains unsupported control characters.`;
    }
    if (UNSAFE_BIOMEDICAL_TEXT_PATTERNS.some(pattern => pattern.test(text))) {
        return `${fieldName} only accepts biomedical research context. Remove violent, threatening or unrelated instructions.`;
    }
    return '';
}

function showInputValidationError(elementId, message) {
    const element = document.getElementById(elementId);
    if (!element) return;
    element.textContent = message || '';
    element.classList.toggle('hidden', !message);
}

async function initAuthUserMenu() {
    const menu = document.getElementById('auth-user-menu');
    const emailEl = document.getElementById('auth-user-email');
    const adminLink = document.getElementById('admin-dashboard-link');
    if (adminLink) adminLink.hidden = true;
    try {
        const response = await fetch('/api/auth/me', {
            headers: { 'Accept': 'application/json' }
        });
        if (!response.ok) return;
        const data = await response.json();
        if (data.quota) updateQuotaStatus(data.quota);
        if (menu && emailEl && data.authenticated && data.email) {
            state.userEmail = data.email;
            emailEl.textContent = data.email;
            menu.classList.remove('hidden');
            if (adminLink) adminLink.hidden = !data.is_admin;
            updateProgressNotificationCopy();
        }
    } catch (_) {
        // The read-only localhost preview has no authentication endpoint.
    }
}

async function initializeFrontendData() {
    if (window.location.protocol === 'file:') {
        console.info('Backend data is available when the application is served over HTTP.');
        updateFeaturedExampleButtons();
        return;
    }

    try {
        const response = await fetch('/api/frontend-data', {
            headers: { 'Accept': 'application/json' },
            cache: 'no-store',
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `Reference data returned HTTP ${response.status}`);

        frontendDataState.geneLists = payload.gene_lists || {};
        frontendDataState.completedExamples = payload.completed_examples || null;
        frontendDataState.ready = true;

        await initGeneListLoader(frontendDataState.geneLists);
        initCompletedExampleLauncher();
        updateFeaturedExampleButtons();

        const params = new URLSearchParams(window.location.search);
        if (params.get('demo') === '1') {
            const requested = String(params.get('example') || '').toUpperCase();
            const select = document.getElementById('completed-example-select');
            if (requested && select && [...select.options].some(option => option.value === requested)) {
                select.value = requested;
                updateCompletedExampleMeta();
            }
            await showBundledDemoResult();
        }
    } catch (error) {
        console.warn('Backend reference data is unavailable:', error);
        const exampleSelect = document.getElementById('gene-list-disease-select');
        if (exampleSelect) exampleSelect.innerHTML = '<option value="">Examples unavailable</option>';
        updateFeaturedExampleButtons();
    }
}

/** Backend-provided completed-result catalog. Full results are loaded on demand. */
function getCompletedExampleArchive() {
    const archive = frontendDataState.completedExamples;
    if (!archive || typeof archive !== 'object') return null;
    const examples = archive.examples;
    if (!examples || typeof examples !== 'object') return null;
    const codes = Object.keys(examples).filter(code => examples[code]);
    if (!codes.length) return null;
    return {
        codes,
        examples,
        defaultCode: codes.includes(archive.default) ? archive.default : codes[0]
    };
}

function describeCompletedExample(example) {
    if (!example) return '';
    const parts = [];
    const geneCount = Number(example.gene_count) || (example.result?.input_genes || []).length;
    if (geneCount) parts.push(`${geneCount} input genes`);
    const pathwayCount = Number(example.pathway_count) || (example.result?.pathways || []).length;
    if (pathwayCount) parts.push(`${pathwayCount} validated pathways`);
    return parts.join(', ');
}

function toggleMoreFeaturedExamples(button) {
    const panel = document.getElementById('featured-more-examples');
    if (!panel) return;
    const opening = panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !opening);
    button?.setAttribute('aria-expanded', String(opening));
}

function setReportView(view = 'summary') {
    const detailed = view === 'detailed';
    elements.resultsSection?.classList.toggle('report-view--detailed', detailed);
    document.querySelectorAll('[data-report-view]').forEach(button => {
        const active = button.dataset.reportView === (detailed ? 'detailed' : 'summary');
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
    });
}

function updateCompletedExampleMeta() {
    const archive = getCompletedExampleArchive();
    const meta = document.getElementById('completed-example-meta');
    const select = document.getElementById('completed-example-select');
    if (!archive || !meta || !select) return;
    meta.textContent = describeCompletedExample(archive.examples[select.value])
        || 'Archived completed analysis';
}

function initCompletedExampleLauncher() {
    const select = document.getElementById('completed-example-select');
    const launcher = document.querySelector('.completed-example-launcher');
    const archive = getCompletedExampleArchive();
    if (!select) return;
    if (!archive) {
        // No archive bundled: keep the plain button, drop the picker.
        launcher?.classList.add('completed-example-launcher--bare');
        select.remove();
        return;
    }
    // The markup ships a single placeholder option; the real list comes from
    // whatever the archive actually contains.
    select.innerHTML = archive.codes.map(code => {
        const example = archive.examples[code];
        const label = example.title || example.disease || code;
        return `<option value="${escapeHtml(code)}">${escapeHtml(label)}</option>`;
    }).join('');
    select.value = archive.defaultCode;
    select.addEventListener('change', updateCompletedExampleMeta);
    updateCompletedExampleMeta();
}

async function fetchCompletedExample(code) {
    const archive = getCompletedExampleArchive();
    if (!archive) return null;
    const resolvedCode = archive.examples[code] ? code : archive.defaultCode;
    if (frontendDataState.resultCache.has(resolvedCode)) {
        return frontendDataState.resultCache.get(resolvedCode);
    }
    const response = await fetch(`/api/completed-examples/${encodeURIComponent(resolvedCode)}`, {
        headers: { 'Accept': 'application/json' },
        cache: 'no-store',
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Completed example returned HTTP ${response.status}`);
    frontendDataState.resultCache.set(resolvedCode, payload);
    return payload;
}

async function showCompletedExample(code) {
    const example = await fetchCompletedExample(code);
    if (!example || !example.result) return false;
    renderCompletedRun(example.result, example.title || example.disease || 'Completed result');
    return true;
}

async function openFeaturedCompletedExample(code) {
    if (window.location.protocol === 'file:') {
        if (!HOSTED_APP_URL) {
            alert('The hosted completed examples are not configured for this preview.');
            return false;
        }
        const hostedUrl = new URL(HOSTED_APP_URL);
        hostedUrl.searchParams.set('demo', '1');
        hostedUrl.searchParams.set('example', code);
        window.location.assign(hostedUrl.toString());
        return true;
    }

    const archive = getCompletedExampleArchive();
    if (!archive || !archive.examples[code]) {
        await loadFeaturedInput(code);
        return false;
    }

    const select = document.getElementById('completed-example-select');
    if (select) {
        select.value = code;
        updateCompletedExampleMeta();
    }

    try {
        if (!await showCompletedExample(code)) return false;
    } catch (error) {
        alert(`Unable to open this completed example: ${error.message}`);
        return false;
    }

    const url = new URL(window.location.href);
    url.searchParams.set('demo', '1');
    url.searchParams.set('example', code);
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    return true;
}

async function showBundledDemoResult() {
    const select = document.getElementById('completed-example-select');
    try {
        if (await showCompletedExample(select ? select.value : undefined)) return;
    } catch (error) {
        console.warn('Completed example could not be opened:', error);
    }
    alert('The completed example data is not available.');
}

function renderCompletedRun(bundledResult, statusLabel) {
    if (!bundledResult) return;

    const demoPathwayIds = {
        'neuroinflammatory response': 'GO:0150076',
        'microglial cell activation': 'GO:0001774',
        'inflammatory response': 'GO:0006954',
        'glial cell activation': 'GO:0061900',
        'protein binding': 'GO:0005515',
        'calcium ion binding': 'GO:0005509',
        'lysosome::GO:CC': 'GO:0005764',
        'endoplasmic reticulum': 'GO:0005783',
        'endoplasmic reticulum lumen': 'GO:0005788',
        'lysosome::KEGG': 'hsa04142',
        'apoptosis': 'hsa04210',
        'innate immune system': 'R-HSA-168249',
        'response to oxidative stress': 'GO:0006979',
        'positive regulation of apoptotic process': 'GO:0043065',
        'protein folding': 'GO:0006457',
        'acute inflammatory response': 'GO:0002526'
    };
    const demoPathwayDescriptions = {
        'GO:0150076': 'A Gene Ontology biological process describing inflammatory responses that occur within nervous-system tissue.',
        'GO:0001774': 'A Gene Ontology biological process describing the transition of microglia into an activated functional state.',
        'GO:0006954': 'A protective tissue response to injury, infection or other harmful stimuli that recruits cellular and molecular defenses.',
        'GO:0061900': 'A Gene Ontology biological process describing activation-associated changes in glial-cell state and function.',
        'GO:0005515': 'A Gene Ontology molecular function representing selective, non-covalent interaction with a protein.',
        'GO:0005509': 'A Gene Ontology molecular function representing selective, non-covalent binding to calcium ions.',
        'GO:0005764': 'A lysosome is a membrane-bounded cellular compartment containing hydrolytic enzymes for degradation and recycling.',
        'GO:0005783': 'The endoplasmic reticulum is a membrane network involved in protein and lipid synthesis, folding and transport.',
        'GO:0005788': 'The endoplasmic reticulum lumen is the internal space enclosed by the endoplasmic-reticulum membrane.',
        'hsa04142': 'A KEGG pathway entry organizing lysosomal components involved in macromolecule degradation, trafficking and recycling.',
        'hsa04210': 'A KEGG pathway entry describing the molecular signaling and execution mechanisms of apoptosis.',
        'R-HSA-168249': 'A curated Reactome pathway covering the receptors, signaling cascades and effector processes of innate immunity.',
        'GO:0006979': 'A Gene Ontology biological process describing changes in cell state or activity caused by oxidative stress.',
        'GO:0043065': 'A Gene Ontology biological process that increases the frequency, rate or extent of programmed apoptotic cell death.',
        'GO:0006457': 'A Gene Ontology biological process in which a polypeptide adopts its functional three-dimensional conformation.',
        'GO:0002526': 'A rapid inflammatory response that occurs soon after tissue injury or exposure to an inflammatory stimulus.'
    };
    const demoPathways = (bundledResult.pathways || []).map(pathway => {
        const name = String(pathway.name || pathway.pathway_name || '').toLowerCase();
        const category = pathway.source || pathway.category || '';
        const pathwayId = getPathwayId(pathway)
            || demoPathwayIds[`${name}::${category}`]
            || demoPathwayIds[name]
            || '';
        return {
            ...pathway,
            pathway_id: pathwayId,
            pathway_description: pathway.pathway_description || demoPathwayDescriptions[pathwayId] || '',
            disease_interpretation: pathway.disease_interpretation || pathway.description || pathway.reasoning || ''
        };
    });
    const validatedByDatabase = {};
    demoPathways.forEach(pathway => {
        const category = pathway.source || pathway.category || 'Other';
        validatedByDatabase[category] = (validatedByDatabase[category] || 0) + 1;
    });
    const archivedComparison = bundledResult.validation_comparison || {};
    const archivedByDatabase = archivedComparison.by_database || {};
    const demoResult = {
        ...bundledResult,
        pathways: demoPathways,
        validation_comparison: {
            ...archivedComparison,
            initial_hypotheses: archivedComparison.initial_hypotheses ?? 49,
            statistically_validated: demoPathways.length,
            rounds: archivedComparison.rounds || [],
            by_database: Object.fromEntries(
                ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'].map(category => [category, {
                    initial_hypotheses: archivedByDatabase[category]?.initial_hypotheses ?? null,
                    statistically_validated: validatedByDatabase[category] || 0
                }])
            )
        }
    };

    // The bundled example is backed by a persisted completed run, so the same
    // export endpoints used by live and history views remain available.
    state.sessionId = bundledResult.session_id || state.sessionId;

    hydrateReasoningTraces(demoResult.reasoning_traces || []);
    showResults(demoResult);

    const analysisStatus = document.getElementById('analysis-status');
    if (analysisStatus) {
        const label = window.location.protocol === 'file:'
            ? 'Offline demo'
            : (statusLabel || 'Result demo');
        analysisStatus.innerHTML =
            '<svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-check"></use></svg> '
            + escapeHtml(label);
        analysisStatus.title = 'Archived completed analysis; no analysis backend required';
    }
}

function getPathwayId(pathway) {
    const value = pathway?.pathway_id ?? pathway?.native ?? pathway?.term_id ?? pathway?.id ?? '';
    return String(value || '').trim();
}

function renderPathwayId(pathway, extraClass = '') {
    const pathwayId = getPathwayId(pathway);
    const label = pathwayId || 'ID unavailable';
    const unavailableClass = pathwayId ? '' : ' pathway-id-badge--unavailable';
    return `<span class="pathway-id-badge${unavailableClass}${extraClass ? ` ${extraClass}` : ''}">${escapeHtml(label)}</span>`;
}

const DATABASE_META = {
    'GO:BP': { name: 'Biological Process', mark: 'BP', className: 'gobp', color: 'var(--cat-gobp)' },
    'GO:MF': { name: 'Molecular Function', mark: 'MF', className: 'gomf', color: 'var(--cat-gomf)' },
    'GO:CC': { name: 'Cellular Component', mark: 'CC', className: 'gocc', color: 'var(--cat-gocc)' },
    'KEGG': { name: 'KEGG Pathway', mark: 'K', className: 'kegg', color: 'var(--cat-kegg)' },
    'REAC': { name: 'Reactome Pathway', mark: 'R', className: 'reac', color: 'var(--cat-reac)' }
};

function getDatabaseMeta(category) {
    return DATABASE_META[category] || {
        name: category || 'Other database',
        mark: 'DB',
        className: 'other',
        color: 'var(--text-secondary)'
    };
}

function renderDatabaseMark(category) {
    const meta = getDatabaseMeta(category);
    const isGeneOntology = String(category || '').startsWith('GO:');
    return `
        <span class="database-mark database-mark--${meta.className}" aria-hidden="true">
            <span class="database-mark-primary">${isGeneOntology ? 'GO' : escapeHtml(meta.mark)}</span>
            ${isGeneOntology ? `<span class="database-mark-sub">${escapeHtml(meta.mark)}</span>` : ''}
        </span>
    `;
}

function getPathwayOfficialUrl(pathway) {
    const pathwayId = getPathwayId(pathway);
    const category = pathway?.source || pathway?.category || '';
    if (!pathwayId) return '';
    if (pathwayId.startsWith('GO:') || category.startsWith('GO:')) {
        return `https://amigo.geneontology.org/amigo/term/${encodeURIComponent(pathwayId)}`;
    }
    if (/^(?:hsa|ko|map)\d+$/i.test(pathwayId) || category === 'KEGG') {
        const keggId = pathwayId.replace(/^KEGG:/i, 'hsa');
        return `https://www.kegg.jp/entry/${encodeURIComponent(keggId)}`;
    }
    if (/^R-[A-Z]+-\d+$/i.test(pathwayId) || category === 'REAC') {
        return `https://reactome.org/content/detail/${encodeURIComponent(pathwayId)}`;
    }
    return '';
}

function renderPathwayNameLink(pathway, name, className = '') {
    const label = escapeHtml(name || pathway?.name || pathway?.pathway_name || 'Unknown pathway');
    const url = getPathwayOfficialUrl(pathway);
    if (!url) return `<span${className ? ` class="${className}"` : ''}>${label}</span>`;
    return `<a class="pathway-official-link${className ? ` ${className}` : ''}" href="${escapeHtml(url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="Open the original database record">${label}<span aria-hidden="true"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></span></a>`;
}

function getGeneOfficialUrl(gene) {
    if (/^ENSG\d+(?:\.\d+)?$/i.test(String(gene || '').trim())) {
        return `https://www.ensembl.org/Homo_sapiens/Gene/Summary?g=${encodeURIComponent(String(gene || '').trim())}`;
    }
    return `https://www.genenames.org/data/gene-symbol-report/#!/symbol/${encodeURIComponent(String(gene || '').trim())}`;
}

function renderGeneOfficialLink(gene, className) {
    const symbol = String(gene || '').trim();
    const sourceName = /^ENSG\d+(?:\.\d+)?$/i.test(symbol) ? 'Ensembl' : 'HGNC';
    return `<a class="${className}" href="${escapeHtml(getGeneOfficialUrl(symbol))}" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="Open ${escapeHtml(symbol)} in ${sourceName}">${escapeHtml(symbol)}<span class="external-link-mark" aria-hidden="true"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></span></a>`;
}

const CELL_TYPE_PATTERNS = [
    ['Pyramidal neurons', /\bpyramidal\s+neurons?\b/i],
    ['Hippocampal neurons', /\bhippocamp(?:us|al)[^.!?]{0,55}\bneurons?\b/i],
    ['Cortical neurons', /\b(?:cortical|cortex)[^.!?]{0,55}\bneurons?\b/i],
    ['Excitatory neurons', /\bexcitatory(?:[^.!?]{0,35})?\bneurons?\b/i],
    ['Inhibitory neurons', /\binhibitory(?:[^.!?]{0,35})?\bneurons?\b/i],
    ['Glutamatergic neurons', /\bglutamatergic\s+neurons?\b/i],
    ['Dopaminergic neurons', /\bdopaminergic\s+neurons?\b/i],
    ['Motor neurons', /\bmotor\s+neurons?\b/i],
    ['Microglia', /\bmicrogli(?:a|al)\b/i],
    ['Astrocytes', /\bastrocyt(?:e|es|ic)\b/i],
    ['Neurons', /\bneuron(?:s|al)?\b/i],
    ['Oligodendrocytes', /\boligodendro(?:cyte|cytes|cytic|glia)\b/i],
    ['Endothelial cells', /\bendothelial(?:\s+cells?)?\b/i],
    ['Pericytes', /\bpericytes?\b/i],
    ['Monocytes', /\bmonocytes?\b/i],
    ['Macrophages', /\bmacrophages?\b/i],
    ['T cells', /\bT[-\s]?cells?\b/i],
    ['B cells', /\bB[-\s]?cells?\b/i],
    ['Dendritic cells', /\bdendritic\s+cells?\b/i],
    ['Epithelial cells', /\bepithelial(?:\s+cells?)?\b/i],
    ['Fibroblasts', /\bfibroblasts?\b/i],
    ['Adipocytes', /\badipocytes?\b/i],
    ['Hepatocytes', /\bhepatocytes?\b/i],
    ['Pancreatic β cells', /\b(?:pancreatic\s+)?(?:beta|β)[-\s]?cells?\b/i],
    ['Enterocytes', /\benterocytes?\b/i],
    ['Goblet cells', /\bgoblet\s+cells?\b/i],
    ['Smooth muscle cells', /\bsmooth\s+muscle\s+cells?\b/i],
    ['Hippocampus', /\bhippocamp(?:us|al)\b/i],
    ['Association cortex', /\bassociation\s+cortex\b/i],
    ['Entorhinal cortex', /\bentorhinal\s+cortex\b/i],
    ['Cortex', /\bcort(?:ex|ical)\b/i],
    ['Synapses', /\bsynaps(?:e|es|tic)\b/i]
];

// The pathway context layer also carries anatomy and subcellular-site terms.
// Keep those visible on each pathway, but do not let Hippocampus/Cortex/Synapses
// displace actual cell types from the run-level "Top cell types" ranking.
const NON_CELL_TYPE_CONTEXT_LABELS = new Set([
    'Hippocampus',
    'Association cortex',
    'Entorhinal cortex',
    'Cortex',
    'Synapses'
]);

const CELL_CONTEXT_ONTOLOGY_TERMS = {
    'Pyramidal neurons': { ontology: 'cl', id: 'CL:0000598', source: 'Cell Ontology' },
    'Hippocampal neurons': { query: 'hippocampal neuron', source: 'Ontology Lookup Service' },
    'Cortical neurons': { query: 'cortical neuron', source: 'Ontology Lookup Service' },
    'Excitatory neurons': { query: 'excitatory neuron', source: 'Cell Ontology' },
    'Inhibitory neurons': { query: 'inhibitory neuron', source: 'Cell Ontology' },
    'Glutamatergic neurons': { query: 'glutamatergic neuron', source: 'Cell Ontology' },
    'Dopaminergic neurons': { ontology: 'cl', id: 'CL:0000700', source: 'Cell Ontology' },
    'Motor neurons': { ontology: 'cl', id: 'CL:0000100', source: 'Cell Ontology' },
    'Microglia': { ontology: 'cl', id: 'CL:0000129', source: 'Cell Ontology' },
    'Astrocytes': { ontology: 'cl', id: 'CL:0000127', source: 'Cell Ontology' },
    'Neurons': { ontology: 'cl', id: 'CL:0000540', source: 'Cell Ontology' },
    'Oligodendrocytes': { ontology: 'cl', id: 'CL:0000128', source: 'Cell Ontology' },
    'Endothelial cells': { ontology: 'cl', id: 'CL:0000115', source: 'Cell Ontology' },
    'Pericytes': { ontology: 'cl', id: 'CL:0000669', source: 'Cell Ontology' },
    'Monocytes': { ontology: 'cl', id: 'CL:0000576', source: 'Cell Ontology' },
    'Macrophages': { ontology: 'cl', id: 'CL:0000235', source: 'Cell Ontology' },
    'T cells': { ontology: 'cl', id: 'CL:0000084', source: 'Cell Ontology' },
    'B cells': { ontology: 'cl', id: 'CL:0000236', source: 'Cell Ontology' },
    'Dendritic cells': { ontology: 'cl', id: 'CL:0000451', source: 'Cell Ontology' },
    'Epithelial cells': { ontology: 'cl', id: 'CL:0000066', source: 'Cell Ontology' },
    'Fibroblasts': { ontology: 'cl', id: 'CL:0000057', source: 'Cell Ontology' },
    'Adipocytes': { ontology: 'cl', id: 'CL:0000136', source: 'Cell Ontology' },
    'Hepatocytes': { ontology: 'cl', id: 'CL:0000182', source: 'Cell Ontology' },
    'Pancreatic β cells': { ontology: 'cl', id: 'CL:0000169', source: 'Cell Ontology' },
    'Enterocytes': { ontology: 'cl', id: 'CL:0000584', source: 'Cell Ontology' },
    'Goblet cells': { ontology: 'cl', id: 'CL:0000160', source: 'Cell Ontology' },
    'Smooth muscle cells': { ontology: 'cl', id: 'CL:0000192', source: 'Cell Ontology' },
    'Hippocampus': { query: 'hippocampus', source: 'UBERON' },
    'Association cortex': { query: 'association cortex', source: 'UBERON' },
    'Entorhinal cortex': { query: 'entorhinal cortex', source: 'UBERON' },
    'Cortex': { ontology: 'uberon', id: 'UBERON:0000956', source: 'UBERON' },
    'Synapses': { ontology: 'go', id: 'GO:0045202', source: 'Gene Ontology' }
};

function getCellContextOfficialUrl(label) {
    const term = CELL_CONTEXT_ONTOLOGY_TERMS[label];
    if (!term) return '';
    if (term.ontology && term.id) {
        return `https://www.ebi.ac.uk/ols4/ontologies/${term.ontology}/terms?obo_id=${encodeURIComponent(term.id)}`;
    }
    return `https://www.ebi.ac.uk/ols4/search?q=${encodeURIComponent(term.query || label)}`;
}

function renderCellContextOfficialLink(label, className = '') {
    const term = CELL_CONTEXT_ONTOLOGY_TERMS[label];
    const url = getCellContextOfficialUrl(label);
    if (!url) return `<span${className ? ` class="${className}"` : ''}>${escapeHtml(label)}</span>`;
    const classes = [className, 'cell-context-official-link'].filter(Boolean).join(' ');
    return `<a class="${classes}" href="${escapeHtml(url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="Open ${escapeHtml(label)} in ${escapeHtml(term.source)}">${escapeHtml(label)}<span class="external-link-mark" aria-hidden="true"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></span></a>`;
}

function renderCellContextFrequencyLink(entry, className = '', showPercent = false) {
    if (!entry?.label || !entry?.total) return '';
    const label = String(entry.label);
    const count = Number(entry.count) || 0;
    const total = Number(entry.total) || 0;
    const percent = Math.round((count / total) * 100);
    const frequency = `${count}/${total}${showPercent ? ` (${percent}%)` : ''}`;
    const title = `${label}: present in ${count} of ${total} validated pathways (${percent}%). Frequency counts each pathway once.`;
    const showFrequency = showPercent || !className.includes('evidence-context-chip');
    const valueMarkup = showFrequency
        ? `<span class="cell-context-frequency-count" aria-label="${escapeHtml(title)}">${escapeHtml(frequency)}</span>`
        : '';
    const term = CELL_CONTEXT_ONTOLOGY_TERMS[label];
    const url = getCellContextOfficialUrl(label);
    const classes = [className, 'cell-context-frequency-chip'].filter(Boolean).join(' ');
    if (!url) {
        return `<span${classes ? ` class="${classes}"` : ''} title="${escapeHtml(title)}"><span>${escapeHtml(label)}</span>${valueMarkup}</span>`;
    }
    return `<a class="${classes} cell-context-official-link" href="${escapeHtml(url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="${escapeHtml(title)} Open ${escapeHtml(label)} in ${escapeHtml(term.source)}"><span>${escapeHtml(label)}</span>${valueMarkup}<span class="external-link-mark" aria-hidden="true"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></span></a>`;
}

function extractCellTypeLabels(text) {
    const source = String(text || '');
    const labels = CELL_TYPE_PATTERNS
        .filter(([, pattern]) => pattern.test(source))
        .map(([label]) => label);
    const hasSpecificNeuronType = labels.some(label => label !== 'Neurons' && label.endsWith('neurons'));
    const hasSpecificCortex = labels.includes('Association cortex') || labels.includes('Entorhinal cortex');
    return labels.filter(label =>
        (label !== 'Neurons' || !hasSpecificNeuronType)
        && (label !== 'Cortex' || !hasSpecificCortex)
    );
}

// ============================================================================
// GENE LIST LOADER
// ============================================================================

async function initGeneListLoader(backendGeneLists = {}) {
    try {
        geneListState.allLists = backendGeneLists && typeof backendGeneLists === 'object'
            ? backendGeneLists
            : {};
        if (!Object.keys(geneListState.allLists).length) {
            throw new Error('No backend gene-list examples were available');
        }
        extendGeneSearchIndexFromCuratedLists();
        updateFeaturedExampleButtons();

        // The project example collection is the source of truth for both disease
        // controls. Rebuilding from the API keeps the two lists paired when
        // diseases are added or renamed in gene_lists.json.
        const curatedDiseaseOptions = buildDiseaseOptionsFromCuratedLists(geneListState.allLists);
        if (curatedDiseaseOptions.length > 0) {
            DISEASE_OPTIONS = curatedDiseaseOptions;
            renderDiseasePresetOptions();
        }

        const diseaseSelect = document.getElementById('gene-list-disease-select');
        if (!diseaseSelect) return;
        diseaseSelect.innerHTML = '<option value="">Select an example</option>';
        DISEASE_OPTIONS.forEach(({ value, label }) => {
            const opt = document.createElement('option');
            opt.value = value;
            const topModule = getTopExampleModule(value);
            const count = Number(topModule?.gene_count ?? topModule?.genes?.length);
            opt.textContent = Number.isFinite(count)
                ? `${label.replace(/\s+\([^)]+\)$/, '')}, ${count} genes`
                : label;
            diseaseSelect.appendChild(opt);
        });

        diseaseSelect.value = '';
    } catch (e) {
        console.warn('Gene list loader: backend data could not be loaded', e);
    }
}

function getTopExampleModule(diseaseCode) {
    const lists = geneListState.allLists?.[diseaseCode]?.lists || [];
    return lists.find(item => /top[_ -]?module/i.test(String(item.id || item.label || '')))
        || lists.find(item => Array.isArray(item.genes) && item.genes.length)
        || null;
}

function updateFeaturedExampleButtons() {
    const archive = getCompletedExampleArchive();
    document.querySelectorAll('.featured-example-button[data-disease]').forEach(button => {
        if (window.location.protocol === 'file:' && HOSTED_APP_URL) {
            const detail = button.querySelector('span');
            if (detail) detail.textContent = 'View example';
            button.disabled = false;
            button.title = 'Open the completed analysis on GenePathwayAI';
            return;
        }
        const archived = archive?.examples?.[button.dataset.disease];
        const detail = button.querySelector('span');
        if (archived) {
            if (detail) detail.textContent = 'View example';
            button.disabled = false;
            return;
        }
        const module = getTopExampleModule(button.dataset.disease);
        const count = Number(module?.gene_count ?? module?.genes?.length);
        if (detail && Number.isFinite(count)) detail.textContent = 'Load example';
        button.disabled = !module;
    });
}

function showFeaturedExamples(event) {
    event?.preventDefault();
    showAnalysisView();
    requestAnimationFrame(() => {
        const launcher = document.getElementById('featured-examples');
        launcher?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        launcher?.querySelector('button')?.focus({ preventScroll: true });
    });
}

async function loadFeaturedInput(diseaseCode) {
    const button = document.querySelector(`.featured-example-button[data-disease="${diseaseCode}"]`);
    const module = getTopExampleModule(diseaseCode);
    if (!module?.genes?.length) {
        if (button) button.title = 'This example is not available in the current preview.';
        return;
    }

    setSelectedGenes(module.genes);
    setDiseaseCombobox(diseaseCode);
    if (button) {
        button.classList.add('is-loaded');
        const original = button.querySelector('span')?.textContent;
        const detail = button.querySelector('span');
        if (detail) detail.textContent = `Loaded ${module.genes.length} genes`;
        setTimeout(() => {
            button.classList.remove('is-loaded');
            if (detail && original) detail.textContent = original;
        }, 1800);
    }
    document.querySelector('.analysis-context-grid')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function toggleGeneListPanel() {
    const panel = document.getElementById('gene-list-panel');
    const btn = document.getElementById('gene-list-toggle');
    if (!panel) return;
    const isHidden = panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !isHidden);
    if (btn) {
        btn.innerHTML = isHidden
            ? 'Close <span aria-hidden="true"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-up"></use></svg></span>'
            : 'Load disease and genes <span aria-hidden="true"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg></span>';
    }
}

function onGeneListDiseaseChange({ syncContext = true } = {}) {
    const diseaseCode = document.getElementById('gene-list-disease-select').value;
    const moduleGroup = document.getElementById('gene-list-module-group');
    const moduleSelect = document.getElementById('gene-list-module-select');
    const metaPanel = document.getElementById('gene-list-meta');

    // reset
    moduleSelect.innerHTML = '<option value="">Select a list</option>';
    metaPanel.classList.add('hidden');
    geneListState.selectedDisease = diseaseCode;
    geneListState.selectedListId = null;
    geneListState.selectedMeta = null;

    if (!diseaseCode || !geneListState.allLists[diseaseCode]) {
        moduleGroup.style.display = 'none';
        return;
    }

    if (syncContext) {
        setDiseaseCombobox(diseaseCode, { syncCurated: false });
    }

    // One choice only: each disease resolves to its compact module-level list.
    const selected = getTopExampleModule(diseaseCode);
    moduleGroup.style.display = 'none';
    if (!selected) return;
    const opt = document.createElement('option');
    opt.value = selected.id;
    opt.textContent = selected.label || diseaseCode;
    moduleSelect.appendChild(opt);
    moduleSelect.value = selected.id;
    onGeneListModuleChange();
}

function onGeneListModuleChange() {
    const listId = document.getElementById('gene-list-module-select').value;
    const metaPanel = document.getElementById('gene-list-meta');
    geneListState.selectedListId = listId;

    if (!listId || !geneListState.selectedDisease) {
        metaPanel.classList.add('hidden');
        return;
    }

    const lists = geneListState.allLists[geneListState.selectedDisease]?.lists || [];
    const meta = lists.find(l => l.id === listId);
    if (!meta) return;

    geneListState.selectedMeta = meta;
    document.getElementById('gene-list-source').textContent = meta.source;
    document.getElementById('gene-list-desc').textContent = meta.description;
    const geneCount = Number.isFinite(meta.gene_count)
        ? meta.gene_count
        : (Array.isArray(meta.genes) ? meta.genes.length : 0);
    document.getElementById('gene-list-count').textContent = `${geneCount} genes`;
    metaPanel.classList.remove('hidden');
}

// ============================================================================
// DISEASE COMBOBOX
// ============================================================================

let DISEASE_OPTIONS = [
    { value: 'AD',  label: "Alzheimer's Disease (AD)" },
    { value: 'ALS', label: 'Amyotrophic Lateral Sclerosis (ALS)' },
    { value: 'IBD', label: 'Inflammatory Bowel Disease (IBD)' },
    { value: 'MS',  label: 'Multiple Sclerosis (MS)' },
    { value: 'PD',  label: "Parkinson's Disease (PD)" },
    { value: 'RA',  label: 'Rheumatoid Arthritis (RA)' },
    { value: 'T2D', label: 'Type 2 Diabetes (T2D)' },
];

const DISEASE_AUTHORITY_RECORDS = {
    AD:  { canonicalName: 'Alzheimer disease', database: 'Open Targets / MONDO', databaseId: 'MONDO:0004975', openTargetsId: 'MONDO_0004975', meshId: 'D000544', description: 'A progressive neurodegenerative disease affecting memory, language and other cognitive functions.' },
    ALS: { canonicalName: 'Amyotrophic lateral sclerosis', database: 'Open Targets / MONDO', databaseId: 'MONDO:0004976', openTargetsId: 'MONDO_0004976', meshId: 'D000690', description: 'A progressive motor neuron disease affecting voluntary muscle control.' },
    IBD: { canonicalName: 'Inflammatory bowel disease', database: 'Open Targets / MONDO', databaseId: 'MONDO:0005265', openTargetsId: 'MONDO_0005265', meshId: 'D015212', description: 'A group of chronic inflammatory disorders of the gastrointestinal tract.' },
    MS:  { canonicalName: 'Multiple sclerosis', database: 'Open Targets / MONDO', databaseId: 'MONDO:0005301', openTargetsId: 'MONDO_0005301', meshId: 'D009103', description: 'A chronic immune-mediated disorder affecting the central nervous system.' },
    PD:  { canonicalName: 'Parkinson disease', database: 'Open Targets / MONDO', databaseId: 'MONDO:0005180', openTargetsId: 'MONDO_0005180', meshId: 'D010300', description: 'A progressive neurodegenerative disorder characterized primarily by motor impairment.' },
    RA:  { canonicalName: 'Rheumatoid arthritis', database: 'Open Targets / MONDO', databaseId: 'MONDO:0008383', openTargetsId: 'MONDO_0008383', meshId: 'D001172', description: 'A chronic systemic autoimmune disease that primarily affects synovial joints.' },
    T2D: { canonicalName: 'Type 2 diabetes mellitus', database: 'Open Targets / MONDO', databaseId: 'MONDO:0005148', openTargetsId: 'MONDO_0005148', meshId: 'D003924', description: 'A metabolic disease characterized by insulin resistance and chronic hyperglycaemia.' },
};

const CURATED_DISEASE_ALIASES = {
    AD: ['Alzheimer Disease', 'Alzheimers Disease', 'Alzheimer'],
    ALS: ['Lou Gehrig Disease', 'Motor Neuron Disease'],
    IBD: ['Inflammatory Bowel Disorder'],
    MS: ['Disseminated Sclerosis'],
    PD: ['Parkinson Disease', 'Parkinsons Disease', 'Parkinsonism'],
    RA: ['Rheumatoid Polyarthritis'],
    T2D: ['Type II Diabetes', 'Type 2 Diabetes Mellitus', 'T2DM'],
};

// A compact offline suggestion catalog. These entries improve discoverability
// without restricting the field: any unmatched text remains a valid custom
// disease context.
const DISEASE_SUGGESTION_SEEDS = [
    { label: 'Systemic Lupus Erythematosus', aliases: ['SLE', 'Lupus'] },
    { label: "Crohn's Disease", aliases: ['Crohn Disease', 'Crohns Disease'] },
    { label: 'Ulcerative Colitis', aliases: ['UC'] },
    { label: 'Celiac Disease', aliases: ['Coeliac Disease'] },
    { label: 'Psoriasis', aliases: ['Psoriatic Disease'] },
    { label: 'Psoriatic Arthritis', aliases: ['PsA'] },
    { label: 'Ankylosing Spondylitis', aliases: ['AS', 'Axial Spondyloarthritis'] },
    { label: 'Systemic Sclerosis', aliases: ['Scleroderma'] },
    { label: "Sjogren's Syndrome", aliases: ['Sjogren Syndrome', 'Sjögren Syndrome'] },
    { label: 'Chronic Obstructive Pulmonary Disease', aliases: ['COPD'] },
    { label: 'Asthma', aliases: ['Bronchial Asthma'] },
    { label: 'Chronic Kidney Disease', aliases: ['CKD'] },
    { label: 'Coronary Artery Disease', aliases: ['CAD', 'Coronary Heart Disease'] },
    { label: 'Heart Failure', aliases: ['Congestive Heart Failure', 'CHF'] },
    { label: 'Hypertension', aliases: ['High Blood Pressure'] },
    { label: 'Type 1 Diabetes', aliases: ['T1D', 'Type 1 Diabetes Mellitus'] },
    { label: 'Obesity', aliases: ['Adiposity'] },
    { label: 'Metabolic Dysfunction-Associated Steatotic Liver Disease', aliases: ['MASLD', 'NAFLD', 'Nonalcoholic Fatty Liver Disease'] },
    { label: "Huntington's Disease", aliases: ['HD', 'Huntington Disease'] },
    { label: 'Frontotemporal Dementia', aliases: ['FTD'] },
    { label: 'Epilepsy', aliases: ['Seizure Disorder'] },
    { label: 'Schizophrenia', aliases: [] },
    { label: 'Major Depressive Disorder', aliases: ['MDD', 'Major Depression'] },
    { label: 'Bipolar Disorder', aliases: ['Bipolar Affective Disorder'] },
    { label: 'Autism Spectrum Disorder', aliases: ['ASD', 'Autism'] },
    { label: 'Breast Cancer', aliases: ['Breast Carcinoma'] },
    { label: 'Lung Cancer', aliases: ['Lung Carcinoma'] },
    { label: 'Colorectal Cancer', aliases: ['CRC', 'Colon Cancer'] },
    { label: 'Prostate Cancer', aliases: ['Prostate Carcinoma'] },
    { label: 'Pancreatic Cancer', aliases: ['Pancreatic Adenocarcinoma'] },
    { label: 'Glioblastoma', aliases: ['GBM', 'Glioblastoma Multiforme'] },
    { label: 'Melanoma', aliases: ['Malignant Melanoma'] },
    { label: 'Acute Myeloid Leukemia', aliases: ['AML'] },
    { label: 'COVID-19', aliases: ['Coronavirus Disease 2019', 'SARS-CoV-2 Disease'] },
];

const diseaseContextState = {
    lastPresetCode: '',
    activeSuggestionIndex: -1,
    selectedMatch: null,
    searchTimer: null,
    searchController: null,
    openTargetsImportController: null,
    openTargetsImportLoading: false,
    openTargetsImportContextId: '',
    lastGeneImport: null,
};

function getDiseaseInput()        { return document.getElementById('disease-input'); }
function getDiseaseHidden()       { return document.getElementById('disease-select'); }
function getDiseasePresetSelect() { return document.getElementById('disease-preset-select'); }
function getDiseaseStatus()       { return document.getElementById('disease-context-status'); }
function getDiseaseSuggestions()  { return document.getElementById('disease-suggestions'); }

function getSelectedOpenTargetsDisease() {
    const selected = diseaseContextState.selectedMatch;
    const curated = getDiseaseAuthority(getDiseaseHidden()?.value);
    const rawId = selected?.openTargetsId || selected?.databaseId ||
        curated?.openTargetsId || curated?.databaseId || getDiseaseHidden()?.value;
    const id = String(rawId || '').trim().replace(':', '_');
    if (!/^[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(id)) return null;

    return {
        id,
        name: selected?.canonicalName || selected?.label || curated?.canonicalName ||
            getDiseaseInput()?.value.trim() || id,
        url: selected?.authorityUrl ||
            `https://platform.opentargets.org/disease/${encodeURIComponent(id)}/associations`,
    };
}

function renderOpenTargetsGeneImportStatus(message, {
    state = 'info',
    sourceUrl = '',
} = {}) {
    const status = document.getElementById('open-targets-gene-import-status');
    if (!status) return;
    status.replaceChildren();
    status.className = `open-targets-gene-import-status is-${state}`;

    const copy = document.createElement('span');
    copy.textContent = message;
    status.appendChild(copy);

    if (/^https:\/\/platform\.opentargets\.org\//.test(sourceUrl)) {
        const link = document.createElement('a');
        link.href = sourceUrl;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = 'Open Targets';
        status.appendChild(link);
    }
}

function clearOpenTargetsGeneImportState() {
    diseaseContextState.lastGeneImport = null;
    const status = document.getElementById('open-targets-gene-import-status');
    status?.classList.add('hidden');
    document.getElementById('clear-open-targets-import-button')?.classList.add('hidden');
}

function updateOpenTargetsGeneImportAvailability() {
    const disease = getSelectedOpenTargetsDisease();
    const contextId = disease?.id || '';
    if (diseaseContextState.openTargetsImportContextId !== contextId) {
        diseaseContextState.openTargetsImportController?.abort();
        diseaseContextState.openTargetsImportContextId = contextId;
        diseaseContextState.lastGeneImport = null;
        const status = document.getElementById('open-targets-gene-import-status');
        status?.classList.add('hidden');
    }

    const button = document.getElementById('open-targets-import-button');
    if (button) {
        button.disabled = !disease || diseaseContextState.openTargetsImportLoading;
        button.title = disease
            ? `Import genes associated with ${disease.name}, ranked by Open Targets overall association score`
            : 'Select an ontology-backed disease or phenotype first';
    }
}

async function requestOpenTargetsAssociatedGenes(diseaseId, limit, signal) {
    const endpoint = `/api/open-targets/associated-genes?disease_id=${encodeURIComponent(diseaseId)}&limit=${limit}`;
    const staticPreview = window.location.protocol === 'file:' ||
        ['localhost', '127.0.0.1'].includes(window.location.hostname);

    try {
        const response = await fetch(endpoint, {
            headers: { 'Accept': 'application/json' },
            cache: 'no-store',
            signal,
        });
        const contentType = response.headers.get('content-type') || '';
        const payload = contentType.includes('application/json') ? await response.json() : {};
        if (response.ok) return payload;
        if (!staticPreview || [400, 404].includes(response.status)) {
            throw new Error(payload.error || `Open Targets import returned HTTP ${response.status}`);
        }
    } catch (error) {
        if (error?.name === 'AbortError') throw error;
        if (!staticPreview) throw error;
    }

    const graphqlQuery = `
      query DiseaseTopTargets($efoId: String!, $size: Int!) {
        disease(efoId: $efoId) {
          id
          name
          associatedTargets(page: {index: 0, size: $size}, orderByScore: "score") {
            count
            rows {
              score
              target { id approvedSymbol approvedName }
            }
          }
        }
      }
    `;
    const response = await fetch('https://api.platform.opentargets.org/api/v4/graphql', {
        method: 'POST',
        headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({
            query: graphqlQuery,
            variables: { efoId: diseaseId, size: limit },
        }),
        signal,
    });
    if (!response.ok) throw new Error(`Open Targets returned HTTP ${response.status}`);
    const upstream = await response.json();
    const disease = upstream?.data?.disease;
    if (!disease) throw new Error('Disease or phenotype was not found in Open Targets');
    const associations = disease.associatedTargets || {};
    const seen = new Set();
    const genes = (associations.rows || [])
        .filter(row => row?.target?.approvedSymbol && row?.target?.id)
        .map(row => ({
            symbol: String(row.target.approvedSymbol).toUpperCase(),
            ensembl_id: row.target.id,
            name: row.target.approvedName || '',
            association_score: Number(row.score),
        }))
        .filter(gene => {
            if (seen.has(gene.symbol)) return false;
            seen.add(gene.symbol);
            return true;
        })
        .sort((a, b) => b.association_score - a.association_score)
        .slice(0, limit);
    return {
        disease: { id: disease.id, name: disease.name },
        genes,
        requested_limit: limit,
        returned_count: genes.length,
        total_associations: Number(associations.count) || 0,
        source: 'Open Targets Platform',
        source_url: `https://platform.opentargets.org/disease/${encodeURIComponent(disease.id)}/associations`,
        ranking: 'overall association score',
    };
}

async function importOpenTargetsAssociatedGenes(limit) {
    const disease = getSelectedOpenTargetsDisease();
    if (!disease) {
        renderOpenTargetsGeneImportStatus('Select an ontology-backed disease or phenotype first.', {
            state: 'error',
        });
        return;
    }
    if (!Number.isInteger(limit) || limit < 25) {
        renderOpenTargetsGeneImportStatus('Choose at least 25 genes.', { state: 'error' });
        return;
    }

    diseaseContextState.openTargetsImportController?.abort();
    const controller = new AbortController();
    diseaseContextState.openTargetsImportController = controller;
    diseaseContextState.openTargetsImportLoading = true;
    updateOpenTargetsGeneImportAvailability();
    renderOpenTargetsGeneImportStatus(`Loading Top ${limit} for ${disease.name}…`, {
        state: 'loading',
    });

    try {
        const payload = await requestOpenTargetsAssociatedGenes(disease.id, limit, controller.signal);
        if (getSelectedOpenTargetsDisease()?.id !== disease.id) return;
        const imported = (payload.genes || [])
            .map(gene => String(gene?.symbol || '').trim().toUpperCase())
            .filter(isSupportedGeneIdentifier);
        if (!imported.length) throw new Error('No associated genes were returned for this disease');

        setSelectedGenes(imported, { preserveOpenTargetsImport: true });
        diseaseContextState.lastGeneImport = {
            disease_id: payload.disease?.id || disease.id,
            disease_name: payload.disease?.name || disease.name,
            requested_limit: limit,
            returned_count: imported.length,
            source: 'Open Targets Platform',
            ranking: 'overall association score',
        };
        renderOpenTargetsGeneImportStatus(`Loaded ${imported.length} genes for ${payload.disease?.name || disease.name}.`, {
            state: 'success',
            sourceUrl: payload.source_url || disease.url,
        });
        document.getElementById('clear-open-targets-import-button')?.classList.remove('hidden');
    } catch (error) {
        if (error?.name !== 'AbortError') {
            renderOpenTargetsGeneImportStatus(error?.message || 'Open Targets import failed.', {
                state: 'error',
            });
        }
    } finally {
        if (diseaseContextState.openTargetsImportController === controller) {
            diseaseContextState.openTargetsImportController = null;
            diseaseContextState.openTargetsImportLoading = false;
            updateOpenTargetsGeneImportAvailability();
        }
    }
}

function initOpenTargetsGeneImport() {
    const limitInput = document.getElementById('open-targets-limit-input');
    document.querySelectorAll('[data-open-targets-preset]').forEach(button => {
        button.addEventListener('click', () => {
            if (limitInput) limitInput.value = button.dataset.openTargetsPreset;
        });
    });
    document.getElementById('open-targets-import-button')?.addEventListener('click', () => {
        importOpenTargetsAssociatedGenes(Number(limitInput?.value));
    });
    document.getElementById('clear-open-targets-import-button')?.addEventListener('click', () => {
        clearSelectedGenes();
        clearOpenTargetsGeneImportState();
    });
    updateOpenTargetsGeneImportAvailability();
}

function buildDiseaseOptionsFromCuratedLists(allLists) {
    return Object.entries(allLists || {}).map(([rawCode, data]) => {
        const value = String(rawCode).trim().toUpperCase();
        const name = String(data?.label || data?.name || value).trim();
        const suffix = `(${value})`;
        const label = name.toUpperCase().endsWith(suffix) ? name : `${name} ${suffix}`;
        return { value, label, ...(DISEASE_AUTHORITY_RECORDS[value] || {}) };
    });
}

function getDiseaseAuthority(optionOrCode) {
    const code = typeof optionOrCode === 'string' ? optionOrCode : optionOrCode?.value;
    return DISEASE_AUTHORITY_RECORDS[String(code || '').toUpperCase()] || null;
}

function findDiseaseOption(query) {
    const normalized = normalizeDiseaseSearchText(query);
    if (!normalized) return null;
    return DISEASE_OPTIONS.find(option => {
        const authority = getDiseaseAuthority(option);
        return [
            option.value,
            option.label,
            option.label.replace(/\s+\([^)]+\)$/, ''),
            authority?.canonicalName,
            authority?.databaseId,
            authority?.openTargetsId,
            ...(CURATED_DISEASE_ALIASES[option.value] || []),
        ].filter(Boolean).some(candidate => normalizeDiseaseSearchText(candidate) === normalized);
    }) || null;
}

function normalizeDiseaseSearchText(value) {
    return String(value || '')
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/[’']/g, '')
        .replace(/&/g, ' and ')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .trim()
        .replace(/\s+/g, ' ');
}

function getDiseaseSuggestionCatalog() {
    const curatedEntries = DISEASE_OPTIONS.map(option => {
        const authority = getDiseaseAuthority(option) || {};
        return {
            label: authority.canonicalName || option.label,
            aliases: [
                option.value,
                option.label,
                option.label.replace(/\s+\([^)]+\)$/, ''),
                ...(CURATED_DISEASE_ALIASES[option.value] || []),
            ],
            curatedCode: option.value,
            authorityUrl: authority.openTargetsId
                ? `https://platform.opentargets.org/disease/${authority.openTargetsId}/associations`
                : '',
            ...authority,
        };
    });

    const seen = new Set();
    return [...curatedEntries, ...DISEASE_SUGGESTION_SEEDS].filter(entry => {
        const key = normalizeDiseaseSearchText(entry.label);
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function diseaseEditDistance(left, right) {
    const a = String(left || '');
    const b = String(right || '');
    const previous = Array.from({ length: b.length + 1 }, (_, index) => index);

    for (let row = 1; row <= a.length; row += 1) {
        const current = [row];
        for (let column = 1; column <= b.length; column += 1) {
            current[column] = Math.min(
                current[column - 1] + 1,
                previous[column] + 1,
                previous[column - 1] + (a[row - 1] === b[column - 1] ? 0 : 1)
            );
        }
        previous.splice(0, previous.length, ...current);
    }
    return previous[b.length];
}

function scoreDiseaseSuggestion(entry, rawQuery) {
    const query = normalizeDiseaseSearchText(rawQuery);
    const compactQuery = query.replace(/\s/g, '');
    if (!compactQuery) return null;

    const candidates = [entry.label, ...(entry.aliases || [])];
    let best = null;
    candidates.forEach((candidate, candidateIndex) => {
        const normalized = normalizeDiseaseSearchText(candidate);
        const compact = normalized.replace(/\s/g, '');
        if (!compact) return;

        let score = Number.POSITIVE_INFINITY;
        if (normalized === query || compact === compactQuery) {
            score = 0;
        } else if (normalized.startsWith(query) || compact.startsWith(compactQuery)) {
            score = 1;
        } else if (compactQuery.length >= 2 && (normalized.includes(query) || compact.includes(compactQuery) ||
            normalized.split(' ').some(token => token.startsWith(query)))) {
            score = 2;
        } else if (compactQuery.length >= 4) {
            const threshold = compactQuery.length <= 5 ? 1 : 2;
            const prefix = compact.slice(0, compactQuery.length);
            const similarLength = Math.abs(compact.length - compactQuery.length) <= threshold;
            if (diseaseEditDistance(compactQuery, prefix) <= threshold ||
                (similarLength && diseaseEditDistance(compactQuery, compact) <= threshold)) {
                score = 3;
            } else if (isSubsequence(compactQuery, compact)) {
                score = 4;
            }
        }

        if (Number.isFinite(score) && (!best || score < best.score)) {
            best = {
                score,
                aliasMatch: candidateIndex > 0,
            };
        }
    });
    return best;
}

function getDiseaseMatchLabel(match) {
    if (match.aliasMatch && match.score <= 2) return 'Alias match';
    if (match.score === 0) return 'Exact match';
    if (match.score === 1) return 'Prefix match';
    if (match.score === 2) return 'Contains match';
    return 'Fuzzy match';
}

function renderDiseasePresetOptions() {
    const select = getDiseasePresetSelect();
    if (!select) return;

    const customActive = Boolean(getDiseaseInput()?.value.trim());
    const selectedMatch = findDiseaseOption(getDiseaseHidden()?.value) ||
        findDiseaseOption(diseaseContextState.lastPresetCode);
    select.replaceChildren();

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select a disease example';
    placeholder.selected = true;
    select.appendChild(placeholder);

    DISEASE_OPTIONS.forEach(option => {
        const item = document.createElement('option');
        item.value = option.value;
        item.textContent = option.label;
        select.appendChild(item);
    });

    select.value = customActive ? '' : (selectedMatch?.value || '');
}

function syncCuratedDiseaseSelect(code, { forceRefresh = false } = {}) {
    const select = document.getElementById('gene-list-disease-select');
    if (!select) return;
    const normalizedCode = String(code || '').trim();
    const hasOption = Array.from(select.options).some(option => option.value === normalizedCode);
    const nextValue = hasOption ? normalizedCode : '';
    const changed = select.value !== nextValue;
    select.value = nextValue;
    if (changed || forceRefresh) {
        onGeneListDiseaseChange({ syncContext: false });
    }
}

function updateDiseaseContextStatus() {
    const status = getDiseaseStatus();
    const customDisease = getDiseaseInput()?.value.trim();
    updateOpenTargetsGeneImportAvailability();
    if (!status) return;

    const selected = diseaseContextState.selectedMatch;
    if (selected) {
        const authorityLink = selected.authorityUrl
            ? `<a href="${escapeHtml(selected.authorityUrl)}" target="_blank" rel="noopener">${escapeHtml(selected.databaseId || selected.database || 'Matched term')} <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></a>`
            : `<small>${escapeHtml(selected.databaseId || selected.database || 'Matched disease term')}</small>`;
        status.innerHTML = `
            <span>Selected disease</span>
            <strong>${escapeHtml(selected.canonicalName || selected.label || selected.inputAlias)}</strong>
            <div class="disease-selection-meta">${authorityLink}${selected.inputAlias ? `<small>Input: ${escapeHtml(selected.inputAlias)}</small>` : ''}</div>
            ${selected.description ? `<p>${escapeHtml(selected.description)}</p>` : ''}`;
        status.classList.toggle('is-custom', !selected.databaseId);
        return;
    }

    if (customDisease) {
        const match = findDiseaseOption(customDisease);
        if (match) {
            const authority = getDiseaseAuthority(match);
            status.innerHTML = `
                <span>Matched disease</span>
                <strong>${escapeHtml(authority?.canonicalName || match.label)}</strong>
                <div class="disease-selection-meta"><small>${escapeHtml(authority?.databaseId || '')}</small><small>Input: ${escapeHtml(customDisease)}</small></div>
                ${authority?.description ? `<p>${escapeHtml(authority.description)}</p>` : ''}`;
        } else {
            status.innerHTML = `<span>Custom disease context</span><strong>${escapeHtml(customDisease)}</strong><small>Select a matched ontology term when available.</small>`;
        }
        status.classList.add('is-custom');
        return;
    }

    const preset = findDiseaseOption(getDiseasePresetSelect()?.value) ||
        findDiseaseOption(getDiseaseHidden()?.value);
    const authority = getDiseaseAuthority(preset) || {};
    status.innerHTML = preset
        ? `<span>Selected disease</span><strong>${escapeHtml(authority.canonicalName || preset.label)}</strong><div class="disease-selection-meta"><a href="https://platform.opentargets.org/disease/${escapeHtml(authority.openTargetsId || '')}/associations" target="_blank" rel="noopener">${escapeHtml(authority.databaseId || '')} <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></a><small>Alias: ${escapeHtml(preset.value)}</small></div>${authority.description ? `<p>${escapeHtml(authority.description)}</p>` : ''}`
        : '<span>Disease context</span><strong>Search for a disease or phenotype</strong>';
    status.classList.remove('is-custom');
}

function setDiseaseCombobox(value, { syncCurated = true } = {}) {
    const normalizedValue = String(value || '').trim();
    const match = findDiseaseOption(normalizedValue);
    const input = getDiseaseInput();
    const hidden = getDiseaseHidden();
    const presetSelect = getDiseasePresetSelect();
    if (!input || !hidden || !presetSelect) return;
    let selectedPreset = null;

    if (!normalizedValue) {
        diseaseContextState.lastPresetCode = '';
        diseaseContextState.selectedMatch = null;
        presetSelect.value = '';
        input.value = '';
        hidden.value = '';
        updateDiseaseContextStatus();
        hideDiseaseSuggestions();
        if (syncCurated) syncCuratedDiseaseSelect('');
        return;
    }

    if (match) {
        selectedPreset = match;
        diseaseContextState.lastPresetCode = selectedPreset?.value || '';
        const authority = getDiseaseAuthority(selectedPreset);
        diseaseContextState.selectedMatch = authority ? {
            ...authority,
            label: authority.canonicalName,
            inputAlias: selectedPreset?.value || '',
            authorityUrl: authority.openTargetsId
                ? `https://platform.opentargets.org/disease/${authority.openTargetsId}/associations`
                : ''
        } : null;
        presetSelect.value = selectedPreset?.value || '';
        input.value = authority?.canonicalName || selectedPreset?.label.replace(/\s+\([^)]+\)$/, '') || '';
        hidden.value = selectedPreset?.value || '';
    } else {
        diseaseContextState.selectedMatch = null;
        presetSelect.value = '';
        input.value = normalizedValue;
        hidden.value = normalizedValue;
    }

    updateDiseaseContextStatus();
    hideDiseaseSuggestions();
    if (syncCurated) {
        syncCuratedDiseaseSelect(selectedPreset?.value || '');
    }
}

function onDiseasePresetChange() {
    const presetSelect = getDiseasePresetSelect();
    const input = getDiseaseInput();
    const hidden = getDiseaseHidden();
    const match = findDiseaseOption(presetSelect?.value);
    if (!presetSelect || !input || !hidden || !match) return;

    diseaseContextState.lastPresetCode = match.value;
    const authority = getDiseaseAuthority(match);
    diseaseContextState.selectedMatch = authority ? {
        ...authority,
        label: authority.canonicalName,
        inputAlias: match.value,
        authorityUrl: authority.openTargetsId
            ? `https://platform.opentargets.org/disease/${authority.openTargetsId}/associations`
            : ''
    } : null;
    input.value = authority?.canonicalName || match.label.replace(/\s+\([^)]+\)$/, '');
    hidden.value = match.value;
    updateDiseaseContextStatus();
    hideDiseaseSuggestions();
    syncCuratedDiseaseSelect(match.value);
}

function onCustomDiseaseInput() {
    const presetSelect = getDiseasePresetSelect();
    const input = getDiseaseInput();
    const hidden = getDiseaseHidden();
    if (!presetSelect || !input || !hidden) return;

    const customDisease = input.value.trim();
    if (customDisease) {
        const exactMatch = findDiseaseOption(customDisease);
        if (exactMatch) {
            const authority = getDiseaseAuthority(exactMatch);
            diseaseContextState.lastPresetCode = exactMatch.value;
            diseaseContextState.selectedMatch = authority ? {
                ...authority,
                label: authority.canonicalName,
                inputAlias: customDisease,
                authorityUrl: authority.openTargetsId
                    ? `https://platform.opentargets.org/disease/${authority.openTargetsId}/associations`
                    : ''
            } : null;
            presetSelect.value = exactMatch.value;
            hidden.value = exactMatch.value;
            syncCuratedDiseaseSelect(exactMatch.value);
        } else {
            diseaseContextState.selectedMatch = null;
            if (presetSelect.value) diseaseContextState.lastPresetCode = presetSelect.value;
            presetSelect.value = '';
            hidden.value = customDisease;
            syncCuratedDiseaseSelect('');
        }
    } else {
        diseaseContextState.selectedMatch = null;
        diseaseContextState.lastPresetCode = '';
        presetSelect.value = '';
        hidden.value = '';
        syncCuratedDiseaseSelect('');
    }
    updateDiseaseContextStatus();
}

function getDiseaseSuggestionOptions() {
    const suggestions = getDiseaseSuggestions();
    if (!suggestions) return [];
    return [...suggestions.querySelectorAll('.disease-suggestion-option')];
}

function renderDiseaseSuggestions(rawQuery) {
    const input = getDiseaseInput();
    const container = getDiseaseSuggestions();
    if (!input || !container) return;

    const query = String(rawQuery || '').trim();
    if (!query) {
        hideDiseaseSuggestions();
        return;
    }

    const matches = getDiseaseSuggestionCatalog()
        .map(entry => ({ entry, match: scoreDiseaseSuggestion(entry, query) }))
        .filter(item => item.match)
        .sort((a, b) => a.match.score - b.match.score ||
            Number(Boolean(b.entry.curatedCode)) - Number(Boolean(a.entry.curatedCode)) ||
            a.entry.label.length - b.entry.label.length ||
            a.entry.label.localeCompare(b.entry.label))
        .slice(0, 7);

    // Curated short aliases such as MS, AD and RA are authoritative matches.
    // Sending those abbreviations to the remote fuzzy search can promote an
    // unrelated name (for example, "MS" -> "myeloid sarcoma") above the
    // already-resolved local disease. Keep the curated match stable and only
    // use the remote search for unresolved text.
    const exactCuratedMatch = findDiseaseOption(query);
    const shouldSearchOpenTargets = query.length >= 2 && !exactCuratedMatch;
    if (exactCuratedMatch && diseaseContextState.searchController) {
        diseaseContextState.searchController.abort();
        diseaseContextState.searchController = null;
    }
    renderDiseaseSuggestionItems(query, matches, {
        includeCustom: !shouldSearchOpenTargets,
        isLoading: shouldSearchOpenTargets,
    });

    if (diseaseContextState.searchTimer) clearTimeout(diseaseContextState.searchTimer);
    if (shouldSearchOpenTargets) {
        diseaseContextState.searchTimer = setTimeout(() => {
            fetchOpenTargetsDiseaseSuggestions(query, matches);
        }, 220);
    }
}

function renderDiseaseSuggestionItems(query, matches, {
    includeCustom = true,
    isLoading = false,
    remoteUnavailable = false,
} = {}) {
    const input = getDiseaseInput();
    const container = getDiseaseSuggestions();
    if (!input || !container) return;

    diseaseContextState.activeSuggestionIndex = -1;
    container.replaceChildren();

    matches.forEach(({ entry, match }) => {
        const option = document.createElement('button');
        option.type = 'button';
        option.className = 'disease-suggestion-option';
        if (entry.isTopHit) option.classList.add('is-top-hit');
        const selectedMatch = diseaseContextState.selectedMatch;
        const isSelected = (entry.curatedCode && entry.curatedCode === getDiseaseHidden()?.value) ||
            (entry.databaseId && selectedMatch?.databaseId && entry.databaseId === selectedMatch.databaseId) ||
            (!entry.curatedCode && normalizeDiseaseSearchText(entry.canonicalName || entry.label) ===
                normalizeDiseaseSearchText(selectedMatch?.canonicalName || selectedMatch?.label));
        if (isSelected) option.classList.add('is-selected');
        option.dataset.disease = entry.canonicalName || entry.label.replace(/\s+\([^)]+\)$/, '');
        if (entry.curatedCode) option.dataset.curatedCode = entry.curatedCode;
        option._diseaseRecord = entry;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');

        const copy = document.createElement('span');
        copy.className = 'disease-suggestion-copy';
        const titleRow = document.createElement('span');
        titleRow.className = 'disease-suggestion-title-row';
        const label = document.createElement('strong');
        label.textContent = entry.canonicalName || entry.label;
        titleRow.appendChild(label);
        if (entry.isTopHit) {
            const topHit = document.createElement('span');
            topHit.className = 'disease-suggestion-top-hit';
            topHit.textContent = 'Top match';
            titleRow.appendChild(topHit);
        }
        if (isSelected) {
            const selectedBadge = document.createElement('span');
            selectedBadge.className = 'disease-suggestion-selected';
            selectedBadge.textContent = 'Selected';
            titleRow.appendChild(selectedBadge);
        }
        const description = document.createElement('small');
        description.textContent = entry.description || `${getDiseaseMatchLabel(match)}${entry.curatedCode ? ', completed example available' : ''}`;
        copy.append(titleRow, description);
        if (entry.matchContext) {
            const matchContext = document.createElement('small');
            matchContext.className = 'disease-suggestion-match-context';
            matchContext.textContent = entry.matchContext;
            copy.appendChild(matchContext);
        }

        const metadata = document.createElement('span');
        metadata.className = 'disease-suggestion-authority';
        metadata.textContent = entry.databaseId || (entry.curatedCode ? entry.curatedCode : getDiseaseMatchLabel(match));
        option.append(copy, metadata);
        container.appendChild(option);
    });

    if (isLoading) {
        const loading = document.createElement('div');
        loading.className = 'disease-suggestion-status is-loading';
        loading.innerHTML = '<span class="disease-search-spinner" aria-hidden="true"></span><span>Searching Open Targets diseases and phenotypes…</span>';
        container.appendChild(loading);
    }

    if (remoteUnavailable) {
        const unavailable = document.createElement('div');
        unavailable.className = 'disease-suggestion-status';
        unavailable.textContent = 'Open Targets search is temporarily unavailable. Local matches are shown.';
        container.appendChild(unavailable);
    }

    const exactMatch = matches.some(({ match }) => match.score === 0);
    if (includeCustom && !exactMatch) {
        const customOption = document.createElement('button');
        customOption.type = 'button';
        customOption.className = 'disease-suggestion-option disease-suggestion-custom';
        customOption.dataset.customDisease = query;
        customOption.setAttribute('role', 'option');
        customOption.setAttribute('aria-selected', 'false');

        const label = document.createElement('strong');
        label.textContent = `Use “${query}”`;
        const metadata = document.createElement('small');
        metadata.textContent = 'Keep as custom context';
        const copy = document.createElement('span');
        copy.className = 'disease-suggestion-copy';
        copy.append(label, metadata);
        customOption.append(copy);
        container.appendChild(customOption);
    }

    container.classList.remove('hidden');
    input.setAttribute('aria-expanded', 'true');
}

async function requestOpenTargetsDiseaseResults(query, signal) {
    try {
        const response = await fetch(`/api/disease-search?q=${encodeURIComponent(query)}`, {
            headers: { 'Accept': 'application/json' },
            signal
        });
        const contentType = response.headers.get('content-type') || '';
        if (response.ok && contentType.includes('application/json')) {
            const payload = await response.json();
            if (payload.available !== false || (payload.results || []).length) return payload;
        }
    } catch (error) {
        if (error?.name === 'AbortError') throw error;
    }

    // Plain static previews do not expose the Flask proxy. Open Targets is a
    // public, read-only API, so use it directly as a local-preview fallback.
    const graphqlQuery = `
      query DiseaseSearch($query: String!) {
        search(queryString: $query, entityNames: ["disease"], page: {index: 0, size: 8}) {
          hits { id name entity description }
        }
      }
    `;
    try {
        const response = await fetch('https://api.platform.opentargets.org/api/v4/graphql', {
            method: 'POST',
            headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: graphqlQuery, variables: { query } }),
            signal,
        });
        if (!response.ok) return { results: [], available: false };
        const payload = await response.json();
        const hits = payload?.data?.search?.hits || [];
        return {
            available: true,
            source: 'Open Targets',
            results: hits.filter(item => item?.id && item?.name).map(item => ({
                id: item.id,
                name: item.name,
                description: item.description || '',
                url: `https://platform.opentargets.org/disease/${item.id}/associations`,
            })),
        };
    } catch (error) {
        if (error?.name === 'AbortError') throw error;
        return { results: [], available: false };
    }
}

async function fetchOpenTargetsDiseaseSuggestions(query, localMatches) {
    if (diseaseContextState.searchController) diseaseContextState.searchController.abort();
    const controller = new AbortController();
    diseaseContextState.searchController = controller;
    try {
        const payload = await requestOpenTargetsDiseaseResults(query, controller.signal);
        if (getDiseaseInput()?.value.trim() !== query) return;

        const normalizedQuery = normalizeDiseaseSearchText(query);
        const remoteMatches = (payload.results || []).map((item, index) => {
            const normalizedName = normalizeDiseaseSearchText(item.name);
            const entry = {
                label: item.name,
                canonicalName: item.name,
                aliases: item.synonyms || [],
                description: item.description || '',
                database: 'Open Targets',
                databaseId: String(item.id || '').replace('_', ':'),
                openTargetsId: item.id || '',
                isRemote: true,
                isTopHit: index === 0,
                matchContext: normalizedName.includes(normalizedQuery)
                    ? 'Matched in Open Targets name'
                    : `Matched via “${query}” in Open Targets`,
                authorityUrl: item.url || (item.id
                    ? `https://platform.opentargets.org/disease/${item.id}/associations`
                    : '')
            };
            return { entry, match: scoreDiseaseSuggestion(entry, query) || { score: 2, aliasMatch: false } };
        });
        const merged = [...remoteMatches, ...localMatches].filter((item, index, items) => {
            const key = item.entry.databaseId || normalizeDiseaseSearchText(item.entry.label);
            return items.findIndex(candidate =>
                (candidate.entry.databaseId || normalizeDiseaseSearchText(candidate.entry.label)) === key
            ) === index;
        }).slice(0, 8);
        renderDiseaseSuggestionItems(query, merged, {
            includeCustom: true,
            remoteUnavailable: payload.available === false,
        });
    } catch (error) {
        if (error?.name !== 'AbortError') {
            renderDiseaseSuggestionItems(query, localMatches, {
                includeCustom: true,
                remoteUnavailable: true,
            });
        }
    }
}

function updateActiveDiseaseSuggestion(options) {
    options.forEach((option, index) => {
        const active = index === diseaseContextState.activeSuggestionIndex;
        option.classList.toggle('active', active);
        option.setAttribute('aria-selected', String(active));
    });
    options[diseaseContextState.activeSuggestionIndex]?.scrollIntoView({ block: 'nearest' });
}

function hideDiseaseSuggestions() {
    getDiseaseSuggestions()?.classList.add('hidden');
    getDiseaseInput()?.setAttribute('aria-expanded', 'false');
    diseaseContextState.activeSuggestionIndex = -1;
}

function selectDiseaseSuggestion(option) {
    if (!option) return;
    const curatedCode = option.dataset.curatedCode;
    if (curatedCode) {
        const typedAlias = getDiseaseInput()?.value.trim() || curatedCode;
        setDiseaseCombobox(curatedCode);
        if (diseaseContextState.selectedMatch) {
            diseaseContextState.selectedMatch.inputAlias = typedAlias;
            updateDiseaseContextStatus();
        }
    } else {
        const disease = option.dataset.customDisease || option.dataset.disease;
        if (!disease) return;
        const record = option._diseaseRecord;
        diseaseContextState.selectedMatch = record ? {
            ...record,
            inputAlias: getDiseaseInput()?.value.trim() || ''
        } : {
            label: disease,
            canonicalName: disease,
            inputAlias: disease,
            database: '',
            databaseId: '',
            description: ''
        };
        getDiseasePresetSelect().value = '';
        getDiseaseInput().value = disease;
        getDiseaseHidden().value = disease;
        syncCuratedDiseaseSelect('');
        updateDiseaseContextStatus();
        hideDiseaseSuggestions();
        getDiseaseInput().focus();
    }
}

function initDiseaseSearch() {
    const input = getDiseaseInput();
    const suggestions = getDiseaseSuggestions();
    if (!input || !suggestions) return;

    input.addEventListener('input', () => {
        onCustomDiseaseInput();
        const error = getBiomedicalTextError(input.value, 'Disease context');
        showInputValidationError('disease-input-error', error);
        if (error) {
            hideDiseaseSuggestions();
            return;
        }
        renderDiseaseSuggestions(input.value);
    });

    input.addEventListener('focus', () => {
        if (input.value.trim()) renderDiseaseSuggestions(input.value);
    });

    input.addEventListener('keydown', event => {
        const options = getDiseaseSuggestionOptions();
        if (event.key === 'ArrowDown' && options.length > 0) {
            event.preventDefault();
            diseaseContextState.activeSuggestionIndex = Math.min(
                diseaseContextState.activeSuggestionIndex + 1,
                options.length - 1
            );
            updateActiveDiseaseSuggestion(options);
            return;
        }

        if (event.key === 'ArrowUp' && options.length > 0) {
            event.preventDefault();
            diseaseContextState.activeSuggestionIndex = Math.max(
                diseaseContextState.activeSuggestionIndex - 1,
                0
            );
            updateActiveDiseaseSuggestion(options);
            return;
        }

        if (event.key === 'Enter' && input.value.trim() && options.length > 0) {
            event.preventDefault();
            const active = options[diseaseContextState.activeSuggestionIndex] || options[0];
            if (active) selectDiseaseSuggestion(active);
            else hideDiseaseSuggestions();
            return;
        }

        if (event.key === 'Tab' && input.value.trim() && options.length > 0) {
            const active = options[diseaseContextState.activeSuggestionIndex] || options[0];
            if (active) selectDiseaseSuggestion(active);
            return;
        }

        if (event.key === 'Escape') hideDiseaseSuggestions();
    });

    suggestions.addEventListener('mousedown', event => {
        const option = event.target.closest('.disease-suggestion-option');
        if (!option) return;
        event.preventDefault();
        selectDiseaseSuggestion(option);
    });

    document.addEventListener('click', event => {
        if (!event.target.closest('.disease-autocomplete-wrapper')) hideDiseaseSuggestions();
    });
}

document.addEventListener('DOMContentLoaded', () => {
    renderDiseasePresetOptions();
    initDiseaseSearch();
    initOpenTargetsGeneImport();
    setDiseaseCombobox('');
});

window.onDiseasePresetChange = onDiseasePresetChange;
window.onCustomDiseaseInput = onCustomDiseaseInput;

// Make gene list functions globally accessible for inline onclick handlers
window.toggleGeneListPanel = toggleGeneListPanel;
window.onGeneListDiseaseChange = onGeneListDiseaseChange;
window.onGeneListModuleChange = onGeneListModuleChange;
window.loadSelectedGeneList = loadSelectedGeneList;
window.showFeaturedExamples = showFeaturedExamples;
window.loadFeaturedInput = loadFeaturedInput;
window.openFeaturedCompletedExample = openFeaturedCompletedExample;
window.toggleMoreFeaturedExamples = toggleMoreFeaturedExamples;

async function loadSelectedGeneList() {
    const { selectedDisease, selectedListId } = geneListState;
    if (!selectedDisease || !selectedListId) return;

    const btn = document.getElementById('gene-list-load-btn');
    btn.textContent = 'Loading...';
    btn.disabled = true;

    try {
        let data = geneListState.selectedMeta;
        if (!data?.genes?.length) {
            const detailUrl = `/api/gene-lists/${encodeURIComponent(selectedDisease)}/${encodeURIComponent(selectedListId)}`;
            const res = await fetch(detailUrl, {
                headers: { 'Accept': 'application/json' },
                cache: 'no-store'
            });
            if (!res.ok) throw new Error(`Gene list detail returned HTTP ${res.status}`);
            data = await res.json();
        }

        const loadedGenes = Array.isArray(data?.genes) ? data.genes : [];
        if (loadedGenes.length === 0) {
            throw new Error('The selected example contains no usable genes');
        }

        setSelectedGenes(loadedGenes);

        // Sync disease combobox to match
        setDiseaseCombobox(selectedDisease);

        btn.innerHTML = `<svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-check"></use></svg> Loaded ${loadedGenes.length} genes`;
        btn.removeAttribute('title');
        setTimeout(() => {
            btn.textContent = 'Load disease and genes';
            btn.disabled = false;
        }, 2000);

        const diseasePicker = document.getElementById('gene-list-disease-select');
        if (diseasePicker) diseasePicker.value = '';
        const modulePicker = document.getElementById('gene-list-module-select');
        if (modulePicker) modulePicker.innerHTML = '<option value="">Select a list</option>';
        document.getElementById('gene-list-meta')?.classList.add('hidden');
        geneListState.selectedDisease = null;
        geneListState.selectedListId = null;
        geneListState.selectedMeta = null;

        // Collapse panel after load
        setTimeout(() => {
            const panel = document.getElementById('gene-list-panel');
            const toggleBtn = document.getElementById('gene-list-toggle');
            if (panel && !panel.classList.contains('hidden')) {
                panel.classList.add('hidden');
                toggleBtn.innerHTML = 'Load disease and genes <span aria-hidden="true"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg></span>';
            }
        }, 2200);

    } catch (e) {
        btn.textContent = 'Could not load. Retry';
        btn.title = e?.message || 'The example gene set could not be loaded';
        btn.disabled = false;
        console.error('Gene list load error:', e);
    }
}

// ============================================================================
// GENE INPUT
// ============================================================================

function extendGeneSearchIndexFromCuratedLists() {
    Object.values(geneListState.allLists).forEach(disease => {
        (disease.lists || []).forEach(list => {
            (list.genes || []).forEach(gene => {
                const symbol = String(gene).trim().toUpperCase();
                if (/^[A-Z0-9][-A-Z0-9]*$/.test(symbol)) {
                    geneSearchState.index.add(symbol);
                }
            });
        });
    });

    if (document.activeElement === elements.geneSearchInput) {
        renderGeneSuggestions(elements.geneSearchInput.value);
    }
}

function getActiveGeneToken() {
    const input = elements.geneInput;
    if (!input) return null;
    const value = input.value;
    const caret = Number.isInteger(input.selectionStart) ? input.selectionStart : value.length;
    const beforeCaret = value.slice(0, caret);
    const match = beforeCaret.match(/(?:^|[,\s])([A-Za-z0-9._-]+)$/);
    if (!match) return null;
    const token = match[1];
    const start = caret - token.length;
    const trailing = value.slice(caret).match(/^[A-Za-z0-9._-]*/)?.[0] || '';
    return {
        query: `${token}${trailing}`.toUpperCase(),
        start,
        end: caret + trailing.length,
    };
}

function hideGeneQuerySuggestions() {
    elements.geneQuerySuggestions?.classList.add('hidden');
    elements.geneInput?.setAttribute('aria-expanded', 'false');
    geneQueryAutocompleteState.activeIndex = -1;
}

function getGeneQueryOptions() {
    return [...(elements.geneQuerySuggestions?.querySelectorAll('.gene-query-suggestion-option') || [])];
}

function updateActiveGeneQuerySuggestion(options) {
    options.forEach((option, index) => {
        const active = index === geneQueryAutocompleteState.activeIndex;
        option.classList.toggle('active', active);
        option.setAttribute('aria-selected', String(active));
    });
    options[geneQueryAutocompleteState.activeIndex]?.scrollIntoView({ block: 'nearest' });
}

function renderGeneQuerySuggestionItems(query, matches, {
    isLoading = false,
    includeCustom = true,
    remoteUnavailable = false,
} = {}) {
    const container = elements.geneQuerySuggestions;
    if (!container) return;
    container.replaceChildren();
    geneQueryAutocompleteState.activeIndex = -1;

    matches.forEach((entry, index) => {
        const option = document.createElement('button');
        option.type = 'button';
        option.className = 'gene-query-suggestion-option';
        if (entry.isTopHit) option.classList.add('is-top-hit');
        option.dataset.gene = entry.symbol;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        option._geneRecord = entry;

        const icon = document.createElement('span');
        icon.className = 'gene-query-suggestion-icon';
        icon.textContent = 'G';

        const copy = document.createElement('span');
        copy.className = 'gene-query-suggestion-copy';
        const title = document.createElement('span');
        title.className = 'gene-query-suggestion-title';
        const symbol = document.createElement('strong');
        symbol.textContent = entry.symbol;
        title.appendChild(symbol);
        if (entry.isTopHit) {
            const badge = document.createElement('span');
            badge.className = 'gene-query-suggestion-top-hit';
            badge.textContent = 'Top match';
            title.appendChild(badge);
        }
        const name = document.createElement('small');
        name.textContent = entry.name || 'Approved human gene symbol';
        copy.append(title, name);

        const identifier = document.createElement('span');
        identifier.className = 'gene-query-suggestion-id';
        identifier.textContent = entry.ensemblId || 'HGNC symbol';
        option.append(icon, copy, identifier);
        container.appendChild(option);
    });

    if (isLoading) {
        const loading = document.createElement('div');
        loading.className = 'gene-query-suggestion-status is-loading';
        loading.innerHTML = '<span class="gene-search-spinner" aria-hidden="true"></span><span>Searching approved human genes…</span>';
        container.appendChild(loading);
    }

    if (remoteUnavailable) {
        const unavailable = document.createElement('div');
        unavailable.className = 'gene-query-suggestion-status';
        unavailable.textContent = 'Online lookup is temporarily unavailable; valid identifiers can still be entered.';
        container.appendChild(unavailable);
    }

    if (includeCustom && isSupportedGeneIdentifier(query) &&
        !matches.some(entry => entry.symbol === query || entry.ensemblId === query)) {
        const custom = document.createElement('button');
        custom.type = 'button';
        custom.className = 'gene-query-suggestion-option gene-query-suggestion-custom';
        custom.dataset.gene = query;
        custom.setAttribute('role', 'option');
        custom.setAttribute('aria-selected', 'false');
        custom.innerHTML = `<span class="gene-query-suggestion-icon">+</span><span class="gene-query-suggestion-copy"><strong>Keep ${escapeHtml(query)}</strong><small>Use this identifier as entered</small></span>`;
        container.appendChild(custom);
    }

    if (!container.children.length) {
        hideGeneQuerySuggestions();
        return;
    }
    container.classList.remove('hidden');
    elements.geneInput?.setAttribute('aria-expanded', 'true');
}

function getLocalGeneQueryMatches(query) {
    const selected = new Set(parseGenes(elements.geneInput?.value || ''));
    return [...geneSearchState.index]
        .filter(symbol => !selected.has(symbol) || symbol === query)
        .map(symbol => ({
            symbol,
            name: '',
            ensemblId: '',
            score: getGeneMatchScore(symbol, query),
            source: 'local',
        }))
        .filter(entry => Number.isFinite(entry.score))
        .sort((a, b) => a.score - b.score || a.symbol.length - b.symbol.length || a.symbol.localeCompare(b.symbol))
        .slice(0, 8);
}

async function requestGeneSearchResults(query, signal) {
    try {
        const response = await fetch(`/api/gene-search?q=${encodeURIComponent(query)}`, {
            headers: { 'Accept': 'application/json' },
            signal,
        });
        const contentType = response.headers.get('content-type') || '';
        if (response.ok && contentType.includes('application/json')) {
            const payload = await response.json();
            if (payload.available !== false || (payload.results || []).length) return payload;
        }
    } catch (error) {
        if (error?.name === 'AbortError') throw error;
    }

    const graphqlQuery = `
      query TargetSearch($query: String!) {
        search(queryString: $query, entityNames: ["target"], page: {index: 0, size: 50}) {
          hits { id name entity description }
        }
      }
    `;
    try {
        const response = await fetch('https://api.platform.opentargets.org/api/v4/graphql', {
            method: 'POST',
            headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: graphqlQuery, variables: { query } }),
            signal,
        });
        if (!response.ok) return { results: [], available: false };
        const payload = await response.json();
        const hits = payload?.data?.search?.hits || [];
        return {
            available: true,
            results: rankGeneSearchHits(hits, query),
            source: 'Open Targets',
        };
    } catch (error) {
        if (error?.name === 'AbortError') throw error;
        return { results: [], available: false };
    }
}

function rankGeneSearchHits(hits, query) {
    const normalizedQuery = String(query || '').trim().toUpperCase();
    return (hits || []).map((item, originalIndex) => {
        const symbol = String(item?.name || '').trim().toUpperCase();
        const ensemblId = String(item?.id || '').trim().toUpperCase();
        const name = String(item?.description || '').trim();
        let matchRank = 4;
        if (symbol === normalizedQuery || ensemblId === normalizedQuery) matchRank = 0;
        else if (symbol.startsWith(normalizedQuery)) matchRank = 1;
        else if (symbol.includes(normalizedQuery)) matchRank = 2;
        else if (name.toUpperCase().includes(normalizedQuery)) matchRank = 3;
        const secondaryPenalty = /pseudogene|antisense|novel transcript/i.test(name) ? 1 : 0;
        return { symbol, ensemblId, name, matchRank, secondaryPenalty, originalIndex };
    }).filter(item => item.symbol && item.ensemblId)
        .sort((a, b) => a.matchRank - b.matchRank || a.secondaryPenalty - b.secondaryPenalty ||
            a.symbol.length - b.symbol.length || a.originalIndex - b.originalIndex)
        .slice(0, 8)
        .map((item, index) => ({
            symbol: item.symbol,
            ensemblId: item.ensemblId,
            name: item.name,
            isTopHit: index === 0,
            source: 'Open Targets',
            url: `https://platform.opentargets.org/target/${item.ensemblId}`,
        }));
}

async function fetchGeneQuerySuggestions(query, localMatches) {
    if (geneQueryAutocompleteState.searchController) {
        geneQueryAutocompleteState.searchController.abort();
    }
    const controller = new AbortController();
    geneQueryAutocompleteState.searchController = controller;
    try {
        const payload = await requestGeneSearchResults(query, controller.signal);
        if (getActiveGeneToken()?.query !== query) return;
        const remote = (payload.results || []).map((entry, index) => ({
            symbol: String(entry.symbol || entry.name || '').toUpperCase(),
            name: entry.name && entry.symbol ? entry.name : (entry.description || ''),
            ensemblId: String(entry.ensembl_id || entry.ensemblId || entry.id || '').toUpperCase(),
            url: entry.url || '',
            source: 'Open Targets',
            isTopHit: index === 0,
        })).filter(entry => entry.symbol);
        const merged = [...remote, ...localMatches].filter((entry, index, entries) =>
            entries.findIndex(candidate => candidate.symbol === entry.symbol) === index
        ).slice(0, 8);
        renderGeneQuerySuggestionItems(query, merged, {
            includeCustom: true,
            remoteUnavailable: payload.available === false,
        });
    } catch (error) {
        if (error?.name !== 'AbortError') {
            renderGeneQuerySuggestionItems(query, localMatches, {
                includeCustom: true,
                remoteUnavailable: true,
            });
        }
    }
}

function scheduleGeneQuerySuggestions() {
    const token = getActiveGeneToken();
    if (!token || token.query.length < 2) {
        hideGeneQuerySuggestions();
        return;
    }
    geneQueryAutocompleteState.tokenStart = token.start;
    geneQueryAutocompleteState.tokenEnd = token.end;
    geneQueryAutocompleteState.query = token.query;
    const localMatches = getLocalGeneQueryMatches(token.query);
    renderGeneQuerySuggestionItems(token.query, localMatches, {
        includeCustom: false,
        isLoading: true,
    });
    if (geneQueryAutocompleteState.searchTimer) clearTimeout(geneQueryAutocompleteState.searchTimer);
    geneQueryAutocompleteState.searchTimer = setTimeout(() => {
        fetchGeneQuerySuggestions(token.query, localMatches);
    }, 220);
}

function selectGeneQuerySuggestion(option) {
    const symbol = String(option?.dataset?.gene || '').toUpperCase();
    if (!symbol) return;
    const input = elements.geneInput;
    const token = getActiveGeneToken() || {
        start: geneQueryAutocompleteState.tokenStart,
        end: geneQueryAutocompleteState.tokenEnd,
    };
    const before = input.value.slice(0, token.start);
    const after = input.value.slice(token.end);
    const separator = after && /^[,\s]/.test(after) ? '' : ' ';
    input.value = `${before}${symbol}${separator}${after}`;
    const caret = before.length + symbol.length + separator.length;
    input.setSelectionRange(caret, caret);
    geneSearchState.index.add(symbol);
    hideGeneQuerySuggestions();
    updateGeneCount();
    input.focus();
}

function initGeneQueryAutocomplete() {
    const input = elements.geneInput;
    const suggestions = elements.geneQuerySuggestions;
    if (!input || !suggestions) return;

    input.addEventListener('input', scheduleGeneQuerySuggestions);
    input.addEventListener('click', scheduleGeneQuerySuggestions);
    input.addEventListener('focus', scheduleGeneQuerySuggestions);
    input.addEventListener('keydown', event => {
        const options = getGeneQueryOptions();
        if (event.key === 'ArrowDown' && options.length) {
            event.preventDefault();
            geneQueryAutocompleteState.activeIndex = Math.min(
                geneQueryAutocompleteState.activeIndex + 1,
                options.length - 1
            );
            updateActiveGeneQuerySuggestion(options);
        } else if (event.key === 'ArrowUp' && options.length) {
            event.preventDefault();
            geneQueryAutocompleteState.activeIndex = Math.max(geneQueryAutocompleteState.activeIndex - 1, 0);
            updateActiveGeneQuerySuggestion(options);
        } else if (event.key === 'Enter' && !suggestions.classList.contains('hidden') && options.length) {
            event.preventDefault();
            selectGeneQuerySuggestion(options[geneQueryAutocompleteState.activeIndex] || options[0]);
        } else if (event.key === 'Escape') {
            hideGeneQuerySuggestions();
        }
    });

    suggestions.addEventListener('mousedown', event => {
        const option = event.target.closest('.gene-query-suggestion-option');
        if (!option) return;
        event.preventDefault();
        selectGeneQuerySuggestion(option);
    });

    document.addEventListener('click', event => {
        if (!event.target.closest('.gene-query-panel')) hideGeneQuerySuggestions();
    });
}

function initGeneSearch() {
    const input = elements.geneSearchInput;
    const suggestions = elements.geneSuggestions;
    if (!input || !suggestions) return;

    input.addEventListener('input', () => {
        input.value = input.value.toUpperCase();
        renderGeneSuggestions(input.value);
    });

    input.addEventListener('focus', () => {
        if (input.value.trim()) renderGeneSuggestions(input.value);
    });

    input.addEventListener('keydown', (event) => {
        const options = [...suggestions.querySelectorAll('.gene-suggestion-option')];

        if (event.key === 'ArrowDown' && options.length > 0) {
            event.preventDefault();
            geneSearchState.activeIndex = Math.min(geneSearchState.activeIndex + 1, options.length - 1);
            updateActiveGeneSuggestion(options);
            return;
        }

        if (event.key === 'ArrowUp' && options.length > 0) {
            event.preventDefault();
            geneSearchState.activeIndex = Math.max(geneSearchState.activeIndex - 1, 0);
            updateActiveGeneSuggestion(options);
            return;
        }

        if (event.key === 'Enter') {
            event.preventDefault();
            const active = options[geneSearchState.activeIndex] || options[0];
            if (active?.dataset.gene) {
                addGeneSymbol(active.dataset.gene);
            } else {
                const typed = input.value.trim().toUpperCase();
                if (/^[A-Z0-9][-A-Z0-9]*$/.test(typed)) addGeneSymbol(typed);
            }
            return;
        }

        if (event.key === 'Backspace' && input.value === '') {
            const genes = parseGenes(elements.geneInput.value);
            if (genes.length > 0) removeGeneSymbol(genes[genes.length - 1]);
            return;
        }

        if (event.key === 'Escape') {
            hideGeneSuggestions();
        }
    });

    suggestions.addEventListener('mousedown', (event) => {
        const option = event.target.closest('.gene-suggestion-option');
        if (!option?.dataset.gene) return;
        event.preventDefault();
        addGeneSymbol(option.dataset.gene);
    });

    elements.clearGenesBtn?.addEventListener('click', clearSelectedGenes);

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.gene-search-composer')) hideGeneSuggestions();
    });
}

function initGeneFileUpload() {
    const input = elements.geneFileInput;
    const button = elements.uploadGeneListBtn;
    if (!input || !button) return;

    button.addEventListener('click', () => input.click());
    input.addEventListener('change', async () => {
        const file = input.files?.[0];
        if (!file) return;
        try {
            const content = await file.text();
            const genes = parseGenes(content);
            setSelectedGenes(genes);
            if (elements.geneInputQuality) {
                elements.geneInputQuality.textContent = `${file.name}: ${genes.length} recognized identifiers`;
            }
        } catch (_) {
            if (elements.geneInputQuality) {
                elements.geneInputQuality.textContent = 'The selected file could not be read.';
            }
        } finally {
            input.value = '';
        }
    });
}

function isSubsequence(query, symbol) {
    let queryIndex = 0;
    for (let i = 0; i < symbol.length && queryIndex < query.length; i += 1) {
        if (symbol[i] === query[queryIndex]) queryIndex += 1;
    }
    return queryIndex === query.length;
}

function getGeneMatchScore(symbol, query) {
    if (symbol === query) return 0;
    if (symbol.startsWith(query)) return 1;
    if (symbol.includes(query)) return 2;
    if (query.length >= 2 && isSubsequence(query, symbol)) return 3;
    return Number.POSITIVE_INFINITY;
}

function renderGeneSuggestions(rawQuery) {
    const input = elements.geneSearchInput;
    const container = elements.geneSuggestions;
    if (!input || !container) return;

    const query = String(rawQuery || '').trim().toUpperCase();
    if (!query) {
        hideGeneSuggestions();
        return;
    }

    const selected = new Set(parseGenes(elements.geneInput.value));
    const matches = [...geneSearchState.index]
        .filter(symbol => !selected.has(symbol))
        .map(symbol => ({
            symbol,
            score: getGeneMatchScore(symbol, query),
            priority: GENE_SEARCH_SEEDS.includes(symbol) ? 0 : 1
        }))
        .filter(item => Number.isFinite(item.score))
        .sort((a, b) => a.score - b.score || a.priority - b.priority ||
            a.symbol.length - b.symbol.length || a.symbol.localeCompare(b.symbol))
        .slice(0, 8);

    geneSearchState.suggestions = matches.map(item => item.symbol);
    geneSearchState.activeIndex = -1;
    container.innerHTML = '';

    matches.forEach(item => {
        const option = document.createElement('button');
        option.type = 'button';
        option.className = 'gene-suggestion-option';
        option.dataset.gene = item.symbol;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');

        const symbol = document.createElement('strong');
        symbol.textContent = item.symbol;
        const matchType = document.createElement('span');
        matchType.textContent = item.score <= 1 ? 'Prefix match' : item.score === 2 ? 'Contains match' : 'Fuzzy match';

        option.append(symbol, matchType);
        container.appendChild(option);
    });

    if (matches.length === 0) {
        const typedIsValid = isSupportedGeneIdentifier(query);
        if (typedIsValid) {
            const option = document.createElement('button');
            option.type = 'button';
            option.className = 'gene-suggestion-option gene-suggestion-custom';
            option.dataset.gene = query;
            option.setAttribute('role', 'option');
            option.setAttribute('aria-selected', 'false');
            option.innerHTML = `<strong>${escapeHtml(query)}</strong><span>Add symbol as entered</span>`;
            container.appendChild(option);
        } else {
            container.innerHTML = '<div class="gene-suggestion-empty">No matching gene symbols</div>';
        }
    }

    container.classList.remove('hidden');
    input.setAttribute('aria-expanded', 'true');
}

function updateActiveGeneSuggestion(options) {
    options.forEach((option, index) => {
        const isActive = index === geneSearchState.activeIndex;
        option.classList.toggle('active', isActive);
        option.setAttribute('aria-selected', String(isActive));
    });
    options[geneSearchState.activeIndex]?.scrollIntoView({ block: 'nearest' });
}

function hideGeneSuggestions() {
    elements.geneSuggestions?.classList.add('hidden');
    elements.geneSearchInput?.setAttribute('aria-expanded', 'false');
    geneSearchState.activeIndex = -1;
}

function setSelectedGenes(genes, { preserveOpenTargetsImport = false } = {}) {
    if (!preserveOpenTargetsImport) clearOpenTargetsGeneImportState();
    const uniqueGenes = [...new Set((genes || [])
        .map(gene => String(gene).trim().toUpperCase())
        .filter(isSupportedGeneIdentifier))];
    elements.geneInput.value = uniqueGenes.join(', ');
    uniqueGenes.forEach(gene => geneSearchState.index.add(gene));
    updateGeneCount();
}

function addGeneSymbol(symbol) {
    const current = parseGenes(elements.geneInput.value);
    setSelectedGenes([...current, symbol]);
    elements.geneSearchInput.value = '';
    hideGeneSuggestions();
    elements.geneSearchInput.focus();
}

function removeGeneSymbol(symbol) {
    const remaining = parseGenes(elements.geneInput.value).filter(gene => gene !== symbol);
    setSelectedGenes(remaining);
}

function clearSelectedGenes() {
    setSelectedGenes([]);
    if (elements.geneSearchInput) {
        elements.geneSearchInput.value = '';
        elements.geneSearchInput.focus();
    }
    hideGeneSuggestions();
}

function renderSelectedGeneChips(genes) {
    const container = elements.selectedGeneStrip;
    if (!container) return;

    container.innerHTML = '';
    container.classList.toggle('is-empty', genes.length === 0);
    if (genes.length <= 10) geneSearchState.expandedSelection = false;
    const visibleGenes = geneSearchState.expandedSelection ? genes : genes.slice(0, 10);

    visibleGenes.forEach(gene => {
        const chip = document.createElement('span');
        chip.className = 'selected-gene-chip';

        const label = document.createElement('span');
        label.textContent = gene;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.textContent = '×';
        remove.setAttribute('aria-label', `Remove ${gene}`);
        remove.addEventListener('click', () => removeGeneSymbol(gene));

        chip.append(label, remove);
        container.appendChild(chip);
    });

    if (genes.length > 10) {
        const more = document.createElement('button');
        more.type = 'button';
        more.className = 'selected-gene-more';
        more.textContent = geneSearchState.expandedSelection
            ? 'Show first 10'
            : `Show all ${genes.length} genes`;
        more.setAttribute('aria-expanded', String(geneSearchState.expandedSelection));
        more.addEventListener('click', () => {
            geneSearchState.expandedSelection = !geneSearchState.expandedSelection;
            renderSelectedGeneChips(genes);
        });
        container.appendChild(more);
    }
}

function updateGeneCount() {
    const genes = parseGenes(elements.geneInput.value);
    elements.geneCount.textContent = `${genes.length} gene${genes.length === 1 ? '' : 's'} selected`;
    const rawTokens = String(elements.geneInput.value || '').split(/[,\n\s;]+/).map(token => token.trim()).filter(Boolean);
    const invalidCount = rawTokens.filter(token => !isSupportedGeneIdentifier(token)).length;
    const ensemblCount = genes.filter(gene => /^ENSG\d+(?:\.\d+)?$/i.test(gene)).length;
    if (elements.geneInputQuality) {
        elements.geneInputQuality.textContent = invalidCount
            ? `${invalidCount} unrecognized token${invalidCount === 1 ? '' : 's'} will be excluded`
            : `${genes.length - ensemblCount} gene symbol${genes.length - ensemblCount === 1 ? '' : 's'}, ${ensemblCount} Ensembl ID${ensemblCount === 1 ? '' : 's'}`;
    }
    elements.clearGenesBtn?.classList.toggle('hidden', genes.length === 0);
    renderSelectedGeneChips(genes);
    syncStartButtonAvailability();
}

function isSupportedGeneIdentifier(value) {
    const token = String(value || '').trim().toUpperCase();
    return /^ENSG\d+(?:\.\d+)?$/.test(token) || /^[A-Z0-9][A-Z0-9-]*$/.test(token);
}

function parseGenes(input) {
    if (!input) return [];
    return [...new Set(input.split(/[,\n\s;]+/)
        .map(g => g.trim().toUpperCase())
        .filter(isSupportedGeneIdentifier))];
}

// ============================================================================
// ANALYSIS
// ============================================================================

function syncStartButtonAvailability() {
    if (!elements.startBtn) return;
    const geneCount = parseGenes(elements.geneInput?.value || '').length;
    const quota = state.quota;
    const quotaBlocked = Boolean(
        quota?.enabled && (
            quota.available === false ||
            Number(quota.user_remaining) <= 0 ||
            Number(quota.global_remaining) <= 0
        )
    );
    elements.startBtn.disabled = state.isAnalyzing || geneCount < 3 || quotaBlocked;
}

function updateQuotaStatus(quota) {
    state.quota = quota || null;
    const box = elements.quotaStatus;
    const headerBox = elements.headerQuotaStatus;
    if (!box) {
        syncStartButtonAvailability();
        return;
    }

    box.classList.remove('quota-status--limited', 'quota-status--unavailable');
    if (!quota?.enabled) {
        box.classList.add('hidden');
        headerBox?.classList.add('hidden');
        syncStartButtonAvailability();
        return;
    }

    box.classList.remove('hidden');
    headerBox?.classList.remove('hidden');
    if (quota.available === false) {
        box.textContent = 'Submissions are paused because the daily usage limit cannot be verified.';
        box.classList.add('quota-status--unavailable');
        if (headerBox) headerBox.textContent = 'Daily usage unavailable';
    } else {
        const userRemaining = Math.max(0, Number(quota.user_remaining) || 0);
        const userLimit = Math.max(0, Number(quota.user_limit) || 0);
        const userUsed = Math.max(0, Number(quota.user_used) || (userLimit - userRemaining));
        const globalRemaining = Math.max(0, Number(quota.global_remaining) || 0);
        const globalLimit = Math.max(0, Number(quota.global_limit) || 0);
        const concurrency = Math.max(1, Number(quota.max_concurrent_jobs) || 1);
        box.textContent = `${userRemaining} of ${userLimit} personal jobs remaining today; ${globalRemaining} of ${globalLimit} site-wide; ${concurrency} analysis at a time`;
        if (headerBox) {
            headerBox.textContent = `Daily usage ${userUsed}/${userLimit}`;
            headerBox.title = `${userRemaining} personal jobs remaining today; ${globalRemaining} of ${globalLimit} site-wide jobs remaining.`;
        }
        if (userRemaining <= 1 || globalRemaining <= 5) {
            box.classList.add('quota-status--limited');
            headerBox?.classList.add('header-quota-status--limited');
        } else {
            headerBox?.classList.remove('header-quota-status--limited');
        }
    }
    syncStartButtonAvailability();
}

async function loadQuotaStatus() {
    try {
        const response = await fetch('/api/quota', { headers: { 'Accept': 'application/json' } });
        const data = await response.json();
        if (response.ok || data.enabled) updateQuotaStatus(data);
    } catch (_) {
        // Static/offline previews do not expose the quota endpoint.
    }
}

async function startAnalysis() {
    // Reset collected reasoning for new analysis
    collectedReasoning.length = 0;

    const genes = parseGenes(elements.geneInput.value);
    const disease = elements.diseaseSelect.value;
    const selectedDisease = diseaseContextState.selectedMatch;
    const useIterative = document.getElementById('iterative-checkbox').checked;
    const selectedModel = document.getElementById('openai-model-select')?.value || 'gpt-5.1';
    const diseaseError = getBiomedicalTextError(
        document.getElementById('disease-input')?.value || disease,
        'Disease context'
    );

    if (diseaseError) {
        showInputValidationError('disease-input-error', diseaseError);
        document.getElementById('disease-input')?.focus();
        return;
    }
    showInputValidationError('disease-input-error', '');

    if (genes.length < 3) {
        alert('Please enter at least 3 genes');
        return;
    }

    // Update UI
    state.isAnalyzing = true;
    state.analysisStartedAt = Date.now();
    state.backgrounded = false;
    state.backgroundResults = null;
    document.body.classList.remove('results-view');
    updateActiveJobBanner();
    elements.startBtn.disabled = true;
    const btnText = useIterative ? 'Starting multiple runs...' : 'Starting...';
    elements.startBtn.innerHTML = `<span class="btn-icon"><svg class="ph ph-spin" aria-hidden="true" focusable="false"><use href="#ph-circle-notch"></use></svg></span><span class="btn-text">${btnText}</span>`;

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                genes,
                disease,
                disease_context: selectedDisease ? {
                    name: selectedDisease.canonicalName || selectedDisease.label || disease,
                    database: selectedDisease.database || '',
                    database_id: selectedDisease.databaseId || '',
                    open_targets_id: selectedDisease.openTargetsId || '',
                    mesh_id: selectedDisease.meshId || '',
                    description: selectedDisease.description || '',
                    url: selectedDisease.authorityUrl || ''
                } : null,
                use_iterative: useIterative,
                model: selectedModel
            })
        });

        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        if (data.quota) updateQuotaStatus(data.quota);

        state.sessionId = data.session_id;

        // Switch to chat view
        document.body.classList.add('analysis-running-view');
        elements.heroSection.classList.add('hidden');
        elements.inputSection.classList.add('hidden');
        elements.chatSection.classList.remove('hidden');
        updateProgressNotificationCopy();
        setActiveWorkflowStep('hypothesize');
        updateAnalysisProgress({
            percent: 1,
            stage: 'Queued',
            detail: 'The analysis request was accepted.',
            state: 'queued',
            elapsed_seconds: 0,
        });

        // Show typing indicator
        showTyping(true);

        // Start polling for updates
        startPolling();

    } catch (error) {
        console.error('Analysis start failed:', error);
        const message = error.message || 'Analysis could not be started.';
        if (/biomedical research context|violent|threatening|unrelated instructions/i.test(message)) {
            showInputValidationError('disease-input-error', message);
        } else {
            alert('Failed to start analysis: ' + message);
        }
        resetStartButton();
    }
}

function resetStartButton() {
    state.isAnalyzing = false;
    document.body.classList.remove('analysis-running-view');
    elements.startBtn.innerHTML = '<span class="btn-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-play"></use></svg></span><span class="btn-text">Start Analysis</span>';
    loadQuotaStatus();
    syncStartButtonAvailability();
}

// ============================================================================
// POLLING
// ============================================================================

function startPolling() {
    stopPolling();
    pollProgress();
    state.pollingInterval = setInterval(pollProgress, 1000);
}

function stopPolling() {
    if (state.pollingInterval) {
        clearInterval(state.pollingInterval);
        state.pollingInterval = null;
    }
}

async function pollProgress() {
    if (!state.sessionId) return;

    try {
        const response = await fetch(`/api/progress/${state.sessionId}`);
        const data = await response.json();

        if (data.error) {
            console.error('Poll error:', data.error);
            return;
        }

        // Update messages
        updateMessages(data.messages);
        updateAnalysisProgress(data.progress, data.status, data.waiting_for_user);

        // Handle waiting state - show query panel for query-enabled checkpoints
        if (data.waiting_for_user) {
            showTyping(false);
            const queryCheckpoints = ['network_biology', 'pathway_query'];
            showQueryPanel(queryCheckpoints.includes(data.current_checkpoint));
        } else if (data.status === 'running') {
            showTyping(true);
            showQueryPanel(false);
        }

        // Handle completion
        if (data.status === 'completed') {
            stopPolling();
            showTyping(false);
            if (state.backgrounded) {
                state.backgroundResults = data.results;
                resetStartButton();
                updateActiveJobBanner({ completed: true });
            } else {
                showResults(data.results);
            }
        } else if (data.status === 'cancelled' || data.status === 'error') {
            stopPolling();
            showTyping(false);
            resetStartButton();
            updateActiveJobBanner({ failed: true });
        }

    } catch (error) {
        console.error('Poll error:', error);
    }
}

function formatElapsedTime(totalSeconds) {
    const seconds = Math.max(0, Number(totalSeconds) || 0);
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = Math.floor(seconds % 60);
    if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
    return `${minutes}:${String(remainder).padStart(2, '0')}`;
}

function getEstimatedRemainingLabel(percent, waitingForUser, checkpointSeconds = null) {
    if (waitingForUser) {
        const seconds = Number(checkpointSeconds);
        return Number.isFinite(seconds)
            ? `Awaiting your input, continues automatically in ${formatElapsedTime(seconds)}`
            : 'Awaiting your input';
    }
    if (percent >= 100) return 'Ready';
    if (percent < 10) return 'About 15–30 minutes remaining';
    if (percent < 30) return 'About 12–25 minutes remaining';
    if (percent < 50) return 'About 8–18 minutes remaining';
    if (percent < 65) return 'About 6–12 minutes remaining';
    if (percent < 80) return 'About 4–9 minutes remaining';
    if (percent < 92) return 'About 2–5 minutes remaining';
    return 'Usually less than 2 minutes remaining';
}

function updateProgressNotificationCopy() {
    if (!elements.analysisProgressEmail) return;
    if (state.emailNotificationsAvailable && state.userEmail) {
        elements.analysisProgressEmail.textContent = `Completion email will be sent to ${state.userEmail}.`;
    } else {
        elements.analysisProgressEmail.textContent = 'You may return to the analysis page while this job continues in the background.';
    }
}

function updateActiveJobBanner({ completed = false, failed = false } = {}) {
    if (!elements.activeJobBanner || !elements.activeJobBannerText) return;
    const visible = state.backgrounded || Boolean(state.backgroundResults) || failed;
    elements.activeJobBanner.classList.toggle('hidden', !visible);
    if (!visible) return;
    if (failed) elements.activeJobBannerText.textContent = 'The background analysis stopped before completion.';
    else if (completed || state.backgroundResults) elements.activeJobBannerText.textContent = 'Your analysis is complete.';
    else {
        const percent = Math.round(Number(elements.analysisProgressBar?.value) || 0);
        elements.activeJobBannerText.textContent = `Analysis continues in the background (${percent}%).`;
    }
    if (elements.viewActiveJob) elements.viewActiveJob.textContent = state.backgroundResults ? 'View result' : 'View progress';
}

function backgroundAnalysis() {
    if (!state.isAnalyzing || !state.sessionId) return;
    state.backgrounded = true;
    showAnalysisView({ preserveActiveJob: true });
    updateActiveJobBanner();
}

function showActiveJob() {
    if (state.backgroundResults) {
        const results = state.backgroundResults;
        state.backgroundResults = null;
        state.backgrounded = false;
        updateActiveJobBanner();
        showResults(results);
        return;
    }
    if (!state.sessionId || !state.isAnalyzing) return;
    state.backgrounded = false;
    document.body.classList.add('analysis-running-view');
    document.body.classList.remove('results-view');
    elements.heroSection?.classList.add('hidden');
    elements.inputSection?.classList.add('hidden');
    elements.resultsSection?.classList.add('hidden');
    elements.chatSection?.classList.remove('hidden');
    updateActiveJobBanner();
}

function updateAnalysisProgress(progress = {}, status = 'running', waitingForUser = false) {
    if (!elements.analysisProgress || !elements.analysisProgressBar) return;

    const percent = Math.max(0, Math.min(100, Number(progress.percent) || 0));
    const progressState = waitingForUser ? 'waiting' : (progress.state || status || 'running');
    const fallbackElapsed = state.analysisStartedAt
        ? Math.floor((Date.now() - state.analysisStartedAt) / 1000)
        : 0;
    const elapsed = Number.isFinite(Number(progress.elapsed_seconds))
        ? Number(progress.elapsed_seconds)
        : fallbackElapsed;

    elements.analysisProgressBar.value = percent;
    elements.analysisProgressBar.textContent = `${Math.round(percent)}%`;
    elements.analysisProgressStage.textContent = progress.stage || 'Analysis in progress';
    elements.analysisProgressPercent.textContent = `${Math.round(percent)}%`;
    elements.analysisProgressDetail.textContent = progress.detail || 'Waiting for the next pipeline update.';
    elements.analysisProgressElapsed.textContent = `Elapsed ${formatElapsedTime(elapsed)}`;
    if (elements.analysisProgressRemaining) {
        elements.analysisProgressRemaining.textContent = getEstimatedRemainingLabel(
            percent,
            waitingForUser,
            progress.checkpoint_remaining_seconds,
        );
    }
    elements.analysisProgress.dataset.state = progressState;
    if (state.backgrounded) updateActiveJobBanner();
    const workflowStep = percent >= 82 ? 'interpret'
        : percent >= 58 ? 'rank'
            : percent >= 30 ? 'validate'
                : 'hypothesize';
    setActiveWorkflowStep(workflowStep);
}

// ============================================================================
// MESSAGES
// ============================================================================

function updateMessages(messages) {
    if (!messages || messages.length <= state.lastMessageCount) return;

    // Add only new messages
    for (let i = state.lastMessageCount; i < messages.length; i++) {
        addMessage(messages[i]);
    }

    state.lastMessageCount = messages.length;

}

// ============================================================================
// PIPELINE STAGE RENDERING
// ============================================================================

const STAGE_DEFS = {
    1: {
        name: 'Hypothesis Generation',
        desc: 'Candidate pathways are proposed across GO:BP, GO:MF, GO:CC, KEGG and Reactome. A structured method record is retained for each database and prompt pass.'
    },
    2: {
        name: 'Statistical Validation',
        desc: 'Each hypothesis is tested against functional enrichment with multiple-testing correction. Only statistically supported hypotheses advance.'
    },
    3: {
        name: 'Evidence-Based Ranking',
        desc: 'Validated pathways are ranked within each database using pathway definitions, disease pathology, intersection genes, enrichment strength and PubMed literature.'
    },
    4: {
        name: 'Multiple-run Feedback',
        desc: 'Validation outcomes, retained pathway IDs and database-specific gaps are summarized for an optional second hypothesis pass.'
    }
};

/**
 * Backend progress messages are authored with emoji prefixes (and occasional
 * box-drawing rules) for terminal logs. The web interface carries its own icon
 * set, so those glyphs are stripped before a message is classified or rendered.
 * Classification matches on wording, never on the emoji, so this is lossless.
 */
const MESSAGE_GLYPH_PREFIX = /^(?:[\u2190-\u21FF\u2300-\u27BF\u2B00-\u2BFF\uFE0F\u200D]|[\uD83C-\uDBFF][\uDC00-\uDFFF])+\s*/;
const MESSAGE_RULE_SUFFIX = /[\s\u2500-\u257F]*[\u2500-\u257F]{3,}[\s\u2500-\u257F]*$/;

function stripMessageGlyphs(content) {
    if (typeof content !== 'string') return content;
    if (content.includes('<table') || content.includes('stats-container')) return content;
    return content.replace(MESSAGE_GLYPH_PREFIX, '').replace(MESSAGE_RULE_SUFFIX, '').trim();
}

function classifySystemMsg(content) {
    const c = content;
    if (/starting pathway analysis/i.test(c))                           return 'analysis-start';
    if (/disease context:/i.test(c))                                    return 'context-info';
    if (/using real analysis|using demo mode|live hypothesis generation/i.test(c)) return 'pipeline-info';
    if (/step 1.*gpt|gpt.*generating.*pathway|initial prompt.*gpt/i.test(c)) return 'stage1-start';
    if (/gpt predicted \d+/i.test(c))                                   return 'stage1-done';
    if (/generated reasoning for \d+ categor/i.test(c))                 return 'stage1-reasoning';
    if (/step 2.*(?:g:profiler|functional enrichment)|(?:g:profiler|functional) enrichment.*analysis/i.test(c)) return 'stage2-start';
    if (/(?:g:profiler|enrichment analysis) (?:found|returned) \d+/i.test(c)) return 'stage2-done';
    if (/step 3.*matching|cross.valid/i.test(c))                        return 'stage3-start';
    if (c.includes('<table') || c.includes('stats-container'))          return 'stats-table';
    if (/filtered \d+ matches.*fdr|→.*fdr-significant|enrichment-record gate/i.test(c)) return 'fdr-note';
    if (/step 4.*ranking|gpt.*ranking \d+|ranking \d+ pathways/i.test(c)) return 'stage4-start';
    if (/ranking complete/i.test(c))                                     return 'stage4-done';
    if (/(?:prompt refinement|multiple runs).*round/i.test(c))          return 'refinement-round';
    if (/final step.*merging|merging.*ranking/i.test(c))                return 'merge-step';
    if (/no pathways|no pathway enrichment|no gpt predictions|no matched pathways/i.test(c)) return 'warn';
    return 'default';
}

function renderPipelineStageCard(num, status, customDesc) {
    const def = STAGE_DEFS[num] || {};
    const desc = customDesc !== undefined ? customDesc : def.desc;
    const statusHtml = status === 'done'
        ? '<span class="ps-status ps-status--done"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-check"></use></svg> Complete</span>'
        : '<span class="ps-status ps-status--running"><span class="ps-spinner"></span>Running</span>';
    return `
      <div class="pipeline-stage-card" data-pipeline-stage="${num}">
        <div class="ps-header">
          <div class="ps-left">
            <span class="ps-num">${num}</span>
            <div>
              <div class="ps-name">${def.name || 'Stage ' + num}</div>
              ${desc ? `<div class="ps-desc">${desc}</div>` : ''}
            </div>
          </div>
          ${statusHtml}
        </div>
      </div>`;
}

function renderPipelineOutputNote(icon, html) {
    const icons = {
        check: phIcon('check'),
        trace: phIcon('git-branch'),
        filter: phIcon('funnel'),
        warn: phIcon('warning'),
        info: phIcon('info')
    };
    return `<div class="pipeline-output-note">
      <span class="pon-icon pon-${icon}">${icons[icon] || '·'}</span>
      <span>${html}</span>
    </div>`;
}

function renderValidationStageWrapper(tableHtml) {
    return `
      <div class="pipeline-validation-card">
        <div class="pvc-header">
          <span class="ps-num">2</span>
          <div>
            <span class="ps-name">Statistical validation by database</span>
            <span class="pvc-subtitle">Generated, matched and statistically validated hypotheses by database</span>
          </div>
        </div>
        ${tableHtml}
      </div>`;
}

function renderRefinementRoundCard(content) {
    const m = content.match(/Round (\d+)\/(\d+)/);
    const roundNum = m ? parseInt(m[1]) : 2;
    if (roundNum <= 1) return renderPipelineStageCard(4, 'running');
    return renderPipelineStageCard(4, 'running', 'Validation feedback applied. A refined hypothesis pass is running with retained pathway IDs and database-specific guidance.');
}

function renderSystemMessage(content) {
    const type = classifySystemMsg(content);
    switch (type) {
        case 'analysis-start':
            return `<div class="ps-analysis-start">${content}</div>`;
        case 'context-info':
            return `<div class="ps-context-note">${content}</div>`;
        case 'pipeline-info':
            return `<div class="ps-context-note">${content}</div>`;
        case 'stage1-start':
            return renderPipelineStageCard(1, 'running');
        case 'stage1-done': {
            const m = content.match(/(\d+) pathways/);
            const n = m ? m[1] : '?';
            return renderPipelineOutputNote('check', `<strong>${n}</strong> pathway hypotheses proposed across GO:BP, GO:MF, GO:CC, KEGG and Reactome`);
        }
        case 'stage1-reasoning': {
            const m = content.match(/(\d+) categor/);
            const n = m ? m[1] : '5';
            return renderPipelineOutputNote('trace', `Database-level biological context captured for <strong>${n}</strong> source categories and carried into downstream interpretation`);
        }
        case 'stage2-start':
            return renderPipelineStageCard(2, 'running');
        case 'stage2-done': {
            const m = content.match(/(\d+) pathways.*?(\d+) significant/);
            if (m) return renderPipelineOutputNote('check', `Enrichment analysis returned <strong>${m[1]}</strong> terms; <strong>${m[2]}</strong> pass the corrected significance threshold`);
            return renderPipelineOutputNote('check', content);
        }
        case 'stage3-start':
            return `<div class="ps-section-divider"><span>Matching hypotheses to enrichment results</span></div>`;
        case 'stats-table':
            return renderValidationStageWrapper(content);
        case 'fdr-note': {
            const recordGate = content.match(/(\d+) matched records.*?(\d+) statistically significant records/i);
            if (recordGate) return renderPipelineOutputNote('filter', `Enrichment-record gate: <strong>${recordGate[1]}</strong> matched records → <strong>${recordGate[2]}</strong> statistically significant records advance to ranking`);
            const m = content.match(/(\d+) matches.*?(\d+) FDR/);
            if (m) return renderPipelineOutputNote('filter', `Statistical gate: <strong>${m[1]}</strong> matched hypotheses → <strong>${m[2]}</strong> pass the corrected threshold → proceed to ranking`);
            const m2 = content.match(/(\d+) matches.*?(\d+) fdr-significant/i);
            if (m2) return renderPipelineOutputNote('filter', `Statistical gate: <strong>${m2[1]}</strong> matches → <strong>${m2[2]}</strong> supported pathways advance`);
            return renderPipelineOutputNote('filter', content);
        }
        case 'stage4-start':
            return renderPipelineStageCard(3, 'running');
        case 'stage4-done':
            return renderPipelineOutputNote('check', content);
        case 'refinement-round':
            return renderRefinementRoundCard(content);
        case 'merge-step':
            return `<div class="ps-section-divider"><span>Merging &amp; Finalising All Iterations</span></div>`;
        case 'warn':
            return renderPipelineOutputNote('warn', content);
        default:
            return content;
    }
}

function addMessage(msg) {
    const div = document.createElement('div');

    // Collect category-level biological context for the lower-priority context panel.
    if (msg.data && msg.data.reasoning) {
        collectedReasoning.push({
            reasoning: msg.data.reasoning,
            category: msg.data.category || null,
            iteration: msg.data.iteration || 1
        });
    }

    if (typeof msg.content === 'string' && msg.type !== 'user') {
        msg = { ...msg, content: stripMessageGlyphs(msg.content) };
    }

    switch (msg.type) {
        case 'system':
            div.className = 'message message-system';
            div.innerHTML = renderSystemMessage(msg.content);
            break;

        case 'result':
            div.className = `message message-result`;
            div.innerHTML = renderResultMessage(msg);
            break;

        case 'checkpoint':
            div.className = `message message-checkpoint`;
            div.innerHTML = renderCheckpointMessage(msg);
            setupCheckpointHandlers(div, msg.data);
            break;

        case 'user':
            div.className = `message message-user`;
            div.innerHTML = msg.content;
            break;

        case 'error':
            div.className = `message message-error`;
            div.innerHTML = renderPipelineOutputNote('warn', msg.content);
            break;

        default:
            div.className = `message message-${msg.type}`;
            div.innerHTML = msg.content;
    }

    elements.chatMessages.appendChild(div);
}

// ============================================================================
// REASONING PATH RENDERING
// ============================================================================

/**
 * Render a collapsible reasoning panel (tigerai.bio inspired)
 */
function renderReasoningPanel(reasoning, category = null, iteration = null, options = {}) {
    if (!reasoning) return '';

    const notEmpty = (v) => v && v !== 'Not provided' && v !== 'N/A';
    const formatReasoningText = (value) => escapeHtml(sanitizeUserFacingAnalysisText(value))
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');
    const hasContent = notEmpty(reasoning.overall_strategy) || notEmpty(reasoning.strategy) ||
        notEmpty(reasoning.gene_analysis) ||
        notEmpty(reasoning.relevance_strength_with_disease);
    if (!hasContent) return '';

    const isRecordView = options.recordView === true;
    const isEmbeddedDatabaseView = options.embeddedDatabase === true;
    const panelId = `reasoning-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`;

    // Determine relevance level from the text
    let relevanceLevel = 'medium';
    const relevanceText = reasoning.relevance_strength_with_disease || '';
    const normalizedRelevance = relevanceText.replace(/\*/g, '').toLowerCase();
    if (normalizedRelevance.startsWith('high') ||
        /relevance[^.]{0,80}\bhigh\b/.test(normalizedRelevance)) {
        relevanceLevel = 'high';
    } else if (normalizedRelevance.startsWith('low') ||
        /relevance[^.]{0,80}\blow\b/.test(normalizedRelevance)) {
        relevanceLevel = 'low';
    }

    // Build category badge if provided
    const categoryBadge = category ?
        `<span class="reasoning-category-tag category-badge ${category.replace(':', '-')}">${category}</span>` : '';

    // Build iteration badge if provided
    const iterationBadge = iteration ?
        `<span class="iteration-badge">${iteration === 1 ? 'Initial Prompt' : 'Refined Prompt'}</span>` : '';

    const categoryNames = {
        'GO:BP': 'Biological Process',
        'GO:MF': 'Molecular Function',
        'GO:CC': 'Cellular Component',
        'KEGG': 'KEGG Pathway',
        'REAC': 'Reactome Pathway'
    };
    const categoryName = categoryNames[category] || category || 'Reasoning record';
    const recordHeader = `
        <div class="reasoning-record-header">
            <div>
                <span class="reasoning-record-eyebrow">Database record</span>
                <div class="reasoning-record-title">
                    ${categoryBadge}
                    <h3>${escapeHtml(categoryName)}</h3>
                </div>
                <p>Generation rationale and validation notes for this database. Pathway-level cell and tissue context appears with each ranked pathway.</p>
            </div>
            ${relevanceText ? `
                <span class="reasoning-record-relevance ${relevanceLevel}">
                    ${relevanceLevel === 'high' ? 'High relevance' : relevanceLevel === 'low' ? 'Low relevance' : 'Moderate relevance'}
                </span>` : ''}
        </div>`;

    let html = `
        <div class="reasoning-panel${isRecordView ? ' reasoning-panel--record expanded' : ''}${isEmbeddedDatabaseView ? ' reasoning-panel--embedded-database' : ''}" id="${panelId}">
            ${isRecordView && !isEmbeddedDatabaseView ? recordHeader : !isRecordView ? `
            <div class="reasoning-header" onclick="toggleReasoningPanel('${panelId}')">
                <div class="reasoning-header-left">
                    <span class="reasoning-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-clipboard-text"></use></svg></span>
                    <div>
                        <div class="reasoning-title">
                            ${categoryBadge}Database reasoning record${iterationBadge}
                        </div>
                        <div class="reasoning-subtitle">Generation rationale and validation notes</div>
                    </div>
                </div>
                <span class="reasoning-toggle"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg></span>
            </div>` : ''}
            ${isRecordView && !isEmbeddedDatabaseView ? `
            <details class="reasoning-full-record">
                <summary>
                    <span>
                        <strong>Method record</strong>
                        <small>Recorded biological context and validation feedback</small>
                    </span>
                    <span class="reasoning-full-record-toggle" aria-hidden="true"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg></span>
                </summary>` : ''}
            <div class="reasoning-content">
                <div class="reasoning-body">`;

    // Prefer the refined field when initial and feedback reasoning have been
    // consolidated into one reader-facing database record.
    const strategyText = reasoning.strategy || reasoning.overall_strategy;
    if (strategyText && strategyText !== 'Not provided' && strategyText !== 'N/A') {
        html += `
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-target"></use></svg></span>
                    Selection approach
                </div>
                <div class="reasoning-section-content strategy">${formatReasoningText(strategyText)}</div>
            </div>`;
    }

    // Gene Analysis (iteration 1)
    if (reasoning.gene_analysis && reasoning.gene_analysis !== 'Not provided' && reasoning.gene_analysis !== 'N/A') {
        html += `
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-flask"></use></svg></span>
                    Gene signals
                </div>
                <div class="reasoning-section-content gene-analysis">${formatReasoningText(reasoning.gene_analysis)}</div>
            </div>`;
    }

    // Database Focus (iteration 1)
    if (reasoning.database_focus && reasoning.database_focus !== 'Not provided' && reasoning.database_focus !== 'N/A') {
        html += `
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-database"></use></svg></span>
                    Database scope
                </div>
                <div class="reasoning-section-content database-focus">${formatReasoningText(reasoning.database_focus)}</div>
            </div>`;
    }

    // Key Gene Functions (iteration 1)
    if (reasoning.key_gene_functions && reasoning.key_gene_functions !== 'Not provided' && reasoning.key_gene_functions !== 'N/A') {
        html += `
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-key"></use></svg></span>
                    Key gene functions
                </div>
                <div class="reasoning-section-content key-gene-functions">${formatReasoningText(reasoning.key_gene_functions)}</div>
            </div>`;
    }

    // Pathway Selection Rationale (iteration 1)
    if (reasoning.pathway_selection_rationale && reasoning.pathway_selection_rationale !== 'Not provided' && reasoning.pathway_selection_rationale !== 'N/A') {
        html += `
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-path"></use></svg></span>
                    Selection rationale
                </div>
                <div class="reasoning-section-content pathway-rationale">${formatReasoningText(reasoning.pathway_selection_rationale)}</div>
            </div>`;
    }

    // Biological Evidence (iteration 1)
    if (reasoning.biological_evidence && reasoning.biological_evidence !== 'Not provided' && reasoning.biological_evidence !== 'N/A') {
        html += `
            <div class="reasoning-separator"></div>
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-book-open"></use></svg></span>
                    Biological support
                </div>
                <div class="reasoning-section-content biological-evidence">${formatReasoningText(reasoning.biological_evidence)}</div>
            </div>`;
    }

    // Learned from Validation Feedback (iter 1: learned_from_previous_iteration, iter 2: learned_from_feedback)
    const learnedText = reasoning.learned_from_feedback || reasoning.learned_from_previous_iteration;
    if (learnedText &&
        learnedText !== 'Not provided' &&
        learnedText !== 'N/A' &&
        !learnedText.includes('First iteration')) {
        html += `
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-books"></use></svg></span>
                    Validation feedback
                </div>
                <div class="reasoning-section-content learned">${formatReasoningText(learnedText)}</div>
            </div>`;
    }

    // Pathway Guidance
    if (reasoning.pathway_guidance &&
        reasoning.pathway_guidance !== 'Not provided' &&
        reasoning.pathway_guidance !== 'N/A') {
        html += `
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-compass"></use></svg></span>
                    Refinement guidance
                </div>
                <div class="reasoning-section-content">${formatReasoningText(reasoning.pathway_guidance)}</div>
            </div>`;
    }

    // Category Adjustments (iter 1: category_specific_adjustments, iter 2: category_adjustments)
    const categoryAdjText = reasoning.category_adjustments || reasoning.category_specific_adjustments;
    if (categoryAdjText &&
        categoryAdjText !== 'Not provided' &&
        categoryAdjText !== 'N/A') {
        html += `
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-chart-bar"></use></svg></span>
                    Database-specific adjustments
                </div>
                <div class="reasoning-section-content category-adjustments">${formatReasoningText(categoryAdjText)}</div>
            </div>`;
    }

    // Validation Reflection (Prompt Refinement pass 2+)
    if (reasoning.validation_reflection &&
        reasoning.validation_reflection !== 'Not provided' &&
        reasoning.validation_reflection !== 'N/A') {
        html += `
            <div class="reasoning-separator"></div>
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-microscope"></use></svg></span>
                    Validation review
                </div>
                <div class="reasoning-section-content validation">${formatReasoningText(reasoning.validation_reflection)}</div>
            </div>`;
    }

    // Failed Pathway Analysis
    if (reasoning.failure_analysis &&
        reasoning.failure_analysis !== 'Not provided' &&
        reasoning.failure_analysis !== 'N/A') {
        html += `
            <div class="reasoning-separator"></div>
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-warning"></use></svg></span>
                    Unsupported hypotheses
                </div>
                <div class="reasoning-section-content failure">${formatReasoningText(reasoning.failure_analysis)}</div>
            </div>`;
    }

    // Bottleneck Diagnosis
    if (reasoning.bottleneck_diagnosis &&
        reasoning.bottleneck_diagnosis !== 'Not provided' &&
        reasoning.bottleneck_diagnosis !== 'N/A') {
        html += `
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-magnifying-glass"></use></svg></span>
                    Coverage gaps
                </div>
                <div class="reasoning-section-content bottleneck">${formatReasoningText(reasoning.bottleneck_diagnosis)}</div>
            </div>`;
    }

    // Relevance Strength
    if (relevanceText && relevanceText !== 'Not provided' && relevanceText !== 'N/A') {
        const badgeIcon = relevanceLevel === 'high' ? phIcon('check') : (relevanceLevel === 'low' ? phIcon('x') : '~');
        html += `
            <div class="reasoning-separator"></div>
            <div class="reasoning-section">
                <div class="reasoning-section-header">
                    <span class="reasoning-section-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-link-simple"></use></svg></span>
                    Disease context
                </div>
                <div class="reasoning-section-content">
                    <span class="relevance-badge ${relevanceLevel}">
                        <span>${badgeIcon}</span>
                        ${relevanceLevel.toUpperCase()}
                    </span>
                    <p style="margin-top: 10px;">${formatReasoningText(relevanceText)}</p>
                </div>
            </div>`;
    }

    html += `
                </div>
            </div>
            ${isRecordView && !isEmbeddedDatabaseView ? '</details>' : ''}
        </div>`;

    return html;
}

/**
 * Toggle reasoning panel expand/collapse
 */
function toggleReasoningPanel(panelId) {
    const panel = document.getElementById(panelId);
    if (panel) {
        panel.classList.toggle('expanded');
    }
}

// Make toggle function globally accessible
window.toggleReasoningPanel = toggleReasoningPanel;

/**
 * Add accessible, independent expand/collapse controls to reasoning fields.
 * All long-form fields start collapsed; cell-type tags remain visible above.
 */
function enhanceReasoningSectionToggles(container) {
    if (!container) return;

    const sections = container.querySelectorAll('.reasoning-panel--record .reasoning-section');
    sections.forEach((section, index) => {
        const header = section.querySelector('.reasoning-section-header');
        const content = section.querySelector('.reasoning-section-content');
        if (!header || !content || header.dataset.toggleReady === 'true') return;

        const contentId = `reasoning-section-content-${index}-${Math.random().toString(36).slice(2, 7)}`;
        const isOpenByDefault = false;

        section.classList.add('reasoning-section--collapsible');
        section.classList.toggle('open', isOpenByDefault);
        header.dataset.toggleReady = 'true';
        header.setAttribute('role', 'button');
        header.setAttribute('tabindex', '0');
        header.setAttribute('aria-expanded', String(isOpenByDefault));
        header.setAttribute('aria-controls', contentId);
        content.id = contentId;

        const toggle = document.createElement('span');
        toggle.className = 'reasoning-section-toggle';
        toggle.setAttribute('aria-hidden', 'true');
        toggle.innerHTML = '<svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg>';
        header.appendChild(toggle);

        const toggleSection = () => {
            const isOpen = section.classList.toggle('open');
            header.setAttribute('aria-expanded', String(isOpen));
        };

        header.addEventListener('click', toggleSection);
        header.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                toggleSection();
            }
        });
    });
}

function renderResultMessage(msg) {
    let html = '';

    // Add reasoning panel if present
    if (msg.data && msg.data.reasoning) {
        html += renderReasoningPanel(
            msg.data.reasoning,
            msg.data.category || null,
            msg.data.iteration || null
        );
    }

    if (msg.data && msg.data.report) {
        html += `<div class="result-report">
            <h3><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-note-pencil"></use></svg> ${msg.content}</h3>
            <div class="report-preview">${formatMarkdown(msg.data.report)}</div>
        </div>`;
        return html;
    }

    if (msg.data && msg.data.pathways) {
        html += `<div>${msg.content}</div>${renderPathwayTable(msg.data.pathways)}`;
        return html;
    }

    // Enhanced QA response rendering with markdown and visual structure
    if (msg.data && msg.data.type === 'gpt_response') {
        const formattedContent = formatMarkdown(msg.content);
        html += `<div class="qa-response">
            <div class="qa-response-header">
                <span class="qa-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-dna"></use></svg></span>
                <span class="qa-title">Analysis response</span>
                <span class="qa-model-badge">${msg.data.model || 'GPT'}</span>
            </div>
            <div class="qa-response-body">
                ${formattedContent}
            </div>
        </div>`;
        return html;
    }

    // Default: Apply markdown formatting to plain text responses
    return html + formatMarkdown(msg.content);
}


function renderCheckpointMessage(msg) {
    const data = msg.data || {};
    const actions = data.actions || ['approve', 'skip'];
    const questions = data.suggested_questions || [];

    const questionEnabled = actions.includes('query');
    let html = `
        <div class="checkpoint-header">
            <span class="checkpoint-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-bell"></use></svg></span>
            <span class="checkpoint-title">${data.name || 'Checkpoint'}</span>
            ${questionEnabled ? '<span class="checkpoint-optional">Optional</span>' : ''}
        </div>
        <div class="checkpoint-description">${msg.content}</div>
        ${questionEnabled ? '<p class="checkpoint-guidance">If you are curious, ask one question. The analysis continues automatically after the answer.</p>' : ''}
    `;

    // Add pathway table preview if available
    if (data.pathways && data.pathways.length > 0) {
        const displayCount = data.pathways.length;
        const totalCount = data.total_pathways || displayCount;
        const countText = displayCount < totalCount
            ? `Showing top ${displayCount} of ${totalCount} pathways`
            : `Found ${displayCount} pathways`;
        html += `<div class="checkpoint-data">
            <strong>${countText}</strong>
            ${renderPathwayTable(data.pathways, totalCount)}
        </div>`;
    }

    // Add suggested questions (clickable to auto-submit)
    if (questions.length > 0) {
        html += `<div class="checkpoint-questions">
            <h4><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-lightbulb"></use></svg> Optional questions</h4>
            <ul>
                ${questions.map(q => `<li class="suggested-question clickable-question" data-question="${escapeHtml(q)}" onclick="selectAndSubmitQuestion(this)">
                    <span class="question-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-lightbulb"></use></svg></span> ${q}
                </li>`).join('')}
            </ul>
        </div>`;
    }

    // Add action buttons
    html += `<div class="checkpoint-actions">`;

    if (actions.includes('approve')) {
        html += `<button class="action-btn action-btn-approve" data-action="approve"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-check-circle"></use></svg> Approve</button>`;
    }
    if (actions.includes('modify')) {
        html += `<button class="action-btn action-btn-modify" data-action="modify"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-pencil-simple"></use></svg> Modify</button>`;
    }
    if (actions.includes('skip')) {
        html += `<button class="action-btn action-btn-skip" data-action="skip"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-skip-forward"></use></svg> ${questionEnabled ? 'Continue without a question' : 'Skip'}</button>`;
    }
    if (actions.includes('query')) {
        html += `<button class="action-btn action-btn-query" data-action="query"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-chat-circle"></use></svg> Ask a question</button>`;
    }
    if (actions.includes('quit')) {
        html += `<button class="action-btn action-btn-quit" data-action="quit"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-x-circle"></use></svg> Quit</button>`;
    }

    html += `</div>`;

    return html;
}

function setupCheckpointHandlers(container, data) {
    // Action buttons
    container.querySelectorAll('.action-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const action = btn.dataset.action;
            if (action === 'query') {
                showQueryPanel(true);
                elements.queryInput.focus();
                return;
            }
            handleCheckpointAction(action);
        });
    });

    // Suggested questions
    container.querySelectorAll('.suggested-question').forEach(item => {
        item.addEventListener('click', () => {
            const question = item.dataset.question;
            elements.queryInput.value = question;
            showQueryPanel(true);
            elements.queryInput.focus();
        });
    });
}

// ============================================================================
// CHECKPOINT ACTIONS
// ============================================================================

async function handleCheckpointAction(action) {
    if (!state.sessionId) return;

    showTyping(true);
    showQueryPanel(false);

    try {
        const response = await fetch(`/api/checkpoint/${state.sessionId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action })
        });

        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

    } catch (error) {
        console.error('Checkpoint action failed:', error);
        addMessage({ type: 'error', content: 'Action failed: ' + error.message });
    }
}

// ============================================================================
// QUERIES
// ============================================================================

function setQuerySubmissionState(pending) {
    elements.queryInput.disabled = pending;
    elements.querySubmit.disabled = pending;
    elements.querySubmit.setAttribute('aria-busy', String(pending));
    const label = elements.querySubmit.querySelector('span');
    if (label) label.textContent = pending ? 'Answering...' : 'Ask';
}

function markActiveCheckpointResolved() {
    const checkpoints = [...elements.chatMessages.querySelectorAll('.message-checkpoint')];
    const checkpoint = checkpoints.at(-1);
    if (!checkpoint || checkpoint.classList.contains('checkpoint-resolved')) return;

    checkpoint.classList.add('checkpoint-resolved');
    const actions = checkpoint.querySelector('.checkpoint-actions');
    if (!actions) return;
    actions.innerHTML = `
        <span class="checkpoint-resume-status" role="status">
            <svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-arrow-right"></use></svg>
            Question answered. Continuing analysis.
        </span>`;
}

async function submitQuery() {
    const query = elements.queryInput.value.trim();
    if (!query || !state.sessionId) return;
    const queryError = getBiomedicalTextError(query, 'Question');
    if (queryError) {
        showInputValidationError('query-input-error', queryError);
        elements.queryInput.focus();
        return;
    }
    showInputValidationError('query-input-error', '');

    elements.queryInput.value = '';
    showTyping(true);
    setQuerySubmissionState(true);

    try {
        const response = await fetch(`/api/query/${state.sessionId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query })
        });

        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // The response is added via polling. A successful checkpoint query
        // now advances the workflow without requiring a separate Skip click.
        if (data.auto_advanced) {
            showQueryPanel(false);
            markActiveCheckpointResolved();
            updateAnalysisProgress({
                percent: elements.analysisProgressBar?.value || 0,
                stage: 'Continuing analysis',
                detail: 'Question answered. Starting the next analysis step.',
                state: 'running',
            }, 'running', false);
            await pollProgress();
        } else {
            showTyping(false);
        }
        setQuerySubmissionState(false);

    } catch (error) {
        console.error('Query failed:', error);
        showTyping(false);
        setQuerySubmissionState(false);
        if (/biomedical research context|violent|threatening|unrelated instructions/i.test(error.message || '')) {
            showInputValidationError('query-input-error', error.message);
            elements.queryInput.value = query;
        } else {
            addMessage({ type: 'error', content: 'Query failed: ' + error.message });
        }
    }
}

/**
 * Global function to select and submit a suggested question
 * Called when user clicks on a suggested question in the checkpoint panel
 */
window.selectAndSubmitQuestion = function (element) {
    const question = element.getAttribute('data-question');
    if (!question) return;

    // Highlight the selected question
    document.querySelectorAll('.clickable-question').forEach(q => q.classList.remove('selected'));
    element.classList.add('selected');

    // Fill the query input and submit
    elements.queryInput.value = question;
    showQueryPanel(true);

    // Auto-submit after a brief delay to show the selection
    setTimeout(() => {
        submitQuery();
    }, 300);
};

// ============================================================================
// UI HELPERS
// ============================================================================

function showTyping(show) {
    elements.typingIndicator.classList.toggle('hidden', !show);
}

function showQueryPanel(show) {
    elements.queryPanel.classList.toggle('hidden', !show);
    if (show) {
        elements.queryInput.focus();
    }
}

// ============================================================================
// STANDALONE RESULTS VIEW
// ============================================================================

function getPathwayScore(pathway) {
    return Number(pathway?.gpt_score ?? pathway?.score ?? pathway?.evidence_score ?? 0);
}

function hydrateReasoningTraces(entries) {
    if (!Array.isArray(entries)) return;

    const restored = entries.map(entry => {
        if (entry?.reasoning) {
            return {
                reasoning: entry.reasoning,
                category: entry.category || null,
                iteration: entry.iteration || 1
            };
        }
        if (entry?.data?.reasoning) {
            return {
                reasoning: entry.data.reasoning,
                category: entry.data.category || null,
                iteration: entry.data.iteration || 1
            };
        }
        return null;
    }).filter(Boolean);

    if (restored.length === 0) return;

    collectedReasoning.length = 0;
    const seen = new Set();
    restored.forEach(entry => {
        const key = `${entry.iteration}|${entry.category || ''}|${JSON.stringify(entry.reasoning)}`;
        if (!seen.has(key)) {
            seen.add(key);
            collectedReasoning.push(entry);
        }
    });
}

function showResults(results) {
    if (!results) return;

    state.isAnalyzing = false;
    resetStartButton();

    // Store results globally for filtering
    currentResults = results;
    setReportView('summary');

    // Prepare data
    const disease = results.disease || document.getElementById('disease-input')?.value || elements.diseaseSelect.value || 'Disease';
    const geneCount = results.gene_count || parseGenes(elements.geneInput.value).length;
    const pathways = results.pathways || [];
    updateRetryNarrativesButton(pathways);

    // Update hero section
    if (elements.diseaseNameDisplay) elements.diseaseNameDisplay.textContent = disease;
    if (elements.geneCountDisplay) elements.geneCountDisplay.textContent = `${geneCount} genes`;
    const resultDate = results.completed_at || results.analysis_date || results.created_at;
    if (elements.analysisDate) {
        elements.analysisDate.textContent = resultDate
            ? new Date(resultDate).toLocaleDateString()
            : new Date().toLocaleDateString();
    }
    if (elements.modelVersion) {
        elements.modelVersion.textContent = results.model || 'GPT-5.1';
    }

    if (Array.isArray(results.reasoning_traces)) {
        hydrateReasoningTraces(results.reasoning_traces);
    }

    // Render overview summary (initial hypotheses vs statistically validated output)
    renderOverviewSummary(pathways, results);

    // Each database now owns its validated pathways, pathway interpretations,
    // and consolidated reasoning details in that order.
    renderEvidenceSectionsView(pathways);

    // Show results view, hide others
    elements.heroSection?.classList.add('hidden');
    elements.inputSection?.classList.add('hidden');
    elements.chatSection?.classList.add('hidden');
    document.getElementById('history-section').style.display = 'none';
    document.getElementById('docs-section').style.display = 'none';
    elements.resultsSection.classList.remove('hidden');
    document.body.classList.remove('analysis-running-view');
    document.body.classList.add('results-view');
    state.backgrounded = false;
    state.backgroundResults = null;
    updateActiveJobBanner();
    setActiveWorkflowStep('rank');

}

function hideResultsView() {
    document.body.classList.remove('analysis-running-view');
    document.body.classList.remove('results-view');
    elements.resultsSection.classList.add('hidden');
    elements.heroSection?.classList.remove('hidden');
    elements.inputSection?.classList.remove('hidden');
    elements.chatSection?.classList.add('hidden');
    setActiveWorkflowStep('input');
}

function renderMetricCards(pathways, results) {
    if (!elements.metricCards) return;

    // Databases that produced at least one validated pathway
    const DB_ORDER = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'];
    const activeDbs = DB_ORDER.filter(db =>
        pathways.some(p => (p.source || p.category || '').includes(db))
    );

    // PubMed references retrieved
    const litCount = pathways.reduce((total, pathway) => total + getPathwayPmids(pathway).length, 0);
    const driverGenes = new Set();
    pathways.forEach(pathway => getPathwayGenes(pathway).forEach(gene => driverGenes.add(gene)));
    const comparison = getValidationComparison(pathways, results);

    elements.metricCards.innerHTML = `
        <div class="metric-card">
            <div class="metric-card-header">
                <span class="metric-card-title">Validated pathways</span>
            </div>
            <div class="metric-card-value">${comparison.statisticallyValidated}</div>
            <div class="metric-card-subtitle">retained after multiple-testing correction</div>
        </div>
        <div class="metric-card">
            <div class="metric-card-header">
                <span class="metric-card-title">Databases represented</span>
            </div>
            <div class="metric-card-value">${activeDbs.length}<span class="metric-card-denom">/5</span></div>
            <div class="metric-card-subtitle metric-db-chips">${
                DB_ORDER.map(db => `<span class="metric-db-chip ${activeDbs.includes(db) ? 'active' : 'inactive'}">${db}</span>`).join('')
            }</div>
        </div>
        <div class="metric-card">
            <div class="metric-card-header">
                <span class="metric-card-title">Intersection genes</span>
            </div>
            <div class="metric-card-value">${driverGenes.size}</div>
            <div class="metric-card-subtitle">intersection genes carried into interpretation</div>
        </div>
        <div class="metric-card">
            <div class="metric-card-header">
                <span class="metric-card-title">Literature records</span>
            </div>
            <div class="metric-card-value">${litCount}</div>
            <div class="metric-card-subtitle">PubMed references via dynamic retrieval</div>
        </div>
    `;
}

function getValidationComparison(pathways, results) {
    const databaseOrder = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'];
    const supplied = results?.validation_comparison || {};
    const suppliedByDatabase = supplied.by_database || {};
    const outputByDatabase = {};
    databaseOrder.forEach(category => { outputByDatabase[category] = 0; });
    (pathways || []).forEach(pathway => {
        const source = pathway.source || pathway.category || '';
        const category = databaseOrder.find(candidate => source.includes(candidate));
        if (category) outputByDatabase[category] += 1;
    });

    const rawInitial = supplied.initial_hypotheses ?? results?.run_summary?.initial_hypotheses;
    const initialHypotheses = Number.isFinite(Number(rawInitial)) ? Number(rawInitial) : null;
    const rawValidated = supplied.statistically_validated ?? results?.run_summary?.significant_pathways;
    const statisticallyValidated = Number.isFinite(Number(rawValidated))
        ? Number(rawValidated)
        : (pathways || []).length;
    const rawMatchedHypotheses = supplied.matched_hypotheses;
    const matchedHypotheses = Number.isFinite(Number(rawMatchedHypotheses))
        ? Number(rawMatchedHypotheses)
        : null;
    const rawValidatedHypotheses = supplied.statistically_validated_hypotheses;
    const validatedHypotheses = Number.isFinite(Number(rawValidatedHypotheses))
        ? Number(rawValidatedHypotheses)
        : null;
    const rounds = Array.isArray(supplied.rounds)
        ? supplied.rounds.map((round, index) => {
            const generated = Number(round?.generated_hypotheses);
            const matched = Number(round?.matched_hypotheses);
            const validated = Number(round?.statistically_validated_hypotheses);
            const roundNumber = Number(round?.round) || index + 1;
            return {
                round: roundNumber,
                generatedHypotheses: Number.isFinite(generated) ? generated : null,
                matchedHypotheses: Number.isFinite(matched) ? matched : null,
                validatedHypotheses: Number.isFinite(validated) ? validated : null
            };
        })
        : [];

    const byDatabase = {};
    databaseOrder.forEach(category => {
        const record = suppliedByDatabase[category] || {};
        const rawCategoryInitial = record.initial_hypotheses ?? record.predicted;
        byDatabase[category] = {
            initialHypotheses: Number.isFinite(Number(rawCategoryInitial)) ? Number(rawCategoryInitial) : null,
            statisticallyValidated: Number.isFinite(Number(record.statistically_validated))
                ? Number(record.statistically_validated)
                : outputByDatabase[category]
        };
    });

    return {
        initialHypotheses,
        statisticallyValidated,
        matchedHypotheses,
        validatedHypotheses,
        rounds,
        byDatabase
    };
}

function getRunMappingSummary(pathways, results) {
    const supplied = results?.mapping_summary || results?.run_summary?.mapping_summary || {};
    const rawInput = supplied.input_count ?? results?.gene_count ?? results?.run_summary?.gene_count;
    const inputCount = Number.isFinite(Number(rawInput)) ? Number(rawInput) : 0;
    const pathwayQuerySizes = (pathways || [])
        .map(pathway => Number(pathway?.query_size))
        .filter(Number.isFinite);
    const inferredMapped = pathwayQuerySizes.length ? Math.max(...pathwayQuerySizes) : inputCount;
    const rawMapped = supplied.mapped_count
        ?? supplied.symbol_mapped_count
        ?? results?.run_summary?.mapped_gene_count
        ?? inferredMapped;
    const mappedCount = Math.max(0, Math.min(inputCount || Number(rawMapped) || 0, Number(rawMapped) || 0));
    const rawFailed = supplied.failed_count;
    const failedCount = Number.isFinite(Number(rawFailed))
        ? Number(rawFailed)
        : Math.max(inputCount - mappedCount, 0);
    return { inputCount, mappedCount, failedCount };
}

function getRunDiseaseContext(results) {
    const inputLabel = String(results?.disease_name || results?.disease || '').trim();
    const name = String(results?.disease_context?.name || inputLabel || 'Disease context').trim();
    const meshByDisease = {
        "alzheimer's disease": 'D000544',
        'ad': 'D000544',
        'inflammatory bowel disease': 'D015212',
        'ibd': 'D015212',
        "parkinson's disease": 'D010300',
        'pd': 'D010300',
        'multiple sclerosis': 'D009103',
        'ms': 'D009103',
        'amyotrophic lateral sclerosis': 'D000690',
        'als': 'D000690',
        'rheumatoid arthritis': 'D001172',
        'ra': 'D001172',
        'type 2 diabetes': 'D003924',
        't2d': 'D003924'
    };
    const meshId = String(
        results?.disease_context?.mesh_id
        || results?.run_summary?.disease_id
        || meshByDisease[name.toLowerCase()]
        || ''
    ).trim();
    const authorityId = String(
        results?.disease_context?.database_id
        || results?.disease_context?.open_targets_id
        || meshId
    ).trim().replace('_', ':');
    const openTargetsId = String(results?.disease_context?.open_targets_id || '').trim();
    const database = String(
        results?.disease_context?.database
        || (openTargetsId || /^MONDO:|^EFO:/i.test(authorityId) ? 'Open Targets' : (meshId ? 'NCBI MeSH' : ''))
    ).trim();
    const authorityUrl = String(results?.disease_context?.url || '').trim()
        || (openTargetsId
            ? `https://platform.opentargets.org/disease/${encodeURIComponent(openTargetsId)}/associations`
            : (meshId ? `https://meshb.nlm.nih.gov/record/ui?ui=${encodeURIComponent(meshId)}` : ''));
    return {
        name,
        inputLabel,
        database,
        databaseId: authorityId,
        meshId,
        url: authorityUrl
    };
}

function getRunCellTypes(pathways) {
    return getRunCellTypeFrequencies(pathways).map(entry => entry.label);
}

function getRunCellTypeFrequencies(pathways) {
    const total = (pathways || []).length;
    const counts = new Map();
    (pathways || []).forEach(pathway => {
        const pathwayLabels = new Set(extractCellTypeLabels(getPathwayCellContext(pathway)));
        pathwayLabels.forEach(label => counts.set(label, (counts.get(label) || 0) + 1));
    });
    const ontologyOrder = new Map(CELL_TYPE_PATTERNS.map(([label], index) => [label, index]));
    return [...counts.entries()]
        .map(([label, count]) => ({
            label,
            count,
            total,
            percent: total ? Math.round((count / total) * 100) : 0,
            order: ontologyOrder.get(label) ?? Number.MAX_SAFE_INTEGER
        }))
        .sort((a, b) => b.count - a.count || a.order - b.order || a.label.localeCompare(b.label));
}

function getUniqueLiteratureCount(pathways) {
    const pmids = new Set();
    (pathways || []).forEach(pathway => getPathwayPmids(pathway).forEach(pmid => pmids.add(pmid)));
    return pmids.size;
}

function renderSummaryRankedTable(pathways, databaseOrder) {
    const rows = [];
    databaseOrder.forEach(database => {
        const ranked = (pathways || [])
            .filter(pathway => (pathway.source || pathway.category || 'Other') === database)
            .sort((a, b) => Number(a.gpt_rank ?? Number.MAX_SAFE_INTEGER) - Number(b.gpt_rank ?? Number.MAX_SAFE_INTEGER));
        ranked.forEach((pathway, index) => {
            const rank = index + 1;
            const pathwayId = pathway.native || pathway.pathway_id || pathway.id || '';
            const name = pathway.name || pathway.pathway_name || 'Unnamed pathway';
            rows.push(`
                <tr data-export-rank="${rank}">
                    <td><span class="category-badge ${database.replace(':', '-')}">${escapeHtml(database)}</span></td>
                    <td>${pathwayId ? renderPathwayId(pathway) : '<span aria-label="Not available">NA</span>'}</td>
                    <td>${rank}</td>
                    <td><button type="button" class="summary-pathway-link" onclick="openSummaryPathway('${escapeHtml(database)}', ${rank})">${escapeHtml(name)}</button></td>
                    <td>${formatPValue(pathway.p_value ?? pathway.pvalue)}</td>
                </tr>`);
        });
    });
    return `
        <section class="summary-ranked-table-wrap" aria-labelledby="summary-ranked-table-title">
            <div class="source-profile-heading">
                <span id="summary-ranked-table-title">Validated pathway ranking</span>
                <strong>${rows.length} pathways</strong>
            </div>
            <div class="summary-ranked-table-scroll">
                <table class="summary-ranked-table">
                    <thead><tr><th>Database</th><th>ID</th><th>Rank</th><th>Pathway</th><th>Adjusted P-value</th></tr></thead>
                    <tbody>${rows.join('')}</tbody>
                </table>
            </div>
        </section>`;
}

window.openSummaryPathway = function (category, rank) {
    const item = [...document.querySelectorAll('details.evidence-item')].find(candidate =>
        candidate.dataset.category === category && Number(candidate.dataset.rank) === Number(rank)
    );
    if (!item) return;
    item.closest('.evidence-section')?.classList.add('open');
    item.open = true;
    item.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

function renderOverviewSummary(pathways, results) {
    const summaryEl = document.getElementById('summary-text');
    if (!summaryEl) return;

    const DB_ORDER = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'];
    const DB_LABELS = {
        'GO:BP': 'Biological Process',
        'GO:MF': 'Molecular Function',
        'GO:CC': 'Cellular Component',
        'KEGG': 'KEGG Pathway',
        'REAC': 'Reactome'
    };

    const comparison = getValidationComparison(pathways, results);
    const mapping = getRunMappingSummary(pathways, results);
    const diseaseContext = getRunDiseaseContext(results);
    const cellTypeFrequencies = getRunCellTypeFrequencies(pathways);
    const rankedCellTypes = cellTypeFrequencies.filter(entry => !NON_CELL_TYPE_CONTEXT_LABELS.has(entry.label));
    const topCellTypes = rankedCellTypes.slice(0, 5);
    const pathwaysWithCellContext = pathways.filter(pathway => getPathwayCellContext(pathway)).length;
    const databasesRepresented = DB_ORDER.filter(db => comparison.byDatabase[db].statisticallyValidated > 0).length;
    const initialDisplay = comparison.initialHypotheses === null ? 'Not available' : comparison.initialHypotheses;
    const sourceProfileMarkup = DB_ORDER.map(db => {
        const counts = comparison.byDatabase[db];
        const denominator = counts.initialHypotheses || comparison.initialHypotheses || 1;
        const retainedWidth = Math.max(4, Math.min(100, Math.round((counts.statisticallyValidated / denominator) * 100)));
        return `
            <div class="source-profile-card">
                <div class="source-profile-card-head">
                    <span class="category-badge ${db.replace(':', '-')}">${db}</span>
                    <strong>${counts.statisticallyValidated}</strong>
                </div>
                <span>${DB_LABELS[db] || db}</span>
                <small>${counts.initialHypotheses === null ? 'validated pathways' : `${counts.initialHypotheses} hypotheses tested`}</small>
                <i aria-hidden="true"><b style="width:${retainedWidth}%"></b></i>
            </div>`;
    }).join('');
    const inputAlias = diseaseContext.inputLabel && normalizeDiseaseSearchText(diseaseContext.inputLabel) !== normalizeDiseaseSearchText(diseaseContext.name)
        ? diseaseContext.inputLabel
        : '';

    summaryEl.innerHTML = `
      <div class="evidence-summary-match">
        <span>Disease match</span>
        <strong>${escapeHtml(diseaseContext.name)}</strong>
        ${diseaseContext.url
            ? `<a href="${escapeHtml(diseaseContext.url)}" target="_blank" rel="noopener">${escapeHtml(diseaseContext.database)} ${escapeHtml(diseaseContext.databaseId)} <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></a>`
            : '<small>Custom disease context</small>'}
        ${inputAlias ? `<small class="evidence-summary-alias">Input: ${escapeHtml(inputAlias)}</small>` : ''}
      </div>

      <div class="evidence-summary-strip">
        <div><strong>${mapping.mappedCount}<small> of ${mapping.inputCount}</small></strong><span>Recognized genes</span><small>${mapping.failedCount} unresolved</small></div>
        <div><strong>${initialDisplay}</strong><span>Initial hypotheses</span><small>prompt pass 1</small></div>
        <div class="evidence-summary-strip--highlight"><strong>${comparison.statisticallyValidated}</strong><span>Validated pathways</span><small>across ${databasesRepresented} databases</small></div>
        <div><strong>${pathwaysWithCellContext}<small> of ${comparison.statisticallyValidated}</small></strong><span>Pathways with cell context</span></div>
      </div>

      <div class="source-profile">
        <div class="source-profile-heading">
          <span>Validated pathways by database</span>
          <strong>${comparison.statisticallyValidated} pathways</strong>
        </div>
        <div class="source-profile-grid">${sourceProfileMarkup}</div>
      </div>

      ${renderSummaryRankedTable(pathways, DB_ORDER)}

      ${topCellTypes.length ? `
        <div class="summary-cell-context summary-cell-context--compact">
          <span class="summary-cell-context-label">Frequently mapped cell types</span>
          <div class="summary-cell-tags">${topCellTypes.map(entry => renderCellContextFrequencyLink(entry, '', true)).join('')}</div>
          <small class="summary-cell-frequency-note">Top ${topCellTypes.length} of ${rankedCellTypes.length} detected cell types. Counts show how many validated pathways contain each cell type.</small>
        </div>` : ''}
    `;
}

function renderLegacyEvidenceAssessment(results) {
    const panel = document.getElementById('evidence-assessment-panel');
    if (!panel) return;

    const assessment = results.evidence_assessment;
    if (!assessment) {
        const pathways = results.pathways || [];
        const fallback = computeLegacyClientSideAssessment(pathways, results);
        renderLegacyAssessmentData(fallback, results);
        return;
    }
    renderLegacyAssessmentData(assessment, results);
}

function computeLegacyClientSideAssessment(pathways, results) {
    if (!pathways || pathways.length === 0) {
        return {
            verdict: 'Insufficient', verdict_level: 0, ices_score: 0,
            category_scores: {
                hgc: { score: 0, label: 'Human Genetic Causality', abbr: 'HGC', count: 0, description: 'No data' },
                bio_coh: { score: 0, label: 'Biological Coherence', abbr: 'BIO_COH', count: 0, description: 'No data' },
                func_evidence: { score: 0, label: 'Functional Evidence', abbr: 'FUNC', count: 0, description: 'No data' },
                consistency: { score: 0, label: 'Cross-Study Consistency', abbr: 'CONS', count: 0, description: 'No data' }
            },
            summary_stats: { total_pathways: 0, significant_pathways: 0, gene_coverage: 0, literature_refs: 0, categories_covered: 0 }
        };
    }

    const cats = {};
    pathways.forEach(p => {
        const c = p.source || p.category || 'Other';
        if (!cats[c]) cats[c] = [];
        cats[c].push(p);
    });

    const avgS = items => {
        const s = items.map(p => p.gpt_score || p.score || 0);
        return s.length ? s.reduce((a, b) => a + b, 0) / s.length : 0;
    };
    const to6 = raw => Math.min(6, Math.round(raw / 100 * 6 * 10) / 10);

    const gobp = cats['GO:BP'] || [];
    const gomf = cats['GO:MF'] || [];
    const gocc = cats['GO:CC'] || [];
    const kegg = cats['KEGG'] || [];
    const reac = cats['REAC'] || [];

    const hgcItems = [...gobp, ...gomf];
    const bioItems = [...gobp, ...gocc];
    const funcItems = [...kegg, ...reac];

    let hgcScore = to6(avgS(hgcItems));
    const hgcSig = hgcItems.filter(p => (p.p_value || p.pvalue || 1) < 0.05).length;
    if (hgcSig >= 5) hgcScore = Math.min(6, Math.round((hgcScore + 0.5) * 10) / 10);

    let bioScore = to6(avgS(bioItems));
    if (bioItems.length >= 10) bioScore = Math.min(6, Math.round((bioScore + 0.3) * 10) / 10);

    let funcScore = to6(avgS(funcItems));
    if (funcItems.length >= 5) funcScore = Math.min(6, Math.round((funcScore + 0.3) * 10) / 10);

    const allScores = pathways.map(p => p.gpt_score || p.score || 0);
    let consScore = 0;
    if (allScores.length >= 3) {
        const mean = allScores.reduce((a, b) => a + b, 0) / allScores.length;
        const variance = allScores.reduce((a, s) => a + (s - mean) ** 2, 0) / allScores.length;
        const cv = mean > 0 ? Math.sqrt(variance) / mean : 1;
        consScore = Math.min(6, Math.round((1 - Math.min(cv, 1)) * 6 * 10) / 10);
    }

    const catsCovered = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'].filter(c => cats[c]).length;

    let ices = Math.round((hgcScore * 0.3 + bioScore * 0.25 + funcScore * 0.25 + consScore * 0.2) * 10) / 10;
    if (catsCovered >= 4) ices = Math.min(6, Math.round((ices + 0.3) * 10) / 10);

    let verdict, level;
    if (ices >= 5) { verdict = 'Very Strong'; level = 4; }
    else if (ices >= 4) { verdict = 'Strong'; level = 3; }
    else if (ices >= 3) { verdict = 'Moderate'; level = 2; }
    else if (ices >= 2) { verdict = 'Weak'; level = 1; }
    else { verdict = 'Insufficient'; level = 0; }

    const sigCount = pathways.filter(p => (p.p_value || p.pvalue || 1) < 0.05).length;

    let litRefs = 0;
    pathways.forEach(p => {
        if (p.pmids) litRefs += p.pmids.length;
        if (p.literature) litRefs += p.literature.length;
    });

    const desc = (name, score, count) => {
        if (score >= 5) return `Very strong ${name} with ${count} supporting pathways`;
        if (score >= 4) return `Strong ${name} supported by ${count} pathways`;
        if (score >= 3) return `Moderate ${name} from ${count} pathways`;
        if (score >= 2) return `Limited ${name} with ${count} pathways identified`;
        if (count > 0) return `Weak ${name} - ${count} pathways with low scores`;
        return `No ${name} available`;
    };

    return {
        verdict, verdict_level: level, ices_score: ices,
        category_scores: {
            hgc: { score: hgcScore, label: 'Human Genetic Causality', abbr: 'HGC', count: hgcItems.length, description: desc('genetic evidence', hgcScore, hgcItems.length) },
            bio_coh: { score: bioScore, label: 'Biological Coherence', abbr: 'BIO_COH', count: bioItems.length, description: desc('biological coherence', bioScore, bioItems.length) },
            func_evidence: { score: funcScore, label: 'Functional Evidence', abbr: 'FUNC', count: funcItems.length, description: desc('functional evidence', funcScore, funcItems.length) },
            consistency: { score: consScore, label: 'Cross-Study Consistency', abbr: 'CONS', count: pathways.length, description: desc('cross-study consistency', consScore, pathways.length) }
        },
        summary_stats: {
            total_pathways: pathways.length,
            significant_pathways: sigCount,
            gene_count: results.gene_count || 0,
            gene_coverage: 0,
            literature_refs: litRefs,
            categories_covered: catsCovered,
            top_pathway: pathways[0]?.name || pathways[0]?.pathway_name || 'N/A',
            strongest_category: Object.keys(cats).length > 0 ? Object.keys(cats).reduce((a, b) => avgS(cats[a]) > avgS(cats[b]) ? a : b) : 'N/A'
        }
    };
}

function renderLegacyAssessmentData(assessment, results) {
    const verdictColors = {
        'Insufficient': { bg: '#fef2f2', text: '#991b1b', border: '#fca5a5' },
        'Weak': { bg: '#fff8e8', text: '#8a5b18', border: '#e7c47d' },
        'Moderate': { bg: '#eff8f3', text: '#356b4d', border: '#8bc4a4' },
        'Strong': { bg: '#e8f5ee', text: '#236044', border: '#58ad7d' },
        'Very Strong': { bg: '#e3f3eb', text: '#164f36', border: '#349968' }
    };

    const verdictDescriptions = {
        'Insufficient': 'The current run does not contain enough validated pathway evidence for a stable interpretation.',
        'Weak': 'Some pathway support is present, but evidence strength or agreement remains limited.',
        'Moderate': 'Multiple validated signals converge, with important gaps that should remain visible in interpretation.',
        'Strong': 'Substantial pathway support is present across complementary databases and literature evidence.',
        'Very Strong': 'The workflow shows broad, coherent and consistently strong support across its evidence dimensions.'
    };

    const dimensionConfig = {
        hgc: {
            label: 'Gene-linked Support',
            abbr: 'HGC*',
            color: '#496c9b',
            categories: ['GO:BP', 'GO:MF']
        },
        bio_coh: {
            label: 'Biological Coherence',
            abbr: 'BIO_COH',
            color: '#3f8d66',
            categories: ['GO:BP', 'GO:CC']
        },
        func_evidence: {
            label: 'Functional Pathway Evidence',
            abbr: 'FUNC',
            color: '#ba7a28',
            categories: ['KEGG', 'REAC']
        },
        consistency: {
            label: 'Cross-Database Consistency',
            abbr: 'CONS',
            color: '#6b5b95',
            categories: ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
        }
    };

    const badge = document.getElementById('verdict-badge');
    const descEl = document.getElementById('verdict-description');
    const vc = verdictColors[assessment.verdict] || verdictColors['Insufficient'];
    if (badge) {
        badge.textContent = assessment.verdict;
        badge.style.background = vc.bg;
        badge.style.color = vc.text;
        badge.style.borderColor = vc.border;
    }
    if (descEl) descEl.textContent = verdictDescriptions[assessment.verdict] || '';

    const pathways = results.pathways || [];
    const dimensions = Object.entries(assessment.category_scores || {}).map(([key, category]) => {
        const config = dimensionConfig[key] || {
            label: category.label || key,
            abbr: category.abbr || key.toUpperCase(),
            color: '#5b6472',
            categories: []
        };
        return {
            key,
            ...config,
            score: Number(category.score || 0),
            count: category.count || 0,
            description: category.description || ''
        };
    });

    const scoreStrip = document.getElementById('evidence-score-strip');
    if (scoreStrip) {
        const scoreCards = dimensions.concat([{
            key: 'ices',
            label: 'Integrated Evidence Score',
            abbr: 'ICES',
            color: '#2f6e8c',
            score: Number(assessment.ices_score || 0)
        }]);

        scoreStrip.innerHTML = scoreCards.map(item => {
            const pct = Math.max(0, Math.min(100, (item.score / 6) * 100));
            return `
                <div class="evidence-score-card ${item.key === 'ices' ? 'evidence-score-card--primary' : ''}">
                    <span class="evidence-score-abbr">${escapeHtml(item.abbr)}</span>
                    <strong class="evidence-score-value">${item.score.toFixed(1)}</strong>
                    <span class="evidence-score-label">${escapeHtml(item.label)}</span>
                    <span class="evidence-score-meter" aria-hidden="true">
                        <span style="width:${pct}%; background:${item.color}"></span>
                    </span>
                </div>
            `;
        }).join('');
    }

    const dimensionContainer = document.getElementById('evidence-dimensions');
    if (dimensionContainer) {
        dimensionContainer.innerHTML = dimensions.map((dimension, index) => {
            const supporting = pathways
                .filter(pathway => {
                    const category = pathway.source || pathway.category || '';
                    return dimension.categories.some(candidate => category.includes(candidate));
                })
                .sort((a, b) => getPathwayScore(b) - getPathwayScore(a))
                .slice(0, 4);

            return `
                <details class="evidence-dimension" ${index === 0 ? 'open' : ''}>
                    <summary>
                        <span class="dimension-title">
                            <span class="dimension-dot" style="background:${dimension.color}"></span>
                            <span>
                                <strong>${escapeHtml(dimension.label)}</strong>
                                <small>${escapeHtml(dimension.abbr)}, ${dimension.count} supporting pathways</small>
                            </span>
                        </span>
                        <span class="dimension-score">${dimension.score.toFixed(1)}<small>/6</small></span>
                    </summary>
                    <div class="dimension-body">
                        <p>${escapeHtml(dimension.description)}</p>
                        <div class="dimension-pathways">
                            ${supporting.length > 0
                                ? supporting.map(pathway => `
                                    <span class="dimension-pathway-chip">
                                        ${renderPathwayNameLink(pathway, pathway.name || pathway.pathway_name || 'Unknown')}
                                        ${renderPathwayId(pathway)}
                                    </span>
                                `).join('')
                                : '<span class="dimension-empty">No supporting pathways in this dimension</span>'
                            }
                        </div>
                    </div>
                </details>
            `;
        }).join('');
    }

    const stats = assessment.summary_stats || {};
    const metaContainer = document.getElementById('analysis-metadata');
    if (metaContainer) {
        const coverageItems = [
            { value: stats.significant_pathways || 0, label: 'Statistically validated pathways' },
            { value: `${stats.categories_covered || 0}/5`, label: 'Databases represented' },
            { value: stats.literature_refs || 0, label: 'Literature records' },
            { value: stats.gene_coverage ? `${stats.gene_coverage}%` : (stats.gene_count || results.gene_count || 0), label: stats.gene_coverage ? 'Gene coverage' : 'Genes analyzed' },
            { value: stats.strongest_category || 'N/A', label: 'Strongest database' },
            { value: pathways.filter(pathway => getPathwayPmids(pathway).length > 0).length, label: 'Pathways with citations' }
        ];

        metaContainer.innerHTML = `
            <div class="coverage-grid">
                ${coverageItems.map(item => `
                    <div class="coverage-item">
                        <strong>${escapeHtml(String(item.value))}</strong>
                        <span>${escapeHtml(item.label)}</span>
                    </div>
                `).join('')}
            </div>
        `;
    }

    const summaryNote = document.getElementById('evidence-summary-note');
    if (summaryNote) {
        const bestPathway = pathways.reduce(
            (best, pathway) => getPathwayScore(pathway) > getPathwayScore(best) ? pathway : best,
            pathways[0] || {}
        );
        const bestName = bestPathway.name || bestPathway.pathway_name || 'No pathway';
        summaryNote.innerHTML = `
            <span class="summary-note-label">Run synthesis</span>
            <p>
                <strong>${stats.significant_pathways || pathways.length} validated pathways</strong>
                span ${stats.categories_covered || 0} databases.
                The highest evidence score belongs to
                <strong>${escapeHtml(bestName)}</strong>
                (${getPathwayScore(bestPathway).toFixed(1)}/100).
            </p>
            <span class="summary-note-source">Pathway hypothesis → statistical validation → literature-supported interpretation</span>
        `;
    }
}

function getLatestReasoningRecords() {
    const databaseOrder = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'];
    const latestByDatabase = new Map();

    collectedReasoning.forEach(entry => {
        if (!entry?.reasoning || !entry?.category) return;
        const current = latestByDatabase.get(entry.category);
        if (!current || Number(entry.iteration || 1) >= Number(current.iteration || 1)) {
            latestByDatabase.set(entry.category, entry);
        }
    });

    return databaseOrder
        .map(category => latestByDatabase.get(category))
        .filter(Boolean);
}

function sanitizeUserFacingAnalysisText(value) {
    return String(value ?? '')
        .replace(/g:Profiler/gi, 'functional enrichment')
        .replace(/FDR-adjusted P-value/gi, 'adjusted P-value')
        .replace(/FDR-controlled enrichment/gi, 'multiple-testing-corrected enrichment')
        .replace(/FDR-significant/gi, 'statistically supported')
        .replace(/\bscientific reviewers?\b/gi, 'research users')
        .replace(/\breviewers?\b/gi, 'users')
        .replace(/\bmanuscript\b/gi, 'analysis')
        .replace(/\bpaper-level\b/gi, 'analysis-level');
}

function normalizeReasoningText(value) {
    if (value == null) return '';
    if (typeof value === 'string') return sanitizeUserFacingAnalysisText(value).trim();
    if (Array.isArray(value)) return value.map(normalizeReasoningText).filter(Boolean).join(' ');
    if (typeof value === 'object') {
        return Object.entries(value)
            .map(([key, item]) => `${key.replace(/_/g, ' ')}: ${normalizeReasoningText(item)}`)
            .filter(Boolean)
            .join(' ');
    }
    return String(value);
}

function getReasoningField(reasoning, fieldName) {
    if (!reasoning || typeof reasoning !== 'object') return '';
    const exact = reasoning[fieldName];
    if (exact != null) return normalizeReasoningText(exact);
    const matchedKey = Object.keys(reasoning).find(key => key.startsWith(fieldName));
    return matchedKey ? normalizeReasoningText(reasoning[matchedKey]) : '';
}

function getDiseaseRelevanceLabel(reasoning) {
    const raw = getReasoningField(reasoning, 'relevance_strength_with_disease');
    const match = raw.match(/\b(high|medium|low)\b/i);
    if (!match) return 'Interpreted';
    return `${match[1][0].toUpperCase()}${match[1].slice(1).toLowerCase()} relevance`;
}

function computeCurrentRunSummary(pathways, results) {
    const databaseOrder = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'];
    const databaseGroups = {};
    pathways.forEach(pathway => {
        const category = pathway.source || pathway.category || 'Other';
        if (!databaseGroups[category]) databaseGroups[category] = [];
        databaseGroups[category].push(pathway);
    });

    const fdrSignificant = pathways.filter(pathway => {
        const value = Number(pathway.p_value ?? pathway.pvalue);
        return Number.isFinite(value) && value < 0.05;
    });
    const rankablePathways = fdrSignificant.length > 0 ? fdrSignificant : pathways;
    const activeDatabases = databaseOrder.filter(category => databaseGroups[category]?.length);
    const literatureRecords = rankablePathways.reduce(
        (total, pathway) => total + getPathwayPmids(pathway).length,
        0
    );
    const reasoningRecords = getLatestReasoningRecords();
    const driverGenes = [];
    rankablePathways.forEach(pathway => {
        getPathwayGenes(pathway).forEach(gene => {
            if (!driverGenes.includes(gene)) driverGenes.push(gene);
        });
    });

    const supplied = results.run_summary || {};
    const suppliedStatus = String(supplied.validation_status || '')
        .replace(/FDR-validated/gi, 'Statistically validated')
        .replace(/No validated pathways/gi, 'No statistically validated pathways');
    return {
        validation_status: suppliedStatus || (fdrSignificant.length > 0 ? 'Statistically validated' : 'No statistically validated pathways'),
        significant_pathways: supplied.significant_pathways ?? fdrSignificant.length,
        total_pathways: supplied.total_pathways ?? pathways.length,
        categories_covered: supplied.categories_covered ?? activeDatabases.length,
        literature_records: supplied.literature_records ?? literatureRecords,
        gene_count: supplied.gene_count ?? results.gene_count ?? 0,
        reasoning_records: reasoningRecords,
        driver_genes: driverGenes,
        feedback_available: collectedReasoning.some(entry => Number(entry?.iteration || 1) > 1)
    };
}

function renderEvidenceAssessment(results) {
    const pathways = results.pathways || [];
    const summary = computeCurrentRunSummary(pathways, results);
    const hasValidatedOutput = summary.significant_pathways > 0;

    const badge = document.getElementById('verdict-badge');
    const description = document.getElementById('verdict-description');
    if (badge) {
        badge.textContent = summary.validation_status;
        badge.style.background = hasValidatedOutput ? '#e8f5ee' : '#fef2f2';
        badge.style.color = hasValidatedOutput ? '#236044' : '#991b1b';
        badge.style.borderColor = hasValidatedOutput ? '#58ad7d' : '#fca5a5';
    }
    if (description) {
        description.textContent = hasValidatedOutput
            ? `${summary.significant_pathways} statistically validated pathways are available for this gene-disease context.`
            : 'No statistically validated pathway is available for this run.';
    }

    const summaryNote = document.getElementById('evidence-summary-note');
    if (summaryNote) {
        summaryNote.innerHTML = `
            <span class="summary-note-label">Run synthesis</span>
            <p>
                <strong>${summary.significant_pathways} statistically validated pathways</strong>
                across ${summary.categories_covered}/5 database channels, supported by
                ${summary.literature_records} linked PubMed records.
            </p>
        `;
    }

    const outputLayers = [
        {
            code: 'VALIDATION',
            value: summary.significant_pathways,
            label: 'statistically validated pathways',
            detail: `${summary.categories_covered}/5 databases represented`
        },
        {
            code: 'BIOLOGICAL INTERPRETATION',
            value: `${summary.categories_covered}/5`,
            label: 'database channels interpreted',
            detail: `${summary.reasoning_records.length} structured interpretation records`
        },
        {
            code: 'LITERATURE',
            value: summary.literature_records,
            label: 'PubMed records',
            detail: 'Linked pathway-disease evidence'
        }
    ];

    const layerContainer = document.getElementById('evidence-score-strip');
    if (layerContainer) {
        layerContainer.innerHTML = outputLayers.map(layer => `
            <div class="evidence-score-card">
                <span class="evidence-score-abbr">${escapeHtml(layer.code)}</span>
                <strong class="evidence-score-value">${escapeHtml(String(layer.value))}</strong>
                <span class="evidence-score-label">${escapeHtml(layer.label)}</span>
                <span class="output-layer-detail">${escapeHtml(layer.detail)}</span>
            </div>
        `).join('');
    }

    const interpretationContainer = document.getElementById('evidence-dimensions');
    if (interpretationContainer) {
        if (summary.reasoning_records.length === 0) {
            interpretationContainer.innerHTML = `
                <div class="dimension-empty">
                    Biological interpretation records were not persisted for this run.
                    Validated pathways and source evidence remain available below.
                </div>
            `;
        } else {
            interpretationContainer.innerHTML = summary.reasoning_records.map((entry, index) => {
                const reasoning = entry.reasoning || {};
                const geneFunctions = getReasoningField(reasoning, 'key_gene_functions') || getReasoningField(reasoning, 'gene_analysis');
                const mechanism = getReasoningField(reasoning, 'pathway_selection_rationale') || getReasoningField(reasoning, 'biological_evidence');
                const relevance = getDiseaseRelevanceLabel(reasoning);

                return `
                    <details class="evidence-dimension" ${index === 0 ? 'open' : ''}>
                        <summary>
                            <span class="dimension-title">
                                <span class="dimension-dot"></span>
                                <span>
                                    <strong>${escapeHtml(entry.category)}</strong>
                                    <small>Interpretation record, ${escapeHtml(relevance)}</small>
                                </span>
                            </span>
                            <span class="dimension-record-pass">Prompt ${Number(entry.iteration || 1)}</span>
                        </summary>
                        <div class="dimension-body structured-record-body">
                            <div class="structured-field">
                                <strong>Driver genes and functions</strong>
                                <p>${escapeHtml(truncateText(geneFunctions || 'Not available in this record.', 430))}</p>
                            </div>
                            <div class="structured-field">
                                <strong>Mechanistic theme and selection rationale</strong>
                                <p>${escapeHtml(truncateText(mechanism || 'Not available in this record.', 430))}</p>
                            </div>
                        </div>
                    </details>
                `;
            }).join('');
        }
    }

    const metadataContainer = document.getElementById('analysis-metadata');
    if (metadataContainer) {
        const coverageItems = [
            { value: summary.significant_pathways, label: 'Statistically validated pathways' },
            { value: `${summary.categories_covered}/5`, label: 'Databases represented' },
            { value: summary.literature_records, label: 'PubMed records' },
            { value: summary.gene_count, label: 'Genes analyzed' },
            { value: summary.driver_genes.length, label: 'Pathway-linked genes represented' },
            { value: summary.feedback_available ? '2 passes' : '1 pass', label: 'Generation mode' }
        ];

        metadataContainer.innerHTML = `
            <div class="coverage-grid">
                ${coverageItems.map(item => `
                    <div class="coverage-item">
                        <strong>${escapeHtml(String(item.value))}</strong>
                        <span>${escapeHtml(item.label)}</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
}

function getPathwayPmids(pathway) {
    const pmids = [];
    const add = value => {
        const normalized = String(value || '').replace(/\D/g, '');
        if (normalized && !pmids.includes(normalized)) pmids.push(normalized);
    };

    if (Array.isArray(pathway?.pmids)) pathway.pmids.forEach(add);
    if (Array.isArray(pathway?.literature)) {
        pathway.literature.forEach(item => add(typeof item === 'object' ? item.pmid : item));
    }

    const description = pathway?.description || pathway?.reasoning || '';
    const matches = String(description).match(/PMID[:\s]?(\d+)/gi) || [];
    matches.forEach(add);
    return pmids;
}

function getPathwayLiteratureRecords(pathway) {
    const records = new Map();
    (Array.isArray(pathway?.literature) ? pathway.literature : []).forEach(item => {
        const rawPmid = typeof item === 'object' ? item?.pmid || item?.PMID : item;
        const pmid = String(rawPmid || '').replace(/\D/g, '');
        if (!pmid || records.has(pmid)) return;
        records.set(pmid, {
            pmid,
            title: typeof item === 'object' ? String(item?.title || '').trim() : '',
            journal: typeof item === 'object' ? String(item?.journal || '').trim() : '',
            year: typeof item === 'object' ? String(item?.year || '').trim() : ''
        });
    });
    getPathwayPmids(pathway).forEach(pmid => {
        if (!records.has(pmid)) records.set(pmid, { pmid, title: '', journal: '', year: '' });
    });
    return [...records.values()];
}

function selectRelatedLiterature(records, evidenceText, fallbackIndex = 0, limit = 1) {
    if (!records.length) return [];
    const ignored = new Set([
        'about', 'after', 'alzheimer', 'alzheimer\'s', 'among', 'associated', 'context',
        'disease', 'evidence', 'from', 'into', 'most', 'pathway', 'process', 'related',
        'relevant', 'support', 'that', 'their', 'these', 'this', 'through', 'where', 'with'
    ]);
    const tokens = new Set(
        String(evidenceText || '').toLowerCase().match(/[a-zβ][a-z0-9β+-]{3,}/g) || []
    );
    const scored = records.map((record, index) => {
        const titleTokens = String(record.title || '').toLowerCase().match(/[a-zβ][a-z0-9β+-]{3,}/g) || [];
        const score = titleTokens.reduce(
            (total, token) => total + (!ignored.has(token) && tokens.has(token) ? 1 : 0),
            0
        );
        return { record, index, score };
    }).sort((a, b) => b.score - a.score || a.index - b.index);
    const selected = scored.filter(item => item.score > 0).slice(0, limit).map(item => item.record);
    for (let offset = 0; selected.length < limit && offset < records.length; offset += 1) {
        const candidate = records[(fallbackIndex + offset) % records.length];
        if (!selected.some(record => record.pmid === candidate.pmid)) selected.push(candidate);
    }
    return selected;
}

function renderInlineEvidenceLiterature(records) {
    if (!records.length) return '';
    return `
        <div class="interpretation-literature-links">
            <span>Literature support</span>
            ${records.map(record => `
                <a href="https://pubmed.ncbi.nlm.nih.gov/${record.pmid}/"
                   target="_blank" rel="noopener"
                   title="${escapeHtml(record.title || `PubMed ${record.pmid}`)}">PMID:${record.pmid} <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></a>`).join('')}
        </div>`;
}

function getLiteratureRecordDomId(evidenceScopeId, pmid) {
    const normalizedPmid = String(pmid || '').replace(/\D/g, '');
    return evidenceScopeId && normalizedPmid
        ? `${evidenceScopeId}-literature-${normalizedPmid}`
        : '';
}

function renderLiteratureRecord(record, evidenceScopeId = '') {
    const metadata = [record.year, record.journal].filter(Boolean).join(', ');
    const recordId = getLiteratureRecordDomId(evidenceScopeId, record.pmid);
    return `
        <a class="evidence-literature-record"
           ${recordId ? `id="${escapeHtml(recordId)}"` : ''}
           data-pmid="${escapeHtml(record.pmid)}"
           href="https://pubmed.ncbi.nlm.nih.gov/${record.pmid}/"
           target="_blank" rel="noopener">
            <strong>${escapeHtml(record.title || `PubMed record ${record.pmid}`)}</strong>
            <span>PMID:${record.pmid}${metadata ? `, ${escapeHtml(metadata)}` : ''} <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></span>
        </a>`;
}

function normalizePathwayGeneList(value) {
    const values = Array.isArray(value)
        ? value
        : (typeof value === 'string' && /[A-Za-z]/.test(value) ? value.split(/[,;|/\s]+/) : []);
    return values
        .map(item => String(item || '').trim().toUpperCase())
        .filter(item => /[A-Z]/.test(item))
        .filter((item, index, items) => items.indexOf(item) === index);
}

function getCurrentInputGeneSymbolSet() {
    const resultInputs = currentResults?.input_genes || currentResults?.query_genes || [];
    const resultValues = Array.isArray(resultInputs) ? resultInputs : String(resultInputs || '').split(/[,;\s]+/);
    const fieldValues = parseGenes(elements.geneInput?.value || '');
    const symbols = [...resultValues, ...fieldValues]
        .map(value => String(value || '').trim().toUpperCase())
        .filter(value => /^[A-Z][A-Z0-9-]*$/.test(value))
        .filter(value => !/^ENSG\d+(?:\.\d+)?$/i.test(value));
    return new Set(symbols);
}

function extractInterpretationGeneSymbols(pathway) {
    const description = String(
        pathway?.disease_interpretation || pathway?.description || pathway?.reasoning || ''
    );
    if (!description) return [];

    // Historical records did not persist g:Profiler intersections. This
    // fallback tolerates phrases such as "such as", "often include" and
    // "in this pathway (e.g., ...)" without treating the periods in e.g. as
    // the end of the gene list.
    const marker = /key\s+(?:driver|contributing)\s+genes?[\s\S]{0,140}?(?:such\s+as|(?:often\s+|typically\s+)?include(?:s|d|ing)?|e\s*\.\s*g\s*\.?\s*,?|:)\s*/i;
    const markerMatch = marker.exec(description);
    if (!markerMatch) return [];

    const remainder = description.slice(markerMatch.index + markerMatch[0].length);
    const segment = remainder.match(
        /^([\s\S]{0,360}?)(?=\.\s+(?:The|This|These|Such|Its|Their|Together|In|Mechanistically|Functionally)\b|\n|$)/i
    )?.[1] || remainder.slice(0, 360);
    const excluded = new Set([
        'AD', 'FDR', 'GO', 'GPT', 'CNS', 'RNA', 'DNA', 'ROS', 'PMID',
        'KEGG', 'REAC', 'BP', 'MF', 'CC', 'APPROVED'
    ]);
    const candidates = (segment.match(/\b[A-Z][A-Z0-9-]{1,14}\b/g) || [])
        .filter(gene => !excluded.has(gene))
        .filter((gene, index, genes) => genes.indexOf(gene) === index);

    // If the current input uses HGNC symbols, never display a narrative gene
    // that is absent from that input list. Ensembl-only historical inputs
    // cannot be reconciled client-side and remain clearly labelled as a
    // narrative fallback rather than an enrichment intersection.
    const inputSymbols = getCurrentInputGeneSymbolSet();
    return inputSymbols.size > 0
        ? candidates.filter(gene => inputSymbols.has(gene))
        : candidates;
}

function getPathwayGeneEvidence(pathway) {
    const explicitIntersections = normalizePathwayGeneList(
        pathway?.intersection_gene_symbols || pathway?.intersection_genes || pathway?.intersections
    );
    if (explicitIntersections.length > 0) {
        const isReplaySnapshot = pathway?.enrichment_source === 'g:Profiler replay snapshot';
        return {
            genes: explicitIntersections,
            source: 'gprofiler-intersection',
            label: 'Intersection genes',
            note: isReplaySnapshot
                ? 'Exact query-term intersection regenerated from the archived input using the bundled enrichment snapshot.'
                : 'Input genes annotated to this pathway in the enrichment result.'
        };
    }

    const legacyIntersections = normalizePathwayGeneList(pathway?.genes);
    if (legacyIntersections.length > 0) {
        return {
            genes: legacyIntersections,
            source: 'legacy-intersection',
            label: 'Intersection genes',
            note: 'Structured pathway-input overlap retained by a legacy result.'
        };
    }

    const mentionedGenes = extractInterpretationGeneSymbols(pathway);
    return {
        genes: mentionedGenes,
        source: mentionedGenes.length > 0 ? 'interpretation-fallback' : 'unavailable',
        label: mentionedGenes.length > 0 ? 'Genes mentioned in interpretation' : 'Intersection genes',
        note: mentionedGenes.length > 0
            ? 'Historical fallback extracted from narrative text; not treated as a statistical intersection.'
            : 'No structured query-term intersection was stored for this result.'
    };
}

function getPathwayGenes(pathway) {
    return getPathwayGeneEvidence(pathway).genes;
}

function cleanDescriptionText(description) {
    const cleaned = String(description || '')
        .replace(/\[PMID[:\s]?\d+(?:,\s*PMID[:\s]?\d+)*\]/gi, '')
        .replace(/\[GOC:[^\]]+\]/gi, '')
        .trim();
    return cleaned
        .replace(/^["“”]+\s*/, '')
        .replace(/\s*["“”]+$/, '')
        .trim();
}

function cleanEvidenceDescription(pathway) {
    const hasDedicatedInterpretation = Object.prototype.hasOwnProperty.call(pathway || {}, 'disease_interpretation');
    const description = hasDedicatedInterpretation
        ? pathway?.disease_interpretation
        : (pathway?.description || pathway?.reasoning || '');
    return cleanDescriptionText(description);
}

function getDiseaseInterpretationPoints(pathway) {
    const structured = Array.isArray(pathway?.interpretation_points)
        ? pathway.interpretation_points
            .filter(point => point && point.text && !/^cell(?:\s*\/\s*tissue)?\s+context$/i.test(String(point.label || '').trim()))
            .map(point => ({
                label: String(point.label || 'Biological interpretation').trim(),
                text: cleanDescriptionText(point.text)
            }))
        : [];
    if (structured.length) return structured;

    const narrative = cleanEvidenceDescription(pathway);
    if (narrative) {
        // Labels may open a line or follow the previous statement inline. Splitting
        // on newlines alone collapsed a four-part interpretation into one block.
        const LABELS = /(?:^|[\r\n]|(?<=[.;!?])\s+)\s*(?:\*\*)?(Pathway description|Biological context|Intersection[-\s]gene interpretation|Gene-level support|Disease pathology(?: and relevance)?|Disease relevance|PubMed literature synthesis|Cell(?:\s*\/\s*tissue)?\s*context)(?:\*\*)?\s*:\s*/gi;
        const hits = [...narrative.matchAll(LABELS)];
        const labeled = [];
        if (hits.length && hits[0].index > 0) {
            const preamble = narrative.slice(0, hits[0].index).trim();
            if (preamble) labeled.push({ label: 'Disease pathology and relevance', text: preamble });
        }
        hits.forEach((hit, index) => {
            const start = hit.index + hit[0].length;
            const end = index + 1 < hits.length ? hits[index + 1].index : narrative.length;
            const text = narrative.slice(start, end).trim();
            if (text) labeled.push({ label: hit[1].trim(), text });
        });
        const filtered = labeled.filter(point => !/^cell(?:\s*\/\s*tissue)?\s*context$/i.test(point.label));
        if (filtered.length >= 2) return filtered;
        return [{ label: 'Biological interpretation', text: narrative }];
    }

    const name = pathway?.name || pathway?.pathway_name || 'This pathway';
    const disease = currentResults?.disease_context?.name
        || currentResults?.disease_name
        || currentResults?.disease
        || 'the selected disease';
    const genes = getPathwayGeneEvidence(pathway).genes;
    const shownGenes = genes.slice(0, 10);
    const geneText = shownGenes.length
        ? `${shownGenes.join(', ')}${genes.length > shownGenes.length ? ` and ${genes.length - shownGenes.length} additional intersection genes` : ''}`
        : 'No structured intersection genes were retained for this result';
    return [
        {
            label: 'Biological context',
            text: getPathwayIntroduction(pathway)
        },
        {
            label: 'Gene-level support',
            text: shownGenes.length
                ? `The submitted gene set maps to this term through ${geneText}.`
                : geneText + '.'
        },
        {
            label: 'Disease relevance',
            text: `${name} is prioritized for biological review in ${disease}.`
        }
    ];
}

function getPathwayCellContext(pathway) {
    const explicit = cleanDescriptionText(
        pathway?.cell_context || pathway?.pathway_cell_context || ''
    );
    if (explicit && !/^not resolved\b/i.test(explicit)) return explicit;

    const structured = Array.isArray(pathway?.interpretation_points)
        ? pathway.interpretation_points.find(point =>
            point?.text && /^cell(?:\s*\/\s*tissue)?\s+context$/i.test(String(point.label || '').trim())
        )
        : null;
    const structuredText = cleanDescriptionText(structured?.text || '');
    return /^not resolved\b/i.test(structuredText) ? '' : structuredText;
}

/**
 * Pathway narrative.
 *
 * The narrative is prose written per the manuscript interpretation
 * specification: an opening overlap statement, notable-protein paragraphs, a
 * functional-cluster paragraph, and a closing summary naming the driving
 * proteins. It is produced server-side (see generate_pathway_narratives) and
 * carried on the record as `pathway_narrative`.
 *
 * Older runs and history entries carry no narrative, so the caller supplies a
 * record-level fallback sentence.
 */
function normalizeNarrativePmids(value) {
    const values = Array.isArray(value) ? value : (value ? [value] : []);
    return values
        .map(item => {
            const raw = item && typeof item === 'object'
                ? item.pmid || item.PMID || item.id
                : item;
            return String(raw || '').replace(/\D/g, '');
        })
        .filter(Boolean)
        .filter((pmid, index, pmids) => pmids.indexOf(pmid) === index);
}

function sanitizeNarrativeText(value) {
    let text = String(value || '').trim();
    if (!text) return '';
    const protocolLeak = /```|driver_genes\s*(?:["'(:]|\[)|"clusters"\s*:|incorrectly formatted|constraints in this environment|correctly formatted\s+(?:an?\s+)?response/i;
    const marker = protocolLeak.exec(text);
    if (marker) text = text.slice(0, marker.index).replace(/[\s`{}\[\],:;]+$/g, '').trim();
    text = text
        .replace(/\b(?:a\s+)?non-intersection pathway component\b/gi, 'pathway component')
        .replace(/\bsubmitted ([^.!?]{0,100}?)-associated proteins\b/gi, 'submitted $1-associated genes')
        .replace(/\bproteins enriched in\b/gi, 'genes enriched in')
        .replace(/\bremaining proteins\b/gi, 'remaining genes')
        .replace(/\bthese proteins\b/gi, 'these genes')
        .replace(/\bthese (\d+) proteins\b/gi, 'these $1 genes')
        .replace(/\bassociated proteins\b/gi, 'associated genes')
        .replace(/\benriched proteins\b/gi, 'enriched genes')
        .replace(/\bintersection proteins\b/gi, 'intersection genes')
        .replace(/\b(?:protein|gene|network) module\b/gi, 'gene set')
        .replace(/\bthe proteins listed for this record\b/gi, 'the genes listed for this record')
        .replace(/\s+/g, ' ')
        .trim();
    // Older narratives often end with a formulaic transition instead of a
    // direct scientific statement.  Remove it at presentation time so archived
    // examples and newly generated runs follow the same editorial style.
    text = text
        .replace(/^(?:(?:overall|taken together|collectively)\s*,?\s*)+/i, '')
        .replace(
            /^Exactly\s+(\d+)\s+[^.!?]{1,140}?\s+associated genes were significantly enriched in the\s+([^.!?]+?)\s+pathway\s*(\([^)]+\))?\./i,
            (_, count, pathwayName, pathwayId) => `${count} input genes map to ${pathwayName.trim()}${pathwayId ? ` ${pathwayId}` : ''}.`
        )
        .replace(/\bIn the context of ([^,]{2,80}),\s*/gi, 'In $1, ')
        .replace(/\bThe association appears to be primarily driven by\b/g, 'The principal driver genes are')
        .replace(/\bindicates that this term captures a substantial component of\b/gi, 'highlights')
        .replace(/([.!?]\s+)(?:overall|taken together|collectively)\s*,?\s*([a-z])/gi,
            (_, boundary, letter) => `${boundary}${letter.toUpperCase()}`)
        .trim();
    if (text) text = `${text.charAt(0).toUpperCase()}${text.slice(1)}`;
    return text.length >= 24 ? text : '';
}

function getPathwayNarrative(pathway) {
    const narrative = pathway?.pathway_narrative;
    if (!narrative || typeof narrative !== 'object') return null;
    const paragraphPmidMap = Array.isArray(narrative.paragraph_pmids)
        ? narrative.paragraph_pmids
        : (Array.isArray(narrative.paragraph_citations) ? narrative.paragraph_citations : []);
    const paragraphs = (Array.isArray(narrative.paragraphs) ? narrative.paragraphs : [])
        .map((paragraph, index) => {
            const isStructured = paragraph && typeof paragraph === 'object';
            const text = sanitizeNarrativeText(
                isStructured
                    ? paragraph.text || paragraph.paragraph || paragraph.content || ''
                    : paragraph || ''
            );
            const pmids = normalizeNarrativePmids(
                isStructured
                    ? paragraph.pmids || paragraph.citations || paragraph.literature
                    : paragraphPmidMap[index]
            );
            return { text, pmids };
        })
        .filter(paragraph => paragraph.text);
    if (!paragraphs.length) return null;
    return {
        paragraphs,
        driverGenes: (Array.isArray(narrative.driver_genes) ? narrative.driver_genes : [])
            .map(gene => String(gene || '').trim())
            .filter(Boolean),
        clusters: (Array.isArray(narrative.clusters) ? narrative.clusters : [])
            .filter(cluster => cluster && String(cluster.label || '').trim())
            .map(cluster => ({
                label: String(cluster.label).trim(),
                genes: (Array.isArray(cluster.genes) ? cluster.genes : [])
                    .map(gene => String(gene || '').trim())
                    .filter(Boolean)
            }))
            .filter(cluster => cluster.genes.length)
    };
}

function getNarrativeParagraphLiterature(paragraph, literature, limit = 2, queryTerms = '') {
    if (!paragraph || !literature.length) return [];

    // Newer server payloads can provide an exact paragraph-to-PMID map. Honor
    // that mapping before considering the compatibility path for old archives.
    const explicitPmids = new Set(paragraph.pmids || []);
    if (explicitPmids.size) {
        return literature.filter(record => explicitPmids.has(record.pmid)).slice(0, limit);
    }

    // Historical archives only persisted a pathway-level literature list. For
    // those records, expose a jump only when the paragraph and paper title have
    // real lexical or protein-symbol overlap; never rotate an unrelated PMID in
    // merely to make every paragraph clickable.
    const ignored = new Set([
        'about', 'after', 'among', 'associated', 'context', 'disease', 'evidence',
        'from', 'into', 'multiple', 'pathway', 'process', 'related', 'relevant',
        'sclerosis', 'support', 'that', 'their', 'these', 'this', 'through', 'where',
        'with'
    ]);
    // The PubMed query for these records was literally "<pathway>" AND "<disease>",
    // so every attached title repeats those words. Matching on them scores the
    // opening count-statement as well as a real mechanistic claim, which is how
    // a sentence carrying no biological assertion ended up citing two papers.
    String(queryTerms || '').toLowerCase().match(/[a-zβ][a-z0-9β+-]{3,}/g)?.forEach(
        token => ignored.add(token)
    );
    const paragraphText = String(paragraph.text || '');
    const paragraphTokens = new Set(
        (paragraphText.toLowerCase().match(/[a-zβ][a-z0-9β+-]{3,}/g) || [])
            .filter(token => !ignored.has(token))
    );
    const paragraphSymbols = new Set(
        paragraphText.match(/\b[A-Z][A-Z0-9-]{2,}\b/g) || []
    );
    return literature
        .map((record, index) => {
            const title = String(record.title || '');
            const titleTokens = title.toLowerCase().match(/[a-zβ][a-z0-9β+-]{3,}/g) || [];
            const titleSymbols = title.match(/\b[A-Z][A-Z0-9-]{2,}\b/g) || [];
            const lexicalScore = titleTokens.reduce(
                (score, token) => score + (!ignored.has(token) && paragraphTokens.has(token) ? 1 : 0),
                0
            );
            const symbolScore = titleSymbols.reduce(
                (score, symbol) => score + (paragraphSymbols.has(symbol) ? 4 : 0),
                0
            );
            return { record, index, score: lexicalScore + symbolScore };
        })
        .filter(item => item.score > 0)
        .sort((a, b) => b.score - a.score || a.index - b.index)
        .slice(0, limit)
        .map(item => item.record);
}

function conciseTakeawayText(value, maxLength = 700) {
    let text = sanitizeNarrativeText(value) || String(value || '').trim();
    if (!text) return '';
    text = text.replace(/^(?:(?:overall|taken together|collectively)\s*,?\s*)+/i, '').trim();
    if (text) text = `${text.charAt(0).toUpperCase()}${text.slice(1)}`;
    text = text.split(/(?<=[.!?])\s+/).slice(0, 2).join(' ').trim();
    if (text.length > maxLength) {
        text = `${text.slice(0, maxLength - 3).replace(/\s+\S*$/, '')}...`;
    }
    return text;
}

function renderNarrativeParagraphs(narrative, literature, evidenceScopeId, queryTerms = '') {
    if (!narrative) return '';
    const rendered = narrative.paragraphs.map((paragraph, index) => {
        const isTakeaway = index === narrative.paragraphs.length - 1;
        const paragraphClass = `narrative-paragraph${isTakeaway ? ' narrative-paragraph--takeaway' : ''}`;
        const paragraphCopy = isTakeaway
            ? `<span class="summary-takeaway-copy">${escapeHtml(conciseTakeawayText(paragraph.text))}</span><span class="detailed-takeaway-copy">${escapeHtml(paragraph.text)}</span>`
            : escapeHtml(paragraph.text);
        const related = getNarrativeParagraphLiterature(paragraph, literature, 2, queryTerms);
        const targetIds = related
            .map(record => getLiteratureRecordDomId(evidenceScopeId, record.pmid))
            .filter(Boolean);
        if (!targetIds.length) return `<p class="${paragraphClass}">${paragraphCopy}</p>`;
        const paperLabel = `${related.length} related paper${related.length === 1 ? '' : 's'}`;
        return `
            <button type="button"
                    class="narrative-evidence-jump ${paragraphClass}"
                    data-evidence-targets="${escapeHtml(targetIds.join(' '))}"
                    aria-pressed="false"
                    onclick="jumpToNarrativeEvidence(this)">
                <span class="narrative-evidence-copy">${paragraphCopy}</span>
                <span class="narrative-evidence-cue">
                    <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg>
                    ${paperLabel}
                </span>
            </button>`;
    });
    const hasTargets = rendered.some(markup => markup.includes('narrative-evidence-jump'));
    return `${hasTargets ? '<span class="narrative-evidence-guide">Related literature is linked from the supported passages.</span>' : ''}${rendered.join('')}`;
}

function renderNarrativeDriverGenes(driverGenes) {
    if (!driverGenes.length) return '';
    return `<div class="narrative-meta-row">
        <span class="narrative-meta-label">Driving genes</span>
        <span class="narrative-gene-row">${driverGenes
            .map(gene => renderGeneOfficialLink(gene, 'evidence-gene-chip evidence-gene-chip--driver'))
            .join('')}</span>
    </div>`;
}

function renderNarrativeClusters(clusters) {
    if (!clusters.length) return '';
    return `<div class="narrative-meta-row">
        <span class="narrative-meta-label">Functional clusters</span>
        <div class="narrative-cluster-list">${clusters.map(cluster => `
            <span class="narrative-cluster">
                <strong>${escapeHtml(cluster.label)}</strong>
                <span class="narrative-gene-row">${cluster.genes
                    .map(gene => renderGeneOfficialLink(gene, 'evidence-gene-chip'))
                    .join('')}</span>
            </span>`).join('')}</div>
    </div>`;
}

/**
 * Ontology-graph note.
 *
 * GO is a directed acyclic graph, so a broad parent term and one of its
 * children can both clear the significance threshold off largely the same
 * genes. When that happens inside one report, saying so is what keeps a reader
 * from counting one signal twice.
 */
function renderNarrativeHierarchyNote(pathway) {
    const hierarchy = pathway?.hierarchy;
    if (!hierarchy || typeof hierarchy !== 'object') return '';
    const parents = (hierarchy.parent_names_in_set || []).filter(Boolean);
    const children = (hierarchy.child_names_in_set || []).filter(Boolean);
    if (!parents.length && !children.length) return '';
    const parts = [];
    if (parents.length) {
        parts.push(`Broader term${parents.length === 1 ? '' : 's'} also retained: ${parents.join(', ')}.`);
    }
    if (children.length) {
        parts.push(`More specific term${children.length === 1 ? '' : 's'} also retained: ${children.join(', ')}.`);
    }
    parts.push('These share much of the same intersection and are one signal read at different resolutions.');
    return `<p class="narrative-hierarchy-note">${escapeHtml(parts.join(' '))}</p>`;
}

function renderNarrativeTierBadge(pathway) {
    const tier = String(pathway?.reporting_tier || '').trim().toLowerCase();
    if (tier !== 'supporting') return '';
    return '<span class="narrative-tier-badge" title="Not among the leading terms for its database">Supporting term</span>';
}

/**
 * Cell/tissue context belongs to the interpretation, not to the ranking audit
 * trail, so it renders as a closing line of the narrative card.
 */
function renderNarrativeCellContext(cell) {
    if (!cell || !cell.cellContext) return '';
    const labels = cell.cellLabels || [];
    const evidence = cell.cellEvidence || [];
    const evidenceMarkup = evidence.length
        ? `<div class="cell-context-claim-evidence">
            <span class="cell-context-evidence-title">References</span>
            ${evidence.map(item => `<div class="cell-context-evidence-item">
                ${item.labels?.length || item.genes?.length ? `<span class="cell-context-evidence-labels">${[
                    ...(item.labels || []),
                    ...(item.genes?.length ? [item.genes.join(', ')] : [])
                ].map(escapeHtml).join(', ')}</span>` : ''}
                ${item.claim ? `<span class="cell-context-evidence-claim">${escapeHtml(item.claim)}</span>` : ''}
                ${(item.citations || []).map(citation => `
                    <a class="cell-context-reference-link"
                       href="https://pubmed.ncbi.nlm.nih.gov/${citation.pmid}/"
                       target="_blank" rel="noopener">
                        <strong>${escapeHtml(citation.title || `PubMed record ${citation.pmid}`)}</strong>
                        <span>PMID:${escapeHtml(citation.pmid)}${citation.year ? `, ${escapeHtml(citation.year)}` : ''}${citation.journal ? `, ${escapeHtml(citation.journal)}` : ''} <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg></span>
                    </a>`).join('')}
            </div>`).join('')}
        </div>`
        : '';
    return `<div class="narrative-meta-row">
        <span class="narrative-meta-label">Cell / tissue context</span>
        ${labels.length ? `<div class="pathway-cell-context-tags" aria-label="Pathway-level cell and tissue context">
            ${labels.map(label => renderCellContextOfficialLink(label)).join('')}
        </div>` : ''}
        <p class="narrative-cell-copy">${escapeHtml(cell.cellContext)}</p>
        ${evidenceMarkup}
    </div>`;
}

function getCellContextClaimEvidence(pathway, literature) {
    const raw = pathway?.cell_context_evidence ?? pathway?.cell_context_claims;
    let entries = Array.isArray(raw) ? raw : (Array.isArray(raw?.claims) ? raw.claims : []);
    if (!entries.length && raw && typeof raw === 'object' && !Array.isArray(raw)) {
        entries = Object.entries(raw)
            .filter(([key]) => key !== 'claims')
            .map(([label, value]) => ({
                labels: [label],
                ...(value && typeof value === 'object' ? value : { pmids: value })
            }));
    }
    const contextLiterature = Array.isArray(pathway?.cell_context_literature)
        ? pathway.cell_context_literature
        : [];
    const recordsByPmid = new Map([...contextLiterature, ...(literature || [])].map(record => [
        String(record?.pmid || record?.PMID || ''),
        {
            pmid: String(record?.pmid || record?.PMID || ''),
            title: String(record?.title || '').trim(),
            journal: String(record?.journal || '').trim(),
            year: String(record?.year || '').trim()
        }
    ]));
    return entries.map(entry => {
        if (!entry || typeof entry !== 'object') return null;
        const labels = (Array.isArray(entry.labels) ? entry.labels : (entry.label ? [entry.label] : []))
            .map(label => String(label || '').trim())
            .filter(Boolean);
        const claim = String(entry.claim || entry.text || entry.context || '').trim();
        const genes = (Array.isArray(entry.genes) ? entry.genes : [])
            .map(gene => String(gene || '').trim())
            .filter(Boolean);
        const pmids = normalizeNarrativePmids(entry.pmids || entry.citations || entry.literature);
        const citations = pmids.map(pmid => recordsByPmid.get(pmid) || { pmid, title: '' });
        // A PMID list without a specific claim or label is still pathway-level
        // evidence and must not be presented as if it supported every chip.
        return pmids.length && (claim || labels.length) ? { labels, genes, claim, citations } : null;
    }).filter(Boolean);
}

function renderOverallInterpretation(pathway, fallbackText, statisticsText, citations, cell, literature, evidenceScopeId) {
    const narrative = getPathwayNarrative(pathway);
    const body = narrative
        ? renderNarrativeParagraphs(
            narrative,
            literature,
            evidenceScopeId,
            `${pathway?.name || ''} ${getRunDiseaseContext(currentResults || {}).name || ''}`
        )
        : `<p>${escapeHtml(fallbackText)}</p>`;
    return `
        <section class="overall-interpretation-card${narrative ? ' overall-interpretation-card--narrative' : ''}">
            <span class="overall-interpretation-label">Overall interpretation${renderNarrativeTierBadge(pathway)}</span>
            ${body}
            ${renderNarrativeHierarchyNote(pathway)}
            ${narrative ? renderNarrativeDriverGenes(narrative.driverGenes) : ''}
            ${narrative ? renderNarrativeClusters(narrative.clusters) : ''}
            ${renderNarrativeCellContext(cell)}
            ${narrative && statisticsText ? `<p class="narrative-record-line">${escapeHtml(statisticsText)}</p>` : ''}
            ${renderInlineEvidenceLiterature(citations)}
        </section>`;
}

/**
 * The pathway-linked literature section below the card already lists every
 * record with its title, year and journal. Some archived literature summaries
 * additionally enumerate the same records inline, so the reader meets each
 * paper twice. The enumeration is dropped and the summary sentence kept.
 */
function trimDuplicatedRecordList(text) {
    const value = String(text || '').trim();
    if (!value) return value;
    const trimmed = value.replace(/\s*Representative records?:.*$/is, '').trim();
    return trimmed || value;
}

function renderDiseaseInterpretation(pathway, rankingContext = {}) {
    const points = getDiseaseInterpretationPoints(pathway);
    const findPoint = label => points.find(point => point.label.toLowerCase() === label.toLowerCase())?.text || '';
    const pathwayDescription = getPathwayIntroduction(pathway);
    const biologyText = findPoint('Biological context') || getPathwayIntroduction(pathway);
    const geneEvidence = getPathwayGeneEvidence(pathway);
    const genes = geneEvidence.genes;
    const shownGenes = genes.slice(0, 10);
    const geneText = findPoint('Intersection-gene interpretation')
        || findPoint('Gene-level support')
        || (shownGenes.length
        ? `The input-pathway intersection contains ${genes.length} gene${genes.length === 1 ? '' : 's'}: ${shownGenes.join(', ')}${genes.length > shownGenes.length ? ` and ${genes.length - shownGenes.length} additional genes` : ''}.`
        : 'No structured input-pathway intersection is available for this record.');
    const diseaseText = trimDuplicatedRecordList(findPoint('Disease pathology and relevance'))
        || findPoint('Disease relevance')
        || points.find(point => /disease/i.test(point.label))?.text
        || cleanEvidenceDescription(pathway)
        || 'Disease relevance was not resolved for this pathway.';
    const pathwayCellContext = getPathwayCellContext(pathway);
    const cellLabels = extractCellTypeLabels(pathwayCellContext);
    const literature = getPathwayLiteratureRecords(pathway);
    const cellEvidence = getCellContextClaimEvidence(pathway, literature);
    const overlapSize = genes.length || Number(pathway?.intersection_size) || null;
    const pathwaySize = getPathwayTermSize(pathway);
    const pValue = formatPValue(pathway?.p_value ?? pathway?.pvalue);
    const statisticalText = `Adjusted enrichment P-value ${pValue}; ${overlapSize ?? 'an unavailable number of'} input genes overlap ${pathwaySize ? `the ${pathwaySize}-gene pathway annotation` : 'the pathway annotation'}.`;
    const literatureText = trimDuplicatedRecordList(findPoint('PubMed literature synthesis')) || (literature.length
        ? `${literature.length} pathway-disease PubMed record${literature.length === 1 ? '' : 's'} support the biological interpretation and gene-disease connections summarized above.`
        : 'No pathway-disease PubMed record was retrieved for this pathway, so the literature component was unavailable for ranking review.');
    const dimensions = [
        {
            label: 'Pathway description',
            text: pathwayDescription,
            supportingText: biologyText !== pathwayDescription ? biologyText : '',
            source: 'Official pathway definition',
            citations: selectRelatedLiterature(literature, `${pathwayDescription} ${biologyText}`, 0, Math.min(2, literature.length))
        },
        {
            label: 'Disease pathology',
            text: diseaseText,
            source: 'Disease pathology and pathway relevance',
            citations: selectRelatedLiterature(literature, diseaseText, 1, Math.min(2, literature.length))
        },
        {
            label: 'Intersection genes',
            text: geneText,
            source: 'Input-pathway intersection',
            citations: selectRelatedLiterature(literature, geneText, 2, Math.min(2, literature.length))
        },
        {
            label: 'Enrichment strength',
            text: statisticalText,
            source: 'Adjusted enrichment result'
        },
        {
            label: 'PubMed literature',
            text: literatureText,
            citations: selectRelatedLiterature(literature, `${diseaseText} ${biologyText}`, 0, Math.min(3, literature.length)),
            source: 'Pathway-disease PubMed retrieval'
        }
    ];
    const rank = Number(rankingContext.rank) || Number(pathway?.gpt_rank) || null;
    const category = rankingContext.category || pathway?.source || pathway?.category || 'this database';
    const categoryTotal = Number(rankingContext.total) || null;
    const diseaseName = getRunDiseaseContext(currentResults || {}).name;
    const overallText = `Enrichment of ${pathway?.name || pathway?.pathway_name || 'this pathway'} in ${diseaseName} links ${overlapSize ?? 'the submitted'} input gene${overlapSize === 1 ? '' : 's'} to the annotated biological process.${cellLabels.length ? ` The mapped context emphasizes ${cellLabels.slice(0, 3).join(', ')}${cellLabels.length > 3 ? ', and related contexts' : ''}.` : ''}`;
    const rankText = rank === 1
        ? `Highest combined biological-evidence position among ${categoryTotal || 'the'} validated ${category} pathways.`
        : `Rank ${rank || 'not available'} of ${categoryTotal || 'the validated'} ${category} pathways after five-source evidence review.`;
    const overallCitations = selectRelatedLiterature(
        literature,
        `${pathwayDescription} ${diseaseText} ${geneText}`,
        0,
        Math.min(3, literature.length)
    );
    // One citation, one place. The same two PMIDs were previously repeated under
    // every dimension and again in the literature section below, which made the
    // card look far better sourced than it is. Each PMID is now shown once, at
    // the first dimension that actually rests on it.
    const shownPmids = new Set(
        (overallCitations || []).map(record => String(record?.pmid || '')).filter(Boolean)
    );
    dimensions.forEach(dimension => {
        const fresh = (dimension.citations || []).filter(record => {
            const pmid = String(record?.pmid || '');
            if (!pmid || shownPmids.has(pmid)) return false;
            shownPmids.add(pmid);
            return true;
        });
        dimension.citations = fresh;
    });

    // Keep the pathway page focused on a take-away-ready interpretation. The
    // supplementary reasoning is available once, at report level, rather
    // than repeated as an internal provenance block beneath every pathway.
    return renderOverallInterpretation(
            pathway,
            overallText,
            statisticalText,
            overallCitations,
            {
                cellContext: pathwayCellContext,
                cellLabels,
                cellEvidence
            },
            literature,
            rankingContext.evidenceScopeId || ''
        );
}

function getPathwayIntroduction(pathway) {
    const explicit = cleanDescriptionText(
        pathway?.pathway_description || pathway?.source_description || pathway?.definition || ''
    );
    if (explicit) return explicit;

    const name = pathway?.name || pathway?.pathway_name || 'this pathway';
    const category = pathway?.source || pathway?.category || '';
    const templates = {
        'GO:BP': `${name} is a Gene Ontology Biological Process term describing a coordinated series of molecular or cellular events.`,
        'GO:MF': `${name} is a Gene Ontology Molecular Function term describing an activity performed by a gene product.`,
        'GO:CC': `${name} is a Gene Ontology Cellular Component term describing a cellular structure, complex or location.`,
        'KEGG': `${name} is a KEGG pathway entry representing an annotated molecular interaction and reaction network.`,
        'REAC': `${name} is a curated Reactome pathway representing a defined set of human biological reactions and events.`
    };
    return templates[category] || `${name} is a validated pathway record from ${category || 'the source database'}.`;
}

function truncateText(text, maxLength = 310) {
    if (!text || text.length <= maxLength) return text;
    return `${text.slice(0, maxLength).trim()}…`;
}

function getPathwayTermSize(pathway) {
    const value = Number(pathway?.term_size ?? pathway?.pathway_size);
    return Number.isFinite(value) && value > 0 ? value : null;
}

function renderEvidenceGenePreview(genes, chipClass) {
    if (!genes.length) return '';
    const visible = genes.slice(0, 10);
    const remainder = genes.length - visible.length;
    return `
        ${visible.map(gene => renderGeneOfficialLink(gene, chipClass)).join('')}
        ${remainder > 0 ? `<span class="evidence-gene-more">+${remainder} more</span>` : ''}`;
}

function renderExpandableEvidenceGenes(genes, chipClass, note) {
    if (!genes.length) {
        return '<span class="evidence-driver-empty">Not available in the source result</span>';
    }
    const visible = genes.slice(0, 10);
    const remaining = genes.slice(10);
    return `
        <div class="evidence-expanded-gene-list" title="${escapeHtml(note)}">
            ${visible.map(gene => renderGeneOfficialLink(gene, chipClass)).join('')}
        </div>
        ${remaining.length ? `
            <details class="evidence-gene-disclosure">
                <summary>Show remaining ${remaining.length} intersection genes</summary>
                <div class="evidence-expanded-gene-list evidence-expanded-gene-list--more">
                    ${remaining.map(gene => renderGeneOfficialLink(gene, chipClass)).join('')}
                </div>
            </details>` : ''}`;
}

function renderExternalEvidenceGenes(pathway) {
    const current = Array.isArray(pathway?.external_evidence_genes)
        ? pathway.external_evidence_genes
        : [];
    // Read the one-off Figure 6 field as a compatibility fallback, while all
    // new live runs write the generic external_evidence_genes contract.
    const legacy = Array.isArray(pathway?.independent_evidence_genes)
        ? pathway.independent_evidence_genes
        : [];
    const entries = (current.length ? current : legacy).filter(entry => entry?.gene);
    if (!entries.length) return '';

    const note = pathway?.external_evidence_note
        || pathway?.independent_evidence_note
        || 'External literature evidence; not used for enrichment or ranking.';
    const sourceLinks = entry => {
        const supplied = Array.isArray(entry?.pmids) ? entry.pmids : [];
        const recovered = (Array.isArray(entry?.source_refs) ? entry.source_refs : [])
            .map(value => String(value || '').match(/PMID\s*:?\s*(\d{6,9})/i)?.[1])
            .filter(Boolean);
        const pmids = [...supplied, ...recovered]
            .map(value => String(value || '').replace(/\D/g, ''))
            .filter((value, index, values) => value && values.indexOf(value) === index);
        return pmids.map(pmid => `
            <a href="https://pubmed.ncbi.nlm.nih.gov/${escapeHtml(pmid)}/"
               target="_blank" rel="noopener">PMID:${escapeHtml(pmid)}
               <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-arrow-up-right"></use></svg>
            </a>`).join('');
    };

    return `
        <details class="external-evidence-block">
            <summary>
                <span>External corroborating genes</span>
                <small>${entries.length} gene${entries.length === 1 ? '' : 's'}; not used for enrichment or ranking</small>
                <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg>
            </summary>
            <div class="external-evidence-body">
                <p>${escapeHtml(note)}</p>
                <div class="external-evidence-grid">
                    ${entries.map(entry => `
                        <div class="external-evidence-gene">
                            ${renderGeneOfficialLink(entry.gene, 'evidence-gene-chip evidence-gene-chip--external')}
                            <span class="external-evidence-categories">
                                ${(entry.categories || []).map(category => `<span>${escapeHtml(category)}</span>`).join('')}
                            </span>
                            ${sourceLinks(entry) ? `<div class="external-evidence-sources">${sourceLinks(entry)}</div>` : ''}
                        </div>`).join('')}
                </div>
            </div>
        </details>`;
}

function normalizeDatabaseCategory(category) {
    const value = String(category || '').trim().toUpperCase();
    if (value === 'GO_BP' || value === 'GOBP') return 'GO:BP';
    if (value === 'GO_MF' || value === 'GOMF') return 'GO:MF';
    if (value === 'GO_CC' || value === 'GOCC') return 'GO:CC';
    if (value === 'REACTOME') return 'REAC';
    return value;
}

function getConsolidatedDatabaseReasoning(category) {
    const categoryKey = normalizeDatabaseCategory(category);
    const records = collectedReasoning
        .filter(entry => entry?.reasoning && normalizeDatabaseCategory(entry.category) === categoryKey)
        .sort((a, b) => Number(a.iteration || 1) - Number(b.iteration || 1));
    if (!records.length) return null;

    return {
        category,
        iteration: Math.max(...records.map(entry => Number(entry.iteration || 1))),
        // Consolidate the initial biological rationale and later validation
        // refinements into one database-level record instead of exposing
        // internal prompt-pass navigation to readers.
        reasoning: Object.assign({}, ...records.map(entry => entry.reasoning))
    };
}

function renderDatabaseReasoningDetails(category) {
    const record = getConsolidatedDatabaseReasoning(category);
    const content = record
        ? renderReasoningPanel(record.reasoning, category, record.iteration, {
            recordView: true,
            embeddedDatabase: true
        })
        : `
            <div class="database-reasoning-empty">
                No method record was stored for this completed analysis.
            </div>`;

    return `
        <details class="database-reasoning-details detailed-report-only">
            <summary class="database-reasoning-summary">
                <strong>Reasoning details</strong>
                <span class="database-reasoning-toggle" aria-hidden="true">
                    <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg>
                </span>
            </summary>
            <div class="database-reasoning-body">
                ${content}
            </div>
        </details>`;
}

function renderEvidenceSectionsView(pathways) {
    if (!elements.evidenceSections) return;

    const cellTypeFrequencyEntries = getRunCellTypeFrequencies(pathways);
    const cellTypeFrequencyMap = new Map(
        cellTypeFrequencyEntries.map(entry => [entry.label, entry])
    );

    // Group pathways by category
    const categories = {};
    pathways.forEach(p => {
        const cat = p.source || p.category || 'Other';
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(p);
    });

    const sectionsHtml = Object.entries(categories).map(([cat, items], sectionIndex) => {
        const info = getDatabaseMeta(cat);
        const rankedItems = [...items].sort((a, b) =>
            Number(a.gpt_rank ?? Number.MAX_SAFE_INTEGER) - Number(b.gpt_rank ?? Number.MAX_SAFE_INTEGER)
        );
        const shownItems = rankedItems.slice(0, pathwayDisplayLimit);

        return `
        <div class="evidence-section ${sectionIndex === 0 ? 'open' : ''}">
            <div class="evidence-section-header" onclick="toggleEvidence(this.parentElement)">
                <div class="evidence-section-title">
                    ${renderDatabaseMark(cat)}
                    <span class="evidence-section-code" style="color: ${info.color};">${cat}</span>
                    <span class="evidence-section-name">${escapeHtml(info.name)}</span>
                    <span class="evidence-section-count">${shownItems.length === rankedItems.length ? `${rankedItems.length} validated pathways` : `Showing ${shownItems.length} of ${rankedItems.length}`}</span>
                </div>
                <div class="evidence-section-action">
                    <span>View pathways</span>
                    <span class="evidence-section-toggle"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg></span>
                </div>
            </div>
            <div class="evidence-section-body">
                <section class="database-output-stage" aria-label="Validated pathways and interpretations">
                    <h4 class="database-output-stage-title">Validated pathways</h4>
                    <div class="database-pathway-list">
                ${shownItems.map((p, rankIndex) => {
            const evidenceScopeId = `evidence-${sectionIndex + 1}-${rankIndex + 1}`;
            const preview = truncateText(getPathwayIntroduction(p), 230);
            const literatureRecords = getPathwayLiteratureRecords(p);
            const pmidList = literatureRecords.map(record => record.pmid);
            const geneEvidence = getPathwayGeneEvidence(p);
            const genes = geneEvidence.genes;
            const overlapSize = genes.length || Number(p.intersection_size) || null;
            const termSize = getPathwayTermSize(p);
            const geneChipClass = geneEvidence.source === 'interpretation-fallback'
                ? 'evidence-gene-chip evidence-gene-chip--narrative'
                : 'evidence-gene-chip';
            const pathwayCellContext = getPathwayCellContext(p);
            const pathwayCellLabels = extractCellTypeLabels(pathwayCellContext);
            const pathwayCellFrequencies = pathwayCellLabels
                .map(label => cellTypeFrequencyMap.get(label))
                .filter(Boolean)
                .sort((a, b) => b.count - a.count || a.order - b.order || a.label.localeCompare(b.label));
            const pathwayTopCellFrequencies = pathwayCellFrequencies.slice(0, 5);
            const remainingPathwayContexts = Math.max(0, pathwayCellFrequencies.length - pathwayTopCellFrequencies.length);

            return `
                    <details class="evidence-item evidence-item--layered" id="${evidenceScopeId}" data-category="${escapeHtml(cat)}" data-rank="${rankIndex + 1}">
                        <summary class="evidence-item-summary">
                            <div class="evidence-summary-main">
                                <div class="evidence-title-line">
                                    <span class="evidence-rank-index">#${rankIndex + 1}</span>
                                    <strong>${renderPathwayNameLink(p, p.name || p.pathway_name || 'Unknown')}</strong>
                                    ${renderPathwayId(p)}
                                </div>
                                <p class="evidence-item-preview"><span class="evidence-preview-label">Definition</span>${escapeHtml(preview)}</p>
                                ${pathwayTopCellFrequencies.length ? `
                                    <div class="evidence-pathway-context-row">
                                        <span class="evidence-driver-label">Cell/tissue context</span>
                                        ${pathwayTopCellFrequencies.map(entry => renderCellContextFrequencyLink(entry, 'evidence-context-chip')).join('')}
                                    </div>` : ''}
                                <div class="evidence-driver-row">
                                    <span class="evidence-driver-label" title="${escapeHtml(geneEvidence.note)}">${escapeHtml(geneEvidence.label)}</span>
                                    ${genes.length > 0
                    ? renderEvidenceGenePreview(genes, geneChipClass)
                    : '<span class="evidence-driver-empty">Not available in the source result</span>'
                }
                                </div>
                            </div>
                            <div class="evidence-summary-metrics">
                                <span class="evidence-key-metric">
                                    <small>Adjusted P-value</small>
                                    <strong>${formatPValue(p.p_value || p.pvalue)}</strong>
                                </span>
                                <span class="evidence-key-metric evidence-key-metric--overlap">
                                    <small>Overlap / pathway size</small>
                                    <strong>${overlapSize ?? 'NA'} / ${termSize ?? 'NA'} genes</strong>
                                </span>
                                <span class="evidence-item-chevron"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg></span>
                            </div>
                        </summary>
                        <div class="evidence-item-expanded">
                            <div class="evidence-full-copy">
                                <span class="evidence-detail-label">Interpretation</span>
                                ${renderDiseaseInterpretation(p, { rank: rankIndex + 1, category: cat, total: rankedItems.length, evidenceScopeId })}
                                <div class="evidence-expanded-genes">
                                    <span class="evidence-detail-label">Input-pathway intersection genes</span>
                                    ${renderExpandableEvidenceGenes(genes, geneChipClass, geneEvidence.note)}
                                </div>
                            </div>
                            <div class="evidence-source-block">
                                <span class="evidence-detail-label">Literature</span>
                                <div class="evidence-item-meta">
                                    ${literatureRecords.length > 0
                    ? literatureRecords.map(record => renderLiteratureRecord(record, evidenceScopeId)).join('')
                    : '<span class="no-pmid">No literature references attached to this record.</span>'
                }
                                </div>
                            </div>
                        </div>
                    </details>
                    `;
        }).join('')}
                    </div>
                </section>
                ${renderDatabaseReasoningDetails(cat)}
            </div>
        </div>
        `;
    }).join('');

    elements.evidenceSections.innerHTML = sectionsHtml;
    enhanceReasoningSectionToggles(elements.evidenceSections);
}


// Global function for evidence toggle
window.toggleEvidence = function (section) {
    section.classList.toggle('open');
};

window.jumpToNarrativeEvidence = function (trigger) {
    if (!trigger) return;
    const evidenceItem = trigger.closest('.evidence-item');
    const targetIds = String(trigger.dataset.evidenceTargets || '')
        .split(/\s+/)
        .filter(Boolean);
    const targets = targetIds
        .map(id => document.getElementById(id))
        .filter(Boolean);
    if (!targets.length) return;

    if (evidenceItem) {
        evidenceItem.querySelectorAll('.narrative-evidence-jump[aria-pressed="true"]')
            .forEach(button => button.setAttribute('aria-pressed', 'false'));
        evidenceItem.querySelectorAll('.evidence-literature-record.is-narrative-evidence-target')
            .forEach(record => record.classList.remove('is-narrative-evidence-target'));
    }
    trigger.setAttribute('aria-pressed', 'true');
    targets.forEach(record => record.classList.add('is-narrative-evidence-target'));

    const primaryTarget = targets[0];
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    primaryTarget.scrollIntoView({
        behavior: reduceMotion ? 'auto' : 'smooth',
        block: 'center',
        inline: 'nearest'
    });
    window.setTimeout(() => {
        try {
            primaryTarget.focus({ preventScroll: true });
        } catch (_error) {
            primaryTarget.focus();
        }
    }, reduceMotion ? 0 : 350);
};


/**
 * Render supporting database-level context using reasoning collected from messages.
 */
function renderDatabaseReasoningAudit(results) {
    const container = document.getElementById('reasoning-audit-container');
    const disclosure = document.getElementById('database-reasoning-audit');
    const categoryCount = document.getElementById('reasoning-audit-category-count');
    const passCount = document.getElementById('reasoning-audit-pass-count');
    if (!container) return;
    if (disclosure) disclosure.open = false;

    if (collectedReasoning.length === 0) {
        if (categoryCount) categoryCount.textContent = '0 database categories';
        if (passCount) passCount.textContent = '0 prompt passes';
        container.innerHTML = `
            <div class="reasoning-audit-empty">
                <strong>No database-level reasoning records are available for this run.</strong>
                <span>They appear when structured reasoning is captured during live hypothesis analysis.</span>
            </div>`;
        return;
    }

    // Group by prompt pass, then present one database record at a time.
    const byIteration = {};
    collectedReasoning.forEach(entry => {
        const iter = entry.iteration || 1;
        if (!byIteration[iter]) byIteration[iter] = [];
        byIteration[iter].push(entry);
    });

    const categoryOrder = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'];
    const categoryNames = {
        'GO:BP': 'Biological Process',
        'GO:MF': 'Molecular Function',
        'GO:CC': 'Cellular Component',
        'KEGG': 'KEGG Pathway',
        'REAC': 'Reactome'
    };
    const iterLabels = { 1: 'Initial Prompt', 2: 'Refined Prompt' };
    const iterationKeys = Object.keys(byIteration).sort((a, b) => Number(a) - Number(b));
    const uniqueCategories = new Set(collectedReasoning.map(entry => entry.category).filter(Boolean));
    if (categoryCount) {
        categoryCount.textContent = `${uniqueCategories.size} database categor${uniqueCategories.size === 1 ? 'y' : 'ies'}`;
    }
    if (passCount) {
        passCount.textContent = `${iterationKeys.length} prompt pass${iterationKeys.length === 1 ? '' : 'es'}`;
    }
    const passTabs = iterationKeys.map((iter, index) => {
        const entries = byIteration[iter];
        const label = iterLabels[iter] || `Pass ${iter}`;
        return `
            <button type="button"
                class="reasoning-pass-tab${index === 0 ? ' active' : ''}"
                data-reasoning-pass="${iter}"
                role="tab"
                aria-selected="${index === 0 ? 'true' : 'false'}"
                onclick="switchReasoningPass(this)">
                <span>${label}</span>
                <small>${entries.length} database${entries.length === 1 ? '' : 's'}</small>
            </button>`;
    }).join('');

    const passViews = iterationKeys.map((iter, passIndex) => {
        const entries = [...byIteration[iter]].sort((a, b) => {
            const aIndex = categoryOrder.indexOf(a.category);
            const bIndex = categoryOrder.indexOf(b.category);
            if (aIndex === -1 && bIndex === -1) return String(a.category).localeCompare(String(b.category));
            if (aIndex === -1) return 1;
            if (bIndex === -1) return -1;
            return aIndex - bIndex;
        });

        const categoryTabs = entries.map((entry, index) => {
            return `
                <button type="button"
                    class="reasoning-category-tab${index === 0 ? ' active' : ''}"
                    data-reasoning-category="${escapeHtml(entry.category || `category-${index}`)}"
                    role="tab"
                    aria-selected="${index === 0 ? 'true' : 'false'}"
                    onclick="switchReasoningCategory(this)">
                    <strong>${escapeHtml(entry.category || 'Other')}</strong>
                    <span>${escapeHtml(categoryNames[entry.category] || entry.category || 'Other')}</span>
                    <small>Method record</small>
                </button>`;
        }).join('');

        const records = entries.map((entry, index) => `
            <div class="reasoning-record-view${index === 0 ? ' active' : ''}"
                data-reasoning-record="${escapeHtml(entry.category || `category-${index}`)}"
                role="tabpanel">
                ${renderReasoningPanel(entry.reasoning, entry.category, parseInt(iter), { recordView: true })}
            </div>`).join('');

        return `
            <section class="reasoning-pass-view${passIndex === 0 ? ' active' : ''}"
                data-reasoning-pass-view="${iter}">
                <div class="reasoning-category-nav" role="tablist" aria-label="Pathway databases">
                    ${categoryTabs}
                </div>
                <div class="reasoning-record-stage">
                    ${records}
                </div>
            </section>`;
    }).join('');

    container.innerHTML = `
        <div class="reasoning-browser">
            <div class="reasoning-browser-toolbar">
                <div>
                    <span class="section-eyebrow">Method records</span>
                    <h3>Database reasoning</h3>
                    <p>Review hypothesis-generation rationale and validation feedback by database.</p>
                </div>
                <div class="reasoning-pass-tabs" role="tablist" aria-label="Prompt passes">
                    ${passTabs}
                </div>
            </div>
            ${passViews}
        </div>`;
    enhanceReasoningSectionToggles(container);
}

window.openDatabaseReasoningAudit = function (event, category) {
    event?.preventDefault();
    event?.stopPropagation();

    const disclosure = document.getElementById('database-reasoning-audit');
    if (!disclosure) return;
    disclosure.open = true;

    const activePass = disclosure.querySelector('.reasoning-pass-view.active');
    const categoryButton = Array.from(activePass?.querySelectorAll('.reasoning-category-tab') || [])
        .find(button => button.dataset.reasoningCategory === category);
    if (categoryButton) switchReasoningCategory(categoryButton);

    disclosure.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

window.switchReasoningPass = function (button) {
    const browser = button.closest('.reasoning-browser');
    if (!browser) return;

    const selectedPass = button.dataset.reasoningPass;
    browser.querySelectorAll('.reasoning-pass-tab').forEach(tab => {
        const isActive = tab === button;
        tab.classList.toggle('active', isActive);
        tab.setAttribute('aria-selected', String(isActive));
    });
    browser.querySelectorAll('.reasoning-pass-view').forEach(view => {
        view.classList.toggle('active', view.dataset.reasoningPassView === selectedPass);
    });
};

window.switchReasoningCategory = function (button) {
    const passView = button.closest('.reasoning-pass-view');
    if (!passView) return;

    const selectedCategory = button.dataset.reasoningCategory;
    passView.querySelectorAll('.reasoning-category-tab').forEach(tab => {
        const isActive = tab === button;
        tab.classList.toggle('active', isActive);
        tab.setAttribute('aria-selected', String(isActive));
    });
    passView.querySelectorAll('.reasoning-record-view').forEach(record => {
        record.classList.toggle('active', record.dataset.reasoningRecord === selectedCategory);
    });
};

// ============================================================================
// RENDERING

// ============================================================================

function renderPathwayTable(pathways) {
    if (!pathways || pathways.length === 0) return '';

    const tableId = `pathway-table-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    // If only 1-3 pathways, show all without slider
    if (pathways.length <= 3) {
        let html = `<table class="pathway-table">
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Pathway / ID</th>
                    <th>Adjusted P-value</th>
                    <th>Category</th>
                </tr>
            </thead>
            <tbody>`;

        pathways.forEach((pw, i) => {
            const categoryClass = (pw.category || '').replace(':', '\\:');
            html += `<tr>
                <td>${i + 1}</td>
                <td><div class="pathway-name-stack">${renderPathwayNameLink(pw, pw.name)}${renderPathwayId(pw)}</div></td>
                <td>${formatPValue(pw.p_value)}</td>
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
                        <th>Pathway / ID</th>
                        <th>Adjusted P-value</th>
                        <th>Category</th>
                    </tr>
                </thead>
                <tbody class="pathway-tbody">`;

    const pw = pathways[0];
    const categoryClass = (pw.category || '').replace(':', '\\:');
    html += `<tr>
        <td>1</td>
        <td><div class="pathway-name-stack">${renderPathwayNameLink(pw, pw.name)}${renderPathwayId(pw)}</div></td>
        <td>${formatPValue(pw.p_value)}</td>
        <td><span class="category-badge ${categoryClass}">${pw.category || '-'}</span></td>
    </tr>`;

    html += `</tbody>
            </table>
            
            <div class="pathway-slider-controls">
                <button class="slider-btn prev-btn"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-left"></use></svg> Previous</button>
                <input type="range" 
                       class="pathway-slider" 
                       min="1" 
                       max="${pathways.length}" 
                       value="1" 
                       step="1">
                <button class="slider-btn next-btn">Next <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-right"></use></svg></button>
            </div>
        </div>
    `;

    setTimeout(() => { setupPathwaySlider(tableId, pathways); }, 0);
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
        const i = index - 1;
        const pw = pathways[i];
        const categoryClass = (pw.category || '').replace(':', '\\:');

        tbody.classList.add('updating');
        setTimeout(() => {
            tbody.innerHTML = `<tr>
                <td>${index}</td>
                <td><div class="pathway-name-stack">${renderPathwayNameLink(pw, pw.name)}${renderPathwayId(pw)}</div></td>
                <td>${formatPValue(pw.p_value)}</td>
                <td><span class="category-badge ${categoryClass}">${pw.category || '-'}</span></td>
            </tr>`;

            tbody.classList.remove('updating');
            currentIndex.textContent = index;
            prevBtn.disabled = index <= 1;
            nextBtn.disabled = index >= pathways.length;
        }, 100);
    }

    slider.addEventListener('input', (e) => updatePathway(parseInt(e.target.value)));
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

function formatPValue(pval) {
    if (!pval) return '-';
    if (pval < 0.0001) return pval.toExponential(1);
    return pval.toFixed(4);
}

function formatMarkdown(md) {
    if (!md) return '';

    let html = md;

    // Code blocks (must be before inline code)
    html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Headers (must be processed line by line)
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Bold and italic (handle *** before ** and *)
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

    // Unordered lists
    html = html.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');

    // Numbered lists
    html = html.replace(/^\d+\. (.+)$/gm, '<li class="numbered">$1</li>');

    // Wrap consecutive list items in ul/ol tags
    html = html.replace(/(<li>.*?<\/li>\n?)+/g, '<ul>$&</ul>');
    html = html.replace(/(<li class="numbered">.*?<\/li>\n?)+/g, function (match) {
        return '<ol>' + match.replace(/ class="numbered"/g, '') + '</ol>';
    });

    // Tables - proper markdown table rendering
    const lines = html.split('\n');
    let inTable = false;
    let tableHtml = '';
    let resultLines = [];
    let headerProcessed = false;

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();

        // Check if this is a table row (starts and ends with |)
        if (line.startsWith('|') && line.endsWith('|')) {
            // Check if this is a separator line (contains only |, -, :, spaces)
            if (line.match(/^\|[\s\-:|]+\|$/)) {
                // This is a separator line, skip it but mark header as processed
                headerProcessed = true;
                continue;
            }

            if (!inTable) {
                inTable = true;
                tableHtml = '<table class="md-table"><thead>';
                headerProcessed = false;
            }

            // Parse cells
            const cells = line.split('|').slice(1, -1).map(c => c.trim());

            if (!headerProcessed) {
                // This is the header row
                tableHtml += '<tr>' + cells.map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>';
            } else {
                // This is a body row
                tableHtml += '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
            }
        } else {
            // Not a table row
            if (inTable) {
                // Close the table
                tableHtml += '</tbody></table>';
                resultLines.push(tableHtml);
                inTable = false;
                tableHtml = '';
                headerProcessed = false;
            }
            resultLines.push(line);
        }
    }

    // Close any remaining table
    if (inTable) {
        tableHtml += '</tbody></table>';
        resultLines.push(tableHtml);
    }

    html = resultLines.join('\n');

    // Horizontal rules
    html = html.replace(/^---+$/gm, '<hr>');

    // Paragraphs (double newlines)
    html = html.replace(/\n\n+/g, '</p><p>');

    // Line breaks (single newlines, but not after block elements)
    html = html.replace(/([^>])\n([^<])/g, '$1<br>$2');

    // Clean up extra line breaks around block elements
    html = html.replace(/<br>\s*(<\/?(?:h[1-6]|p|ul|ol|pre|table|hr|thead|tbody|tr|th|td))/gi, '$1');
    html = html.replace(/(<\/(?:h[1-6]|p|ul|ol|pre|table|hr|thead|tbody|tr|th|td)>)\s*<br>/gi, '$1');

    // Wrap in paragraph tags if not already in block element
    if (!html.match(/^<(h[1-6]|p|ul|ol|pre|table)/)) {
        html = '<p>' + html + '</p>';
    }

    return html;
}


function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================================================
// TIGERAI-STYLED TOP 10 PATHWAYS RENDERING
// ============================================================================

/**
 * Render the complete results page with Top 10 pathways
 */
function renderTop10PathwaysResults(data) {
    const disease = data.disease || 'Disease';
    const geneCount = data.gene_count || 0;
    const pathways = data.pathways || [];
    const top10 = pathways.slice(0, 10);

    // Calculate summary scores
    const avgScore = top10.length > 0
        ? (top10.reduce((sum, p) => sum + (p.score || 0), 0) / top10.length).toFixed(1)
        : '0.0';
    const topPvalue = top10.length > 0 && top10[0].p_value
        ? formatPValue(top10[0].p_value)
        : '-';
    const strongCount = top10.filter(p => getEvidenceStrength(p.score) === 'strong').length;
    const overallStrength = getOverallStrength(avgScore);

    let html = `
        <!-- Results Hero -->
        <div class="results-hero">
            <div>
                <h1 class="results-hero-title">
                    ${escapeHtml(disease)}<span class="hero-x">×</span>Pathway Analysis
                </h1>
                <span class="gene-count-badge"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-chart-bar"></use></svg> ${geneCount} genes analyzed</span>
            </div>
            <div class="overall-status ${overallStrength}">
                <svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-check"></use></svg> ${capitalizeFirst(overallStrength)} Evidence
            </div>
        </div>
        
        <!-- Model Tabs -->
        <div class="model-tabs">
            <div class="model-tab active">
                <span class="model-tab-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-dna"></use></svg></span>
                <span>Interpretation</span>
            </div>
            <div class="model-tab">
                <span class="model-tab-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-chart-line"></use></svg></span>
                <span>Enrichment</span>
            </div>
        </div>
        
        <!-- Score Cards -->
        ${renderScoreCards(top10, avgScore, topPvalue, strongCount)}
        
        <!-- Top 10 Pathways Table -->
        <h3 style="margin-bottom: 16px; font-size: 1.1rem;"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-clipboard-text"></use></svg> Top 10 Ranked Pathways</h3>
        ${renderBrowseTable(top10)}
        
        <!-- Evidence Sections by Category -->
        ${renderEvidenceByCategory(top10)}
        
        <!-- Integration Summary -->
        ${renderIntegrationSummary(data, top10)}
    `;

    return html;
}

/**
 * Render score metric cards
 */
function renderScoreCards(pathways, avgScore, topPvalue, strongCount) {
    const uniqueCategories = [...new Set(pathways.map(p => p.category).filter(Boolean))];

    return `
        <div class="score-card-row">
            <div class="score-card">
                <div class="score-card-label">Avg Score</div>
                <div class="score-card-value highlight">${avgScore}</div>
            </div>
            <div class="score-card">
                <div class="score-card-label">Top p-value</div>
                <div class="score-card-value">${topPvalue}</div>
            </div>
            <div class="score-card">
                <div class="score-card-label">Strong Evidence</div>
                <div class="score-card-value">${strongCount}</div>
            </div>
            <div class="score-card">
                <div class="score-card-label">Categories</div>
                <div class="score-card-value">${uniqueCategories.length}</div>
            </div>
            <div class="score-card">
                <div class="score-card-label">Total Pathways</div>
                <div class="score-card-value">${pathways.length}</div>
            </div>
        </div>
    `;
}

/**
 * Render browse-style ranking table
 */
function renderBrowseTable(pathways) {
    if (!pathways || pathways.length === 0) {
        return '<p class="no-data">No pathways found.</p>';
    }

    let html = `
        <table class="browse-table">
            <thead>
                <tr>
                    <th style="width: 60px;">Rank</th>
                    <th>Pathway / ID</th>
                    <th style="width: 100px;">Category</th>
                    <th style="width: 100px;">p-value</th>
                    <th style="width: 100px;">Evidence</th>
                    <th style="width: 80px;">Score</th>
                </tr>
            </thead>
            <tbody>
    `;

    pathways.forEach((pw, i) => {
        const category = pw.category || 'Unknown';
        const categoryClass = category.replace(':', '-');
        const evidenceStrength = getEvidenceStrength(pw.score);
        const score = pw.score ? pw.score.toFixed(1) : '-';

        html += `
            <tr>
                <td class="rank-cell">${i + 1}</td>
                <td class="pathway-name"><div class="pathway-name-stack">${renderPathwayNameLink(pw, pw.name)}${renderPathwayId(pw)}</div></td>
                <td><span class="category-badge ${categoryClass}">${category}</span></td>
                <td>${formatPValue(pw.p_value)}</td>
                <td><span class="status-pill ${evidenceStrength}">${capitalizeFirst(evidenceStrength)}</span></td>
                <td class="score-cell">${score}</td>
            </tr>
        `;
    });

    html += `
            </tbody>
        </table>
    `;

    return html;
}

/**
 * Render evidence sections grouped by category
 */
function renderEvidenceByCategory(pathways) {
    const categories = {};
    pathways.forEach(pw => {
        const cat = pw.category || 'Other';
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(pw);
    });

    let html = '<div style="margin-top: 32px;">';
    html += '<h3 style="margin-bottom: 16px; font-size: 1.1rem;"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-books"></use></svg> Evidence by Category</h3>';

    const categoryIcons = {
        'GO:BP': phIcon('dna'),
        'GO:MF': phIcon('gear'),
        'GO:CC': phIcon('house'),
        'KEGG': phIcon('microscope'),
        'REAC': phIcon('arrows-clockwise'),
        'Other': phIcon('folder')
    };

    for (const [cat, pws] of Object.entries(categories)) {
        const icon = categoryIcons[cat] || phIcon('folder');
        const sectionId = `evidence-${cat.replace(/[^a-zA-Z0-9]/g, '-')}-${Date.now()}`;

        html += `
            <div class="evidence-section" id="${sectionId}">
                <div class="evidence-header" onclick="toggleEvidenceSection('${sectionId}')">
                    <div class="evidence-header-left">
                        <div class="evidence-icon">${icon}</div>
                        <span class="evidence-title">${cat} (${pws.length} pathways)</span>
                    </div>
                    <span class="evidence-toggle"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-caret-down"></use></svg></span>
                </div>
                <div class="evidence-content">
                    <div class="evidence-body">
                        ${pws.map(pw => renderPathwayEvidence(pw)).join('')}
                    </div>
                </div>
            </div>
        `;
    }

    html += '</div>';
    return html;
}

/**
 * Render individual pathway evidence item
 */
function renderPathwayEvidence(pathway) {
    const strength = getEvidenceStrength(pathway.score);
    const genes = pathway.genes || [];
    const pmids = pathway.literature || [];

    let html = `
        <div class="evidence-item">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                <strong style="color: var(--text-primary); font-size: 0.95rem;">${renderPathwayNameLink(pathway, pathway.name)}</strong>
                <span class="status-pill ${strength}">${capitalizeFirst(strength)}</span>
            </div>
    `;

    // Reasoning if available
    if (pathway.gpt_reasoning) {
        html += `<p class="evidence-text">${escapeHtml(pathway.gpt_reasoning)}</p>`;
    }

    // Gene pills
    if (genes.length > 0) {
        html += `
            <div class="gene-pills">
                ${genes.slice(0, 8).map(g => `<span class="gene-pill">${escapeHtml(g)}</span>`).join('')}
                ${genes.length > 8 ? `<span class="gene-pill">+${genes.length - 8} more</span>` : ''}
            </div>
        `;
    }

    // PMID links
    if (pmids.length > 0) {
        html += `
            <div class="pmid-links">
                ${pmids.map(pm => {
            const pmid = typeof pm === 'object' ? pm.pmid : pm;
            return `<a class="pmid-link" href="https://pubmed.ncbi.nlm.nih.gov/${pmid}" target="_blank">PMID:${pmid}</a>`;
        }).join('')}
            </div>
        `;
    }

    // Score and p-value info
    html += `
        <div style="margin-top: 8px; font-size: 0.8rem; color: var(--text-muted);">
            Score: ${pathway.score ? pathway.score.toFixed(1) : '-'} | p-value: ${formatPValue(pathway.p_value)}
        </div>
    `;

    html += '</div>';
    return html;
}

/**
 * Render integration summary section
 */
function renderIntegrationSummary(data, topPathways) {
    const disease = data.disease || 'the disease';
    const topPathwayNames = topPathways.slice(0, 3).map(p => p.name).join(', ');
    const categories = [...new Set(topPathways.map(p => p.category).filter(Boolean))];

    // Use AI reasoning if available, otherwise generate summary
    const summaryContent = data.integration_summary || data.gpt_summary ||
        `The analysis identified <strong>${topPathways.length}</strong> top-ranked pathways associated with ${disease}. ` +
        `The highest-scoring pathways include <strong>${topPathwayNames}</strong>. ` +
        `These pathways span ${categories.length} ontology categories (${categories.join(', ')}), ` +
        `suggesting diverse biological mechanisms underlying the disease phenotype.`;

    return `
        <div class="integration-summary">
            <div class="integration-summary-header">
                <span class="integration-summary-icon"><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-link-simple"></use></svg></span>
                <span class="integration-summary-title">Integration Summary</span>
            </div>
            <div class="integration-summary-content">
                ${summaryContent}
            </div>
        </div>
    `;
}

/**
 * Toggle evidence section expand/collapse
 */
function toggleEvidenceSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (section) {
        section.classList.toggle('expanded');
    }
}

// Make toggle function globally accessible
window.toggleEvidenceSection = toggleEvidenceSection;

/**
 * Helper: Get evidence strength from score
 */
function getEvidenceStrength(score) {
    if (!score) return 'insufficient';
    if (score >= 70) return 'strong';
    if (score >= 40) return 'moderate';
    if (score >= 20) return 'weak';
    return 'insufficient';
}

/**
 * Helper: Get overall strength classification
 */
function getOverallStrength(avgScore) {
    const score = parseFloat(avgScore);
    if (score >= 80) return 'very-strong';
    if (score >= 60) return 'strong';
    if (score >= 40) return 'moderate';
    if (score >= 20) return 'weak';
    return 'insufficient';
}

/**
 * Helper: Capitalize first letter
 */
function capitalizeFirst(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1).replace('-', ' ');
}

// ============================================================================
// EXPORT
// ============================================================================

function toggleExportDropdown(e) {
    e.stopPropagation();
    const dropdown = document.getElementById('export-dropdown');
    if (dropdown) {
        dropdown.classList.toggle('hidden');
    }
}

function closeExportDropdown() {
    const dropdown = document.getElementById('export-dropdown');
    if (dropdown) {
        dropdown.classList.add('hidden');
    }
}

function updateRetryNarrativesButton(pathways) {
    const button = elements.retryNarrativesBtn;
    if (!button) return;
    const unresolved = (pathways || []).filter(pathway =>
        pathway?.pathway_narrative?.generated !== true
    ).length;
    button.classList.toggle('hidden', unresolved === 0);
    button.disabled = false;
    button.innerHTML = '<span><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-arrows-clockwise"></use></svg> Refresh interpretations</span>';
    button.title = unresolved
        ? `${unresolved} pathway narrative${unresolved === 1 ? '' : 's'} require regeneration.`
        : 'Every pathway narrative passed validation.';
}

async function retryFallbackNarratives() {
    if (!state.sessionId) return;
    const button = elements.retryNarrativesBtn;
    const originalHtml = button?.innerHTML;
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span><svg class="ph ph-spin" aria-hidden="true" focusable="false"><use href="#ph-circle-notch"></use></svg> Starting…</span>';
    }
    try {
        const response = await fetch(`/api/retry-narratives/${state.sessionId}`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { Accept: 'application/json' }
        });
        const payload = await response.json();
        if (!response.ok || payload.error) {
            throw new Error(payload.error || `Interpretation refresh failed (${response.status})`);
        }
        if (payload.quota) updateQuotaStatus(payload.quota);
        state.sessionId = payload.session_id;
        state.isAnalyzing = true;
        state.analysisStartedAt = Date.now();
        document.body.classList.add('analysis-running-view');
        elements.resultsSection?.classList.add('hidden');
        elements.heroSection?.classList.add('hidden');
        elements.inputSection?.classList.add('hidden');
        elements.chatSection?.classList.remove('hidden');
        setActiveWorkflowStep('interpret');
        updateAnalysisProgress({
            percent: 1,
            stage: 'Queued',
            detail: 'Interpretation refresh was accepted.',
            state: 'queued',
            elapsed_seconds: 0,
        });
        showTyping(true);
        startPolling();
    } catch (error) {
        console.error('Interpretation refresh failed:', error);
        alert('Interpretation refresh failed: ' + error.message);
        if (button) {
            button.disabled = false;
            button.innerHTML = originalHtml;
        }
    }
}

function getPdfExportLimit() {
    const value = document.getElementById('pdf-export-limit')?.value || 'all';
    return value === 'all' ? Infinity : Number(value) || Infinity;
}

function getPdfExportLimitQuery() {
    const limit = getPdfExportLimit();
    return Number.isFinite(limit) ? String(limit) : 'all';
}

function prepareLocalPdf(format) {
    const resultsSection = elements.resultsSection || document.getElementById('results-section');
    const previousDetailed = resultsSection?.classList.contains('report-view--detailed');
    const previousDisplayLimit = pathwayDisplayLimit;
    const previousOpenItems = new Set(
        [...document.querySelectorAll('details.evidence-item[open]')]
            .map(item => `${item.dataset.category || ''}::${item.dataset.rank || ''}`)
    );
    const previousTitle = document.title;
    const targetView = format === 'pdf' ? 'detailed' : 'summary';
    const exportLimit = getPdfExportLimit();
    pathwayDisplayLimit = exportLimit;
    if (currentResults?.pathways) renderEvidenceSectionsView(currentResults.pathways);
    document.querySelectorAll('details.evidence-item').forEach(item => {
        item.open = true;
    });
    document.querySelectorAll('.summary-ranked-table tbody tr').forEach(row => {
        const rank = Number(row.dataset.exportRank) || Infinity;
        row.classList.toggle('pdf-export-excluded', Number.isFinite(exportLimit) && rank > exportLimit);
    });
    setReportView(targetView);
    closeExportDropdown();
    document.body.classList.add('local-pdf-print');
    document.title = format === 'pdf'
        ? 'GenePathwayAI_detailed_report'
        : 'GenePathwayAI_takeaway_summary';

    let restored = false;
    const restore = () => {
        if (restored) return;
        restored = true;
        document.body.classList.remove('local-pdf-print');
        document.title = previousTitle;
        document.querySelectorAll('.summary-ranked-table tbody tr').forEach(row => {
            row.classList.remove('pdf-export-excluded');
        });
        pathwayDisplayLimit = previousDisplayLimit;
        if (currentResults?.pathways) renderEvidenceSectionsView(currentResults.pathways);
        document.querySelectorAll('details.evidence-item').forEach(item => {
            const key = `${item.dataset.category || ''}::${item.dataset.rank || ''}`;
            item.open = previousOpenItems.has(key);
        });
        setReportView(previousDetailed ? 'detailed' : 'summary');
    };
    return restore;
}

// Exposed for deterministic browser regression checks; invoking it prepares
// the print DOM and returns a restore callback without opening a print dialog.
window.prepareLocalPdfExport = prepareLocalPdf;

function printLocalPdf(format) {
    if (typeof window.print !== 'function') {
        throw new Error('This browser does not provide a print-to-PDF function.');
    }
    const restore = prepareLocalPdf(format);
    window.addEventListener('afterprint', restore, { once: true });
    // The animation frame lets the requested Summary/Detailed layout settle
    // before the native dialog captures the document.
    requestAnimationFrame(() => window.setTimeout(() => {
        window.print();
        // Safari versions that omit afterprint still return from this call.
        window.setTimeout(restore, 250);
    }, 50));
}

async function exportData(format) {
    if (!state.sessionId) return;

    const btn = document.querySelector(`.export-option[data-format="${format}"]`);
    if (btn) {
        const originalText = btn.querySelector('.export-option-title').textContent;
        btn.querySelector('.export-option-title').textContent = 'Exporting...';
        btn.disabled = true;
    }

    try {
        const isPdf = format === 'pdf' || format === 'pdf-summary';
        if (isPdf && window.location.protocol === 'file:') {
            printLocalPdf(format);
            return;
        }
        if (format === 'csv' || format === 'json') {
            const link = document.createElement('a');
            link.href = `/api/export/${encodeURIComponent(state.sessionId)}/${format}?download=1`;
            link.download = '';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            return;
        }

        const exportUrl = `/api/export/${state.sessionId}/${format}${isPdf ? `?limit=${encodeURIComponent(getPdfExportLimitQuery())}` : ''}`;
        const response = await fetch(exportUrl, {
            credentials: 'same-origin',
            headers: isPdf ? { Accept: 'application/pdf' } : undefined
        });

        if (isPdf) {
            const contentType = (response.headers.get('Content-Type') || '').toLowerCase();
            if (!response.ok || !contentType.includes('application/pdf')) {
                let message = `Export failed (${response.status})`;
                try {
                    const errorPayload = JSON.parse(await response.text());
                    message = errorPayload.error || message;
                } catch (_) {
                    if (response.redirected || contentType.includes('text/html')) {
                        message = 'The export request returned a sign-in page. Please sign in again, then retry.';
                    } else if (response.ok) {
                        message = 'The server returned an invalid PDF response.';
                    }
                }
                throw new Error(message);
            }
            const blob = await response.blob();
            const signature = new TextDecoder('ascii').decode(
                await blob.slice(0, 5).arrayBuffer()
            );
            if (blob.size < 8 || signature !== '%PDF-') {
                throw new Error('The generated report was not a valid PDF. Please retry or contact the administrator.');
            }
            const disposition = response.headers.get('Content-Disposition') || '';
            const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
            const filename = filenameMatch?.[1] || (format === 'pdf-summary'
                ? 'GenePathwayAI_takeaway_summary.pdf'
                : 'GenePathwayAI_detailed_report.pdf');
            downloadExportBlob(blob, filename);
            return;
        }

    } catch (error) {
        console.error('Export failed:', error);
        alert('Export failed: ' + error.message);
    } finally {
        if (btn) {
            const titles = {
                'pdf-summary': 'Take-away Summary (.pdf)',
                'pdf': 'Detailed Report (.pdf)',
                'csv': 'Pathway Table (.csv)',
                'json': 'Raw Data (.json)'
            };
            btn.querySelector('.export-option-title').textContent = titles[format] || 'Export';
            btn.disabled = false;
        }
    }
}

function downloadExportBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ============================================================================
// RUN HISTORY
// ============================================================================

let historyData = [];

function showHistoryPanel() {
    document.body.classList.remove('analysis-running-view');
    document.body.classList.remove('results-view');
    hideProductTour({ followContinuation: false });
    document.getElementById('hero-section').classList.add('hidden');
    document.getElementById('hero-section').style.display = 'none';
    const resultsSection = document.getElementById('results-section');
    if (resultsSection) {
        resultsSection.classList.add('hidden');
        resultsSection.style.display = '';
    }
    const processSection = document.getElementById('process-section');
    if (processSection) processSection.style.display = 'none';
    const inputSection = document.getElementById('input-section');
    if (inputSection) {
        inputSection.classList.add('hidden');
        inputSection.style.display = 'none';
    }
    const chatSection = document.getElementById('chat-section');
    if (chatSection) chatSection.classList.add('hidden');
    document.getElementById('docs-section').style.display = 'none';

    document.getElementById('history-section').style.display = 'block';

    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const historyLink = document.querySelector('.nav-link[data-view="history"]');
    if (historyLink) historyLink.classList.add('active');

    loadHistory();
}

function showAnalysisView({ preserveActiveJob = false } = {}) {
    const url = new URL(window.location.href);
    const returningFromCompletedExample = url.searchParams.get('demo') === '1';
    if (returningFromCompletedExample) {
        url.searchParams.delete('demo');
        url.searchParams.delete('example');
        url.hash = '';
        window.history.replaceState(null, '', `${url.pathname}${url.search}`);
        setDiseaseCombobox('');
        setSelectedGenes([]);
        clearOpenTargetsGeneImportState();
        getFeaturedExamplesMenuItems().forEach(item => {
            item.classList.remove('is-current');
            item.removeAttribute('aria-current');
        });
    }
    document.body.classList.remove('analysis-running-view');
    document.body.classList.remove('results-view');
    document.getElementById('history-section').style.display = 'none';
    document.getElementById('docs-section').style.display = 'none';

    document.getElementById('hero-section').style.display = '';
    document.getElementById('hero-section').classList.remove('hidden');
    const inputSection = document.getElementById('input-section');
    if (inputSection) {
        inputSection.style.display = '';
        inputSection.classList.remove('hidden');
    }
    const chatSection = document.getElementById('chat-section');
    if (chatSection) chatSection.classList.add('hidden');
    const resultsSection = document.getElementById('results-section');
    if (resultsSection) resultsSection.classList.add('hidden');

    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const analysisLink = document.querySelector('.nav-link[data-view="analysis"]');
    if (analysisLink) analysisLink.classList.add('active');
    setActiveWorkflowStep('input');
    if (!preserveActiveJob) updateActiveJobBanner();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function loadHistory() {
    try {
        const response = await fetch('/api/history');
        const data = await response.json();
        historyData = data.history || [];
        renderHistoryTable(historyData);
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

function renderHistoryTable(entries) {
    const tbody = document.getElementById('history-tbody');
    const emptyState = document.getElementById('history-empty');
    const tableContainer = document.getElementById('history-table-container');
    const countEl = document.querySelector('.history-results-count');

    if (!entries || entries.length === 0) {
        tableContainer.style.display = 'none';
        emptyState.style.display = 'block';
        if (countEl) countEl.textContent = '';
        return;
    }

    tableContainer.style.display = 'block';
    emptyState.style.display = 'none';
    if (countEl) countEl.textContent = `${entries.length} result${entries.length !== 1 ? 's' : ''}`;

    tbody.innerHTML = entries.map(entry => {
        const createdDate = entry.created_at ? new Date(entry.created_at).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit'
        }) : 'Unknown';

        const statusClass = entry.status === 'completed' ? 'status-completed' :
                           entry.status === 'error' ? 'status-error' : 'status-other';
        const statusLabel = entry.status === 'completed' ? 'Completed' :
                           entry.status === 'error' ? 'Error' : entry.status;

        const shortId = entry.session_id ? entry.session_id.substring(0, 8) : 'N/A';

        return `
            <tr>
                <td>
                    <span class="session-id-cell" title="${entry.session_id}" onclick="copySessionId('${entry.session_id}')">
                        ${shortId} <span class="copy-icon"><svg class="ph ph-xs" aria-hidden="true" focusable="false"><use href="#ph-copy"></use></svg></span>
                    </span>
                </td>
                <td><strong>${escapeHtml(entry.disease_name || entry.disease || 'Unknown')}</strong></td>
                <td>
                    <span class="genes-preview" title="${escapeHtml(entry.genes_preview || '')}">
                        ${entry.gene_count || 0} genes
                    </span>
                </td>
                <td><span class="model-badge">${escapeHtml(entry.model || 'gpt-5.1')}</span></td>
                <td>${createdDate}</td>
                <td><span class="history-status ${statusClass}">${statusLabel}</span></td>
                <td class="history-actions">
                    ${entry.status === 'completed' ? `<button class="history-action-btn view-btn" onclick="viewHistoryEntry('${entry.session_id}')">View</button>` : ''}
                    <button class="history-action-btn rerun-btn" onclick="rerunHistoryEntry('${entry.session_id}')">Re-run</button>
                    <button class="history-action-btn delete-btn" onclick="deleteHistoryEntry('${entry.session_id}')">Delete</button>
                </td>
            </tr>
        `;
    }).join('');
}

function filterHistory() {
    const searchText = (document.getElementById('history-search').value || '').toLowerCase();
    const statusFilter = document.getElementById('history-status-filter').value;

    let filtered = historyData;

    if (searchText) {
        filtered = filtered.filter(e =>
            (e.disease_name || '').toLowerCase().includes(searchText) ||
            (e.disease || '').toLowerCase().includes(searchText) ||
            (e.genes_preview || '').toLowerCase().includes(searchText) ||
            (e.session_id || '').toLowerCase().includes(searchText)
        );
    }

    if (statusFilter) {
        filtered = filtered.filter(e => e.status === statusFilter);
    }

    renderHistoryTable(filtered);
}

function copySessionId(sessionId) {
    navigator.clipboard.writeText(sessionId).then(() => {}).catch(() => {});
}

async function viewHistoryEntry(sessionId) {
    try {
        const response = await fetch(`/api/history/${sessionId}`);
        if (!response.ok) {
            alert('Failed to load this analysis. It may have been deleted.');
            return;
        }
        const data = await response.json();

        document.getElementById('history-section').style.display = 'none';
        document.getElementById('docs-section').style.display = 'none';

        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        const analysisLink = document.querySelector('.nav-link[data-view="analysis"]');
        if (analysisLink) analysisLink.classList.add('active');

        if (data.results) {
            window.currentSessionId = sessionId;
            state.sessionId = sessionId;
            data.results.disease = data.disease_name || data.disease || data.results.disease;
            data.results.gene_count = data.gene_count || (data.genes ? data.genes.length : data.results.gene_count);
            data.results.created_at = data.created_at || data.results.created_at;
            data.results.completed_at = data.completed_at || data.results.completed_at;
            hydrateReasoningTraces(data.messages || data.results.reasoning_traces || []);
            showResults(data.results);
        }
    } catch (error) {
        console.error('Failed to view history entry:', error);
        alert('Failed to load analysis results.');
    }
}

async function rerunHistoryEntry(sessionId) {
    try {
        const response = await fetch(`/api/history/${sessionId}`);
        if (!response.ok) {
            alert('Failed to load this analysis for re-run.');
            return;
        }
        const data = await response.json();

        document.getElementById('history-section').style.display = 'none';
        document.getElementById('hero-section').style.display = '';
        const inputSection = document.getElementById('input-section');
        if (inputSection) inputSection.style.display = '';

        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        const analysisLink = document.querySelector('.nav-link[data-view="analysis"]');
        if (analysisLink) analysisLink.classList.add('active');

        const geneInput = document.getElementById('gene-input');
        const diseaseSelect = document.getElementById('disease-select');
        if (geneInput && data.genes) {
            geneInput.value = data.genes.join(', ');
            updateGeneCount();
        }
        if (data.disease) {
            setDiseaseCombobox(data.disease);
        }

        const heroSection = document.getElementById('hero-section');
        if (heroSection) heroSection.scrollIntoView({ behavior: 'smooth' });

    } catch (error) {
        console.error('Failed to prepare re-run:', error);
        alert('Failed to load analysis data for re-run.');
    }
}

async function deleteHistoryEntry(sessionId) {
    if (!confirm('Are you sure you want to delete this analysis from history?')) return;

    try {
        const response = await fetch(`/api/history/${sessionId}`, { method: 'DELETE' });
        if (response.ok) {
            loadHistory();
        } else {
            alert('Failed to delete entry.');
        }
    } catch (error) {
        console.error('Failed to delete:', error);
    }
}

// ============================================================================
// DOCUMENTATION
// ============================================================================

const DOCUMENTATION_ORDER = [
    { id: 'what-is', title: 'What is GenePathwayAI?' },
    { id: 'quick-start', title: 'Quick Start Guide' },
    { id: 'inputs', title: 'Genes & Disease Input' },
    { id: 'gene-mapping', title: 'Gene Mapping & QC' },
    { id: 'analysis-pipeline', title: 'Analysis Pipeline' },
    { id: 'pathway-categories', title: 'Pathway Categories' },
    { id: 'checkpoints', title: 'Interactive Checkpoints' },
    { id: 'results', title: 'Reading the Results' },
    { id: 'export-history', title: 'Export & History' },
    { id: 'usage', title: 'Usage Limits' },
    { id: 'data-sources', title: 'Data Sources' },
    { id: 'faq', title: 'FAQ' },
];

function getDocumentationHashId() {
    const match = String(window.location.hash || '').match(/^#docs\/([a-z0-9-]+)$/i);
    return match ? match[1] : '';
}

function showDocsPanel(requestedDocId = '') {
    document.body.classList.remove('analysis-running-view');
    document.body.classList.remove('results-view');
    hideProductTour({ followContinuation: false });
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.querySelector('.nav-link[data-view="docs"]').classList.add('active');

    document.getElementById('hero-section')?.classList.add('hidden');
    document.getElementById('input-section')?.classList.add('hidden');
    document.getElementById('chat-section')?.classList.add('hidden');
    document.getElementById('results-section')?.classList.add('hidden');
    document.getElementById('history-section').style.display = 'none';
    document.getElementById('docs-section').style.display = 'block';

    const docId = requestedDocId || getDocumentationHashId() || 'what-is';
    const targetLink = document.querySelector(`.docs-nav-link[data-doc="${docId}"]`);
    if (!switchDoc(docId, targetLink, false)) switchDoc('what-is', null, false);
    window.history.replaceState(null, '', `#docs/${document.querySelector('.doc-page.active')?.id.replace(/^doc-/, '') || 'what-is'}`);
}

window.showDocsPanel = showDocsPanel;

function switchDoc(docId, linkEl, updateHash = true) {
    document.querySelectorAll('.doc-page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.docs-nav-link').forEach(l => l.classList.remove('active'));

    const page = document.getElementById('doc-' + docId);
    const navLink = linkEl || document.querySelector(`.docs-nav-link[data-doc="${docId}"]`);
    if (!page) return false;

    page.classList.add('active');
    if (navLink) navLink.classList.add('active');
    renderDocumentationPager(page, docId);
    if (updateHash) window.history.replaceState(null, '', `#docs/${docId}`);

    const content = document.querySelector('.docs-content');
    if (content) content.scrollTop = 0;
    return true;
}

window.switchDoc = switchDoc;

function renderDocumentationPager(page, docId) {
    page.querySelector('.doc-pager')?.remove();

    const currentIndex = DOCUMENTATION_ORDER.findIndex(item => item.id === docId);
    if (currentIndex < 0) return;

    const pager = document.createElement('nav');
    pager.className = 'doc-pager';
    pager.setAttribute('aria-label', 'Documentation pages');

    const addPagerItem = (item, direction) => {
        if (!item) {
            const placeholder = document.createElement('span');
            placeholder.className = 'doc-pager-placeholder';
            pager.appendChild(placeholder);
            return;
        }

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'doc-pager-button';
        button.innerHTML = `<small>${direction === 'previous'
            ? `${phIcon('arrow-left', 'ph-xs')} Previous`
            : `Next ${phIcon('arrow-right', 'ph-xs')}`}</small><strong>${escapeHtml(item.title)}</strong>`;
        button.addEventListener('click', () => switchDoc(item.id));
        pager.appendChild(button);
    };

    addPagerItem(DOCUMENTATION_ORDER[currentIndex - 1], 'previous');
    addPagerItem(DOCUMENTATION_ORDER[currentIndex + 1], 'next');
    page.appendChild(pager);
}

function filterDocumentation(rawQuery) {
    const query = String(rawQuery || '').trim().toLowerCase();
    const links = Array.from(document.querySelectorAll('.docs-nav-link'));

    links.forEach(link => {
        const docId = link.dataset.doc;
        const page = docId ? document.getElementById(`doc-${docId}`) : null;
        const searchableText = `${link.textContent || ''} ${page?.textContent || ''}`.toLowerCase();
        link.hidden = Boolean(query) && !searchableText.includes(query);
    });

    document.querySelectorAll('.docs-nav-group').forEach(group => {
        let sibling = group.nextElementSibling;
        let hasVisibleLink = false;
        while (sibling && !sibling.classList.contains('docs-nav-group')) {
            if (sibling.classList.contains('docs-nav-link') && !sibling.hidden) {
                hasVisibleLink = true;
            }
            sibling = sibling.nextElementSibling;
        }
        group.classList.toggle('is-hidden', !hasVisibleLink);
    });

    const visibleInternalLinks = links.filter(link => link.dataset.doc && !link.hidden);
    const emptyState = document.getElementById('docs-search-empty');
    if (emptyState) emptyState.hidden = visibleInternalLinks.length > 0;

    const activeLink = document.querySelector('.docs-nav-link.active');
    if (query && activeLink?.hidden && visibleInternalLinks.length) {
        switchDoc(visibleInternalLinks[0].dataset.doc, visibleInternalLinks[0]);
    }
}

window.filterDocumentation = filterDocumentation;

document.addEventListener('DOMContentLoaded', () => {
    const docId = getDocumentationHashId();
    if (docId) showDocsPanel(docId);
});

async function clearAllHistory() {
    if (!confirm('Are you sure you want to clear all history? This cannot be undone.')) return;

    try {
        const response = await fetch('/api/history', { method: 'DELETE' });
        if (response.ok) {
            loadHistory();
        }
    } catch (error) {
        console.error('Failed to clear history:', error);
    }
}
