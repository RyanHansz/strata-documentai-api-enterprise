import { adminClient } from "./http.js";

export async function list() {
  return adminClient.request("GET", "/v1/config/extraction-rules");
}

export async function put(documentType, requiredFields, optionalFields) {
  return adminClient.request("PUT", "/v1/config/extraction-rules", {
    document_type: documentType,
    required_fields: requiredFields,
    optional_fields: optionalFields,
  });
}

export async function get(documentType) {
  return adminClient.request("GET", `/v1/config/extraction-rules?document_type=${encodeURIComponent(documentType)}`);
}

export async function remove(documentType) {
  return adminClient.request("DELETE", `/v1/config/extraction-rules?document_type=${encodeURIComponent(documentType)}`);
}
