const adminElements = {
    email: document.getElementById('admin-user-email'),
    status: document.getElementById('admin-status'),
    refresh: document.getElementById('admin-refresh'),
    managedUsers: document.getElementById('admin-managed-users'),
    globalUsage: document.getElementById('admin-global-usage'),
    activeJobs: document.getElementById('admin-active-jobs'),
    defaultLimit: document.getElementById('admin-default-limit'),
    quotaDay: document.getElementById('admin-quota-day'),
    rows: document.getElementById('admin-user-rows'),
};

let adminPayload = null;

function setAdminStatus(message, state = '') {
    adminElements.status.textContent = message;
    adminElements.status.className = `admin-status${state ? ` is-${state}` : ''}`;
}

async function readJson(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
}

function createTextElement(tag, text, className = '') {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
}

function renderAdminUser(user) {
    const row = document.createElement('tr');

    const userCell = document.createElement('td');
    userCell.className = 'admin-user-cell';
    userCell.appendChild(createTextElement('strong', user.email));
    userCell.appendChild(createTextElement(
        'span',
        user.limit_source === 'override' ? 'Custom limit' : 'Default limit',
    ));
    row.appendChild(userCell);

    const statusCell = document.createElement('td');
    statusCell.appendChild(createTextElement(
        'span',
        user.registered ? 'Active' : 'Not yet seen',
        `admin-badge${user.registered ? '' : ' admin-badge--pending'}`,
    ));
    row.appendChild(statusCell);
    row.appendChild(createTextElement('td', String(user.used)));

    const limitCell = document.createElement('td');
    const editor = document.createElement('div');
    editor.className = 'admin-limit-editor';
    const input = document.createElement('input');
    input.className = 'admin-limit-input';
    input.type = 'number';
    input.min = '1';
    input.max = String(adminPayload.max_user_limit || 200);
    input.value = String(user.limit);
    input.setAttribute('aria-label', `Daily limit for ${user.email}`);
    editor.appendChild(input);
    limitCell.appendChild(editor);
    row.appendChild(limitCell);

    row.appendChild(createTextElement('td', String(user.remaining)));

    const actionCell = document.createElement('td');
    const save = createTextElement('button', 'Save', 'admin-button');
    save.type = 'button';
    save.addEventListener('click', () => updateUserLimit(user.email, Number(input.value), save));
    actionCell.appendChild(save);
    if (user.limit_source === 'override') {
        const reset = createTextElement('button', 'Use default', 'admin-button admin-button--text');
        reset.type = 'button';
        reset.addEventListener('click', () => updateUserLimit(user.email, null, reset));
        actionCell.appendChild(reset);
    }
    row.appendChild(actionCell);
    return row;
}

function renderAdminDashboard(payload) {
    adminPayload = payload;
    adminElements.managedUsers.textContent = String(payload.managed_user_count || payload.users?.length || 0);
    adminElements.globalUsage.textContent = `${payload.global_used || 0} / ${payload.global_limit || 0}`;
    adminElements.activeJobs.textContent = `${payload.active_jobs || 0} / ${payload.max_concurrent_jobs || 1}`;
    adminElements.defaultLimit.textContent = String(payload.default_user_limit || 0);
    adminElements.quotaDay.textContent = payload.day ? `${payload.day} · resets 00:00 UTC` : '';
    adminElements.rows.replaceChildren(...(payload.users || []).map(renderAdminUser));
}

async function loadAdminDashboard(showSuccess = false) {
    adminElements.refresh.disabled = true;
    setAdminStatus('Loading…');
    try {
        const payload = await readJson(await fetch('/api/admin/users', {
            headers: {Accept: 'application/json'},
        }));
        renderAdminDashboard(payload);
        setAdminStatus(
            payload.enabled ? (showSuccess ? 'Updated.' : '') : 'Daily quota enforcement is disabled.',
            showSuccess ? 'success' : '',
        );
    } catch (error) {
        setAdminStatus(error.message, 'error');
    } finally {
        adminElements.refresh.disabled = false;
    }
}

async function updateUserLimit(email, dailyLimit, button) {
    if (dailyLimit !== null && (!Number.isInteger(dailyLimit) || dailyLimit < 1 || dailyLimit > (adminPayload.max_user_limit || 200))) {
        setAdminStatus(`Enter a whole number from 1 to ${adminPayload.max_user_limit || 200}.`, 'error');
        return;
    }
    button.disabled = true;
    setAdminStatus('Saving…');
    try {
        await readJson(await fetch(`/api/admin/users/${encodeURIComponent(email)}/quota`, {
            method: 'PUT',
            headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
            body: JSON.stringify({daily_limit: dailyLimit}),
        }));
        await loadAdminDashboard(true);
    } catch (error) {
        setAdminStatus(error.message, 'error');
        button.disabled = false;
    }
}

async function initializeAdmin() {
    try {
        const identity = await readJson(await fetch('/api/auth/me', {
            headers: {Accept: 'application/json'},
        }));
        if (!identity.is_admin) {
            window.location.replace('/');
            return;
        }
        adminElements.email.textContent = identity.email || '';
        await loadAdminDashboard();
    } catch (error) {
        setAdminStatus(error.message, 'error');
    }
}

adminElements.refresh.addEventListener('click', () => loadAdminDashboard(true));
initializeAdmin();
