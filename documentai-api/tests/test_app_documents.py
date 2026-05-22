"""Tests for document endpoints (upload, query, delete, search)."""

import pytest

from documentai_api.models.api_responses import JobStatusResponse
from documentai_api.utils.jobs import JobStatus


@pytest.fixture(autouse=True)
def _disable_auth(disable_auth):
    pass


def test_document_upload_no_file(api_client):
    response = api_client.post("/v1/documents")
    assert response.status_code == 422


def test_document_status_not_found(ddb_doc_metadata_table_resource, api_client):
    response = api_client.get("/v1/documents/fake-job-id")
    assert response.status_code == 404


def test_get_document_results_with_extracted_data(api_client, mocker):
    """Test getting results with extracted data."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.return_value = JobStatus(
        ddb_record={"fileName": "test.pdf", "tenantId": "test-tenant"},
        object_key="test.pdf",
        process_status="success",
        v1_response_json='{"jobId": "test-job-id", "jobStatus": "success", "message": "Document processed successfully"}',
    )

    mock_build_api_response = mocker.patch(
        "documentai_api.utils.response_builder.build_v1_api_response"
    )
    mock_build_api_response.return_value = {
        "jobId": "test-job-id",
        "jobStatus": "success",
        "message": "Document processed successfully",
        "extractedData": {},
    }

    response = api_client.get("/v1/documents/test-job-id?include_extracted_data=true")

    assert response.status_code == 200
    mock_build_api_response.assert_called_once_with(
        object_key="test.pdf",
        job_status="success",
        include_extracted_data=True,
    )


def test_get_document_results_in_progress(api_client, mocker):
    """Test getting results for in-progress job."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.return_value = JobStatus(
        ddb_record={"fileName": "test.pdf", "tenantId": "test-tenant"},
        object_key="test.pdf",
        process_status="started",
        v1_response_json=None,
    )

    response = api_client.get("/v1/documents/test-job-id")

    assert response.status_code == 200
    data = response.json()
    assert data["jobStatus"] == "started"
    assert "in progress" in data["message"].lower()


def test_create_document_invalid_file_type(api_client, empty_zip_bytes):
    """Test document upload with invalid file type."""
    files = {"file": ("test.zip", empty_zip_bytes, "application/zip")}
    response = api_client.post("/v1/documents", files=files)

    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]


def test_create_document_asynchronous(api_client, blank_pdf_bytes):
    """Test asynchronous document upload (default behavior, returns job_id immediately)."""
    files = {"file": ("test.pdf", blank_pdf_bytes, "application/pdf")}
    response = api_client.post("/v1/documents", files=files)

    assert response.status_code == 200
    data = response.json()
    assert "jobId" in data
    assert data["jobStatus"] == "not_started"
    assert "uploaded successfully" in data["message"].lower()


def test_create_document_with_external_fields(api_client, blank_pdf_bytes, mocker):
    """Test document upload with external_document_id, external_system_id, and ai_consent_flag."""
    mock_insert = mocker.patch("documentai_api.app_documents.insert_minimal_ddb_record")

    files = {"file": ("test.pdf", blank_pdf_bytes, "application/pdf")}
    data = {
        "external_document_id": "ext-doc-123",
        "external_system_id": "ext-sys-456",
        "ai_consent_flag": "true",
    }
    response = api_client.post("/v1/documents", files=files, data=data)

    assert response.status_code == 200
    call_kwargs = mock_insert.call_args.kwargs
    assert call_kwargs["external_document_id"] == "ext-doc-123"
    assert call_kwargs["external_system_id"] == "ext-sys-456"
    assert call_kwargs["ai_consent_flag"] is True


def test_create_document_ai_consent_declined(api_client, blank_pdf_bytes, mocker):
    """Test document upload with ai_consent_flag=false bypasses processing."""
    mock_insert = mocker.patch("documentai_api.app_documents.insert_minimal_ddb_record")
    mock_classify = mocker.patch("documentai_api.app_documents.classify_as_ai_consent_declined")
    mock_classify.return_value = {
        "response_code": "003",
        "response_message": "Document not processed - AI consent not provided",
    }
    mock_upload = mocker.patch("documentai_api.app_documents.upload_document_for_processing")

    files = {"file": ("test.pdf", blank_pdf_bytes, "application/pdf")}
    data = {"ai_consent_flag": "false"}
    response = api_client.post("/v1/documents", files=files, data=data)

    assert response.status_code == 200
    result = response.json()
    assert result["jobStatus"] == "ai_consent_declined"
    assert "AI consent not provided" in result["message"]
    mock_insert.assert_called_once()
    mock_classify.assert_called_once()
    mock_upload.assert_not_called()


def test_create_document_synchronous(api_client, blank_pdf_bytes, mocker):
    """Test synchronous document upload (wait=true)."""
    mock_get_results = mocker.patch("documentai_api.app.get_v1_document_processing_results")
    mock_get_results.return_value = JobStatusResponse(
        job_id="test-id", job_status="success", message="Document processed successfully"
    )

    files = {"file": ("test.pdf", blank_pdf_bytes, "application/pdf")}
    response = api_client.post("/v1/documents?wait=true", files=files)

    assert response.status_code == 200
    assert response.json()["jobStatus"] == "success"


