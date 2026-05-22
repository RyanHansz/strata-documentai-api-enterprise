"""Document endpoints (upload, query, delete, search)."""

import json
import uuid
from typing import Annotated

import filetype  # type: ignore[import-untyped]
from fastapi import (
    APIRouter,
    Depends,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)

from documentai_api.config.constants import (
    ApiVisualizationTag,
    DocumentCategory,
    FileValidation,
    ProcessStatus,
    UploadMethod,
)
from documentai_api.config.env import get_aws_config
from documentai_api.logging import get_logger
from documentai_api.models.api_responses import (
    DocumentSearchRequest,
    DocumentSearchResponse,
    JobStatusResponse,
    UploadAsyncResponse,
)
from documentai_api.schemas.document_metadata import DocumentMetadata
from documentai_api.utils.auth import UserContext, get_user_context
from documentai_api.utils.ddb import (
    classify_as_ai_consent_declined,
    classify_as_conversion_failed,
    classify_as_failed,
    insert_minimal_ddb_record,
)
from documentai_api.utils.jobs import get_job_status
from documentai_api.utils.models import ClassificationData
from documentai_api.utils.tenant import validate_document_tenant_access
from documentai_api.utils.uploads import (
    ImageConversionError,
    generate_unique_filename,
    upload_document_for_processing,
)

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_user_context)])

MAX_SEARCH_JOB_IDS = 25


