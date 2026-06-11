/**
 * Dev bypass: injects a fake session and mocks all API/Cognito calls so the
 * admin UI works without a real backend or Cognito pool.
 *
 * Loaded via a <script> tag BEFORE bundle.js.
 */

// --- Fake JWT (super-admin role, never expires) ---
function makeJwt(payload) {
  const enc = (obj) =>
    btoa(JSON.stringify(obj))
      .replace(/=/g, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(payload)}.fakesig`;
}

const FAKE_SESSION = {
  accessToken: makeJwt({ sub: "dev-user", exp: 9999999999 }),
  idToken: makeJwt({
    sub: "dev-user",
    email: "dev@example.com",
    "cognito:groups": ["super-admin"],
    exp: 9999999999,
  }),
  refreshToken: "fake-refresh",
  email: "dev@example.com",
  expiresAt: Date.now() + 24 * 60 * 60 * 1000,
};

sessionStorage.setItem("docai_console_session", JSON.stringify(FAKE_SESSION));

// --- Mock data (camelCase, matching what the views expect) ---

const MOCK_TENANTS = [
  { tenantId: "acme", displayName: "Acme Corp", primaryContact: "admin@acme.com", isActive: true },
  { tenantId: "globex", displayName: "Globex Inc", primaryContact: "ops@globex.com", isActive: true },
];

const MOCK_KEYS = [
  {
    keyPrefix: "sk_live_abc123",
    apiKeyName: "Production Key",
    environment: "production",
    tenantId: "acme",
    emailAddress: "admin@acme.com",
    isActive: true,
    createdAt: "2025-01-15T10:00:00Z",
    expiresAt: null,
    lastUsed: "2025-06-01T08:00:00Z",
  },
  {
    keyPrefix: "sk_test_def456",
    apiKeyName: "Test Key",
    environment: "test",
    tenantId: "globex",
    emailAddress: "dev@globex.com",
    isActive: true,
    createdAt: "2025-03-01T09:00:00Z",
    expiresAt: "2026-03-01T00:00:00Z",
    lastUsed: null,
  },
];

const MOCK_USERS = [
  { email: "alice@acme.com", tenantId: "acme", roles: ["tenant-admin"], isApproved: true },
  { email: "bob@globex.com", tenantId: "globex", roles: ["tenant-admin"], isApproved: true },
  { email: "pending@example.com", tenantId: null, roles: [], isApproved: false },
];

const MOCK_RULES = [
  {
    tenantId: "acme",
    documentType: "invoice",
    requiredFields: ["invoice_number", "date", "total"],
    optionalFields: ["vendor_name", "line_items"],
    blueprintArn: null,
  },
];

const MOCK_DOC_CATEGORIES = [
  { categoryId: "invoices", displayName: "Invoices", tenantId: "acme" },
  { categoryId: "contracts", displayName: "Contracts", tenantId: "acme" },
];

const MOCK_AUDIT_LOG = [
  { eventType: "login", email: "alice@acme.com", timestamp: "2025-06-10T14:32:00Z", details: {} },
  { eventType: "api_key_created", email: "alice@acme.com", timestamp: "2025-06-10T14:35:00Z", details: { keyName: "Production Key" } },
];

// --- Fetch interceptor ---
const _origFetch = window.fetch.bind(window);

window.fetch = async function (input, init) {
  const url = typeof input === "string" ? input : input.url;

  // config.json
  if (url.endsWith("config.json")) {
    return jsonResponse({
      api_endpoint: { value: "" },
      cognito_user_pool_id: { value: "fake" },
      cognito_client_id: { value: "fake" },
    });
  }

  // Cognito – silently succeed
  if (url.includes("cognito-idp") || url.includes("amazonaws.com")) {
    return jsonResponse({ message: "ok" });
  }

  // Derive path from URL (handles both absolute and relative URLs)
  const path = (() => {
    try {
      return new URL(url, location.origin).pathname;
    } catch {
      return url;
    }
  })();
  const method = (init?.method || "GET").toUpperCase();

  // Tenants
  if (path.startsWith("/v1/admin/tenants")) {
    if (method === "GET") return jsonResponse({ tenants: MOCK_TENANTS });
    if (method === "POST") {
      const body = JSON.parse(init?.body || "{}");
      const t = { tenantId: body.tenant_id, displayName: body.display_name, primaryContact: body.primary_contact, isActive: true };
      MOCK_TENANTS.push(t);
      return jsonResponse(t);
    }
    return jsonResponse({ success: true });
  }

  // API Keys
  if (path.startsWith("/v1/admin/api-keys")) {
    if (method === "GET") return jsonResponse({ keys: MOCK_KEYS });
    if (method === "POST") {
      const body = JSON.parse(init?.body || "{}");
      const newKey = {
        keyPrefix: "sk_new_" + Math.random().toString(36).slice(2, 8),
        apiKeyName: body.api_key_name,
        environment: body.environment,
        tenantId: body.tenant_id,
        emailAddress: body.email_address,
        isActive: true,
        createdAt: new Date().toISOString(),
        expiresAt: body.expires_at || null,
        lastUsed: null,
      };
      MOCK_KEYS.push(newKey);
      return jsonResponse({ ...newKey, apiKey: newKey.keyPrefix + "_FULL_KEY_SHOWN_ONCE" });
    }
    return jsonResponse({ success: true });
  }

  // Users
  if (path.startsWith("/v1/admin/users")) {
    if (method === "GET") return jsonResponse({ users: MOCK_USERS, tenants: MOCK_TENANTS });
    return jsonResponse({ success: true });
  }

  // Extraction rules
  if (path.startsWith("/v1/config/extraction-rules")) {
    if (method === "GET") return jsonResponse({ rules: MOCK_RULES });
    return jsonResponse({ success: true });
  }

  // Document categories
  if (path.includes("document-categories")) {
    if (method === "GET") return jsonResponse({ categories: MOCK_DOC_CATEGORIES });
    return jsonResponse({ success: true });
  }

  // Audit log
  if (path.startsWith("/v1/admin/audit")) {
    if (method === "GET") return jsonResponse({ items: MOCK_AUDIT_LOG, total: MOCK_AUDIT_LOG.length });
  }

  // Documents / test documents
  if (path.startsWith("/v1/admin/documents") || path.startsWith("/v1/documents")) {
    if (method === "GET") return jsonResponse({ items: [], total: 0 });
  }

  // Schemas / blueprints
  if (path.startsWith("/v1/config/schemas") || path.startsWith("/v1/admin/schemas")) {
    return jsonResponse({ schemas: [] });
  }

  // Health
  if (path.includes("/health")) {
    return jsonResponse({ status: "ok" });
  }

  // Fallback: real fetch (fonts, etc.)
  return _origFetch(input, init);
};

function jsonResponse(data, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}
