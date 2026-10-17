from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS
from routers.companies import router as companies_router
from routers.shipment_matches import router as shipment_matches_router
from routers.shipments import router as shipments_router
from routers.users import router as users_router

app = FastAPI(title="ZamLine", version="0.1.0")

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

app.include_router(users_router)
app.include_router(companies_router)
app.include_router(shipment_matches_router)
app.include_router(shipments_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
