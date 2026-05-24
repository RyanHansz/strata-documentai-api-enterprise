import * as Helpers from "../utils/helpers.js";
import * as Toast from "../utils/toast.js";
import * as SchemasService from "../services/schemas.js";
import * as RulesService from "../services/rules.js";
import * as TenantsService from "../services/tenants.js";
import { DEMO_SCHEMAS } from "../demo/schemas.js";
import { DEMO_RULES } from "../demo/rules.js";

let _list, _title, _fieldsList, _discardBtn, _saveBtn, _tenantSelect, _isDemo = false;
let _activeDocType = null;
let _hasUnsavedChanges = false;
let _onNavigate = null;
let _schemas = {};
let _rules = {};
let _selectedTenantId = null;

export function init({ list, title, fieldsList, discardBtn, saveBtn, tenantSelect, onNavigate }) {
  _list = list;
  _title = title;
  _fieldsList = fieldsList;
  _discardBtn = discardBtn;
  _saveBtn = saveBtn;
  _tenantSelect = tenantSelect;
  _onNavigate = onNavigate;

  discardBtn.addEventListener("click", discard);
  saveBtn.addEventListener("click", save);

  if (_tenantSelect) {
    _tenantSelect.addEventListener("change", onTenantChange);
  }
}

export function setDemo(val) { _isDemo = val; }
export function getActiveDocType() { return _activeDocType; }
export function hasUnsavedChanges() { return _hasUnsavedChanges; }

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
  for (const docType of Object.keys(schemas).sort()) {
    const rules = _rules[docType] || {};
    const reqCount = (rules.requiredFields || []).length;
    const totalFields = (schemas[docType]?.fields || []).length;

    const li = document.createElement("li");
    li.innerHTML = `
      <span class="blueprint-name">${Helpers.esc(docType)}</span>
      <span class="blueprint-badge">${reqCount}/${totalFields}</span>
    `;
    li.addEventListener("click", () => select(docType));
    _list.appendChild(li);
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
