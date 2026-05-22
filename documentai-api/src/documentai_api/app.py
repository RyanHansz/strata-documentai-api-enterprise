import asyncio
import json
import os
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from mangum import Mangum

# Routers
from documentai_api.app_batch import router as batch_router
from documentai_api.app_build import router as build_router
from documentai_api.app_documents import router as documents_router
from documentai_api.app_presigned import router as presigned_router
from documentai_api.config.constants import (
    API_VERSION,
    APIConfig,
    ApiVisualizationTag,
    DictionaryBlueprintField,
    DictionaryBlueprintSchema,
    DictionaryFormatType,
    FileValidation,
    ProcessStatus,
)
from documentai_api.config.env import get_app_env_config
from documentai_api.logging import get_logger
from documentai_api.models.api_responses import (
    ConfigResponse,
    DictionaryDocumentCategoriesResponse,
    DictionaryFieldsResponse,
    DictionaryResponseCodesResponse,
    DictionarySchemaDetailResponse,
    DictionarySchemaListResponse,
    DictionarySearchResponse,
    ExtractionRuleDeleteResponse,
    ExtractionRuleItem,
    ExtractionRulesListResponse,
    HealthResponse,
    JobStatusResponse,
)
from documentai_api.utils.auth import verify_api_key
from documentai_api.utils.ddb import (
    classify_as_failed,
)
from documentai_api.utils.jobs import get_job_status
from documentai_api.utils.models import ClassificationData
from documentai_api.utils.response_builder import build_csv_response
from documentai_api.utils.schemas import get_all_fields, get_all_schemas, get_document_schema

logger = get_logger(__name__)

