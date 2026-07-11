import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))

print("Importing ovrtx...", flush=True)
import ovrtx
import numpy as np
print("ovrtx imported", flush=True)

SCENE = Path(__file__).parent.parent / "data" / "simple_scene.usda"

print("Creating Renderer...", flush=True)
config = ovrtx.RendererConfig(
    selection_outline_enabled=True,
    log_file_path="ovrtx-step.log",
)
r = ovrtx.Renderer(config=config)
print("Renderer created", flush=True)

print(f"Opening USD: {SCENE.resolve()}...", flush=True)
r.open_usd(str(SCENE.resolve()))
print("open_usd done, resetting...", flush=True)
r.reset()
print("reset done", flush=True)

products = r.query_prims(
    require_all=[(ovrtx.FilterKind.PRIM_TYPE, "RenderProduct")],
    attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
)
product = list(products.keys())[0]
print(f"Using render product: {product}", flush=True)

print("Calling step()...", flush=True)
start = time.time()
res = r.step(render_products={product}, delta_time=1.0 / 60.0)
elapsed = time.time() - start
print(f"step() completed in {elapsed:.1f}s", flush=True)
print(f"Products returned: {list(res.keys())}", flush=True)
frame = res[product].frames[0]
print(f"Frame render vars: {list(frame.render_vars.keys())}", flush=True)
mapping = frame.render_vars["LdrColor"].map(device=ovrtx.Device.CPU)
pixels = np.from_dlpack(mapping)
print(f"Pixels shape: {pixels.shape}, dtype: {pixels.dtype}", flush=True)

print("Done.", flush=True)
