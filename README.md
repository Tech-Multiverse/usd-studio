# USD Studio

A browser-based multimedia production tool built on NVIDIA Omniverse libraries:
- [`ovrtx`](https://github.com/nvidia-omniverse/ovrtx) for RTX rendering
- [`ovstream`](https://github.com/nvidia-omniverse/ovstream) for WebRTC streaming
- [`ovphysx`](https://github.com/NVIDIA-Omniverse/PhysX/tree/main/ovphysx) for physics (planned)

Load a USD scene, view it live in the browser, and render stills or MP4 videos for media production.

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

5. Enter a USD scene path (e.g. `C:/Users/Rob/dev/usd_studio/data/simple_scene.usda`) and click **Load Scene**, then **Start Stream**.

## Project Layout

```
usd_studio/
  backend/src/usd_studio/   FastAPI backend
    renderer.py             ovrtx wrapper with camera/light injection
    streamer.py             ovstream WebRTC streaming
    usd_utils.py            USD composition helpers
    main.py                 API endpoints
  frontend/                 React + TypeScript UI
  data/                     Sample USD scenes
  outputs/                  Rendered stills/videos
  docker-compose.yml        Future Docker support
```

## Notes

- The first run of `ovrtx` compiles and caches shaders; startup may take a minute or two.
- If a USD scene lacks a camera or light, the backend injects a default camera, dome light, and distant light automatically.
- The nut-and-bolt digital twin references absolute paths; a studio wrapper will be added to repath those assets.
