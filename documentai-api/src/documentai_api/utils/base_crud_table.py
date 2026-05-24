"""Base CRUD table for DynamoDB operations.

Subclass and declare table config to get standard CRUD operations:

    class TenantsTable(BaseCrudTable):
        table_name_env = "tenants_table_name"
        pk_field = "tenantId"

    tenants = TenantsTable()
    tenants.get("acme")
    tenants.list_all(active_only=True)
    tenants.create({"tenantId": "acme", "displayName": "Acme Corp"})
"""

from datetime import UTC, datetime
from typing import Any

from documentai_api.config.env import get_aws_config
from documentai_api.logging import get_logger
from documentai_api.services import ddb as ddb_service
from documentai_api.utils.aws_client_factory import AWSClientFactory

logger = get_logger(__name__)


class BaseCrudTable:
    """Generic CRUD operations for a DynamoDB table."""

    table_name_env: str
    pk_field: str
    sk_field: str | None = None
    active_field: str = "isActive"
    created_field: str = "createdAt"
    updated_field: str = "updatedAt"

    def _get_table_name(self) -> str:
        table_name: str | None = getattr(get_aws_config(), self.table_name_env.lower(), None)
        if not table_name:
            raise ValueError(f"{self.table_name_env} not configured")
        return table_name

    def _build_key(self, pk_value: str, sk_value: str | None = None) -> dict[str, str]:
        key: dict[str, str] = {self.pk_field: pk_value}
        if self.sk_field and sk_value:
            key[self.sk_field] = sk_value
        return key

    def get(self, pk_value: str, sk_value: str | None = None) -> dict[str, Any] | None:
        """Get a single item by key."""
        return ddb_service.get_item(self._get_table_name(), self._build_key(pk_value, sk_value))

    def list_by_pk(self, pk_value: str, active_only: bool = True) -> list[dict[str, Any]]:
        """List items by partition key."""
        if self.sk_field:
            items = ddb_service.query_by_pk(self._get_table_name(), self.pk_field, pk_value)
        else:
            items = ddb_service.scan(self._get_table_name())
            items = [i for i in items if i.get(self.pk_field) == pk_value]

        if active_only and self.active_field:
            items = [i for i in items if i.get(self.active_field, True)]
        return items

    def list_all(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Scan all items (use sparingly)."""
        items = ddb_service.scan(self._get_table_name())
        if active_only and self.active_field:
            items = [i for i in items if i.get(self.active_field, True)]
        return items

    def create(self, item: dict[str, Any], check_exists: bool = True) -> dict[str, Any]:
        """Create a new item. Raises ValueError if it already exists (when check_exists=True)."""
        pk_value = item[self.pk_field]
        sk_value = item.get(self.sk_field) if self.sk_field else None

        if check_exists:
            existing = self.get(pk_value, sk_value)
            if existing:
                raise ValueError(f"Item already exists: {pk_value}/{sk_value or ''}")

        now = datetime.now(UTC).isoformat()
        item.setdefault(self.created_field, now)
        item.setdefault(self.updated_field, now)
        if self.active_field:
            item.setdefault(self.active_field, True)

        ddb_service.put_item(self._get_table_name(), item)
        return item

    def update(self, pk_value: str, sk_value: str | None = None, **fields: Any) -> dict[str, Any]:
        """Update fields on an existing item. Raises ValueError if not found or no fields."""
        existing = self.get(pk_value, sk_value)
        if not existing:
            raise ValueError("Item not found")

        # Filter out None values
        updates = {k: v for k, v in fields.items() if v is not None}
        if not updates:
            raise ValueError("No fields to update")

        now = datetime.now(UTC).isoformat()
        updates[self.updated_field] = now

        update_parts = []
        expr_values: dict[str, Any] = {}
        for field_name, value in updates.items():
            param = f":{field_name}"
            update_parts.append(f"{field_name} = {param}")
            expr_values[param] = value

        update_expr = "SET " + ", ".join(update_parts)
        key = self._build_key(pk_value, sk_value)

        ddb_service.update_item(self._get_table_name(), key, update_expr, expr_values)

        updated = self.get(pk_value, sk_value)
        if not updated:
            raise ValueError("Update failed")
        return updated

    def upsert(self, pk_value: str, sk_value: str | None = None, **fields: Any) -> dict[str, Any]:
        """Create or update atomically. Sets created_field only if item is new."""
        now = datetime.now(UTC).isoformat()

        update_parts = []
        expr_values: dict[str, Any] = {":now": now}

        for field_name, value in fields.items():
            if value is not None:
                param = f":{field_name}"
                update_parts.append(f"{field_name} = {param}")
                expr_values[param] = value

        update_parts.append(f"{self.updated_field} = :now")
        update_parts.append(f"{self.created_field} = if_not_exists({self.created_field}, :now)")

        update_expr = "SET " + ", ".join(update_parts)
        key = self._build_key(pk_value, sk_value)

        table = AWSClientFactory.get_ddb_table(self._get_table_name())
        response = table.update_item(
            Key=key,
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW",
        )
        return response["Attributes"]

    def deactivate(self, pk_value: str, sk_value: str | None = None) -> bool:
        """Soft-delete by setting active_field to False. Returns False if not found."""
        existing = self.get(pk_value, sk_value)
        if not existing:
            return False

        now = datetime.now(UTC).isoformat()
        key = self._build_key(pk_value, sk_value)
        update_expr = f"SET {self.active_field} = :isActive, {self.updated_field} = :updatedAt"
        expr_values: dict[str, Any] = {":isActive": False, ":updatedAt": now}

        ddb_service.update_item(self._get_table_name(), key, update_expr, expr_values)
        return True

    def delete(self, pk_value: str, sk_value: str | None = None) -> bool:
        """Hard-delete an item. Returns False if not found."""
        key = self._build_key(pk_value, sk_value)
        existing = ddb_service.get_item(self._get_table_name(), key)
        if not existing:
            return False
        ddb_service.delete_item(self._get_table_name(), key)
        return True

    def query(
        self,
        key_condition: Any,
        filter_expression: Any | None = None,
        index_name: str | None = None,
        limit: int | None = None,
        scan_forward: bool = True,
        start_key: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Run a DDB query with full control over conditions.

        Returns (items, last_evaluated_key). last_evaluated_key is None if
        there are no more pages.
        """
        table = AWSClientFactory.get_ddb_table(self._get_table_name())

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": key_condition,
            "ScanIndexForward": scan_forward,
        }
        if filter_expression is not None:
            kwargs["FilterExpression"] = filter_expression
        if index_name:
            kwargs["IndexName"] = index_name
        if limit:
            kwargs["Limit"] = limit
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key

        response = table.query(**kwargs)
        return response.get("Items", []), response.get("LastEvaluatedKey")
