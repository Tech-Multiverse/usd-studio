import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))

print("Importing ovrtx...", flush=True)
import ovrtx
print("ovrtx imported", flush=True)

SCENE = Path(__file__).parent.parent / "data" / "simple_scene.usda"

print("Creating Renderer...", flush=True)
config = ovrtx.RendererConfig(
    selection_outline_enabled=True,
    log_file_path="ovrtx-open.log",
)
r = ovrtx.Renderer(config=config)
print("Renderer created", flush=True)

print(f"Opening USD: {SCENE.resolve()}...", flush=True)
start = time.time()
r.open_usd(str(SCENE.resolve()))
elapsed = time.time() - start
print(f"open_usd completed in {elapsed:.1f}s", flush=True)

print("Querying render products...", flush=True)
products = r.query_prims(
    require_all=[(ovrtx.FilterKind.PRIM_TYPE, "RenderProduct")],
    attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
)
print(f"Render products: {list(products.keys())}", flush=True)

print("Querying cameras...", flush=True)
cameras = r.query_prims(
    require_all=[(ovrtx.FilterKind.PRIM_TYPE, "Camera")],
    attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
)
print(f"Cameras: {list(cameras.keys())}", flush=True)

print("Done.", flush=True)
