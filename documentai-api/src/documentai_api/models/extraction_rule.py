"""Response models for extraction rule endpoints."""

from documentai_api.models.base import BaseApiResponse


class ExtractionRuleItem(BaseApiResponse):
    tenant_id: str
    document_type: str
    required_fields: list[str]
    optional_fields: list[str]
    created_at: str
    updated_at: str


class ExtractionRulesListResponse(BaseApiResponse):
    rules: list[ExtractionRuleItem]


class ExtractionRuleDeleteResponse(BaseApiResponse):
    message: str
