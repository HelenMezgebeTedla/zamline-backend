from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS, ENVIRONMENT
from database import Base, engine
from security.http import install_security
from routers.audit_logs import router as audit_logs_router
from routers.companies import router as companies_router
from routers.cost_settings import router as cost_settings_router
from routers.reservations import router as reservations_router
from routers.shipment_matches import router as shipment_matches_router
from routers.shipments import router as shipments_router
from routers.trucks import router as trucks_router
from routers.users import router as users_router

Base.metadata.create_all(bind=engine)

PUBLIC_DOCS = ENVIRONMENT.strip().lower() != "production"

app = FastAPI(
    title="ZamLine",
    version="0.2.0",
    docs_url="/docs" if PUBLIC_DOCS else None,
    redoc_url="/redoc" if PUBLIC_DOCS else None,
    openapi_url="/openapi.json" if PUBLIC_DOCS else None,
)

install_security(app)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

app.include_router(users_router)
app.include_router(audit_logs_router)
app.include_router(companies_router)
app.include_router(cost_settings_router)
app.include_router(shipments_router)
app.include_router(trucks_router)
app.include_router(shipment_matches_router)
app.include_router(reservations_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
