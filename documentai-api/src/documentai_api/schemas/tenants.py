"""Schema for the tenants DynamoDB table."""

from documentai_api.utils.base_crud_table import BaseCrudTable


class TenantRecord:
    """Field names for the tenants DynamoDB table."""

    TENANT_ID = "tenantId"
    DISPLAY_NAME = "displayName"
    PRIMARY_CONTACT = "primaryContact"
    IS_ACTIVE = "isActive"
    CREATED_AT = "createdAt"
    UPDATED_AT = "updatedAt"


class TenantsTable(BaseCrudTable):
    table_name_env = "tenants_table_name"
    pk_field = TenantRecord.TENANT_ID
    active_field = TenantRecord.IS_ACTIVE
    created_field = TenantRecord.CREATED_AT
    updated_field = TenantRecord.UPDATED_AT
