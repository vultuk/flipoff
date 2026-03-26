const loginShell = document.getElementById('login-shell');
const dashboardShell = document.getElementById('dashboard-shell');
const loginPanel = document.getElementById('login-panel');
const loginForm = document.getElementById('login-form');
const settingsForm = document.getElementById('settings-form');
const screensForm = document.getElementById('screens-form');
const messageForm = document.getElementById('message-form');
const logoutBtn = document.getElementById('logout-btn');
const clearMessageBtn = document.getElementById('clear-message-btn');
const statusMessage = document.getElementById('status-message');

const colsInput = document.getElementById('cols');
const rowsInput = document.getElementById('rows');
const messageDurationInput = document.getElementById('message-duration');
const durationInput = document.getElementById('api-duration');
const adminPasswordSettingInput = document.getElementById('admin-password-setting');
const adminPasswordConfirmSettingInput = document.getElementById('admin-password-confirm-setting');
const passwordInput = document.getElementById('password');
const remoteMessageInput = document.getElementById('remote-message');

const screensList = document.getElementById('screens-list');
const screensDraftNote = document.getElementById('screens-draft-note');
const pluginCatalogNote = document.getElementById('plugin-catalog-note');
const addScreenBtn = document.getElementById('add-screen-btn');
const screenModal = document.getElementById('screen-modal');
const screenModalForm = document.getElementById('screen-modal-form');
const screenModalTitle = document.getElementById('screen-modal-title');
const screenTypeSelect = document.getElementById('screen-type-select');
const screenNameInput = document.getElementById('screen-name-input');
const manualScreenFields = document.getElementById('manual-screen-fields');
const pluginScreenFields = document.getElementById('plugin-screen-fields');
const screenLineFields = document.getElementById('screen-line-fields');
const pluginSelect = document.getElementById('plugin-select');
const pluginRefreshMinutesInput = document.getElementById('plugin-refresh-minutes');
const pluginSettingsFields = document.getElementById('plugin-settings-fields');
const pluginCommonSettingsSection = document.getElementById('plugin-common-settings-section');
const pluginCommonSettingsFields = document.getElementById('plugin-common-settings-fields');
const pluginDesignFields = document.getElementById('plugin-design-fields');
const closeScreenModalBtn = document.getElementById('close-screen-modal-btn');
const cancelScreenModalBtn = document.getElementById('cancel-screen-modal-btn');

const workspaceTitle = document.getElementById('workspace-title');
const workspaceCopy = document.getElementById('workspace-copy');
const navButtons = Array.from(document.querySelectorAll('[data-page-target]'));
const pagePanels = Array.from(document.querySelectorAll('.workspace-page'));

let currentConfig = null;
let availablePlugins = [];
let pluginCommonSettings = {};
let screenDrafts = [];
let screensDirty = false;
let activePage = 'home';
let editingScreenIndex = null;
let draggedScreenIndex = null;

loginForm.addEventListener('submit', handleLogin);
settingsForm.addEventListener('submit', handleSaveSettings);
screensForm.addEventListener('submit', handleSaveScreens);
messageForm.addEventListener('submit', handleSendMessage);
logoutBtn.addEventListener('click', handleLogout);
clearMessageBtn.addEventListener('click', handleClearMessage);
addScreenBtn.addEventListener('click', () => openScreenModal());
screensList.addEventListener('click', handleScreensListClick);
screensList.addEventListener('dragstart', handleScreenDragStart);
screensList.addEventListener('dragover', handleScreenDragOver);
screensList.addEventListener('drop', handleScreenDrop);
screensList.addEventListener('dragend', clearDragState);
screenModalForm.addEventListener('submit', handleSaveScreenModal);
screenTypeSelect.addEventListener('change', handleScreenTypeChange);
pluginSelect.addEventListener('change', handlePluginSelectionChange);
closeScreenModalBtn.addEventListener('click', closeScreenModal);
cancelScreenModalBtn.addEventListener('click', closeScreenModal);
screenModal.addEventListener('cancel', () => {
  editingScreenIndex = null;
});

for (const navButton of navButtons) {
  navButton.addEventListener('click', () => {
    switchPage(navButton.dataset.pageTarget);
  });
}

void loadAdminState();

