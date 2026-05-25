import * as CategoriesService from "../services/document-categories.js";
import * as TenantContext from "../utils/tenant-context.js";
import * as Helpers from "../utils/helpers.js";
import * as Toast from "../utils/toast.js";

let _tbody, _noCategories, _createBtn, _refreshBtn;
let _modal, _form, _nameInput, _displayNameInput, _descriptionInput, _cancelBtn, _errorEl, _titleEl;
let _editingCategory = null;

export function init() {
  _tbody = document.getElementById("categories-tbody");
  _noCategories = document.getElementById("no-categories");
  _createBtn = document.getElementById("create-category-btn");
  _refreshBtn = document.getElementById("refresh-categories-btn");

  _modal = document.getElementById("category-modal");
  _form = document.getElementById("category-form");
  _nameInput = document.getElementById("category-name");
  _displayNameInput = document.getElementById("category-display-name");
  _descriptionInput = document.getElementById("category-description");
  _cancelBtn = document.getElementById("category-cancel");
  _errorEl = document.getElementById("category-form-error");
  _titleEl = document.getElementById("category-modal-title");

  TenantContext.onChange((tenantId) => {
    _createBtn.disabled = !tenantId;
    if (tenantId) loadCategories();
    else clearTable();
  });

  _createBtn.addEventListener("click", openCreateModal);
  _refreshBtn.addEventListener("click", () => { if (TenantContext.getTenantId()) loadCategories(); });
  _cancelBtn.addEventListener("click", closeModal);
  _form.addEventListener("submit", handleSubmit);
}

export async function load() {
  const tenantId = TenantContext.getTenantId();
  _createBtn.disabled = !tenantId;
  if (tenantId) loadCategories();
}


function clearTable() {
  _tbody.innerHTML = "";
  _noCategories.classList.remove("hidden");
}

async function loadCategories() {
  try {
    const resp = await CategoriesService.list(TenantContext.getTenantId());
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
        <button class="btn-sm btn-secondary" data-action="edit" data-name="${Helpers.esc(cat.categoryName)}" data-display="${Helpers.esc(cat.displayName)}" data-desc="${Helpers.esc(cat.description || "")}">Edit</button>
        ${cat.isActive ? `<button class="btn-sm btn-danger" data-action="delete" data-name="${Helpers.esc(cat.categoryName)}">Deactivate</button>` : ""}
      </td>
    </tr>
  `).join("");

  _tbody.querySelectorAll("[data-action=edit]").forEach(btn => {
    btn.addEventListener("click", () => openEditModal(btn.dataset.name, btn.dataset.display, btn.dataset.desc));
  });
  _tbody.querySelectorAll("[data-action=delete]").forEach(btn => {
    btn.addEventListener("click", () => deactivate(btn.dataset.name));
  });
}

function openCreateModal() {
  _editingCategory = null;
  _titleEl.textContent = "Create category";
  _nameInput.value = "";
  _nameInput.disabled = false;
  _displayNameInput.value = "";
  _descriptionInput.value = "";
  _errorEl.classList.add("hidden");
  _modal.classList.remove("hidden");
}

function openEditModal(name, displayName, description) {
  _editingCategory = name;
  _titleEl.textContent = "Edit category";
  _nameInput.value = name;
  _nameInput.disabled = true;
  _displayNameInput.value = displayName;
  _descriptionInput.value = description;
  _errorEl.classList.add("hidden");
  _modal.classList.remove("hidden");
}

function closeModal() {
  _modal.classList.add("hidden");
  _editingCategory = null;
}

async function handleSubmit(e) {
  e.preventDefault();
  _errorEl.classList.add("hidden");

  const name = _nameInput.value.trim();
  const displayName = _displayNameInput.value.trim();
  const description = _descriptionInput.value.trim();

  try {
    if (_editingCategory) {
      await CategoriesService.update(TenantContext.getTenantId(), _editingCategory, { displayName, description });
      Toast.show("Category updated");
    } else {
      await CategoriesService.create(TenantContext.getTenantId(), name, displayName, description);
      Toast.show("Category created");
    }
    closeModal();
    loadCategories();
  } catch (err) {
    _errorEl.textContent = err.message;
    _errorEl.classList.remove("hidden");
  }
}

function deactivate(categoryName) {
  if (!confirm(`Deactivate category "${categoryName}"?`)) return;

  CategoriesService.remove(TenantContext.getTenantId(), categoryName)
    .then(() => { Toast.show("Category deactivated"); loadCategories(); })
    .catch(e => Toast.show(`Failed: ${e.message}`));
}