@router.post(
    "/v1/documents",
    name="postUpload",
    tags=[ApiVisualizationTag.DOCUMENTS_UPLOAD],
)
async def create_document(
    request: Request,
    response: Response,
    file: UploadFile,
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
    wait: bool = False,
    timeout: int = 180,
) -> UploadAsyncResponse | JobStatusResponse:
    """Upload a document for processing."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    if not trace_id:
        trace_id = str(uuid.uuid4())

    file_content = await file.read()
    actual_content_type = filetype.guess_mime(file_content) or "application/octet-stream"

    logger.info(
        "Upload received",
        extra={
            "upload_filename": file.filename,
            "declared_content_type": file.content_type,
            "detected_content_type": actual_content_type,
            "size_bytes": len(file_content),
            "first_bytes_hex": file_content[:16].hex() if file_content else "",
        },
    )

    if not FileValidation.is_supported(actual_content_type):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid file type detected '{actual_content_type}'. File must be "
                f"{', '.join(FileValidation.SUPPORTED_CONTENT_TYPES)}"
            ),
        )

    logger.info(
        f"Processing {file.filename}; category: {category}; content-type: {actual_content_type}"
    )

    file.file.seek(0)
    job_id = str(uuid.uuid4())
    unique_file_name = generate_unique_filename(file.filename, job_id)
    original_file_name = file.filename
    ddb_key = unique_file_name

    input_location = get_aws_config().documentai_input_location
    dest_path = f"{input_location}/{unique_file_name}"

    insert_minimal_ddb_record(
        ddb_key=ddb_key,
        original_file_name=original_file_name,
        job_id=job_id,
        user_provided_document_category=category,
        trace_id=trace_id,
        content_type=actual_content_type,
        external_document_id=external_document_id,
        external_system_id=external_system_id,
        ai_consent_flag=ai_consent_flag,
        upload_method=UploadMethod.DIRECT,
        tenant_id=auth.tenant_id,
        client_name=auth.client_name,
    )

    # bypass processing if AI consent not provided
    if ai_consent_flag is False:
        result = classify_as_ai_consent_declined(object_key=ddb_key)
        response.headers["X-Trace-ID"] = trace_id
        return JobStatusResponse(
            job_id=job_id,
            job_status=ProcessStatus.AI_CONSENT_DECLINED.value,
            message=result.get("response_message", "Document not processed"),
        )

    try:
        await upload_document_for_processing(
            src_file=file.file,
            dest_path=dest_path,
            original_file_name=file.filename,
            content_type=actual_content_type,
            user_provided_document_category=category,
            job_id=job_id,
            trace_id=trace_id,
        )
    except ImageConversionError as e:
        result = classify_as_conversion_failed(object_key=ddb_key, error_message=str(e))
        response.headers["X-Trace-ID"] = trace_id
        return JobStatusResponse(
            job_id=job_id,
            job_status=ProcessStatus.CONVERSION_FAILED.value,
            message=result.get("response_message", "Image conversion failed"),
        )
    except HTTPException as e:
        classify_as_failed(
            object_key=ddb_key,
            error_message=e.detail,
            data=ClassificationData(additional_info=e.detail),
        )
        raise

    response.headers["X-Trace-ID"] = trace_id
    if not wait:
        return UploadAsyncResponse(
            job_id=job_id,
            job_status=ProcessStatus.NOT_STARTED.value,
            message="Document uploaded successfully",
        )
    else:
        from documentai_api.app import get_v1_document_processing_results

        return await get_v1_document_processing_results(job_id, timeout)


@router.get(
    "/v1/documents/{job_id}",
    tags=[ApiVisualizationTag.DOCUMENTS_QUERY],
)
async def get_document_results(
    job_id: str,
    auth: Annotated[UserContext, Depends(get_user_context)],
    include_extracted_data: bool = False,
) -> JobStatusResponse:
    """Get processing results by job ID."""
    try:
        job_status = get_job_status(job_id)

        validate_document_tenant_access(job_status.ddb_record, auth.tenant_id, job_id)

        if job_status.process_status == ProcessStatus.DELETED.value:
            raise HTTPException(status_code=404, detail=f"Job ID {job_id} not found")

        if not job_status.v1_response_json:
            return JobStatusResponse(
                job_id=job_id,
                job_status=job_status.process_status or "processing",
                message="Processing in progress",
            )

        # processing complete
        if include_extracted_data:
            from documentai_api.utils.response_builder import build_v1_api_response

            if not job_status.object_key or not job_status.process_status:
                raise HTTPException(status_code=500, detail=f"Incomplete record for job {job_id}")

            return JobStatusResponse(
                **build_v1_api_response(
                    object_key=job_status.object_key,
                    job_status=job_status.process_status,
                    include_extracted_data=True,
                )
            )
        else:
            return JobStatusResponse(**json.loads(job_status.v1_response_json))

    except HTTPException:
        raise
    except Exception as e:
        msg = f"Error retrieving results for job {job_id}: {e}"
        logger.error(msg)
        raise HTTPException(status_code=500, detail="Failed to retrieve results") from e


@router.delete(
    "/v1/documents/{job_id}",
    name="deleteDocument",
    tags=[ApiVisualizationTag.DOCUMENTS_DELETE],
)
async def delete_document(
    job_id: str, auth: Annotated[UserContext, Depends(get_user_context)]
) -> Response:
    """Delete a document by job ID. Removes S3 file and marks DDB record as deleted."""
    from documentai_api.services import s3 as s3_service
    from documentai_api.utils.s3 import parse_s3_uri

    job_status = get_job_status(job_id)

    validate_document_tenant_access(job_status.ddb_record, auth.tenant_id, job_id)

    current_status = job_status.process_status
    if current_status == ProcessStatus.DELETED.value:
        raise HTTPException(status_code=404, detail=f"Job ID {job_id} not found")

    if not current_status or not ProcessStatus.is_classified(current_status):
        raise HTTPException(
            status_code=400, detail="Cannot delete a document that is still processing"
        )

    # delete S3 file
    if job_status.object_key:
        try:
            input_location = get_aws_config().documentai_input_location
            if input_location:
                bucket, prefix = parse_s3_uri(input_location)
                s3_key = f"{prefix}/{job_status.object_key}" if prefix else job_status.object_key
                s3_service.delete_object(bucket, s3_key)
        except Exception as e:
            logger.warning(f"Failed to delete S3 object for job {job_id}: {e}")

    # mark DDB record as deleted
    from documentai_api.utils.ddb import update_ddb

    if not job_status.object_key:
        raise HTTPException(status_code=500, detail=f"Incomplete record for job {job_id}")

    update_ddb(object_key=job_status.object_key, status=ProcessStatus.DELETED)

    return Response(status_code=204)


@router.post(
    "/v1/documents/search",
    name="searchDocuments",
    tags=[ApiVisualizationTag.DOCUMENTS_QUERY],
)
async def search_documents(
    body: DocumentSearchRequest, auth: Annotated[UserContext, Depends(get_user_context)]
) -> DocumentSearchResponse:
    """Search for multiple documents by job IDs."""
    if not body.job_ids:
        raise HTTPException(status_code=400, detail="job_ids must not be empty")
    if len(body.job_ids) > MAX_SEARCH_JOB_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum of {MAX_SEARCH_JOB_IDS} job_ids per request",
        )

    results: list[JobStatusResponse] = []
    for job_id in body.job_ids:
        try:
            job_status = get_job_status(job_id)

            if (
                not job_status.ddb_record
                or job_status.ddb_record.get(DocumentMetadata.TENANT_ID) != auth.tenant_id
            ):
                results.append(
                    JobStatusResponse(
                        job_id=job_id,
                        job_status="not_found",
                        message="Job ID not found",
                    )
                )
            elif not job_status.v1_response_json:
                results.append(
                    JobStatusResponse(
                        job_id=job_id,
                        job_status=job_status.process_status or "processing",
                        message="Processing in progress",
                    )
                )
            elif body.include_extracted_data:
                from documentai_api.utils.response_builder import build_v1_api_response

                if not job_status.object_key or not job_status.process_status:
                    results.append(
                        JobStatusResponse(
                            job_id=job_id,
                            job_status="error",
                            message="Incomplete record",
                        )
                    )
                else:
                    results.append(
                        JobStatusResponse(
                            **build_v1_api_response(
                                object_key=job_status.object_key,
                                job_status=job_status.process_status,
                                include_extracted_data=True,
                            )
                        )
                    )
            else:
                results.append(JobStatusResponse(**json.loads(job_status.v1_response_json)))
        except Exception as e:
            logger.error(f"Error retrieving job {job_id} in search: {e}")
            results.append(
                JobStatusResponse(
                    job_id=job_id,
                    job_status="error",
                    message="Failed to retrieve results",
                )
            )

    return DocumentSearchResponse(results=results)