app = FastAPI(
    title=APIConfig.TITLE,
    description=APIConfig.DESCRIPTION,
    version=APIConfig.VERSION,
)
app.include_router(documents_router)
app.include_router(batch_router)
app.include_router(build_router)
app.include_router(presigned_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lambda entrypoint for the API container. Configure the API Lambda function with
# ImageConfig.Command = ["documentai_api.app.handler"].
handler = Mangum(app, lifespan="off")

# Configure logging when running in Lambda. main() bypassed, so LoggingContext is
# never entered the normal way; without it, INFO logs are silently dropped.
# AWS_LAMBDA_FUNCTION_NAME is set automatically by the Lambda runtime.
if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    from documentai_api.logging.config import LoggingContext

    LoggingContext("documentai_api")

CONFIG_EXCLUDED_ROUTES = {"/", "/health", "/config", "/openapi.json", "/docs", "/redoc"}


def discover_endpoints(app: FastAPI) -> dict[str, str]:
    """Build a sorted map of operation name → path for all non-excluded routes."""
    endpoints = {}
    for route in app.routes:
        if isinstance(route, APIRoute) and route.name and route.path not in CONFIG_EXCLUDED_ROUTES:
            endpoints[route.name] = route.path
    return dict(sorted(endpoints.items()))


# =============================================================================
# Shared utilities (used by multiple routers)
# =============================================================================


async def get_v1_document_processing_results(job_id: str, timeout: int) -> JobStatusResponse:
    """Poll for document processing completion with timeout."""
    elapsed_time = 0
    object_key = None
    polling_interval = 5

    while elapsed_time < timeout:
        try:
            job_status = get_job_status(job_id)

            if job_status.object_key:
                object_key = job_status.object_key

            # processing complete, return results
            if (
                job_status.process_status
                and ProcessStatus.is_completed(job_status.process_status)
                and job_status.v1_response_json
            ):
                return JobStatusResponse(**json.loads(job_status.v1_response_json))

            # still processing, wait and poll again
            await asyncio.sleep(polling_interval)
            elapsed_time += polling_interval

        except Exception as e:
            msg = f"Error polling DynamoDB for job {job_id}: {e}"
            logger.error(msg)

            await asyncio.sleep(polling_interval)
            elapsed_time += polling_interval

    # timeout - update ddb with failure if we have object_key
    if object_key:
        classify_as_failed(
            object_key=object_key,
            error_message="Processing timeout",
            data=ClassificationData(
                additional_info=f"Processing did not complete within {timeout} seconds"
            ),
        )

    return JobStatusResponse(
        job_id=job_id,
        job_status=ProcessStatus.FAILED.value,
        message=f"Processing timeout after {timeout} seconds",
    )


# =============================================================================
# Public endpoints (no auth required)
# =============================================================================


@app.get("/")
def root() -> dict[str, Any]:
    return {"message": APIConfig.TITLE, "status": "healthy"}


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(message="healthy")


@app.get("/config", dependencies=[Depends(verify_api_key)])
def get_config(request: Request) -> ConfigResponse:
    endpoints = discover_endpoints(app)
    endpoints["postUploadSyncronous"] = f"{endpoints['postUpload']}?wait=true"

    app_config = get_app_env_config()
    return ConfigResponse(
        api_url=f"{request.url.scheme}://{request.url.netloc}",
        version=API_VERSION,
        image_tag=app_config.image_tag,
        environment=app_config.environment,
        endpoints=endpoints,
        supported_file_types=list(FileValidation.SUPPORTED_CONTENT_TYPES),
    )


# ==============================================================================
# Dictionary endpoints
# ==============================================================================


@app.get(
    "/v1/dictionary/schemas",
    dependencies=[Depends(verify_api_key)],
    name="getSchemaList",
    tags=[ApiVisualizationTag.DICTIONARY_SCHEMAS],
)
async def list_schemas() -> DictionarySchemaListResponse:
    """List all supported document types."""
    try:
        schemas = get_all_schemas()
    except Exception as e:
        logger.error(f"Failed to retrieve schemas: {e}")
        raise HTTPException(status_code=503, detail="Unable to retrieve dictionary schemas") from e
    return DictionarySchemaListResponse(schemas=sorted(schemas.keys()))


@app.get(
    "/v1/dictionary/schemas/{document_type}",
    dependencies=[Depends(verify_api_key)],
    name="getSchemaDetail",
    response_model=DictionarySchemaDetailResponse,
    tags=[ApiVisualizationTag.DICTIONARY_SCHEMAS],
)
async def get_schema_detail(
    document_type: str, format: DictionaryFormatType = DictionaryFormatType.JSON
) -> Any:
    """Get field schema for a specific document type."""
    try:
        schema = get_document_schema(document_type)
    except Exception as e:
        logger.error(f"Failed to retrieve schema for {document_type}: {e}")
        raise HTTPException(
            status_code=503, detail="Unable to retrieve dictionary schema detail"
        ) from e

    if not schema:
        raise HTTPException(status_code=404, detail=f"Schema not found: {document_type}")

    data = schema[DictionaryBlueprintSchema.FIELDS]

    if format == DictionaryFormatType.CSV:
        return build_csv_response(data)

    return DictionarySchemaDetailResponse(document_type=document_type, fields=data)


@app.get(
    "/v1/dictionary/fields",
    dependencies=[Depends(verify_api_key)],
    name="getAllFields",
    response_model=DictionaryFieldsResponse,
    tags=[ApiVisualizationTag.DICTIONARY_FIELDS],
)
async def get_all_schema_fields(
    format: DictionaryFormatType = DictionaryFormatType.JSON,
) -> Any:
    """Get all fields across all document types."""
    try:
        data = get_all_fields()
    except Exception as e:
        logger.error(f"Failed to retrieve fields: {e}")
        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve dictionary fields",
        ) from e

    if format == DictionaryFormatType.CSV:
        return build_csv_response(data)

    return DictionaryFieldsResponse(fields=data)


@app.get(
    "/v1/dictionary/search",
    dependencies=[Depends(verify_api_key)],
    name="searchSchemas",
    response_model=DictionarySearchResponse,
    tags=[ApiVisualizationTag.DICTIONARY_FIELDS],
)
async def search_schema_fields(
    q: str | None = None,
    field: DictionaryBlueprintField | None = None,
    format: DictionaryFormatType = DictionaryFormatType.JSON,
) -> Any:
    """Search fields across all blueprints."""
    try:
        data = get_all_fields()
    except Exception as e:
        logger.error(f"Failed to retrieve fields for search: {e}")
        raise HTTPException(
            status_code=503,
            detail="Unable to search dictionary fields",
        ) from e

    if q:
        query = q.lower()
        if field:
            data = [f for f in data if query in str(f.get(field, "")).lower()]
        else:
            data = [f for f in data if any(query in str(v).lower() for v in f.values())]

    if format == DictionaryFormatType.CSV:
        return build_csv_response(data)

    return DictionarySearchResponse(fields=data)


