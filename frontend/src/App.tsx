import { useEffect, useRef, useState } from 'react';
import { connectWebRTC } from './webrtc';

const API_BASE = '/api';

interface SceneInfo {
  loaded: boolean;
  scene?: string;
  camera?: string;
  render_product?: string;
}

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [scenePath, setScenePath] = useState('');
  const [scene, setScene] = useState<SceneInfo | null>(null);
  const [webrtcPort, setWebrtcPort] = useState(49100);
  const [connected, setConnected] = useState(false);
  const [streamSize, setStreamSize] = useState({ width: 1280, height: 720 });
  const [logs, setLogs] = useState<string[]>([]);
  const disconnectRef = useRef<(() => void) | null>(null);

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
              </>
            ) : (
              <span className="error">No scene loaded</span>
            )}
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
        <video id="remote-video" ref={videoRef} width={streamSize.width} height={streamSize.height} autoPlay playsInline tabIndex={-1} />
        {!connected && <div className="status">Stream not connected</div>}
      </main>
    </div>
  );
}
