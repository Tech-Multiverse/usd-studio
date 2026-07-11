import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))

from usd_studio.renderer import StudioRenderer

SCENE = Path(__file__).parent.parent / "data" / "simple_scene.usda"
OUT = Path(__file__).parent.parent / "outputs" / "simple_minimal.png"

t0 = time.time()
print(f"start", flush=True)
r = StudioRenderer(width=640, height=480)
print(f"renderer created in {time.time() - t0:.1f}s", flush=True)
info = r.load_scene(SCENE)
print(f"loaded in {time.time() - t0:.1f}s: {info}", flush=True)
OUT.parent.mkdir(parents=True, exist_ok=True)
r.save_still(OUT)
print(f"saved in {time.time() - t0:.1f}s: {OUT}", flush=True)
r.close()
print(f"done in {time.time() - t0:.1f}s", flush=True)
