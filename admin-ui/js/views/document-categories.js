import * as CategoriesService from "../services/document-categories.js";
import * as TenantsService from "../services/tenants.js";
import * as Helpers from "../utils/helpers.js";
import * as Toast from "../utils/toast.js";

let _tbody, _noCategories, _tenantSelect, _createBtn, _refreshBtn;
let _selectedTenantId = null;

export function init() {
  _tbody = document.getElementById("categories-tbody");
  _noCategories = document.getElementById("no-categories");
  _tenantSelect = document.getElementById("categories-tenant-select");
  _createBtn = document.getElementById("create-category-btn");
  _refreshBtn = document.getElementById("refresh-categories-btn");

  _tenantSelect.addEventListener("change", () => {
    _selectedTenantId = _tenantSelect.value || null;
    _createBtn.disabled = !_selectedTenantId;
    if (_selectedTenantId) loadCategories();
  });

  _createBtn.addEventListener("click", promptCreate);
  _refreshBtn.addEventListener("click", () => { if (_selectedTenantId) loadCategories(); });
}

export async function load() {
  // Populate tenant selector
  if (_tenantSelect.options.length <= 1) {
    try {
      const resp = await TenantsService.list();
      for (const tenant of resp.tenants || []) {
        const opt = document.createElement("option");
        opt.value = tenant.tenantId;
        opt.textContent = tenant.displayName || tenant.tenantId;
        _tenantSelect.appendChild(opt);
      }
    } catch {
      // Tenant list unavailable
    }
  }
}

async function loadCategories() {
  try {
    const resp = await CategoriesService.list(_selectedTenantId);
    renderTable(resp.categories || []);
  } catch (e) {
    Toast.show(`Failed to load categories: ${e.message}`);
  }
}

function renderTable(categories) {
  if (categories.length === 0) {
    _tbody.innerHTML = "";
    _noCategories.classList.remove("hidden");
    return;
  }
  _noCategories.classList.add("hidden");
  _tbody.innerHTML = categories.map(cat => `
    <tr>
      <td>${Helpers.esc(cat.categoryName)}</td>
      <td>${Helpers.esc(cat.displayName)}</td>
      <td>${Helpers.esc(cat.description || "—")}</td>
      <td>${cat.isActive ? '<span class="badge badge-success">Active</span>' : '<span class="badge badge-neutral">Inactive</span>'}</td>
      <td>
        <button class="btn-sm btn-secondary" data-action="edit" data-name="${Helpers.esc(cat.categoryName)}">Edit</button>
        ${cat.isActive ? `<button class="btn-sm btn-danger" data-action="delete" data-name="${Helpers.esc(cat.categoryName)}">Deactivate</button>` : ""}
      </td>
    </tr>
  `).join("");

  _tbody.querySelectorAll("[data-action=edit]").forEach(btn => {
    btn.addEventListener("click", () => promptEdit(btn.dataset.name));
  });
  _tbody.querySelectorAll("[data-action=delete]").forEach(btn => {
    btn.addEventListener("click", () => deactivate(btn.dataset.name));
  });
}

function promptCreate() {
  const name = prompt("Category name (lowercase, dashes/underscores):");
  if (!name) return;
  const displayName = prompt("Display name:");
  if (!displayName) return;
  const description = prompt("Description (optional):") || "";

  CategoriesService.create(_selectedTenantId, name, displayName, description)
    .then(() => { Toast.show("Category created"); loadCategories(); })
    .catch(e => Toast.show(`Failed: ${e.message}`));
}

function promptEdit(categoryName) {
  const displayName = prompt(`New display name for "${categoryName}":`);
  if (!displayName) return;
  const description = prompt("New description (optional):") || undefined;

  CategoriesService.update(_selectedTenantId, categoryName, { displayName, description })
    .then(() => { Toast.show("Category updated"); loadCategories(); })
    .catch(e => Toast.show(`Failed: ${e.message}`));
}

function deactivate(categoryName) {
  if (!confirm(`Deactivate category "${categoryName}"?`)) return;

  CategoriesService.remove(_selectedTenantId, categoryName)
    .then(() => { Toast.show("Category deactivated"); loadCategories(); })
    .catch(e => Toast.show(`Failed: ${e.message}`));
}