async function loadAdminState({ successMessage = 'Admin ready.', showSuccessMessage = true } = {}) {
  try {
    const configResponse = await fetch('/api/admin/config', { credentials: 'same-origin' });

    if (configResponse.status === 401) {
      showLogin();
      return;
    }

    if (!configResponse.ok) {
      const error = await readError(configResponse, 'Unable to load admin configuration.');
      showLogin();
      setStatus(error, 'error');
      return;
    }

    const screensResponse = await fetch('/api/admin/screens', { credentials: 'same-origin' });
    if (screensResponse.status === 401) {
      showLogin();
      return;
    }

    if (!screensResponse.ok) {
      const error = await readError(screensResponse, 'Unable to load screen definitions.');
      showLogin();
      setStatus(error, 'error');
      return;
    }

    const config = await configResponse.json();
    const screensPayload = await screensResponse.json();
    showDashboard(config, screensPayload);

    if (showSuccessMessage) {
      setStatus(successMessage, 'success');
    }
  } catch {
    showLogin();
    setStatus('Unable to reach the admin API.', 'error');
  }
}

async function handleLogin(event) {
  event.preventDefault();
  setStatus('Checking password...');

  try {
    const response = await fetch('/api/admin/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ password: passwordInput.value }),
    });

    if (!response.ok) {
      setStatus(await readError(response, 'Login failed.'), 'error');
      return;
    }

    passwordInput.value = '';
    await loadAdminState();
  } catch {
    setStatus('Unable to reach the admin API.', 'error');
  }
}

async function handleSaveSettings(event) {
  event.preventDefault();

  if (!currentConfig) {
    setStatus('Load the admin config before saving settings.', 'error');
    return;
  }

  if (screensDirty) {
    setStatus('Save screens before changing settings so the draft screen stack is not lost.', 'error');
    return;
  }

  setStatus('Saving settings...');

  const nextAdminPassword = adminPasswordSettingInput.value;
  const confirmAdminPassword = adminPasswordConfirmSettingInput.value;
  if (nextAdminPassword || confirmAdminPassword) {
    if (nextAdminPassword !== confirmAdminPassword) {
      setStatus('The new admin password confirmation does not match.', 'error');
      return;
    }
  }

  try {
    const payload = {
      cols: Number(colsInput.value),
      rows: Number(rowsInput.value),
      messageDurationSeconds: Number(messageDurationInput.value),
      apiMessageDurationSeconds: Number(durationInput.value),
    };

    if (nextAdminPassword) {
      payload.adminPassword = nextAdminPassword;
    }

    const response = await fetch('/api/admin/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      setStatus(await readError(response, 'Save failed.'), 'error');
      return;
    }

    adminPasswordSettingInput.value = '';
    adminPasswordConfirmSettingInput.value = '';
    await loadAdminState({
      successMessage: nextAdminPassword
        ? 'Settings and admin password saved. Display pages will refresh automatically.'
        : 'Settings saved. Display pages will refresh automatically.',
      showSuccessMessage: true,
    });
  } catch {
    setStatus('Unable to reach the admin API.', 'error');
  }
}

async function handleSaveScreens(event) {
  event.preventDefault();

  if (!currentConfig) {
    setStatus('Load the admin config before saving screens.', 'error');
    return;
  }

  setStatus('Saving screens...');

  try {
    const response = await fetch('/api/admin/screens', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        pluginCommonSettings,
        screens: screenDrafts.map(serializeScreenForSave),
      }),
    });

    if (!response.ok) {
      setStatus(await readError(response, 'Save failed.'), 'error');
      return;
    }

    await loadAdminState({
      successMessage: 'Screens saved. Display pages will refresh automatically.',
      showSuccessMessage: true,
    });
  } catch {
    setStatus('Unable to reach the admin API.', 'error');
  }
}

async function handleLogout() {
  try {
    await fetch('/api/admin/session', {
      method: 'DELETE',
      credentials: 'same-origin',
    });
  } catch {
    // Clear local state even if the request fails.
  }

  currentConfig = null;
  availablePlugins = [];
  pluginCommonSettings = {};
  screenDrafts = [];
  screensDirty = false;
  editingScreenIndex = null;
  remoteMessageInput.value = '';
  closeScreenModal();
  showLogin();
  setStatus('Logged out.');
}

async function handleSendMessage(event) {
  event.preventDefault();

  const message = remoteMessageInput.value.trim();
  if (!message) {
    setStatus('Enter a message before sending it.', 'error');
    return;
  }

  setStatus('Sending remote message...');

  try {
    const response = await fetch('/api/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ message }),
    });

    if (!response.ok) {
      setStatus(await readError(response, 'Unable to send the remote message.'), 'error');
      return;
    }

    setStatus('Remote message sent.', 'success');
  } catch {
    setStatus('Unable to reach the admin API.', 'error');
  }
}

