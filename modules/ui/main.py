import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

app = FastAPI(title="Kyron Medical Patient Portal UI")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Serve static assets (CSS, JS, images, etc.)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def serve_index():
    """Serve the single-page patient portal."""
    return FileResponse(str(STATIC_DIR / "index.html"), media_type="text/html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
