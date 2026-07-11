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
                self.render_product = next(iter(products))
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

    def load_scene(
        self,
        usd_path: str | Path,
        camera_path: Optional[str] = None,
        render_product: Optional[str] = None,
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

            # If no render product or camera, compose an injection layer.
            if not self.render_product or not self.camera_path:
                logger.info("Scene lacks camera/render product; injecting defaults")
                layer_usda, self.camera_path, self.render_product = build_scene_layer(
                    self.scene_path,
                    camera_path=self.camera_path,
                    render_product_path=self.render_product,
                    width=self.width,
                    height=self.height,
                )
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
