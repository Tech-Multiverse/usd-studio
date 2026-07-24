import { useEffect, useRef, useState } from 'react';
import { connectWebRTC } from './webrtc';

const API_BASE = '/api';

interface SceneInfo {
  loaded: boolean;
  scene?: string;
  camera?: string;
  render_product?: string;
}

interface PhysicsStatus {
  running: boolean;
  ready: boolean;
  playing: boolean;
  time: number;
  bodies: string[];
  error?: string | null;
}

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [scenePath, setScenePath] = useState('');
  const [scene, setScene] = useState<SceneInfo | null>(null);
  const [webrtcPort, setWebrtcPort] = useState(49100);
  const [connected, setConnected] = useState(false);
  const [streamSize, setStreamSize] = useState({ width: 1280, height: 720 });
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [physics, setPhysics] = useState<PhysicsStatus | null>(null);
  const [physicsBusy, setPhysicsBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const disconnectRef = useRef<(() => void) | null>(null);
  const mouseRef = useRef<{ down: boolean; button: number; x: number; y: number; moved: boolean }>({
    down: false,
    button: 0,
    x: 0,
    y: 0,
    moved: false,
  });

  const log = (msg: string) => {
    console.log(msg);
    setLogs((prev: string[]) => [msg, ...prev].slice(0, 50));
  };

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((data) => {
        log(`Backend healthy: scene_loaded=${data.scene_loaded}`);
        return fetch(`${API_BASE}/scene`);
      })
      .then((r) => r.json())
      .then((data: SceneInfo) => {
        setScene(data);
      })
      .catch((err) => log(`Health check failed: ${String(err)}`));
  }, []);

  useEffect(() => {
    const updatePhysics = () => {
      fetch(`${API_BASE}/physics/status`)
        .then((response) => response.json())
        .then((data: PhysicsStatus) => setPhysics(data))
        .catch(() => undefined);
    };
    updatePhysics();
    const timer = window.setInterval(updatePhysics, 500);
    return () => window.clearInterval(timer);
  }, []);

  const loadScene = async () => {
    if (!scenePath) return;
    try {
      const res = await fetch(`${API_BASE}/scene/load`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: scenePath }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Load failed');
      setScene({ loaded: true, scene: data.scene, camera: data.camera, render_product: data.render_product });
      setPhysics(null);
      log(`Loaded ${data.scene} with ${data.prim_count} prims`);
    } catch (err) {
      log(`Load error: ${String(err)}`);
    }
  };

  const startStream = async () => {
    if (!videoRef.current) return;
    try {
      const res = await fetch(`${API_BASE}/webrtc/start`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Stream start failed');
      setWebrtcPort(data.signal_port);
      setStreamSize({ width: data.width, height: data.height });
      log(`WebRTC signal port: ${data.signal_port}`);

      disconnectRef.current = await connectWebRTC(
        data.signal_port,
        'remote-video',
        (msg: string) => log(`WebRTC: ${msg}`),
        () => {
          const video = document.getElementById('remote-video') as HTMLVideoElement | null;
          if (video) {
            video.muted = false;
            if (video.srcObject) {
              video.play().catch((e) => console.warn('video.play() rejected:', e));
            }
            video.focus();
          }
        },
      );
      setConnected(true);
    } catch (err) {
      log(`Stream error: ${String(err)}`);
    }
  };

  const stopStream = () => {
    disconnectRef.current?.();
    disconnectRef.current = null;
    setConnected(false);
    log('WebRTC disconnected');
  };

  const renderStill = async () => {
    try {
      const res = await fetch(`${API_BASE}/render/still`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: 'still.png' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Render failed');
      log(`Saved still: ${data.path}`);
    } catch (err) {
      log(`Render error: ${String(err)}`);
    }
  };

  const runPhysics = async (action: 'initialize' | 'play' | 'pause' | 'step' | 'reset') => {
    setPhysicsBusy(true);
    try {
      const response = await fetch(`${API_BASE}/physics/${action}`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Physics ${action} failed`);
      setPhysics(data);
      log(`Physics: ${action}`);
    } catch (err) {
      log(`Physics error: ${String(err)}`);
    } finally {
      setPhysicsBusy(false);
    }
  };

  const postCamera = async (endpoint: string, body: unknown) => {
    try {
      const res = await fetch(`${API_BASE}/camera/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Camera command failed');
    } catch (err) {
      console.warn(`Camera ${endpoint} failed:`, err);
    }
  };

  const postPick = async (x: number, y: number) => {
    try {
      const res = await fetch(`${API_BASE}/pick`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ x, y }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Pick failed');
      const path = data.path || null;
      setSelectedPath(path);
      log(path ? `Picked: ${path}` : 'Picked: nothing');
      // Highlight on backend.
      await fetch(`${API_BASE}/select`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
    } catch (err) {
      console.warn('Pick failed:', err);
    }
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLVideoElement>) => {
    if (!connected) return;
    mouseRef.current = {
      down: true,
      button: e.button,
      x: e.clientX,
      y: e.clientY,
      moved: false,
    };
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLVideoElement>) => {
    if (!connected || !mouseRef.current.down) return;
    const dx = e.clientX - mouseRef.current.x;
    const dy = e.clientY - mouseRef.current.y;
    if (Math.abs(dx) < 2 && Math.abs(dy) < 2) return;
    mouseRef.current.x = e.clientX;
    mouseRef.current.y = e.clientY;
    mouseRef.current.moved = true;

    const video = videoRef.current;
    if (!video) return;
    const rect = video.getBoundingClientRect();
    const ndx = dx / rect.width;
    const ndy = dy / rect.height;

    if (mouseRef.current.button === 0) {
      // Left drag: orbit.
      void postCamera('orbit/delta', {
        delta_yaw: -ndx * 3.0,
        delta_pitch: -ndy * 3.0,
      });
    } else if (mouseRef.current.button === 2) {
      // Right drag: pan.
      void postCamera('pan', { dx: ndx, dy: -ndy });
    }
  };

  const handleMouseUp = (e: React.MouseEvent<HTMLVideoElement>) => {
    if (!connected || !mouseRef.current.down) return;
    const wasMoved = mouseRef.current.moved;
    mouseRef.current.down = false;
    if (wasMoved) return;

    // Click without drag: pick/select.
    const video = videoRef.current;
    if (!video) return;
    const rect = video.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    void postPick(x, y);
  };

  const handleWheelNative = (e: WheelEvent) => {
    if (!connected) return;
    e.preventDefault();
    void postCamera('zoom', { delta: e.deltaY * 0.002 });
  };

  const handleContextMenu = (e: React.MouseEvent<HTMLVideoElement>) => {
    e.preventDefault();
  };

  // Attach native wheel listener so we can call preventDefault (passive: false).
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.addEventListener('wheel', handleWheelNative, { passive: false });
    return () => {
      video.removeEventListener('wheel', handleWheelNative);
    };
  }, [connected]);

  return (
    <div className="app">
      <aside className="sidebar">
        <h1>USD Studio</h1>

        <div className="group">
          <label>Scene path</label>
          <input
            type="text"
            value={scenePath}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setScenePath(e.target.value)}
            placeholder="C:/path/to/scene.usda"
          />
          <button onClick={loadScene} disabled={!scenePath}>
            Load Scene
          </button>
        </div>

        <div className="group">
          <label>Status</label>
          <div className="status">
            {scene?.loaded ? (
              <>
                <span className="success">Scene loaded</span>
                <br />
                Camera: {scene.camera}
                <br />
                Product: {scene.render_product}
                <br />
                Selected: {selectedPath || 'none'}
              </>
            ) : (
              <span className="error">No scene loaded</span>
            )}
          </div>
        </div>

        <div className="group">
          <label>Physics simulation</label>
          <div className="status physics-status">
            {physics?.error ? (
              <span className="error">{physics.error}</span>
            ) : physics?.ready ? (
              <>
                <span className={physics.playing ? 'success' : ''}>
                  {physics.playing ? 'Playing' : 'Paused'}
                </span>
                <br />
                Time: {physics.time.toFixed(2)}s
                <br />
                Rigid bodies: {physics.bodies.length}
              </>
            ) : (
              'Not initialized'
            )}
          </div>
          <button
            onClick={() => void runPhysics('initialize')}
            disabled={!scene?.loaded || physicsBusy || Boolean(physics?.running)}
          >
            Initialize
          </button>
          <button
            onClick={() => void runPhysics(physics?.playing ? 'pause' : 'play')}
            disabled={!physics?.ready || physicsBusy}
          >
            {physics?.playing ? 'Pause' : 'Play'}
          </button>
          <button
            onClick={() => void runPhysics('step')}
            disabled={!physics?.ready || physicsBusy || physics?.playing}
          >
            Step
          </button>
          <button
            onClick={() => void runPhysics('reset')}
            disabled={!physics?.ready || physicsBusy}
          >
            Reset
          </button>
        </div>

        <div className="group">
          <label>Controls (while streaming)</label>
          <div className="status">
            Left drag: orbit
            <br />
            Right drag: pan
            <br />
            Scroll: zoom
            <br />
            Click: select prim
          </div>
        </div>

        <div className="group">
          <button onClick={startStream} disabled={connected || !scene?.loaded}>
            Start Stream
          </button>
          <button onClick={stopStream} disabled={!connected}>
            Stop Stream
          </button>
          <button onClick={renderStill} disabled={!scene?.loaded}>
            Render Still
          </button>
        </div>

        <div className="group">
          <label>Signal port</label>
          <input
            type="number"
            value={webrtcPort}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setWebrtcPort(Number(e.target.value))}
          />
        </div>

        <div className="group">
          <label>Log</label>
          <div className="status">
            {logs.map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        </div>
      </aside>

      <main className="viewport">
        <video
          id="remote-video"
          ref={videoRef}
          width={streamSize.width}
          height={streamSize.height}
          autoPlay
          playsInline
          tabIndex={-1}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => { mouseRef.current.down = false; }}
          onContextMenu={handleContextMenu}
        />
        {!connected && <div className="status">Stream not connected</div>}
      </main>
    </div>
  );
}
