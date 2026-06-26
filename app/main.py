from fastapi import FastAPI

from app.modules.auth.routers.auth_routers import router as authroute

app = FastAPI()
app.include_router(authroute)

@app.get("/")
def hello():
    return "running"