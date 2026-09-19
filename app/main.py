from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.errors import ERROR_RESPONSES, add_error_handlers
from app.logging_setup import setup_logging
from app.middleware import RequestContextMiddleware
from app.modules.appointments.router import router as appointments_router
from app.modules.assignments.router import router as assignments_router
from app.modules.auth.router import router as auth_router
from app.modules.health.router import router as health_router
from app.modules.notifications.router import router as notifications_router
from app.modules.organisations.router import router as organisations_router
from app.modules.patients.router import app_router as patient_app_router
from app.modules.patients.router import router as patients_router
from app.modules.summary.router import router as summary_router
from app.modules.tasks.router import router as tasks_router
from app.modules.users.router import router as users_router

settings = get_settings()
setup_logging()

app = FastAPI(
    title="Healthcare CRM API",
    version="1.0.0",
    description=(
        "Backend for a healthcare CRM and its dedicated patient app.\n\n"
        "**Log in:** call `POST /api/v1/auth/login`, copy the `access_token`, click **Authorize** "
        "and paste it. Demo users are listed in the README (created by `python seed.py`).\n\n"
        "**Errors** always look like `{\"error\": {\"code\", \"message\", \"request_id\", \"fields\"}}`."
    ),
    # The interactive docs are for development. In production they are switched off.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

add_error_handlers(app)

# Only the origins listed in CORS_ORIGINS may call the API from a browser. Empty means none.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID", "X-API-Key"],
    expose_headers=["X-Request-ID", "Retry-After"],
)
# Added last, so it is the outermost layer and sees every request and response.
app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)

for router in [health_router, auth_router, organisations_router, users_router, patients_router,
               assignments_router, appointments_router, tasks_router, notifications_router, summary_router,
               patient_app_router]:
    app.include_router(router, responses=ERROR_RESPONSES)
