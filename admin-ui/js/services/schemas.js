import { adminClient } from "./http.js";

export async function list() {
  return adminClient.request("GET", "/v1/dictionary/schemas");
}

export async function get(documentType) {
  return adminClient.request("GET", `/v1/dictionary/schemas/${encodeURIComponent(documentType)}`);
}
