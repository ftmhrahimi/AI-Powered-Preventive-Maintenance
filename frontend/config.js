window.APP_CONFIG = {
  BACKEND_URL:         "http://10.224.235.31:9701",
  LLM_URL:             "http://10.224.235.31:9701/api/llm", 
  LLM_MODEL:           "./", 
  MINIO_BASE:          "http://10.224.235.31:9000/pm-photos", 
  EXTRACT_API:         "http://10.224.235.31:9701/extract", 
  JOB_API_BASE:        "http://10.224.235.31:9701",   // e.g. http://10.224.235.31:5000
  EXTRACT_PHOTOS:      false, 
  PHOTO_MAX_INDEX:     50, 
  GPS_RADIUS_METERS:   300, 
  DATE_TOLERANCE_DAYS: 3 
};

// window.APP_CONFIG = {
//   BACKEND_URL:         "${BACKEND_URL}",
//   LLM_URL:             "${FRONTEND_LLM_URL}", 
//   LLM_MODEL:           "${FRONTEND_LLM_MODEL}", 
//   MINIO_BASE:          "${FRONTEND_MINIO_BASE}", 
//   EXTRACT_API:         "${FRONTEND_EXTRACT_API}", 
//   EXTRACT_PHOTOS:      "${FRONTEND_EXTRACT_PHOTOS}", 
//   PHOTO_MAX_INDEX:     "${PHOTO_MAX_INDEX}", 
//   GPS_RADIUS_METERS:   "${GPS_RADIUS_METERS}", 
//   DATE_TOLERANCE_DAYS: "${DATE_TOLERANCE_DAYS}" 
// };
// window.APP_CONFIG = {
//   LLM_URL:             "http://10.224.235.31:9701/api/llm",
//   LLM_MODEL:           "./",
//   MINIO_BASE:          "http://10.224.235.31:9000/pm-photos",
//   EXTRACT_API:         "http://10.224.235.31:9701/extract",
//   BACKEND_URL:         "http://10.224.235.31:9701",
//   EXTRACT_PHOTOS:      false,
//   PHOTO_MAX_INDEX:     50,
//   GPS_RADIUS_METERS:   300,
//   DATE_TOLERANCE_DAYS: 3
// };
