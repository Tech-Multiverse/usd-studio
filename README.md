# USD Studio

  > **UNDER CONSTRUCTION** 🚧   
> USD Studio is an active work in progress!

A browser-based multimedia production tool built on NVIDIA Omniverse libraries:
- [`ovrtx`](https://github.com/nvidia-omniverse/ovrtx) for RTX rendering
- [`ovstream`](https://github.com/nvidia-omniverse/ovstream) for WebRTC streaming
- [`ovphysx`](https://github.com/NVIDIA-Omniverse/PhysX/tree/main/ovphysx) for rigid-body physics

Load a USD scene, view it live in the browser, run its rigid-body simulation, and render stills or MP4 videos for media production.

## Requirements

- Windows 10/11 with an NVIDIA RTX-capable GPU
- NVIDIA driver supporting CUDA 12.x (tested with driver 580.97 / CUDA 13.0)
- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) with the `usd_studio_env` environment

## Quick Start

1. Activate the conda environment:
   ```powershell
   conda activate usd_studio_env
   ```

2. Start the FastAPI backend:
   ```powershell
   cd backend
   python -m usd_studio.main
   ```

3. In a second terminal, start the React frontend:
   ```powershell
   cd frontend
   npm run dev
   ```

4. Open http://localhost:5173 in your browser.

5. Click **Browse...** and select a `.usd`, `.usda`, `.usdc`, or `.usdz` scene. You can also enter a server-local path and click **Load Scene**.

6. WebRTC streaming starts automatically after the scene loads. Physics initialization is enabled by default and remains paused until you click **Play**. Clear **Initialize physics after load** before loading if you only want rendering.

### Scene Loading

- **Browse:** Uploads the selected scene to the backend and loads it immediately. Prefer `.usdz` for scenes that depend on textures, layers, or other files because browser uploads select one file at a time.
- **Path:** Loads a path directly from the backend machine. Use this for unpackaged scenes with relative asset references.
- **Streaming:** Starts and connects automatically when a scene is available. Manual stream controls remain available as a fallback.
- **Physics:** Initializes automatically by default but does not auto-play. Scenes without supported rigid bodies report a physics error without preventing rendering.

## Project Layout

```
usd_studio/
  backend/src/usd_studio/   FastAPI backend
    renderer.py             ovrtx wrapper with camera/light injection
    streamer.py             ovstream WebRTC streaming
    physics.py              ovphysx worker controller
    physics_worker.py       isolated CPU physics process
    usd_utils.py            USD composition helpers
    main.py                 API endpoints
  frontend/                 React + TypeScript UI
  data/                     Sample USD scenes
  outputs/                  Rendered stills/videos
  docker-compose.yml        Future Docker support
```

## Notes

- The first run of `ovrtx` or `ovphysx` compiles and caches shaders; startup may take a minute or two.
- If a USD scene lacks a camera or light, the backend injects a default camera, dome light, and distant light automatically.
- Physics runs in an isolated CPU subprocess because `ovrtx` and `ovphysx` must not coexist in one process.
- Browser uploads copy only the selected file. Use `.usdz` or the server-local path field when a scene has external dependencies.
