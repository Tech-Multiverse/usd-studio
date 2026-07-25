from __future__ import annotations

import argparse
import json
import math
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
from ovphysx import PhysX
from ovphysx.types import TensorType


def pose_matrix(pose: np.ndarray) -> list[list[float]]:
    px, py, pz, x, y, z, w = (float(value) for value in pose)
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm > 1e-8:
        w, x, y, z = w / norm, x / norm, y / norm, z / norm
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy), 0.0],
        [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx), 0.0],
        [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy), 0.0],
        [px, py, pz, 1.0],
    ]


def matrix_pose(matrix4d: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(matrix4d, dtype=np.float32)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("Pose matrix must be a finite 4x4 matrix")
    rotation_rows = matrix[:3, :3]
    scale = np.linalg.norm(rotation_rows, axis=1)
    if np.any(scale < 1e-8):
        raise ValueError("Pose matrix has an invalid scale")
    rotation = (rotation_rows / scale[:, None]).T
    trace = float(np.trace(rotation))
    if trace > 0.0:
        root = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * root
        x = (rotation[2, 1] - rotation[1, 2]) / root
        y = (rotation[0, 2] - rotation[2, 0]) / root
        z = (rotation[1, 0] - rotation[0, 1]) / root
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        root = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
        w = (rotation[2, 1] - rotation[1, 2]) / root
        x = 0.25 * root
        y = (rotation[0, 1] + rotation[1, 0]) / root
        z = (rotation[0, 2] + rotation[2, 0]) / root
    elif rotation[1, 1] > rotation[2, 2]:
        root = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
        w = (rotation[0, 2] - rotation[2, 0]) / root
        x = (rotation[0, 1] + rotation[1, 0]) / root
        y = 0.25 * root
        z = (rotation[1, 2] + rotation[2, 1]) / root
    else:
        root = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
        w = (rotation[1, 0] - rotation[0, 1]) / root
        x = (rotation[0, 2] + rotation[2, 0]) / root
        y = (rotation[1, 2] + rotation[2, 1]) / root
        z = 0.25 * root
    return np.array([matrix[3, 0], matrix[3, 1], matrix[3, 2], x, y, z, w], dtype=np.float32)


def read_commands(commands: queue.Queue[str]) -> None:
    for line in sys.stdin:
        commands.put(line.strip())


def emit(payload: dict) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--usd", required=True)
    parser.add_argument("--body", action="append", default=[])
    parser.add_argument("--dt", type=float, default=1.0 / 60.0)
    args = parser.parse_args()

    usd_path = Path(args.usd).resolve()
    if not usd_path.is_file():
        emit({"type": "error", "message": f"Scene not found: {usd_path}"})
        return 2

    commands: queue.Queue[str] = queue.Queue()
    threading.Thread(target=read_commands, args=(commands,), daemon=True).start()
    physx = PhysX(device="cpu")
    binding = None
    try:
        physx.add_usd(str(usd_path))
        physx.step(args.dt, 0.0)
        binding = physx.create_tensor_binding(
            prim_paths=args.body or None,
            pattern=None if args.body else "/**",
            tensor_type=TensorType.RIGID_BODY_POSE,
            raise_if_empty=True,
        )
        body_paths = list(binding.prim_paths) if hasattr(binding, "prim_paths") else list(args.body)
        if not body_paths:
            raise RuntimeError("No rigid bodies were found in the scene")
        poses = np.zeros(binding.shape, dtype=np.float32)
        sim_time = args.dt
        playing = False
        running = True
        emit({"type": "ready", "bodies": body_paths, "dt": args.dt})
        binding.read(poses)
        emit({
            "type": "poses",
            "time": sim_time,
            "prims": [
                {"path": path, "matrix4d": pose_matrix(poses[index])}
                for index, path in enumerate(body_paths)
            ],
        })

        while running:
            command = None
            try:
                command = commands.get(timeout=args.dt if playing else 0.1)
            except queue.Empty:
                pass

            if command:
                request = json.loads(command)
                action = request.get("action")
                if action == "play":
                    playing = True
                    emit({"type": "state", "playing": True, "time": sim_time})
                elif action == "pause":
                    playing = False
                    emit({"type": "state", "playing": False, "time": sim_time})
                elif action == "step":
                    playing = False
                    physx.step(args.dt, sim_time)
                    sim_time += args.dt
                    binding.read(poses)
                    emit({
                        "type": "poses",
                        "time": sim_time,
                        "prims": [
                            {"path": path, "matrix4d": pose_matrix(poses[index])}
                            for index, path in enumerate(body_paths)
                        ],
                    })
                    emit({"type": "state", "playing": False, "time": sim_time})
                elif action == "set_pose":
                    if playing:
                        raise RuntimeError("Pause physics before setting a rigid-body pose")
                    path = str(request.get("path", ""))
                    if path not in body_paths:
                        raise ValueError(f"Unknown rigid body: {path}")
                    poses[body_paths.index(path)] = matrix_pose(request.get("matrix4d", []))
                    binding.write(poses)
                    binding.read(poses)
                    emit({
                        "type": "poses",
                        "time": sim_time,
                        "prims": [
                            {"path": body_path, "matrix4d": pose_matrix(poses[index])}
                            for index, body_path in enumerate(body_paths)
                        ],
                    })
                elif action == "shutdown":
                    running = False

            if playing and running:
                started = time.perf_counter()
                physx.step(args.dt, sim_time)
                sim_time += args.dt
                binding.read(poses)
                emit({
                    "type": "poses",
                    "time": sim_time,
                    "prims": [
                        {"path": path, "matrix4d": pose_matrix(poses[index])}
                        for index, path in enumerate(body_paths)
                    ],
                })
                remaining = args.dt - (time.perf_counter() - started)
                if remaining > 0:
                    time.sleep(remaining)
    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
        return 1
    finally:
        if binding is not None:
            binding.destroy()
        physx.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
