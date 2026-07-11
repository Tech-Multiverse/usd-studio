"""OVSTREAM WebRTC wrapper that feeds ovrtx frames to browser clients."""

import logging
import threading
import time
from pathlib import Path

import numpy as np
import ovrtx
import ovstream
import warp as wp

logger = logging.getLogger(__name__)


wp.init()


@wp.kernel
def _swap_rb(buf: wp.array3d(dtype=wp.uint8)):
    x, y = wp.tid()
    r = buf[y, x, 0]
    b = buf[y, x, 2]
    buf[y, x, 0] = b
    buf[y, x, 2] = r


class WebRTCStreamer:
    """Streams an ovrtx render to a WebRTC client using ovstream."""

    def __init__(self, renderer, signal_port: int = 49100, width: int = 1280, height: int = 720):
        self.renderer = renderer
        self.signal_port = signal_port
        self.width = width
        self.height = height
        self._server: ovstream.Server | None = None
        self._stream_buf: wp.array | None = None
        self._event: wp.Event | None = None
        self._stream: wp.Stream | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> dict:
        """Initialize ovstream and start the WebRTC server."""
        ovstream.initialize()

        # Discover actual resolution from a warm-up frame.
        with self.renderer.render_frame_cuda() as mapping:
            tensor = wp.from_dlpack(mapping.tensor)
            if tensor.ndim != 3 or tensor.shape[2] != 4 or tensor.dtype != wp.uint8:
                raise RuntimeError(f"Unexpected ovrtx output {tensor.shape} {tensor.dtype}")
            self.height, self.width = int(tensor.shape[0]), int(tensor.shape[1])

        self._stream_buf = wp.zeros((self.height, self.width, 4), dtype=wp.uint8, device="cuda:0")
        self._stream = wp.get_stream("cuda:0")
        self._event = wp.Event(device="cuda:0")
        cuda_context = int(wp.get_device("cuda:0").context)

        self._server = ovstream.Server(ovstream.ServerType.WEBRTC)
        self._server.on_connection = self._on_connection
        self._server.on_input = self._on_input

        cfg = ovstream.ServerConfig(
            width=self.width,
            height=self.height,
            cuda_device=0,
            cuda_context=cuda_context,
            webrtc_signal_port=self.signal_port,
        )
        self._server.start(cfg)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

        logger.info("WebRTC server started on signal port %d", self.signal_port)
        return {
            "signal_port": self.signal_port,
            "width": self.width,
            "height": self.height,
        }

    def _on_connection(self, connected: bool) -> None:
        logger.info("WebRTC client %s", "connected" if connected else "disconnected")

    def _on_input(self, event) -> None:
        # Placeholder: forward mouse/keyboard events to renderer/frontend later.
        logger.debug("Input event: %s", event)

    def _loop(self) -> None:
        target_dt = 1.0 / 60.0
        while self._running:
            try:
                with self.renderer.render_frame_cuda() as mapping:
                    source = wp.from_dlpack(mapping.tensor)
                    wp.copy(self._stream_buf, source)

                wp.launch(_swap_rb, dim=(self.width, self.height), inputs=[self._stream_buf], device="cuda:0")
                self._stream.record_event(self._event)

                frame = ovstream.VideoFrame.from_cuda_array(
                    self._stream_buf,
                    sync=ovstream.CudaSync(
                        stream=self._stream.cuda_stream,
                        wait_event=self._event.cuda_event,
                    ),
                )
                try:
                    self._server.stream_video(frame)
                except ovstream.OvstreamError:
                    pass  # no client connected
            except Exception as exc:
                logger.exception("Stream loop error: %s", exc)
            time.sleep(max(0.0, target_dt - (1.0 / 60.0)))

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._server:
            try:
                self._server.stop()
            except ovstream.OvstreamError:
                pass
            self._server.close()
        ovstream.shutdown()
        logger.info("WebRTC server stopped")