async function handleClearMessage() {
  setStatus('Clearing active override...');

  try {
    const response = await fetch('/api/message', {
      method: 'DELETE',
      credentials: 'same-origin',
    });

    if (!response.ok) {
      setStatus(await readError(response, 'Unable to clear the remote message.'), 'error');
      return;
    }

    setStatus('Remote override cleared.', 'success');
  } catch {
    setStatus('Unable to reach the admin API.', 'error');
  }
}

function handleScreensListClick(event) {
  const actionButton = event.target.closest('[data-screen-action]');
  if (!actionButton) {
    return;
  }

  const screenItem = actionButton.closest('.screen-item');
  if (!screenItem) {
    return;
  }

  const index = Number(screenItem.dataset.index);
  const action = actionButton.dataset.screenAction;

  if (action === 'edit') {
    openScreenModal(index);
    return;
  }

  if (action === 'delete') {
    if (screenDrafts.length <= 1) {
      setStatus('At least one screen is required.', 'error');
      return;
    }

    screenDrafts.splice(index, 1);
    markScreensDirty('Screen removed locally. Save screens to persist the new stack.');
    renderScreensList();
    return;
  }

  if (action === 'refresh') {
    void refreshPluginScreen(index);
  }
}

function handleScreenDragStart(event) {
  const screenItem = event.target.closest('.screen-item');
  if (!screenItem) {
    return;
  }

  draggedScreenIndex = Number(screenItem.dataset.index);
  screenItem.classList.add('dragging');

  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', screenItem.dataset.index);
  }
}

function handleScreenDragOver(event) {
  if (draggedScreenIndex === null) {
    return;
  }

  const targetItem = event.target.closest('.screen-item');
  if (!targetItem) {
    return;
  }

  event.preventDefault();
  clearDragIndicators();

  const targetIndex = Number(targetItem.dataset.index);
  if (targetIndex !== draggedScreenIndex) {
    targetItem.classList.add('drag-over');
  }
}

function handleScreenDrop(event) {
  if (draggedScreenIndex === null) {
    return;
  }

  const targetItem = event.target.closest('.screen-item');
  if (!targetItem) {
    return;
  }

  event.preventDefault();

  const targetIndex = Number(targetItem.dataset.index);
  if (targetIndex === draggedScreenIndex) {
    clearDragState();
    return;
  }

  const targetBounds = targetItem.getBoundingClientRect();
  const placeAfter = event.clientY > targetBounds.top + targetBounds.height / 2;
  const movedScreen = screenDrafts.splice(draggedScreenIndex, 1)[0];
  let insertIndex = targetIndex;

  if (draggedScreenIndex < targetIndex) {
    insertIndex = placeAfter ? targetIndex : targetIndex - 1;
  } else if (placeAfter) {
    insertIndex = targetIndex + 1;
  }

  screenDrafts.splice(insertIndex, 0, movedScreen);
  markScreensDirty('Screen order changed locally. Save screens to persist the new rotation.');
  renderScreensList();
}

function handleSaveScreenModal(event) {
  event.preventDefault();

  if (!currentConfig) {
    setStatus('Load the admin config before editing screens.', 'error');
    return;
  }

  const type = screenTypeSelect.value;
  const name = screenNameInput.value.trim();
  const id = editingScreenIndex === null ? createLocalScreenId() : screenDrafts[editingScreenIndex].id;

  if (type === 'manual') {
    const lines = Array.from(screenLineFields.querySelectorAll('input')).map((input) => input.value.trim());
    const lastPopulatedIndex = findLastPopulatedIndex(lines);

    if (lastPopulatedIndex === -1) {
      setStatus('Enter at least one line for the manual screen.', 'error');
      return;
    }

    upsertScreenDraft(editingScreenIndex, {
      id,
      type: 'manual',
      name,
      enabled: true,
      lines: lines.slice(0, lastPopulatedIndex + 1),
    });
    closeScreenModal();
    return;
  }

  const plugin = getPluginById(pluginSelect.value);
  if (!plugin) {
    setStatus('Select a plugin before saving the screen.', 'error');
    return;
  }

  const refreshMinutes = Number(pluginRefreshMinutesInput.value);
  if (!Number.isInteger(refreshMinutes) || refreshMinutes < 1) {
    setStatus('Refresh interval must be at least 1 minute.', 'error');
    return;
  }

  const settings = collectSchemaValues(plugin.settingsSchema, 'settings');
  const commonSettings = collectSchemaValues(plugin.commonSettingsSchema || [], 'common');
  const design = collectSchemaValues(plugin.designSchema, 'design');

  if (plugin.commonSettingsNamespace) {
    pluginCommonSettings[plugin.commonSettingsNamespace] = commonSettings;
  }

  upsertScreenDraft(editingScreenIndex, {
    id,
    type: 'plugin',
    name,
    enabled: true,
    pluginId: plugin.id,
    pluginName: plugin.name,
    refreshIntervalSeconds: refreshMinutes * 60,
    settings,
    design,
    lastError: null,
    lastRefreshedAt: null,
  });
  closeScreenModal();
}

