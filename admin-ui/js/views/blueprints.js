import * as Helpers from "../utils/helpers.js";
import * as Toast from "../utils/toast.js";
import * as SchemasService from "../services/schemas.js";
import { DEMO_SCHEMAS } from "../demo/schemas.js";
import { DEMO_RULES } from "../demo/rules.js";

let _list, _title, _fieldsList, _discardBtn, _isDemo = false;
let _activeDocType = null;
let _hasUnsavedChanges = false;
let _onNavigate = null;
let _schemas = {};
let _rules = {};

export function init({ list, title, fieldsList, discardBtn, saveBtn, onNavigate }) {
  _list = list;
  _title = title;
  _fieldsList = fieldsList;
  _discardBtn = discardBtn;
  _onNavigate = onNavigate;

  discardBtn.addEventListener("click", discard);
  saveBtn.addEventListener("click", save);
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
    const schemaList = await SchemasService.list();
    _schemas = {};
    for (const docType of schemaList.schemas) {
      try {
        const detail = await SchemasService.get(docType);
        _schemas[docType] = detail.fields || [];
      } catch {
        _schemas[docType] = [];
      }
    }
    // Load extraction rules for each schema
    _rules = {};
    try {
      const rulesResp = await RulesService.list();
      for (const rule of rulesResp.rules || []) {
        _rules[rule.documentType] = rule;
      }
    } catch {
      // No rules configured yet
    }
    populateSidebar(_schemas);
  } catch (e) {
    Toast.show(`Failed to load blueprints: ${e.message}`);
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
    const fields = _schemas[_activeDocType] || [];
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
    const totalFields = (schemas[docType] || []).length;

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

  const fields = _schemas[docType] || [];
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
  // TODO: Requires tenant selector before rules can be saved
  Toast.show("Select a tenant to save extraction rules");
}
