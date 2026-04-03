import uvicorn
from fastapi import FastAPI

from router import router

app = FastAPI(
    title="Kyron Medical — Scheduler Service",
    description="Appointment scheduling REST API for the Kyron Medical patient portal.",
    version="1.0.0",
)

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=3002, reload=False)
