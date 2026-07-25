"""FastAPI application for USD Studio."""

import asyncio
import json
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .config import settings
from .physics import PhysicsController
from .renderer import StudioRenderer
from .scene_packages import (
    USD_EXTENSIONS,
    choose_root_scene,
    create_package_directory,
    extract_zip_package,
    find_scene_files,
    safe_relative_path,
)
from .streamer import WebRTCStreamer

logger = logging.getLogger(__name__)

renderer: Optional[StudioRenderer] = None
streamer: Optional[WebRTCStreamer] = None
physics: Optional[PhysicsController] = None


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


class CameraOrbitDeltaRequest(BaseModel):
    delta_yaw: float
    delta_pitch: float


class CameraPanRequest(BaseModel):
    dx: float
    dy: float


class CameraZoomRequest(BaseModel):
    delta: float


class PickRequest(BaseModel):
    x: float
    y: float


class SelectRequest(BaseModel):
    path: Optional[str] = None


class StillRenderRequest(BaseModel):
    filename: str = "still.png"
    quality: int = 95


@asynccontextmanager
async def lifespan(app: FastAPI):
    global renderer, streamer, physics
    logging.basicConfig(level=logging.INFO)
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.outputs_dir).mkdir(parents=True, exist_ok=True)

    renderer = StudioRenderer(width=settings.render_width, height=settings.render_height)
    streamer = WebRTCStreamer(renderer, signal_port=settings.webrtc_signal_port)
    physics = PhysicsController(renderer.apply_world_poses)

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
        if physics:
            physics.stop()
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
        if physics:
            await asyncio.to_thread(physics.stop)
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


async def write_upload(file: UploadFile, destination: Path, max_bytes: int) -> int:
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as target:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("Upload exceeds the configured size limit")
            target.write(chunk)
    return total


def package_response(directory: Path, preferred_name: str) -> dict:
    scenes = find_scene_files(directory)
    root_scene = choose_root_scene(scenes, preferred_name)
    return {
        "path": str(root_scene),
        "scenes": [str(scene) for scene in scenes],
        "package": str(directory.resolve()),
    }


@app.post("/api/scene/upload")
async def upload_scene(file: UploadFile = File(...)):
    if not renderer:
        raise HTTPException(status_code=503, detail="Renderer not ready")
    filename = Path(file.filename or "scene.usda").name
    if Path(filename).suffix.lower() not in USD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Choose a .usd, .usda, .usdc, or .usdz file")
    package_dir = create_package_directory(Path(settings.uploads_dir), filename)
    try:
        destination = package_dir / filename
        await write_upload(file, destination, settings.max_package_upload_bytes)
        return package_response(package_dir, filename)
    except ValueError as exc:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/scene/package/archive")
async def upload_scene_archive(file: UploadFile = File(...)):
    if not renderer:
        raise HTTPException(status_code=503, detail="Renderer not ready")
    filename = Path(file.filename or "scene.zip").name
    if Path(filename).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="Choose a .zip scene package")
    package_dir = create_package_directory(Path(settings.uploads_dir), filename)
    archive_path = package_dir / filename
    try:
        await write_upload(file, archive_path, settings.max_package_upload_bytes)
        await asyncio.to_thread(
            extract_zip_package,
            archive_path,
            package_dir,
            settings.max_package_files,
            settings.max_package_expanded_bytes,
        )
        archive_path.unlink(missing_ok=True)
        return package_response(package_dir, filename)
    except ValueError as exc:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/scene/package/folder")