function handleScreenTypeChange() {
  syncModalSections();
}

function handlePluginSelectionChange() {
  renderPluginSchemaFields();
}

async function refreshPluginScreen(index) {
  const screen = screenDrafts[index];
  if (!screen || screen.type !== 'plugin') {
    return;
  }

  if (screensDirty) {
    setStatus('Save screens before refreshing a plugin screen so the server is using the same configuration.', 'error');
    return;
  }

  setStatus(`Refreshing ${getScreenTitle(screen, index)}...`);

  try {
    const response = await fetch(`/api/admin/screens/${encodeURIComponent(screen.id)}/refresh`, {
      method: 'POST',
      credentials: 'same-origin',
    });

    if (!response.ok) {
      setStatus(await readError(response, 'Unable to refresh the plugin screen.'), 'error');
      return;
    }

    await loadAdminState({
      successMessage: `${getScreenTitle(screen, index)} refreshed.`,
      showSuccessMessage: true,
    });
  } catch {
    setStatus('Unable to reach the admin API.', 'error');
  }
}

function showLogin() {
  loginShell.classList.remove('hidden');
  dashboardShell.classList.add('hidden');
  loginPanel.classList.remove('hidden');
  switchPage('home');
  passwordInput.focus();
}

function showDashboard(config, screensPayload) {
  loginShell.classList.add('hidden');
  dashboardShell.classList.remove('hidden');
  applyConfig(config);
  applyScreensPayload(screensPayload);
  switchPage(activePage);
}

function applyConfig(config) {
  currentConfig = {
    cols: config.cols,
    rows: config.rows,
    messageDurationSeconds: config.messageDurationSeconds,
    apiMessageDurationSeconds: config.apiMessageDurationSeconds,
  };

  colsInput.value = String(config.cols);
  rowsInput.value = String(config.rows);
  messageDurationInput.value = String(config.messageDurationSeconds);
  durationInput.value = String(config.apiMessageDurationSeconds);
}

function applyScreensPayload(payload) {
  availablePlugins = clone(payload.plugins || []);
  pluginCommonSettings = clone(payload.pluginCommonSettings || {});
  screenDrafts = clone(payload.screens || []);
  screensDirty = false;
  updateScreensDraftNote();
  updatePluginCatalogNote();
  renderScreensList();
}

