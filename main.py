from fastapi import FastAPI
from database import Base, engine
from routers.shipment_matches import router as shipment_matches_router
from routers.shipments import router as shipments_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ZamLine", version="0.1.0")

app.include_router(shipment_matches_router)

app.include_router(shipments_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
