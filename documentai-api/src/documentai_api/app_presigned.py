"""Presigned URL endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Response

from documentai_api.config.constants import (
    ApiVisualizationTag,
    DocumentCategory,
    FileValidation,
    ProcessStatus,
    UploadMethod,
)
from documentai_api.config.env import get_aws_config
from documentai_api.logging import get_logger
from documentai_api.models.api_responses import PresignedUploadResponse
from documentai_api.utils.auth import UserContext, get_user_context
from documentai_api.utils.ddb import insert_minimal_ddb_record
from documentai_api.utils.uploads import generate_unique_filename

logger = get_logger(__name__)

router = APIRouter()

PRESIGNED_URL_EXPIRY_SECONDS = 900  # 15 minutes


@router.post(
    "/v1/documents/presigned-url",
    name="createPresignedUrl",
    tags=[ApiVisualizationTag.DOCUMENTS_UPLOAD],
)
async def create_presigned_upload_url(
    response: Response,
    filename: Annotated[str, Form(description="Original filename")],
    content_type: Annotated[str, Form(description="MIME type of the file")],
    auth: Annotated[UserContext, Depends(get_user_context)],
    category: Annotated[
        DocumentCategory | None, Form(description="Type of document being uploaded")
    ] = None,
    trace_id: Annotated[str | None, Header(alias="X-Trace-ID")] = None,
    external_document_id: Annotated[
        str | None, Form(description="External document identifier")
    ] = None,
    external_system_id: Annotated[
        str | None, Form(description="External system identifier")
    ] = None,
    ai_consent_flag: Annotated[bool | None, Form(description="AI consent flag")] = None,
) -> PresignedUploadResponse:
    """Generate a presigned URL for direct S3 upload."""
    from documentai_api.services import s3 as s3_service
    from documentai_api.utils.s3 import parse_s3_uri

    if content_type not in FileValidation.BDA_NATIVE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Presigned uploads only support BDA-native formats: "
                f"{', '.join(FileValidation.BDA_NATIVE)}. "
                f"For '{content_type}', use the direct upload endpoint (POST /v1/documents) "
                f"which handles format conversion automatically."
            ),
        )

    if not trace_id:
        trace_id = str(uuid.uuid4())

    input_location = get_aws_config().documentai_input_location
    if not input_location:
        raise HTTPException(status_code=500, detail="Upload location not configured")

    job_id = str(uuid.uuid4())
    unique_file_name = generate_unique_filename(filename, job_id)
    ddb_key = unique_file_name

    bucket_name, prefix = parse_s3_uri(input_location)
    object_key = f"{prefix}/{unique_file_name}" if prefix else unique_file_name

    insert_minimal_ddb_record(
        ddb_key=ddb_key,
        original_file_name=filename,
        job_id=job_id,
        process_status=ProcessStatus.PENDING_UPLOAD,
        user_provided_document_category=category,
        trace_id=trace_id,
        content_type=content_type,
        external_document_id=external_document_id,
        external_system_id=external_system_id,
        ai_consent_flag=ai_consent_flag,
        upload_method=UploadMethod.PRESIGNED,
        tenant_id=auth.tenant_id,
        client_name=auth.client_name,
    )

    metadata = {
        "job-id": job_id,
        "trace-id": trace_id,
        "original-file-name": filename,
    }
    if category:
        metadata["user-provided-document-category"] = category.value

    try:
        presigned_url = s3_service.generate_presigned_url(
            bucket=bucket_name,
            key=object_key,
            content_type=content_type,
            metadata=metadata,
            expiration=PRESIGNED_URL_EXPIRY_SECONDS,
        )
    except Exception as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate upload URL") from e

    headers = {
        "Content-Type": content_type,
        "x-amz-meta-job-id": job_id,
        "x-amz-meta-trace-id": trace_id,
        "x-amz-meta-original-file-name": filename,
    }
    if category:
        headers["x-amz-meta-user-provided-document-category"] = category.value

    response.headers["X-Trace-ID"] = trace_id
    return PresignedUploadResponse(
        upload_url=presigned_url,
        headers=headers,
        job_id=job_id,
        expires_in=PRESIGNED_URL_EXPIRY_SECONDS,
    )