function renderScreensList() {
  screensList.replaceChildren();

  if (screenDrafts.length === 0) {
    const emptyState = document.createElement('div');
    emptyState.className = 'screen-empty';
    emptyState.textContent = 'No screens configured yet.';
    screensList.append(emptyState);
    return;
  }

  for (const [index, screen] of screenDrafts.entries()) {
    const screenItem = document.createElement('article');
    screenItem.className = 'screen-item';
    screenItem.draggable = true;
    screenItem.dataset.index = String(index);

    const header = document.createElement('div');
    header.className = 'screen-item-header';

    const titleGroup = document.createElement('div');

    const title = document.createElement('h3');
    title.className = 'screen-item-title';
    title.textContent = getScreenTitle(screen, index);

    const meta = document.createElement('div');
    meta.className = 'screen-item-meta';
    meta.append(
      buildScreenChip(screen.type === 'manual' ? 'Manual' : 'Plugin', screen.type === 'manual' ? '' : 'accent'),
    );

    if (screen.type === 'plugin') {
      meta.append(buildScreenChip(screen.pluginName || screen.pluginId));
      meta.append(buildScreenChip(`${Math.round(screen.refreshIntervalSeconds / 60)} min`));

      if (screen.lastError) {
        meta.append(buildScreenChip('Needs attention', 'error'));
      } else if (screen.lastRefreshedAt) {
        meta.append(buildScreenChip(`Updated ${formatTimestamp(screen.lastRefreshedAt)}`));
      }
    }

    titleGroup.append(title, meta);

    const actions = document.createElement('div');
    actions.className = 'screen-item-actions';
    actions.append(
      buildScreenActionButton('drag-handle', 'Drag to reorder'),
    );

    if (screen.type === 'plugin') {
      actions.append(buildScreenActionButton('', 'Refresh', 'refresh'));
    }

    actions.append(
      buildScreenActionButton('', 'Edit', 'edit'),
      buildScreenActionButton('danger', 'Delete', 'delete'),
    );

    header.append(titleGroup, actions);

    const copy = document.createElement('p');
    copy.className = 'screen-item-copy';
    copy.textContent = getScreenSummary(screen);

    const preview = document.createElement('div');
    preview.className = 'screen-preview';

    for (const line of getScreenPreviewLines(screen)) {
      const lineElement = document.createElement('div');
      lineElement.className = 'screen-preview-line';
      if (!line) {
        lineElement.classList.add('is-empty');
      } else {
        lineElement.textContent = line;
      }
      preview.append(lineElement);
    }

    screenItem.append(header, copy, preview);
    screensList.append(screenItem);
  }
}

function buildScreenChip(label, extraClassName = '') {
  const chip = document.createElement('span');
  chip.className = ['screen-chip', extraClassName].filter(Boolean).join(' ');
  chip.textContent = label;
  return chip;
}

function buildScreenActionButton(extraClassName, label, action = '') {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = ['screen-action', extraClassName].filter(Boolean).join(' ');
  button.textContent = label;

  if (action) {
    button.dataset.screenAction = action;
  }

  return button;
}

function openScreenModal(index = null) {
  if (!currentConfig) {
    setStatus('Load the admin config before editing screens.', 'error');
    return;
  }

  editingScreenIndex = index;
  const draft = index === null ? buildDefaultManualDraft() : clone(screenDrafts[index]);

  screenModalTitle.textContent = index === null ? 'Add Screen' : `Edit ${getScreenTitle(draft, index)}`;
  screenTypeSelect.value = draft.type;
  screenNameInput.value = draft.name || '';

  renderManualFields(draft.type === 'manual' ? draft.lines : []);
  populatePluginSelect(draft.pluginId);
  populatePluginEditor(draft);
  syncModalSections();

  if (typeof screenModal.showModal === 'function') {
    screenModal.showModal();
  } else {
    screenModal.setAttribute('open', 'open');
  }

  const firstInput = screenModal.querySelector('input, select, textarea');
  if (firstInput) {
    firstInput.focus();
  }
}

function closeScreenModal() {
  editingScreenIndex = null;

  if (typeof screenModal.close === 'function' && screenModal.open) {
    screenModal.close();
    return;
  }

  screenModal.removeAttribute('open');
}

function populatePluginSelect(selectedPluginId = '') {
  pluginSelect.replaceChildren();

  for (const plugin of availablePlugins) {
    const option = document.createElement('option');
    option.value = plugin.id;
    option.textContent = plugin.name;
    pluginSelect.append(option);
  }

  if (selectedPluginId && getPluginById(selectedPluginId)) {
    pluginSelect.value = selectedPluginId;
    return;
  }

  if (availablePlugins[0]) {
    pluginSelect.value = availablePlugins[0].id;
  }
}

function populatePluginEditor(draft) {
  const plugin = getPluginById(draft.pluginId || pluginSelect.value);
  if (!plugin) {
    pluginRefreshMinutesInput.value = '60';
    pluginSettingsFields.replaceChildren();
    pluginCommonSettingsFields.replaceChildren();
    pluginDesignFields.replaceChildren();
    pluginCommonSettingsSection.classList.add('hidden');
    return;
  }

  pluginSelect.value = plugin.id;
  pluginRefreshMinutesInput.value = String(Math.max(1, Math.round((draft.refreshIntervalSeconds || plugin.defaultRefreshIntervalSeconds) / 60)));
  renderPluginSchemaFields(draft.settings || {}, draft.design || {});
}

