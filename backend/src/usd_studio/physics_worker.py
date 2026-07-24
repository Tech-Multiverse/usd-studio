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
