from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.allergies import router as allergies_router
from app.api.auth import router as auth_router
from app.api.conditions import router as conditions_router
from app.api.health import router as health_router
from app.api.health_profile import router as health_profile_router
from app.api.medications import router as medications_router
from app.api.symptoms import router as symptoms_router
from app.api.workspace import router as workspace_router
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.API_V1_STR)
app.include_router(allergies_router, prefix=settings.API_V1_STR)
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(health_profile_router, prefix=settings.API_V1_STR)
app.include_router(conditions_router, prefix=settings.API_V1_STR)
app.include_router(medications_router, prefix=settings.API_V1_STR)
app.include_router(symptoms_router, prefix=settings.API_V1_STR)
app.include_router(workspace_router, prefix=settings.API_V1_STR)


@app.get("/")
async def root():
    return {
        "message": "Personal Healthcare API",
        "health_check": f"{settings.API_V1_STR}/health",
    }