function renderPluginSchemaFields(settingsValues = null, designValues = null) {
  const plugin = getPluginById(pluginSelect.value);

  pluginSettingsFields.replaceChildren();
  pluginCommonSettingsFields.replaceChildren();
  pluginDesignFields.replaceChildren();

  if (!plugin) {
    pluginCommonSettingsSection.classList.add('hidden');
    return;
  }

  for (const field of plugin.settingsSchema) {
    pluginSettingsFields.append(buildSchemaField(field, 'settings', settingsValues));
  }

  const commonSettingsValues = plugin.commonSettingsNamespace
    ? pluginCommonSettings[plugin.commonSettingsNamespace] || {}
    : {};
  const commonSchema = plugin.commonSettingsSchema || [];
  pluginCommonSettingsSection.classList.toggle('hidden', commonSchema.length === 0);

  for (const field of commonSchema) {
    pluginCommonSettingsFields.append(buildSchemaField(field, 'common', commonSettingsValues));
  }

  for (const field of plugin.designSchema) {
    pluginDesignFields.append(buildSchemaField(field, 'design', designValues));
  }
}

function buildSchemaField(field, sectionName, values) {
  const wrapper = document.createElement('label');
  wrapper.className = 'field';

  const label = document.createElement('span');
  label.textContent = field.label;

  const value = values && field.name in values ? values[field.name] : field.default;
  let control;

  if (field.type === 'select') {
    control = document.createElement('select');
    for (const option of field.options || []) {
      const optionEl = document.createElement('option');
      optionEl.value = option.value;
      optionEl.textContent = option.label;
      control.append(optionEl);
    }
    control.value = value ?? '';
  } else if (field.type === 'checkbox') {
    control = document.createElement('input');
    control.type = 'checkbox';
    control.checked = Boolean(value);
  } else if (field.type === 'number') {
    control = document.createElement('input');
    control.type = 'number';
    control.value = value ?? '';
  } else {
    control = document.createElement('input');
    control.type = 'text';
    control.value = value ?? '';
    control.placeholder = field.placeholder || '';
  }

  control.dataset.schemaSection = sectionName;
  control.dataset.fieldName = field.name;
  wrapper.append(label, control);

  if (field.helpText) {
    const help = document.createElement('p');
    help.className = 'helper-copy';
    help.textContent = field.helpText;
    wrapper.append(help);
  }

  return wrapper;
}

function syncModalSections() {
  const isPlugin = screenTypeSelect.value === 'plugin';
  manualScreenFields.classList.toggle('hidden', isPlugin);
  pluginScreenFields.classList.toggle('hidden', !isPlugin);
}

function renderManualFields(lines = []) {
  screenLineFields.replaceChildren();

  for (let lineIndex = 0; lineIndex < currentConfig.rows; lineIndex += 1) {
    const field = document.createElement('label');
    field.className = 'field';

    const label = document.createElement('span');
    label.textContent = `Line ${lineIndex + 1}`;

    const input = document.createElement('input');
    input.type = 'text';
    input.maxLength = currentConfig.cols;
    input.value = lines[lineIndex] ?? '';
    input.placeholder = `Up to ${currentConfig.cols} characters`;

    field.append(label, input);
    screenLineFields.append(field);
  }
}

function collectSchemaValues(schema, sectionName) {
  const values = {};

  for (const field of schema) {
    const control = screenModal.querySelector(`[data-schema-section="${sectionName}"][data-field-name="${field.name}"]`);
    if (!control) {
      continue;
    }

    if (field.type === 'checkbox') {
      values[field.name] = Boolean(control.checked);
      continue;
    }

    if (field.type === 'number') {
      values[field.name] = Number(control.value);
      continue;
    }

    values[field.name] = String(control.value || '').trim();
  }

  return values;
}

function upsertScreenDraft(index, screen) {
  const nextScreen = {
    ...screen,
    previewLines: buildLocalPreviewLines(screen),
  };

  if (index === null) {
    screenDrafts.push(nextScreen);
    markScreensDirty(`${getScreenTitle(nextScreen, screenDrafts.length - 1)} added locally. Save screens to persist it.`);
  } else {
    screenDrafts[index] = nextScreen;
    markScreensDirty(`${getScreenTitle(nextScreen, index)} updated locally. Save screens to persist it.`);
  }

  renderScreensList();
}

