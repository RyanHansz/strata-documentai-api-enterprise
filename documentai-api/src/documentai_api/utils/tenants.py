"""Tenant DDB operations."""

from typing import Any

from documentai_api.schemas.tenants import TenantRecord, TenantsTable

_table = TenantsTable()


def get_tenant(tenant_id: str) -> dict[str, Any] | None:
    """Get a tenant by ID. Returns None if not found."""
    return _table.get(tenant_id)


def get_extraction_confidence_floor(tenant_id: str | None) -> float:
    """Get the extraction confidence floor for a tenant, falling back to global default."""
    from documentai_api.config.constants import ConfigDefaults

    if tenant_id:
        record = _table.get(tenant_id)
        if record and TenantRecord.EXTRACTION_CONFIDENCE_FLOOR in record:
            return float(record[TenantRecord.EXTRACTION_CONFIDENCE_FLOOR])
    return ConfigDefaults.FIELD_CONFIDENCE_THRESHOLD


def list_tenants(*, active_only: bool = True) -> list[dict[str, Any]]:
    """List all tenants, optionally filtered to active only."""
    return _table.list_all(active_only=active_only)


def create_tenant(
    tenant_id: str,
    display_name: str,
    primary_contact: str | None = None,
    extraction_confidence_floor: float | None = None,
) -> dict[str, Any]:
    """Create a new tenant. Raises ValueError if already exists."""
    item: dict[str, Any] = {
        TenantRecord.TENANT_ID: tenant_id,
        TenantRecord.DISPLAY_NAME: display_name,
    }
    if primary_contact:
        item[TenantRecord.PRIMARY_CONTACT] = primary_contact
    if extraction_confidence_floor is not None:
        item[TenantRecord.EXTRACTION_CONFIDENCE_FLOOR] = extraction_confidence_floor

    return _table.create(item)


def update_tenant(tenant_id: str, **fields: Any) -> dict[str, Any]:
    """Update tenant fields. Returns updated record. Raises ValueError if not found."""
    field_map = {
        "display_name": TenantRecord.DISPLAY_NAME,
        "primary_contact": TenantRecord.PRIMARY_CONTACT,
        "is_active": TenantRecord.IS_ACTIVE,
        "extraction_confidence_floor": TenantRecord.EXTRACTION_CONFIDENCE_FLOOR,
    }
    # Map python kwargs to DDB field names
    ddb_fields = {field_map[k]: v for k, v in fields.items() if k in field_map and v is not None}
    if not ddb_fields:
        raise ValueError("No fields to update")

    return _table.update(tenant_id, **ddb_fields)


def deactivate_tenant(tenant_id: str) -> bool:
    """Soft-delete a tenant. Returns True if deactivated."""
    return _table.deactivate(tenant_id)
