import * as Helpers from "../utils/helpers.js";
import * as Toast from "../utils/toast.js";
import * as SchemasService from "../services/schemas.js";
import * as RulesService from "../services/rules.js";
import * as BlueprintTestService from "../services/blueprint-test.js";
import * as TenantsService from "../services/tenants.js";
import { DEMO_SCHEMAS } from "../demo/schemas.js";
import { DEMO_RULES } from "../demo/rules.js";

let _list, _title, _fieldsList, _discardBtn, _saveBtn, _tenantSelect, _isDemo = false;
let _testBtn, _testTenantSelect, _testCategorySelect, _testFileInput, _runTestBtn, _cancelTestBtn, _testElapsed, _testResults, _testHistoryList;
let _activeDocType = null;
let _hasUnsavedChanges = false;
let _onNavigate = null;
let _schemas = {};
let _rules = {};
let _selectedTenantId = null;
let _testAbortController = null;
let _testTimer = null;

export function init({ list, title, fieldsList, discardBtn, saveBtn, tenantSelect, testBtn, testTenantSelect, testCategorySelect, testFileInput, runTestBtn, cancelTestBtn, testElapsed, testResults, testHistoryList, onNavigate }) {
  _list = list;
  _title = title;
  _fieldsList = fieldsList;
  _discardBtn = discardBtn;
  _saveBtn = saveBtn;
  _tenantSelect = tenantSelect;
  _testBtn = testBtn;
  _testTenantSelect = testTenantSelect;
  _testCategorySelect = testCategorySelect;
  _testFileInput = testFileInput;
  _runTestBtn = runTestBtn;
  _cancelTestBtn = cancelTestBtn;
  _testElapsed = testElapsed;
  _testResults = testResults;
  _testHistoryList = testHistoryList;
  _onNavigate = onNavigate;

  discardBtn.addEventListener("click", discard);
  saveBtn.addEventListener("click", save);

  if (_tenantSelect) {
    _tenantSelect.addEventListener("change", onTenantChange);
  }
  if (_testBtn) {
    _testBtn.addEventListener("click", () => { if (_onNavigate) _onNavigate("view-test-documents"); });
  }
  if (_testTenantSelect) {
    _testTenantSelect.addEventListener("change", updateRunBtnState);
  }
  if (_testCategorySelect) {
    _testCategorySelect.addEventListener("change", updateRunBtnState);
  }
  if (_testFileInput) {
    _testFileInput.addEventListener("change", updateRunBtnState);
  }
  if (_runTestBtn) {
    _runTestBtn.addEventListener("click", runTest);
  }
  if (_cancelTestBtn) {
    _cancelTestBtn.addEventListener("click", cancelTest);
  }
}

export function setDemo(val) { _isDemo = val; }
export function getActiveDocType() { return _activeDocType; }
export function hasUnsavedChanges() { return _hasUnsavedChanges; }

export async function loadTestView() {
  if (_testTenantSelect && _testTenantSelect.options.length <= 1) {
    try {
      const resp = await TenantsService.list();
      for (const tenant of resp.tenants || []) {
        const opt = document.createElement("option");
        opt.value = tenant.tenantId;
        opt.textContent = tenant.displayName || tenant.tenantId;
        _testTenantSelect.appendChild(opt);
      }
    } catch {
      // Tenant list unavailable
    }
  }
  if (_testCategorySelect && _testCategorySelect.options.length <= 1) {
    try {
      const resp = await SchemasService.getCategories();
      for (const cat of resp.documentCategories || []) {
        const opt = document.createElement("option");
        opt.value = cat;
        opt.textContent = cat.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
        _testCategorySelect.appendChild(opt);
      }
    } catch {
      // Categories unavailable
    }
  }
  renderTestHistory();
}

function updateRunBtnState() {
  if (_runTestBtn) {
    _runTestBtn.disabled = !(
      _testCategorySelect?.value &&
      _testFileInput?.files.length
    );
  }
}

const TEST_HISTORY_KEY = "docai_test_history";

