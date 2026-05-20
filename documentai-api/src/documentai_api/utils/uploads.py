"""Shared helpers used by single-file and batch upload endpoints."""

import os
from io import BytesIO
from typing import BinaryIO

import filetype  # type: ignore[import-untyped]
from fastapi import HTTPException, UploadFile

from documentai_api.config.constants import (
    DocumentCategory,
    FileValidation,
    S3MetadataKeys,
)
from documentai_api.config.env import EnvVars
from documentai_api.logging import get_logger
from documentai_api.services import s3 as s3_service
from documentai_api.utils.image_conversion import convert_to_png
from documentai_api.utils.s3 import parse_s3_uri

logger = get_logger(__name__)


class ImageConversionError(Exception):
    """Raised when image format conversion fails."""


async def validate_file_type(file: UploadFile) -> str:
    """Read the file, detect its MIME type, verify it's supported, reset the read pointer.

    Returns the detected content type string.

    Raises:
        HTTPException 400: if the type isn't in FileValidation.SUPPORTED_CONTENT_TYPES.
    """
    file_content = await file.read()
    actual_content_type = filetype.guess_mime(file_content) or "application/octet-stream"

    if not FileValidation.is_supported(actual_content_type):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid file type detected '{actual_content_type}'"
                + (f" for '{file.filename}'" if file.filename else "")
                + f". File must be {', '.join(FileValidation.SUPPORTED_CONTENT_TYPES)}"
            ),
        )

    file.file.seek(0)  # reset pointer for subsequent reads
    return actual_content_type


def _save_original_to_preprocessing(file_bytes: bytes, object_key: str, content_type: str) -> None:
    """Save original file to preprocessing location for audit trail."""
    preprocessing_location = os.environ.get(EnvVars.DOCUMENTAI_PREPROCESSING_LOCATION)
    if not preprocessing_location:
        return

    pre_bucket, pre_prefix = parse_s3_uri(preprocessing_location)
    pre_key = f"{pre_prefix}/{object_key}" if pre_prefix else object_key

    try:
        s3_service.upload_file(pre_bucket, pre_key, BytesIO(file_bytes), content_type)
        logger.info(f"Original file saved to preprocessing: {pre_key}")
    except Exception as e:
        logger.warning(f"Failed to save original to preprocessing: {e}")


async def upload_document_for_processing(
    src_file: BinaryIO,
    dest_path: str,
    original_file_name: str,
    content_type: str,
    user_provided_document_category: DocumentCategory | None = None,
    job_id: str | None = None,
    trace_id: str | None = None,
    batch_id: str | None = None,
    build_id: str | None = None,
) -> None:
    """Upload a document file to S3 with traceability metadata.

    If the file requires format conversion (HEIC, WebP, GIF, BMP), the original
    is saved to the preprocessing location and a converted PNG is uploaded to the
    destination path.
    """
    bucket_name, object_key = parse_s3_uri(dest_path)

    # handle format conversion for mobile/unsupported-by-BDA formats
    if FileValidation.needs_conversion(content_type):
        file_bytes = src_file.read()
        logger.info(
            f"Converting {content_type} to PNG",
            extra={"upload_filename": original_file_name, "original_size_bytes": len(file_bytes)},
        )

        _save_original_to_preprocessing(file_bytes, os.path.basename(object_key), content_type)

        try:
            converted_bytes = convert_to_png(file_bytes, content_type)
        except ValueError as e:
            raise ImageConversionError(str(e)) from e

        src_file = BytesIO(converted_bytes)
        content_type = "image/png"

    try:
        metadata = {}
        if user_provided_document_category:
            if not isinstance(user_provided_document_category, DocumentCategory):
                raise ValueError(
                    f"Expected DocumentCategory, got {type(user_provided_document_category)}"
                )

            metadata[S3MetadataKeys.USER_PROVIDED_DOCUMENT_CATEGORY] = (
                user_provided_document_category.value
            )

        metadata[S3MetadataKeys.ORIGINAL_FILE_NAME] = original_file_name

        if job_id:
            metadata[S3MetadataKeys.JOB_ID] = job_id

        if trace_id:
            metadata[S3MetadataKeys.TRACE_ID] = trace_id

        if batch_id:
            metadata[S3MetadataKeys.BATCH_ID] = batch_id

        if build_id:
            metadata[S3MetadataKeys.BUILD_ID] = build_id

        logger.debug(
            "S3: Starting upload",
            extra={"metadata": metadata, "dest_path": dest_path},
        )

        s3_service.upload_file(bucket_name, object_key, src_file, content_type, metadata)
        logger.info("=== S3 UPLOAD SUCCESS ===")

    except Exception as e:
        logger.error(f"Error uploading file to S3: {e}")
        raise HTTPException(
            status_code=500,
            detail="Document upload failed",
        ) from e
