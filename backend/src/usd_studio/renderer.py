"""Thread-safe ovrtx renderer wrapper."""

import logging
import math
import tempfile
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import ovrtx
from PIL import Image

from .usd_utils import build_scene_layer

logger = logging.getLogger(__name__)


class StudioRenderer:
    """Wraps ovrtx.Renderer with scene loading, camera/light injection, and I/O."""

    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        render_product: Optional[str] = None,
        camera_path: Optional[str] = None,
    ):
        self.width = width
        self.height = height
        self.render_product = render_product
        self.camera_path = camera_path
        self.scene_path: Optional[Path] = None
        self.has_scene = False
        self._lock = threading.Lock()

        config = ovrtx.RendererConfig(
            selection_outline_enabled=True,
            log_file_path="ovrtx-studio.log",
        )
        self._renderer = ovrtx.Renderer(config=config)
        logger.info("ovrtx renderer created")

    def _discover_paths(self) -> None:
        if not self.render_product:
            products = self._renderer.query_prims(
                require_all=[(ovrtx.FilterKind.PRIM_TYPE, "RenderProduct")],
                attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
            )
            if products:
                # Prefer a Studio-injected render product over any existing
                # viewport textures that may be tied to missing sensors/cameras.
                paths = list(products.keys())
                for p in paths:
                    if p.startswith("/Studio/"):
                        self.render_product = p
                        break
                else:
                    self.render_product = paths[0]
                logger.info("Discovered render product: %s", self.render_product)
            else:
                logger.warning("No RenderProduct found in scene")

        if not self.camera_path:
            cameras = self._renderer.query_prims(
                require_all=[(ovrtx.FilterKind.PRIM_TYPE, "Camera")],
                attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
            )
            if cameras:
                self.camera_path = self._pick_main_camera(cameras)
                logger.info("Discovered camera: %s", self.camera_path)
            else:
                logger.warning("No Camera found in scene")

    @staticmethod
    def _pick_main_camera(cameras: dict) -> str:
        paths = list(cameras.keys())
        for path in paths:
            name = path.split("/")[-1].lower()
            if name in {"camera", "camera0", "cam", "maincamera"}:
                return path
        for path in paths:
            name = path.split("/")[-1].lower()
            if "motion" not in name and "test" not in name:
                return path
        return paths[0]

    def _frame_camera_to_scene(self) -> None:
        """Position the current camera to frame the scene bounding box.

        Filters out lights, cameras, render settings, and prims with non-finite
        or grossly large authored extents (e.g. ground planes).
        """
        try:
            prims = self._renderer.query_prims(
                require_all=[(ovrtx.FilterKind.HAS_ATTRIBUTE, "extent")],
                attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
            )
            if not prims:
                logger.warning("No prims with extent found; cannot auto-frame")
                return

            # Collect per-prim world-space bounding boxes, skipping known
            # non-renderable or unbounded prims.
            skip_tokens = {"light", "camera", "render", "studio", "looks", "material"}
            candidates = []
            for path in prims:
                lower = path.lower()
                if any(tok in lower for tok in skip_tokens):
                    continue
                if not lower.startswith("/world"):
                    continue
                try:
                    xform_tensor = self._renderer.read_attribute("omni:xform", [path])
                    xform = np.from_dlpack(xform_tensor).reshape(4, 4)
                    extent_tensor = self._renderer.read_attribute("extent", [path])
                    extent = np.from_dlpack(extent_tensor).reshape(-1, 3)
                    if extent.shape[0] < 2:
                        continue
                    local_min, local_max = extent[0], extent[1]
                    if not np.isfinite(local_min).all() or not np.isfinite(local_max).all():
                        continue
                    size = local_max - local_min
                    if not np.all(size >= 0):
                        continue
                    diagonal = float(np.linalg.norm(size))
                    if not np.isfinite(diagonal) or diagonal <= 0:
                        continue
                    candidates.append((path, xform, local_min, local_max, diagonal))
                except Exception:
                    continue

            if not candidates:
                logger.warning("No finite renderable prims found; cannot auto-frame")
                return

            # Reject outliers whose diagonal is more than 10x the median diagonal.
            # This drops huge ground planes while keeping the actual model.
            diagonals = sorted(c[4] for c in candidates)
            median_diag = diagonals[len(diagonals) // 2]
            max_allowed = max(median_diag * 10.0, median_diag + 1.0)

            world_min = np.full(3, float("inf"), dtype=np.float64)
            world_max = np.full(3, -float("inf"), dtype=np.float64)
            included = 0
            for _path, xform, local_min, local_max, diagonal in candidates:
                if diagonal > max_allowed:
                    continue
                corners = np.array([
                    [local_min[0], local_min[1], local_min[2], 1.0],
                    [local_min[0], local_min[1], local_max[2], 1.0],
                    [local_min[0], local_max[1], local_min[2], 1.0],
                    [local_min[0], local_max[1], local_max[2], 1.0],
                    [local_max[0], local_min[1], local_min[2], 1.0],
                    [local_max[0], local_min[1], local_max[2], 1.0],
                    [local_max[0], local_max[1], local_min[2], 1.0],
                    [local_max[0], local_max[1], local_max[2], 1.0],
                ], dtype=np.float64)
                world_corners = corners @ xform.T
                world_min = np.minimum(world_min, world_corners[:, :3].min(axis=0))
                world_max = np.maximum(world_max, world_corners[:, :3].max(axis=0))
                included += 1

            if not np.isfinite(world_min).all() or not np.isfinite(world_max).all():
                logger.warning("Could not compute scene bounds")
                return

            center = (world_min + world_max) * 0.5
            size = world_max - world_min
            radius = float(np.linalg.norm(size) * 0.5)
            if radius <= 0 or not np.isfinite(radius):
                radius = 1.0

            distance = max(radius * 2.5, 0.001)
            yaw = math.radians(45)
            pitch = math.radians(30)
            self.orbit_camera(center, distance, yaw, pitch)
            logger.info("Camera framed to %d prims: center=%s radius=%.4f", included, center, radius)
        except Exception as exc:
            logger.warning("Auto-frame failed: %s", exc)

    def load_scene(
        self,
        usd_path: str | Path,
        camera_path: Optional[str] = None,
        render_product: Optional[str] = None,
        auto_frame: bool = True,
    ) -> dict:
        """Open a USD stage, injecting camera/light/render product if needed."""
        with self._lock:
            usd_path = Path(usd_path)
            if not usd_path.exists():
                raise FileNotFoundError(usd_path)

            self.scene_path = usd_path.resolve()
            self.camera_path = camera_path
            self.render_product = render_product

            # First try loading the scene as-is to see what is present.
            self._renderer.open_usd(str(self.scene_path))
            self._renderer.reset()
            self._discover_paths()

            # Compose the scene through a Studio injection layer so we control
            # the render product resolution and can use the scene's camera.
            logger.info("Composing Studio render product at %dx%d", self.width, self.height)
            layer_usda, default_camera, default_product = build_scene_layer(
                self.scene_path,
                camera_path=self.camera_path,
                render_product_path=None,
                width=self.width,
                height=self.height,
            )
            self.camera_path = self.camera_path or default_camera
            self.render_product = default_product
            self._renderer.open_usd_from_string(layer_usda)
            self._renderer.reset()
            self._discover_paths()

            # Warm-up frames
            if self.render_product:
                for _ in range(3):
                    self._renderer.step(
                        render_products={self.render_product},
                        delta_time=1.0 / 60.0,
                    )
                self.has_scene = True
            else:
                self.has_scene = False
                raise RuntimeError("No render product available after scene load")

            # If we injected a camera, frame it on the scene bounds.
            if auto_frame and self.camera_path and self.camera_path.startswith("/Studio/"):
                self._frame_camera_to_scene()

            prims = self._renderer.query_prims(attribute_filter_mode=ovrtx.AttributeFilterMode.NONE)
            return {
                "scene": str(self.scene_path),
                "camera": self.camera_path,
                "render_product": self.render_product,
                "prim_count": len(prims),
                "prims": list(prims.keys())[:250],
            }

    def render_frame(self) -> np.ndarray:
        """Render one frame and return HxWxRGBA uint8 CPU numpy array."""
        with self._lock:
            products = self._renderer.step(
                render_products={self.render_product},
                delta_time=1.0 / 60.0,
            )
            frame = products[self.render_product].frames[0]
            mapping = frame.render_vars["LdrColor"].map(device=ovrtx.Device.CPU)
            return np.from_dlpack(mapping)

    def render_frame_cuda(self):
        """Render one frame and return the mapped CUDA tensor (context manager)."""
        with self._lock:
            products = self._renderer.step(
                render_products={self.render_product},
                delta_time=1.0 / 60.0,
            )
            frame = products[self.render_product].frames[0]
            return frame.render_vars["LdrColor"].map(device=ovrtx.Device.CUDA)

    def save_still(self, output_path: Path, quality: int = 95) -> Path:
        """Render and save a still image."""
        pixels = self.render_frame()
        img = Image.fromarray(pixels).convert("RGB")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, quality=quality)
        logger.info("Saved still: %s", output_path)
        return output_path

    def set_camera_transform(self, matrix: np.ndarray) -> None:
        """Set the camera transform from a 4x4 row-major matrix."""
        with self._lock:
            self._renderer.write_attribute(
                prim_paths=[self.camera_path],
                attribute_name="omni:xform",
                tensor=matrix.reshape(1, 4, 4),
            )

    def get_camera_transform(self) -> np.ndarray:
        """Read the camera transform as a 4x4 row-major matrix."""
        with self._lock:
            tensor = self._renderer.read_attribute("omni:xform", [self.camera_path])
            return np.from_dlpack(tensor).reshape(4, 4).copy()

    def orbit_camera(self, center: np.ndarray, radius: float, yaw: float, pitch: float) -> None:
        """Position the camera orbiting a center point."""
        pitch = max(-math.radians(89), min(math.radians(89), pitch))
        eye = center + np.array([
            radius * math.cos(pitch) * math.cos(yaw),
            radius * math.cos(pitch) * math.sin(yaw),
            radius * math.sin(pitch),
        ], dtype=np.float64)
        forward = center - eye
        forward /= np.linalg.norm(forward)
        world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        right = np.cross(forward, world_up)
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)

        matrix = np.eye(4, dtype=np.float64)
        matrix[0, :3] = right
        matrix[1, :3] = up
        matrix[2, :3] = -forward
        matrix[:3, 3] = eye
        self.set_camera_transform(matrix)

    def list_cameras(self) -> list[str]:
        with self._lock:
            cameras = self._renderer.query_prims(
                require_all=[(ovrtx.FilterKind.PRIM_TYPE, "Camera")],
                attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
            )
            return list(cameras.keys())

    def list_render_products(self) -> list[str]:
        with self._lock:
            products = self._renderer.query_prims(
                require_all=[(ovrtx.FilterKind.PRIM_TYPE, "RenderProduct")],
                attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
            )
            return list(products.keys())

    def close(self) -> None:
        with self._lock:
            del self._renderer
        logger.info("Renderer closed")
