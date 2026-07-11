import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))

print("Importing ovrtx...", flush=True)
import ovrtx
print("ovrtx imported", flush=True)

print("Creating RendererConfig...", flush=True)
config = ovrtx.RendererConfig(
    selection_outline_enabled=True,
    log_file_path="ovrtx-create.log",
)
print("RendererConfig created", flush=True)

print("Creating Renderer (this should take < 30 s)...", flush=True)
start = time.time()
r = ovrtx.Renderer(config=config)
elapsed = time.time() - start
print(f"Renderer created in {elapsed:.1f}s", flush=True)

print("Querying prims...", flush=True)
prims = r.query_prims(attribute_filter_mode=ovrtx.AttributeFilterMode.NONE)
print(f"Prims found: {len(prims)}", flush=True)

print("Done.", flush=True)
