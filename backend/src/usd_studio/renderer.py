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
        self._lock = threading.RLock()

        # Camera orbit state; updated by mouse interactions.
        self._camera_center = np.array([0.0, 0.0, 0.0], dtype=np.float64)
        self._camera_radius = 1.5
        self._camera_yaw = math.radians(45.0)
        self._camera_pitch = math.radians(30.0)
        self._selected_path: Optional[str] = None
        self._physics_scales: dict[str, np.ndarray] = {}

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

    def _scene_bounds(self) -> tuple[Optional[np.ndarray], Optional[float]]:
        """Compute the world-space bounding box of renderable scene prims.

        Filters out lights, cameras, render settings, and prims with non-finite
        or grossly large authored extents (e.g. ground planes).
        Returns (center, radius) or (None, None) on failure.
        """
        try:
            prims = self._renderer.query_prims(
                require_all=[(ovrtx.FilterKind.HAS_ATTRIBUTE, "extent")],
                attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
            )
            if not prims:
                return None, None

            skip_tokens = {
                "light", "camera", "render", "studio", "looks", "material",
                "ground", "plane", "collision", "physics",
            }
            candidates = []
            for path in prims:
                lower = path.lower()
                if any(tok in lower for tok in skip_tokens):
                    continue
                if not lower.startswith("/world"):
                    continue
                # Skip root scene xforms that aggregate child extents (e.g. /World).
                if path == "/World":
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
                return None, None

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
                world_corners = corners @ xform
                world_min = np.minimum(world_min, world_corners[:, :3].min(axis=0))
                world_max = np.maximum(world_max, world_corners[:, :3].max(axis=0))
                included += 1

            if not np.isfinite(world_min).all() or not np.isfinite(world_max).all():
                return None, None

            center = (world_min + world_max) * 0.5
            size = world_max - world_min
            radius = float(np.linalg.norm(size) * 0.5)
            if radius <= 0 or not np.isfinite(radius):
                radius = 1.0
            return center, radius

        except Exception as exc:
            logger.warning("Scene bounds computation failed: %s", exc)
            return None, None

    def _init_camera_state_from_scene(self, auto_frame: bool) -> None:
        """Compute scene bounds and initialize orbit state; optionally frame a Studio camera."""
        try:
            center, radius = self._scene_bounds()
            if center is None or radius is None:
                logger.warning("Could not compute scene bounds; using defaults")
                return

            distance = max(radius * 2.5, 0.001)
            self._camera_center = center
            self._camera_radius = distance
            self._camera_yaw = math.radians(45)
            self._camera_pitch = math.radians(30)

            if auto_frame and self.camera_path and self.camera_path.startswith("/Studio/"):
                self.orbit_camera(center, distance, self._camera_yaw, self._camera_pitch)
                logger.info("Camera framed to scene: center=%s radius=%.4f", center, radius)
            else:
                logger.info("Camera orbit state initialized from scene bounds: radius=%.4f", distance)
        except Exception as exc:
            logger.warning("Camera state init failed: %s", exc)

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
            self._physics_scales.clear()
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

            # Always compute scene bounds; they initialize the camera orbit state
            # used by mouse interactions even when the scene camera is kept as-is.
            self._init_camera_state_from_scene(auto_frame=auto_frame)

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
        """Position the camera orbiting a center point and store the orbit state."""
        self._camera_center = np.asarray(center, dtype=np.float64).copy()
        self._camera_radius = max(radius, 0.001)
        self._camera_yaw = yaw
        self._camera_pitch = max(-math.radians(89), min(math.radians(89), pitch))
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
        matrix[3, :3] = eye
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

    def list_rigid_bodies(self) -> list[str]:
        with self._lock:
            prims = self._renderer.query_prims(
                attribute_filter_mode=ovrtx.AttributeFilterMode.ALL,
            )
            paths = []
            for path, attributes in prims.items():
                if "physics:rigidBodyEnabled" not in attributes:
                    continue
                try:
                    enabled = np.from_dlpack(
                        self._renderer.read_attribute("physics:rigidBodyEnabled", [path])
                    ).reshape(-1)
                    if enabled.size and not bool(enabled[0]):
                        continue
                except Exception:
                    pass
                paths.append(path)
            return paths

    def apply_world_poses(self, prims: list[dict]) -> None:
        if not prims:
            return
        with self._lock:
            world_matrices = {
                item["path"]: np.asarray(item["matrix4d"], dtype=np.float64)
                for item in prims
                if item.get("path") and item.get("matrix4d")
            }
            for path in world_matrices:
                if path in self._physics_scales:
                    continue
                try:
                    authored = np.from_dlpack(
                        self._renderer.read_attribute("omni:xform", [path])
                    ).reshape(4, 4)
                    scale = np.linalg.norm(authored[:3, :3], axis=1)
                    self._physics_scales[path] = np.diag([*scale, 1.0])
                except Exception:
                    self._physics_scales[path] = np.eye(4, dtype=np.float64)
            paths = sorted(world_matrices, key=lambda path: path.count("/"))
            local_matrices = []
            for path in paths:
                parent_path = path.rsplit("/", 1)[0]
                parent_world = world_matrices.get(parent_path)
                if parent_world is None and parent_path:
                    try:
                        parent_tensor = self._renderer.read_attribute("omni:xform", [parent_path])
                        parent_world = np.from_dlpack(parent_tensor).reshape(4, 4).copy()
                    except Exception:
                        parent_world = np.eye(4, dtype=np.float64)
                if parent_world is None:
                    parent_world = np.eye(4, dtype=np.float64)
                rigid_local = world_matrices[path] @ np.linalg.inv(parent_world)
                local_matrices.append(self._physics_scales[path] @ rigid_local)
            self._renderer.write_attribute(
                prim_paths=paths,
                attribute_name="omni:xform",
                tensor=np.stack(local_matrices),
            )

    def _camera_basis(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return (eye, forward, right, up) from the current camera transform."""
        matrix = self.get_camera_transform()
        eye = matrix[3, :3].copy()
        forward = -matrix[2, :3].copy()
        right = matrix[0, :3].copy()
        up = matrix[1, :3].copy()
        return eye, forward, right, up

    def _look_at(self, eye: np.ndarray, target: np.ndarray, world_up: np.ndarray) -> np.ndarray:
        """Build a 4x4 row-major camera transform looking from eye to target."""
        forward = target - eye
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, world_up)
        norm = np.linalg.norm(right)
        if norm < 1e-6:
            right = np.cross(forward, np.array([0.0, 1.0, 0.0]))
            norm = np.linalg.norm(right)
        right /= norm
        up = np.cross(right, forward)

        matrix = np.eye(4, dtype=np.float64)
        matrix[0, :3] = right
        matrix[1, :3] = up
        matrix[2, :3] = -forward
        matrix[3, :3] = eye
        return matrix

    def get_camera_state(self) -> dict:
        return {
            "center": self._camera_center.tolist(),
            "radius": self._camera_radius,
            "yaw": self._camera_yaw,
            "pitch": self._camera_pitch,
        }

    def orbit_delta(self, delta_yaw: float, delta_pitch: float) -> None:
        """Orbit the camera around a pivot point in front of it (left-drag)."""
        with self._lock:
            eye, forward, right, _up = self._camera_basis()
            # Use a focus distance tied to the current orbit radius so orbit feels
            # natural regardless of scene scale.
            focus = self._camera_radius
            pivot = eye + forward * focus

            # Pitch rotation around camera right axis.
            cos_p = math.cos(delta_pitch)
            sin_p = math.sin(delta_pitch)
            offset = eye - pivot
            pitch_axis = right
            offset = (
                offset * cos_p
                + np.cross(pitch_axis, offset) * sin_p
                + pitch_axis * np.dot(pitch_axis, offset) * (1 - cos_p)
            )
            # Yaw rotation around world up.
            cos_y = math.cos(delta_yaw)
            sin_y = math.sin(delta_yaw)
            world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
            offset = (
                offset * cos_y
                + np.cross(world_up, offset) * sin_y
                + world_up * np.dot(world_up, offset) * (1 - cos_y)
            )
            new_eye = pivot + offset
            matrix = self._look_at(new_eye, pivot, world_up)
            self.set_camera_transform(matrix)

    def pan_delta(self, dx: float, dy: float) -> None:
        """Pan the camera in its view plane (right-drag).

        dx/dy are normalized viewport coordinates (-1..1) in screen space.
        """
        with self._lock:
            eye, _forward, right, up = self._camera_basis()
            scale = self._camera_radius * 0.75
            delta = (right * dx + up * dy) * scale
            self._camera_center += delta
            # Pan both eye and pivot so orbit continues from the same relative point.
            eye += delta
            matrix = self.get_camera_transform()
            matrix[3, :3] = eye
            self.set_camera_transform(matrix)

    def zoom_delta(self, delta: float) -> None:
        """Dolly the camera forward/backward (mouse wheel)."""
        with self._lock:
            eye, forward, _right, _up = self._camera_basis()
            # Move eye along forward direction, scaled by radius.
            scale = self._camera_radius * delta
            new_eye = eye + forward * scale
            # Keep looking at the same pivot point so the view doesn't drift.
            pivot = eye + forward * self._camera_radius
            world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
            matrix = self._look_at(new_eye, pivot, world_up)
            self.set_camera_transform(matrix)

    def pick(self, nx: float, ny: float) -> Optional[str]:
        """Pick the prim at normalized viewport coordinates (0..1, 0..1).

        (0,0) is the top-left of the image, matching mouse events and the
        render buffer row order.
        """
        x = int(nx * self.width)
        y = int(ny * self.height)
        with self._lock:
            self._renderer.enqueue_pick_query(
                render_product_path=self.render_product,
                left=x,
                top=y,
                right=x + 1,
                bottom=y + 1,
            )
            products = self._renderer.step(
                render_products={self.render_product},
                delta_time=1.0 / 60.0,
            )
            frame = products[self.render_product].frames[0]
            pick_var = frame.render_vars[ovrtx.OVRTX_RENDER_VAR_PICK_HIT]
            mapping = pick_var.map(device=ovrtx.Device.CPU)
            try:
                hit_count = int(
                    np.from_dlpack(mapping.params["hitCount"]).reshape(-1)[0]
                )
                if hit_count == 0:
                    return None
                prim_paths = np.from_dlpack(mapping["primPath"]).copy().reshape(-1)
                path_id = int(prim_paths[0])
                path = self._renderer.resolve_prim_path_id(path_id)
                return path if path else None
            finally:
                mapping.unmap()

    def select(self, prim_path: Optional[str]) -> Optional[str]:
        """Highlight a prim with the selection outline and return it."""
        with self._lock:
            if self._selected_path:
                self._renderer.write_attribute(
                    prim_paths=[self._selected_path],
                    attribute_name=ovrtx.OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP,
                    tensor=np.array([0], dtype=np.uint8),
                )
            self._selected_path = prim_path
            if prim_path:
                self._renderer.write_attribute(
                    prim_paths=[prim_path],
                    attribute_name=ovrtx.OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP,
                    tensor=np.array([1], dtype=np.uint8),
                )
        logger.info("Selected: %s", prim_path)
        return prim_path

    def get_selected(self) -> Optional[str]:
        return self._selected_path

    def close(self) -> None:
        with self._lock:
            del self._renderer
        logger.info("Renderer closed")