async def upload_scene_folder(
    files: list[UploadFile] = File(...),
    relative_paths_json: str = Form(...),
):
    if not renderer:
        raise HTTPException(status_code=503, detail="Renderer not ready")
    try:
        relative_paths = json.loads(relative_paths_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid folder manifest") from exc
    if not isinstance(relative_paths, list) or len(relative_paths) != len(files):
        raise HTTPException(status_code=400, detail="Folder manifest does not match uploaded files")
    if not files or len(files) > settings.max_package_files:
        raise HTTPException(status_code=400, detail=f"Choose a folder with at most {settings.max_package_files} files")
    package_name = str(relative_paths[0]).replace("\\", "/").split("/", 1)[0]
    package_dir = create_package_directory(Path(settings.uploads_dir), package_name)
    try:
        destinations: set[Path] = set()
        total = 0
        for file, relative_value in zip(files, relative_paths):
            relative_path = safe_relative_path(str(relative_value))
            destination = (package_dir / relative_path).resolve()
            if package_dir.resolve() not in destination.parents or destination in destinations:
                raise ValueError(f"Invalid or duplicate package path: {relative_value}")
            destinations.add(destination)
            total += await write_upload(
                file,
                destination,
                settings.max_package_upload_bytes - total,
            )
        return package_response(package_dir, package_name)
    except ValueError as exc:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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


@app.post("/api/camera/orbit/delta")
async def orbit_camera_delta(req: CameraOrbitDeltaRequest):
    if not renderer or not renderer.has_scene:
        raise HTTPException(status_code=503, detail="No scene loaded")
    await asyncio.to_thread(renderer.orbit_delta, req.delta_yaw, req.delta_pitch)
    return {"ok": True}


@app.post("/api/camera/pan")
async def pan_camera(req: CameraPanRequest):
    if not renderer or not renderer.has_scene:
        raise HTTPException(status_code=503, detail="No scene loaded")
    await asyncio.to_thread(renderer.pan_delta, req.dx, req.dy)
    return {"ok": True}


@app.post("/api/camera/zoom")
async def zoom_camera(req: CameraZoomRequest):
    if not renderer or not renderer.has_scene:
        raise HTTPException(status_code=503, detail="No scene loaded")
    await asyncio.to_thread(renderer.zoom_delta, req.delta)
    return {"ok": True}


@app.post("/api/pick")
async def pick_prim(req: PickRequest):
    if not renderer or not renderer.has_scene:
        raise HTTPException(status_code=503, detail="No scene loaded")
    path = await asyncio.to_thread(renderer.pick, req.x, req.y)
    return {"path": path}


@app.post("/api/select")
async def select_prim(req: SelectRequest):
    if not renderer or not renderer.has_scene:
        raise HTTPException(status_code=503, detail="No scene loaded")
    selected = await asyncio.to_thread(renderer.select, req.path)
    return {"selected": selected}


@app.get("/api/selected")
async def get_selected():
    if not renderer or not renderer.has_scene:
        return {"selected": None}
    return {"selected": renderer.get_selected()}


@app.get("/api/physics/status")
async def physics_status():
    if not physics:
        raise HTTPException(status_code=503, detail="Physics controller not ready")
    return physics.status()


@app.post("/api/physics/initialize")
async def initialize_physics():
    if not renderer or not renderer.has_scene or not renderer.scene_path:
        raise HTTPException(status_code=503, detail="Load a scene before initializing physics")
    if not physics:
        raise HTTPException(status_code=503, detail="Physics controller not ready")
    try:
        body_paths = await asyncio.to_thread(renderer.list_rigid_bodies)
        return await asyncio.to_thread(physics.start, renderer.scene_path, body_paths)
    except Exception as exc:
        logger.exception("Failed to initialize physics")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def run_physics_command(command: str):
    if not physics:
        raise HTTPException(status_code=503, detail="Physics controller not ready")
    try:
        return await asyncio.to_thread(getattr(physics, command))
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/physics/play")
async def play_physics():
    return await run_physics_command("play")


@app.post("/api/physics/pause")
async def pause_physics():
    return await run_physics_command("pause")


@app.post("/api/physics/step")
async def step_physics():
    return await run_physics_command("step")


@app.post("/api/physics/reset")
async def reset_physics():
    return await run_physics_command("reset")


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
