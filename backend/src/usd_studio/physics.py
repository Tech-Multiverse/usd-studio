from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class PhysicsController:
    def __init__(self, pose_callback: Callable[[list[dict]], None], dt: float = 1.0 / 60.0):
        self._pose_callback = pose_callback
        self._dt = dt
        self._process: Optional[subprocess.Popen[str]] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._scene: Optional[Path] = None
        self._bodies: list[str] = []
        self._ready = False
        self._playing = False
        self._sim_time = 0.0
        self._error: Optional[str] = None

    def start(self, scene_path: Path, body_paths: list[str]) -> dict:
        self.stop()

        command = [
            sys.executable,
            "-m",
            "usd_studio.physics_worker",
            "--usd",
            str(Path(scene_path).resolve()),
            "--dt",
            str(self._dt),
        ]
        for path in body_paths:
            command.extend(["--body", path])

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=creationflags,
        )
        with self._lock:
            self._process = process
            self._scene = Path(scene_path).resolve()
            self._bodies = list(body_paths)
            self._ready = False
            self._playing = False
            self._sim_time = 0.0
            self._error = None

        self._stdout_thread = threading.Thread(target=self._read_stdout, args=(process,), daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, args=(process,), daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        logger.info("Started physics worker for %s with %d rigid bodies", scene_path, len(body_paths))
        return self.status()

    def _read_stdout(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("ovphysx: %s", line.rstrip())
                continue
            message_type = message.get("type")
            with self._lock:
                if message_type == "ready":
                    self._ready = True
                    self._bodies = list(message.get("bodies", self._bodies))
                elif message_type == "state":
                    self._playing = bool(message.get("playing"))
                    self._sim_time = float(message.get("time", self._sim_time))
                elif message_type == "poses":
                    self._sim_time = float(message.get("time", self._sim_time))
                elif message_type == "error":
                    self._error = str(message.get("message", "Physics worker failed"))
                    self._playing = False
            if message_type == "poses":
                try:
                    self._pose_callback(message.get("prims", []))
                except Exception:
                    logger.exception("Failed to apply physics poses")
            elif message_type == "error":
                logger.error("Physics worker: %s", message.get("message"))

        with self._lock:
            if self._process is process:
                self._ready = False
                self._playing = False
                if process.poll() not in (None, 0) and not self._error:
                    self._error = f"Physics worker exited with code {process.returncode}"

    @staticmethod
    def _read_stderr(process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            logger.info("ovphysx: %s", line.rstrip())

    def _send(self, action: str) -> dict:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                raise RuntimeError(self._error or "Physics worker is not running")
            process.stdin.write(json.dumps({"action": action}) + "\n")
            process.stdin.flush()
        return self.status()

    def play(self) -> dict:
        return self._send("play")

    def pause(self) -> dict:
        return self._send("pause")

    def step(self) -> dict:
        return self._send("step")

    def reset(self) -> dict:
        with self._lock:
            scene = self._scene
            bodies = list(self._bodies)
        if scene is None:
            raise RuntimeError("Physics has not been initialized")
        return self.start(scene, bodies)

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._ready = False
            self._playing = False
        if process is None:
            return
        if process.poll() is None:
            try:
                if process.stdin:
                    process.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
                    process.stdin.flush()
                process.wait(timeout=3.0)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                stream.close()

    def status(self) -> dict:
        with self._lock:
            process = self._process
            running = process is not None and process.poll() is None
            return {
                "running": running,
                "ready": self._ready,
                "playing": self._playing,
                "time": self._sim_time,
                "scene": str(self._scene) if self._scene else None,
                "bodies": list(self._bodies),
                "error": self._error,
            }
