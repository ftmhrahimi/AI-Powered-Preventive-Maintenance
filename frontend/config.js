// Runtime configuration template.
// At container startup, envsubst renders this file with values from the
// environment (see frontend/Dockerfile and docker-compose.yml).
//
// BACKEND_URL is empty by default so all API calls are same-origin and are
// proxied to the backend container by nginx (see nginx.conf). This means no
// server IP is ever baked into the frontend.
window.APP_CONFIG = {
  BACKEND_URL:     "${BACKEND_URL}",
  MINIO_BASE:      "${FRONTEND_MINIO_BASE}",
  PHOTO_MAX_INDEX: ${PHOTO_MAX_INDEX}
};
