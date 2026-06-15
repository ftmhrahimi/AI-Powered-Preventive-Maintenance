# PM Batch Validator — Production Infrastructure

This repository contains a Flask-based backend and a single-page HTML frontend for validating preventive maintenance PDF reports using AI and object storage.

## Features
- Multi-user authentication and shared report database.
- Parallel PDF processing with job-level Pause/Resume controls.
- AI-based validation of checklist items and checkbox states.
- Automatic extraction of photos and metadata from PDF reports.
- Structured logging to console and file.
- Production-ready WSGI setup using Gunicorn.
- Configurable CORS and rate limiting.
- Docker and Docker Compose support.

## Getting Started

> **Deploying to the offline production server (10.130.154.133)?**
> Follow the step-by-step guide in [DEPLOYMENT.md](DEPLOYMENT.md). It covers
> building images on a connected machine, transferring them with
> `docker save`/`docker load`, configuration, backups, and troubleshooting.

### Prerequisites
- Docker and Docker Compose
- OR Python 3.11+
- External LLM inference server (vLLM, configured in `.env`)
- MinIO is **included** in `docker-compose.yml` (no external MinIO needed)

### Deployment Scenarios

#### 1. Docker Compose (recommended)
1. **Prepare configuration**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to set your service addresses and `ALLOWED_ORIGIN`.

2. **Launch the stack**:
   ```bash
   docker compose up --build -d
   ```
   The application will be available at `http://localhost`.

#### 2. Running Locally (Development)
**Backend**:
```bash
cd backend
pip install -r requirements.txt
cp ../.env .env
gunicorn -c gunicorn.conf.py server:app
```

**Frontend**:
Serve the `frontend/` directory with any static file server.

## API Documentation

### Health Check
- **Endpoint**: `GET /health`
- **Response**: `{"status": "ok"}`

### LLM Proxy
- **Endpoint**: `POST /api/llm`
- **Rate Limit**: 60 requests per minute.

### PDF Extraction
- **Endpoint**: `POST /extract`
- **Rate Limit**: 10 requests per minute.
- **Max File Size**: 50MB.

## Admin Panel
- Initial credentials come from `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env`
  (created on first start — change the password before deploying).
- View and manage reports across all users.

## File Structure
- `backend/server.py`: Main Flask application entry point.
- `backend/extractor.py`: PDF parsing and image extraction logic.
- `backend/db.py`: SQLite database management.
- `frontend/index.html`: Single-file frontend application.
- `backend/gunicorn.conf.py`: Configuration for the production WSGI server.
- `backend/logs/`: Directory containing application and access logs.
