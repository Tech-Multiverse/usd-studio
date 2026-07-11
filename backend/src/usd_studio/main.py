"""FastAPI application for USD Studio."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .config import settings
from .renderer import StudioRenderer
from .streamer import WebRTCStreamer

logger = logging.getLogger(__name__)

renderer: Optional[StudioRenderer] = None
streamer: Optional[WebRTCStreamer] = None


class LoadSceneRequest(BaseModel):
    path: str
    camera_path: Optional[str] = None
    render_product: Optional[str] = None


class CameraOrbitRequest(BaseModel):
    center_x: float = 0.0
    center_y: float = 0.0
    center_z: float = 0.0
    radius: float = 1.5
    yaw: float = 0.0
    pitch: float = 0.3


class StillRenderRequest(BaseModel):
    filename: str = "still.png"
    quality: int = 95


@asynccontextmanager
async def lifespan(app: FastAPI):
    global renderer, streamer
    logging.basicConfig(level=logging.INFO)
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.outputs_dir).mkdir(parents=True, exist_ok=True)

    renderer = StudioRenderer(width=settings.render_width, height=settings.render_height)
    streamer = WebRTCStreamer(renderer, signal_port=settings.webrtc_signal_port)

    # Load the default scene if one is configured.
    default = settings.default_scene or ""
    if default and Path(default).exists():
        try:
            await asyncio.to_thread(renderer.load_scene, default)
            logger.info("Loaded default scene: %s", default)
        except Exception as exc:
            logger.warning("Failed to load default scene %s: %s", default, exc)

    try:
        yield
    finally:
        if streamer:
            streamer.stop()
        if renderer:
            renderer.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"ok": True, "scene_loaded": renderer.has_scene if renderer else False}


@app.get("/api/scene")
async def scene_info():
    if not renderer or not renderer.has_scene:
        return {"loaded": False}
    return {
        "loaded": True,
        "scene": str(renderer.scene_path),
        "camera": renderer.camera_path,
        "render_product": renderer.render_product,
    }


@app.post("/api/scene/load")
async def load_scene(req: LoadSceneRequest):
    if not renderer:
        raise HTTPException(status_code=503, detail="Renderer not ready")
    path = Path(req.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Scene not found: {path}")
    try:
        info = await asyncio.to_thread(
            renderer.load_scene,
            path,
            req.camera_path,
            req.render_product,
        )
        return info
    except Exception as exc:
        logger.exception("Failed to load scene")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/scene/upload")
async def upload_scene(file: UploadFile = File(...)):
    if not renderer:
        raise HTTPException(status_code=503, detail="Renderer not ready")
    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    dest = uploads / (file.filename or "scene.usda")
    try:
        with open(dest, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"path": str(dest.resolve())}


@app.get("/api/cameras")
async def list_cameras():
    if not renderer or not renderer.has_scene:
        return {"cameras": []}
    return {"cameras": renderer.list_cameras()}


@app.get("/api/render_products")
async def list_render_products():
    if not renderer or not renderer.has_scene:
        return {"render_products": []}
    return {"render_products": renderer.list_render_products()}


@app.post("/api/camera/orbit")
async def orbit_camera(req: CameraOrbitRequest):
    if not renderer or not renderer.has_scene:
        raise HTTPException(status_code=503, detail="No scene loaded")
    import numpy as np
    center = np.array([req.center_x, req.center_y, req.center_z], dtype=np.float64)
    await asyncio.to_thread(
        renderer.orbit_camera,
        center,
        req.radius,
        req.yaw,
        req.pitch,
    )
    return {"ok": True}


@app.post("/api/render/still")
async def render_still(req: StillRenderRequest):
    if not renderer or not renderer.has_scene:
        raise HTTPException(status_code=503, detail="No scene loaded")
    out = Path(settings.outputs_dir) / req.filename
    try:
        await asyncio.to_thread(renderer.save_still, out, req.quality)
        return {"path": str(out)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/outputs/{filename}")
async def get_output(filename: str):
    path = Path(settings.outputs_dir) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@app.post("/api/webrtc/start")
async def start_webrtc():
    if not streamer:
        raise HTTPException(status_code=503, detail="Streamer not ready")
    if not renderer or not renderer.has_scene:
        raise HTTPException(status_code=503, detail="Load a scene before streaming")
    if streamer._running:
        return {
            "signal_port": streamer.signal_port,
            "width": streamer.width,
            "height": streamer.height,
            "already_running": True,
        }
    try:
        info = streamer.start()
        return info
    except Exception as exc:
        logger.exception("Failed to start WebRTC")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/webrtc/status")
async def webrtc_status():
    return {
        "signal_port": settings.webrtc_signal_port,
        "running": streamer._running if streamer else False,
    }


def main():
    uvicorn.run("usd_studio.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