function switchPage(pageId) {
  activePage = pageId;

  for (const navButton of navButtons) {
    const isActive = navButton.dataset.pageTarget === pageId;
    navButton.classList.toggle('active', isActive);

    if (isActive) {
      navButton.setAttribute('aria-current', 'page');
      workspaceTitle.textContent = navButton.dataset.pageTitle;
      workspaceCopy.textContent = navButton.dataset.pageCopy;
    } else {
      navButton.removeAttribute('aria-current');
    }
  }

  for (const pagePanel of pagePanels) {
    pagePanel.classList.toggle('hidden', pagePanel.dataset.page !== pageId);
  }
}

function markScreensDirty(message) {
  screensDirty = true;
  updateScreensDraftNote();
  if (message) {
    setStatus(message);
  }
}

function updateScreensDraftNote() {
  screensDraftNote.classList.toggle('hidden', !screensDirty);
}

function updatePluginCatalogNote() {
  if (availablePlugins.length === 0) {
    pluginCatalogNote.textContent = 'No plugins are installed yet.';
    return;
  }

  const names = availablePlugins.map((plugin) => plugin.name).join(', ');
  pluginCatalogNote.textContent = `${availablePlugins.length} plugin${availablePlugins.length === 1 ? '' : 's'} available: ${names}.`;
}

function clearDragIndicators() {
  for (const item of screensList.querySelectorAll('.screen-item')) {
    item.classList.remove('drag-over');
  }
}

function clearDragState() {
  draggedScreenIndex = null;
  clearDragIndicators();

  for (const item of screensList.querySelectorAll('.screen-item')) {
    item.classList.remove('dragging');
  }
}

function getScreenTitle(screen, index) {
  return screen.name || screen.pluginName || `Screen ${index + 1}`;
}

function getScreenSummary(screen) {
  if (screen.type === 'manual') {
    return 'Manual split-flap message.';
  }

  const city = screen.settings?.city || 'Unconfigured city';
  const country = screen.settings?.country || 'country';
  return `${screen.pluginName || screen.pluginId} for ${city}, ${country}.`;
}

function getScreenPreviewLines(screen) {
  const lines = Array.isArray(screen.previewLines) && screen.previewLines.length > 0
    ? screen.previewLines
    : buildLocalPreviewLines(screen);
  return padLocalLines(lines);
}

function buildLocalPreviewLines(screen) {
  if (screen.type === 'manual') {
    return padLocalLines(screen.lines || []);
  }

  const title = (screen.design?.title || screen.settings?.city || screen.pluginName || 'PLUGIN').trim().toUpperCase();
  const detail = screen.lastError
    ? screen.lastError.toUpperCase()
    : 'PLUGIN SCREEN';
  return padLocalLines([
    '',
    title.slice(0, currentConfig.cols),
    detail.slice(0, currentConfig.cols),
  ]);
}

function padLocalLines(lines) {
  const normalized = Array.isArray(lines) ? [...lines] : [];
  while (normalized.length < currentConfig.rows) {
    normalized.push('');
  }
  return normalized.slice(0, currentConfig.rows);
}

function serializeScreenForSave(screen) {
  if (screen.type === 'manual') {
    return {
      id: screen.id,
      type: 'manual',
      name: screen.name || '',
      enabled: true,
      lines: screen.lines,
    };
  }

  return {
    id: screen.id,
    type: 'plugin',
    name: screen.name || '',
    enabled: true,
    pluginId: screen.pluginId,
    refreshIntervalSeconds: screen.refreshIntervalSeconds,
    settings: screen.settings || {},
    design: screen.design || {},
  };
}

function buildDefaultManualDraft() {
  return {
    id: createLocalScreenId(),
    type: 'manual',
    name: '',
    enabled: true,
    lines: [],
  };
}

function getPluginById(pluginId) {
  return availablePlugins.find((plugin) => plugin.id === pluginId) || null;
}

function findLastPopulatedIndex(lines) {
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    if (lines[index]) {
      return index;
    }
  }

  return -1;
}

function formatTimestamp(timestamp) {
  try {
    return new Date(timestamp).toLocaleString([], {
      hour: '2-digit',
      minute: '2-digit',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return timestamp;
  }
}

function createLocalScreenId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `screen-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function setStatus(message, kind = '') {
  statusMessage.textContent = message;
  statusMessage.className = 'status-message';
  if (kind) {
    statusMessage.classList.add(kind);
  }
}

async function readError(response, fallback) {
  try {
    const payload = await response.json();
    return payload.error || fallback;
  } catch {
    return fallback;
  }
}
