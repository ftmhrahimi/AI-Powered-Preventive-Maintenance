// Runtime configuration template.
// At container startup, envsubst renders this file with values from the
// environment (see frontend/Dockerfile CMD and docker-compose.yml).
//
// BACKEND_URL is empty by default so all API calls are same-origin and are
// proxied to the backend container by nginx (see nginx.conf). This means no
// server IP is ever baked into the frontend.
window.APP_CONFIG = {
  BACKEND_URL:         "${BACKEND_URL}",
  LLM_URL:             "${BACKEND_URL}/api/llm",
  LLM_MODEL:           "${FRONTEND_LLM_MODEL}",
  MINIO_BASE:          "${FRONTEND_MINIO_BASE}",
  EXTRACT_API:         "${BACKEND_URL}/extract",
  JOB_API_BASE:        "${BACKEND_URL}",
  EXTRACT_PHOTOS:      ${FRONTEND_EXTRACT_PHOTOS},
  PHOTO_MAX_INDEX:     ${PHOTO_MAX_INDEX},
  GPS_RADIUS_METERS:   ${GPS_RADIUS_METERS},
  DATE_TOLERANCE_DAYS: ${DATE_TOLERANCE_DAYS}
};