def test_get_document_results_error_handling(api_client, mocker):
    """Test error handling in get_document_results."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.side_effect = Exception("Unexpected error")

    response = api_client.get("/v1/documents/test-job-id")

    assert response.status_code == 500
    assert "Failed to retrieve results" in response.json()["detail"]


def test_search_documents_success(api_client, mocker):
    """Test searching multiple job IDs returns results."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.side_effect = [
        JobStatus(
            ddb_record={"fileName": "test.pdf", "tenantId": "test-tenant"},
            object_key="test.pdf",
            process_status="success",
            v1_response_json='{"jobId": "job-1", "jobStatus": "success", "message": "Done"}',
        ),
        JobStatus(ddb_record=None, object_key=None, process_status=None, v1_response_json=None),
    ]

    response = api_client.post("/v1/documents/search", json={"jobIds": ["job-1", "job-2"]})

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    assert results[0]["jobStatus"] == "success"
    assert results[1]["jobStatus"] == "not_found"


def test_search_documents_in_progress(api_client, mocker):
    """Test search returns processing status for incomplete jobs."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.return_value = JobStatus(
        ddb_record={"fileName": "test.pdf", "tenantId": "test-tenant"},
        object_key="test.pdf",
        process_status="started",
        v1_response_json=None,
    )

    response = api_client.post("/v1/documents/search", json={"jobIds": ["job-1"]})

    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["jobStatus"] == "started"
    assert "in progress" in results[0]["message"].lower()


def test_search_documents_empty_list(api_client):
    """Test search with empty job_ids returns 400."""
    response = api_client.post("/v1/documents/search", json={"jobIds": []})
    assert response.status_code == 400


def test_search_documents_exceeds_limit(api_client):
    """Test search with too many job_ids returns 400."""
    job_ids = [f"job-{i}" for i in range(26)]
    response = api_client.post("/v1/documents/search", json={"jobIds": job_ids})
    assert response.status_code == 400
    assert "Maximum of 25" in response.json()["detail"]


def test_search_documents_handles_errors_gracefully(api_client, mocker):
    """Test search continues when individual job lookup fails."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.side_effect = Exception("DDB error")

    response = api_client.post("/v1/documents/search", json={"jobIds": ["job-1"]})

    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["jobStatus"] == "error"
    assert "Failed to retrieve" in results[0]["message"]


def test_delete_document_success(api_client, mocker):
    """Test successful document deletion."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.return_value = JobStatus(
        ddb_record={"fileName": "test.pdf", "tenantId": "test-tenant"},
        object_key="test.pdf",
        process_status="success",
        v1_response_json='{"jobId": "job-1", "jobStatus": "success", "message": "Done"}',
    )
    mock_s3_delete = mocker.patch("documentai_api.services.s3.delete_object")
    mock_update_ddb = mocker.patch("documentai_api.utils.ddb.update_ddb")

    response = api_client.delete("/v1/documents/job-1")

    assert response.status_code == 204
    mock_s3_delete.assert_called_once()
    mock_update_ddb.assert_called_once()


def test_delete_document_not_found(api_client, mocker):
    """Test deleting non-existent document returns 404."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.return_value = JobStatus(
        ddb_record=None, object_key=None, process_status=None, v1_response_json=None
    )

    response = api_client.delete("/v1/documents/fake-job")

    assert response.status_code == 404


def test_delete_document_still_processing(api_client, mocker):
    """Test deleting in-progress document returns 400."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.return_value = JobStatus(
        ddb_record={"fileName": "test.pdf", "tenantId": "test-tenant"},
        object_key="test.pdf",
        process_status="started",
        v1_response_json=None,
    )

    response = api_client.delete("/v1/documents/job-1")

    assert response.status_code == 400
    assert "still processing" in response.json()["detail"]


def test_delete_document_already_deleted(api_client, mocker):
    """Test deleting already-deleted document returns 404."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.return_value = JobStatus(
        ddb_record={"fileName": "test.pdf"},
        object_key="test.pdf",
        process_status="deleted",
        v1_response_json=None,
    )

    response = api_client.delete("/v1/documents/job-1")

    assert response.status_code == 404


def test_get_document_results_deleted_returns_404(api_client, mocker):
    """Test GET on deleted document returns 404."""
    mock_get_job_status = mocker.patch("documentai_api.app_documents.get_job_status")
    mock_get_job_status.return_value = JobStatus(
        ddb_record={"fileName": "test.pdf"},
        object_key="test.pdf",
        process_status="deleted",
        v1_response_json='{"jobId": "job-1", "jobStatus": "deleted", "message": "Document has been deleted"}',
    )

    response = api_client.get("/v1/documents/job-1")

    assert response.status_code == 404
