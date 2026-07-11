import sys
from pathlib import Path
import numpy as np
import ovrtx
from PIL import Image

USD_URL = "https://omniverse-content-production.s3.us-west-2.amazonaws.com/Samples/Robot-OVRTX/robot-ovrtx.usda"
OUTPUT = Path("c:/Users/Rob/dev/usd_studio/outputs/smoke.png")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

print("Creating renderer...", file=sys.stderr)
renderer = ovrtx.Renderer()
print("Loading USD...", file=sys.stderr)
renderer.open_usd(USD_URL)
print("Stepping...", file=sys.stderr)
products = renderer.step(render_products={"/Render/Camera"}, delta_time=1.0 / 60)
print("Reading output...", file=sys.stderr)
for product in products.values():
    for frame in product.frames:
        var = frame.render_vars["LdrColor"].map(device=ovrtx.Device.CPU)
        pixels = np.from_dlpack(var)
        img = Image.fromarray(pixels)
        img.save(OUTPUT)
        print(f"Saved {OUTPUT} ({img.size})")
