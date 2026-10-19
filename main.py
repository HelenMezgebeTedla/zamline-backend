from fastapi import FastAPI

from database import Base, engine
from routers.shipment_matches import router as shipment_matches_router
from routers.trucks import router as trucks_router
from routers.companies import router as companies_router
from routers.shipments import router as shipments_router
from routers.users import router as users_router
from routers.audit_logs import router as audit_logs_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ZamLine", version="0.2.0")

app.include_router(shipment_matches_router)
app.include_router(trucks_router)
app.include_router(users_router)
app.include_router(audit_logs_router)
app.include_router(companies_router)
app.include_router(shipment_matches_router)
app.include_router(shipments_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