@app.get(
    "/v1/dictionary/response-codes",
    dependencies=[Depends(verify_api_key)],
    name="getResponseCodes",
    response_model=DictionaryResponseCodesResponse,
    tags=[ApiVisualizationTag.DICTIONARY_REFERENCE],
)
async def get_response_codes(format: DictionaryFormatType = DictionaryFormatType.JSON) -> Any:
    """Get list of response codes and their meanings."""
    from documentai_api.utils.response_codes import ResponseCodes

    data = ResponseCodes.get_all()

    if format == DictionaryFormatType.CSV:
        return build_csv_response(data)

    return DictionaryResponseCodesResponse(response_codes=data)


@app.get(
    "/v1/dictionary/document-categories",
    dependencies=[Depends(verify_api_key)],
    name="getDocumentCategories",
    response_model=DictionaryDocumentCategoriesResponse,
    tags=[ApiVisualizationTag.DICTIONARY_REFERENCE],
)
async def get_document_categories(format: DictionaryFormatType = DictionaryFormatType.JSON) -> Any:
    """Get list of supported document categories."""
    from documentai_api.config.constants import DOCUMENT_CATEGORIES

    data = [{"category": c} for c in DOCUMENT_CATEGORIES]

    if format == DictionaryFormatType.CSV:
        return build_csv_response(data)

    return DictionaryDocumentCategoriesResponse(document_categories=DOCUMENT_CATEGORIES)


# ==============================================================================
# Rule configuration endpoints
# ==============================================================================


@app.get(
    "/v1/config/extraction-rules",
    dependencies=[Depends(verify_api_key)],
    name="getExtractionRules",
    response_model=ExtractionRulesListResponse,
    tags=[ApiVisualizationTag.CONFIG_RULES],
)
async def get_extraction_rules(
    tenant_id: str,
    document_type: str | None = None,
) -> Any:
    """Get extraction rules for a tenant."""
    from documentai_api.utils.extraction_rules import get_rules

    rules = get_rules(tenant_id, document_type)

    if not rules:
        raise HTTPException(status_code=404, detail="No rules found")
    return ExtractionRulesListResponse(rules=[ExtractionRuleItem(**r) for r in rules])


@app.put(
    "/v1/config/extraction-rules",
    dependencies=[Depends(verify_api_key)],
    name="putExtractionRule",
    response_model=ExtractionRuleItem,
    tags=[ApiVisualizationTag.CONFIG_RULES],
)
async def put_extraction_rule(
    tenant_id: Annotated[str, Form()],
    document_type: Annotated[str, Form()],
    required_fields: Annotated[str, Form()],  # JSON string list of required field names
    optional_fields: Annotated[str, Form()],  # JSON string list of optional field names
) -> Any:
    """Create or update an extraction rule."""
    from documentai_api.utils.extraction_rules import upsert_rule

    try:
        parsed_required_fields = json.loads(required_fields)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400, detail="required_fields must be valid JSON array"
        ) from None

    try:
        parsed_optional_fields = json.loads(optional_fields)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400, detail="optional_fields must be valid JSON array"
        ) from None

    rule = upsert_rule(tenant_id, document_type, parsed_required_fields, parsed_optional_fields)
    return ExtractionRuleItem(**rule)


@app.delete(
    "/v1/config/extraction-rules",
    dependencies=[Depends(verify_api_key)],
    name="deleteExtractionRule",
    response_model=ExtractionRuleDeleteResponse,
    tags=[ApiVisualizationTag.CONFIG_RULES],
)
async def delete_extraction_rule(
    tenant_id: str,
    document_type: str,
) -> Any:
    """Delete an extraction rule."""
    from documentai_api.utils.extraction_rules import delete_rule

    delete_rule(tenant_id, document_type)
    return ExtractionRuleDeleteResponse(message="Rule deleted")