function getTestHistory() {
  try {
    return JSON.parse(sessionStorage.getItem(TEST_HISTORY_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveTestResult(filename, result) {
  const history = getTestHistory();
  history.unshift({
    id: result.testId,
    filename,
    timestamp: new Date().toISOString(),
    matchedBlueprint: result.matchedBlueprint,
    matchedConfidence: result.matchedConfidence,
    result,
  });
  // Keep last 20 tests
  sessionStorage.setItem(TEST_HISTORY_KEY, JSON.stringify(history.slice(0, 20)));
}

export function clearTestHistory() {
  sessionStorage.removeItem(TEST_HISTORY_KEY);
}

function renderTestHistory() {
  if (!_testHistoryList) return;
  const history = getTestHistory();
  if (history.length === 0) {
    _testHistoryList.innerHTML = '<li class="empty-state">No tests yet</li>';
    return;
  }
  _testHistoryList.innerHTML = "";
  for (const entry of history) {
    const li = document.createElement("li");
    li.className = "test-history-item";
    const time = new Date(entry.timestamp).toLocaleTimeString();
    li.innerHTML = `
      <span class="test-history-name">${Helpers.esc(entry.filename)}</span>
      <span class="test-history-meta">${Helpers.esc(entry.matchedBlueprint || "Unknown")} • ${time}</span>
    `;
    li.addEventListener("click", () => {
      _testHistoryList.querySelectorAll("li").forEach(l => l.classList.remove("active"));
      li.classList.add("active");
      renderTestResults(entry.result);
    });
    _testHistoryList.appendChild(li);
  }
}

export async function load() {
  if (_isDemo) {
    _schemas = DEMO_SCHEMAS;
    _rules = DEMO_RULES;
    populateSidebar(_schemas);
    return;
  }
  try {
    // Load schemas
    const schemaList = await SchemasService.list();
    _schemas = {};
    for (const docType of schemaList.schemas) {
      try {
        const detail = await SchemasService.get(docType);
        _schemas[docType] = {
          fields: detail.fields || [],
          blueprintArn: detail.blueprintArn || null,
        };
      } catch {
        _schemas[docType] = { fields: [], blueprintArn: null };
      }
    }
    populateSidebar(_schemas);

    // Load tenants for selector
    if (_tenantSelect) {
      await loadTenants();
    }
  } catch (e) {
    Toast.show(`Failed to load blueprints: ${e.message}`);
  }
}

async function loadTenants() {
  try {
    const resp = await TenantsService.list();
    _tenantSelect.innerHTML = '<option value="">— Select tenant —</option>';
    for (const tenant of resp.tenants || []) {
      const opt = document.createElement("option");
      opt.value = tenant.tenantId;
      opt.textContent = tenant.displayName || tenant.tenantId;
      _tenantSelect.appendChild(opt);
    }
  } catch {
    // Tenant-admin may not have list access — use their own tenant
    _tenantSelect.classList.add("hidden");
  }
}

async function onTenantChange() {
  _selectedTenantId = _tenantSelect.value || null;
  _saveBtn.disabled = !_selectedTenantId;
  _saveBtn.title = _selectedTenantId ? "" : "Select a tenant to save rules";
  updateTestBtnState();

  // Load rules for selected tenant
  _rules = {};
  if (_selectedTenantId) {
    try {
      const rulesResp = await RulesService.list(_selectedTenantId);
      for (const rule of rulesResp.rules || []) {
        _rules[rule.documentType] = rule;
      }
    } catch {
      // No rules yet
    }
  }
  populateSidebar(_schemas);
  if (_activeDocType) {
    select(_activeDocType);
  }
}

function markDirty() {
  if (!_hasUnsavedChanges) {
    _hasUnsavedChanges = true;
    _title.innerHTML = `${Helpers.esc(_activeDocType)} <span class="unsaved-dot">●</span>`;
    _discardBtn.classList.remove("hidden");
  }
}

function markClean() {
  _hasUnsavedChanges = false;
  _title.textContent = _activeDocType;
  _discardBtn.classList.add("hidden");
}

function discard() {
  if (_activeDocType) {
    const fields = _schemas[_activeDocType]?.fields || [];
    const rules = _rules[_activeDocType] || {};
    renderFields(fields, rules);
    markClean();
    Toast.show("Changes discarded");
  }
}

export function populateSidebar(schemas) {
  _list.innerHTML = "";

  // Group by category
  const categories = {};
  for (const docType of Object.keys(schemas).sort()) {
    const category = schemas[docType]?.category || "other";
    if (!categories[category]) categories[category] = [];
    categories[category].push(docType);
  }

  for (const category of Object.keys(categories).sort()) {
    const header = document.createElement("li");
    header.className = "blueprint-category";
    header.textContent = category.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    _list.appendChild(header);

    for (const docType of categories[category]) {
      const rules = _rules[docType] || {};
      const reqCount = (rules.requiredFields || []).length;
      const totalFields = (schemas[docType]?.fields || []).length;

      const li = document.createElement("li");
      li.className = "blueprint-item";
      li.innerHTML = `
        <span class="blueprint-name">${Helpers.esc(docType)}</span>
        <span class="blueprint-badge">${reqCount}/${totalFields}</span>
      `;
      li.addEventListener("click", () => select(docType));
      _list.appendChild(li);
    }
  }
}

export function select(docType) {
  if (_hasUnsavedChanges && !confirm("You have unsaved changes. Discard?")) return;
  _activeDocType = docType;
  _hasUnsavedChanges = false;

  _list.querySelectorAll("li").forEach((li) => {
    li.classList.toggle("active", li.querySelector(".blueprint-name")?.textContent === docType);
  });

  _title.textContent = docType;
  if (_onNavigate) _onNavigate("view-blueprint");
  updateTestBtnState();

  const fields = _schemas[docType]?.fields || [];
  const rules = _rules[docType] || {};
  renderFields(fields, rules);
}

function renderFields(fields, rules) {
  _fieldsList.innerHTML = "";
  const required = new Set(rules.requiredFields || []);
  const optional = new Set(rules.optionalFields || []);

  for (const field of fields) {
    let state = "excluded";
    if (required.has(field.name)) state = "required";
    else if (optional.has(field.name)) state = "optional";

    const row = document.createElement("div");
    row.className = "field-row";
    row.innerHTML = `
      <div class="field-info">
        <span class="field-name">${Helpers.esc(field.name)}</span>
        ${field.description ? `<span class="field-description">${Helpers.esc(field.description)}</span>` : ""}
        <span class="field-type">${Helpers.esc(field.type)}</span>
      </div>
      <div class="field-toggles">
        <label class="toggle-label">
          <input type="radio" name="field-${Helpers.esc(field.name)}" value="required" ${state === "required" ? "checked" : ""}>
          <span class="toggle-badge toggle-required">Required</span>
        </label>
        <label class="toggle-label">
          <input type="radio" name="field-${Helpers.esc(field.name)}" value="optional" ${state === "optional" ? "checked" : ""}>
          <span class="toggle-badge toggle-optional">Optional</span>
        </label>
        <label class="toggle-label">
          <input type="radio" name="field-${Helpers.esc(field.name)}" value="excluded" ${state === "excluded" ? "checked" : ""}>
          <span class="toggle-badge toggle-excluded">Excluded</span>
        </label>
      </div>
    `;
    row.querySelectorAll("input").forEach((input) => {
      input.addEventListener("change", markDirty);
    });
    _fieldsList.appendChild(row);
  }
}

function getSelections() {
  const required = [];
  const optional = [];
  _fieldsList.querySelectorAll(".field-row").forEach((row) => {
    const name = row.querySelector(".field-name").textContent;
    const checked = row.querySelector("input:checked");
    if (checked?.value === "required") required.push(name);
    else if (checked?.value === "optional") optional.push(name);
  });
  return { requiredFields: required, optionalFields: optional };
}

async function save() {
  if (!_selectedTenantId) {
    Toast.show("Select a tenant to save extraction rules");
    return;
  }
  if (!_activeDocType) {
    Toast.show("Select a blueprint first");
    return;
  }
  const selections = getSelections();
  const blueprintArn = _schemas[_activeDocType]?.blueprintArn || null;
  try {
    await RulesService.put(_selectedTenantId, _activeDocType, selections.requiredFields, selections.optionalFields, blueprintArn);
    _rules[_activeDocType] = selections;
    markClean();
    Toast.show(`Rules saved for ${_activeDocType}`);
    populateSidebar(_schemas);
    _list.querySelectorAll("li").forEach((li) => {
      li.classList.toggle("active", li.querySelector(".blueprint-name")?.textContent === _activeDocType);
    });
  } catch (e) {
    Toast.show(`Failed to save rules: ${e.message}`);
  }
}


function updateTestBtnState() {
  if (_testBtn) {
    _testBtn.disabled = !(_selectedTenantId && _activeDocType);
    _testBtn.title = _testBtn.disabled ? "Select a tenant and blueprint first" : "Test extraction on a sample document";
  }
}

async function runTest() {
  const file = _testFileInput.files[0];
  const tenantId = _testTenantSelect?.value || null;
  const category = _testCategorySelect?.value;
  if (!file || !category) return;

  _runTestBtn.disabled = true;
  _runTestBtn.textContent = "Processing...";
  _cancelTestBtn.classList.remove("hidden");
  _testResults.classList.add("hidden");
  _testElapsed.classList.remove("hidden");

  // Start elapsed timer
  const startTime = Date.now();
  _testTimer = setInterval(() => {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
    _testElapsed.textContent = `Elapsed: ${elapsed}s`;
  }, 1000);

  _testAbortController = new AbortController();

  try {
    const result = await BlueprintTestService.run(file, tenantId, category, _activeDocType, _testAbortController.signal);
    saveTestResult(file.name, result);
    renderTestHistory();
    renderTestResults(result);
  } catch (e) {
    if (e.name !== "AbortError") {
      Toast.show(`Test failed: ${e.message}`);
    }
  } finally {
    clearInterval(_testTimer);
    _runTestBtn.disabled = false;
    _runTestBtn.textContent = "Run Extraction";
    _cancelTestBtn.classList.add("hidden");
    _testAbortController = null;
  }
}

function cancelTest() {
  if (_testAbortController) {
    _testAbortController.abort();
    Toast.show("Test cancelled");
  }
}

function renderTestResults(result) {
  _testResults.classList.remove("hidden");

  const fields = result.extractedFields || {};
  const filtered = result.filteredFields || {};
  const missing = result.missingRequiredFields || [];
  const confidences = result.fieldConfidences || {};

  let html = `
    <div class="test-meta">
      <span><strong>Matched:</strong> ${Helpers.esc(result.matchedBlueprint || "None")}</span>
      <span><strong>Confidence:</strong> ${result.matchedConfidence ? (result.matchedConfidence * 100).toFixed(1) + "%" : "N/A"}</span>
    </div>
  `;

  if (missing.length > 0) {
    html += `<div class="test-missing"><strong>Missing required:</strong> ${missing.map(f => Helpers.esc(f)).join(", ")}</div>`;
  }

  html += `<table class="test-fields-table"><thead><tr><th>Field</th><th>Value</th><th>Confidence</th><th>Status</th></tr></thead><tbody>`;

  const allFieldNames = new Set([...Object.keys(fields), ...missing]);
  for (const name of [...allFieldNames].sort()) {
    const value = fields[name];
    const inFiltered = name in filtered;
    const isMissing = missing.includes(name);
    const confidence = confidences[name];

    let statusBadge;
    if (isMissing) {
      statusBadge = '<span class="badge badge-error">Missing</span>';
    } else if (inFiltered) {
      statusBadge = '<span class="badge badge-success">Extracted</span>';
    } else {
      statusBadge = '<span class="badge badge-neutral">Excluded</span>';
    }

    const displayValue = value !== undefined && value !== null ? Helpers.esc(String(value)) : "—";
    const confDisplay = confidence !== undefined ? `${(confidence * 100).toFixed(0)}%` : "—";
    html += `<tr><td>${Helpers.esc(name)}</td><td class="field-value">${displayValue}</td><td>${confDisplay}</td><td>${statusBadge}</td></tr>`;
  }

  html += `</tbody></table>`;
  _testResults.innerHTML = html;
}
