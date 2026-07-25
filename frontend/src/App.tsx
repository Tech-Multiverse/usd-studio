import { useEffect, useRef, useState } from 'react';
import { connectWebRTC } from './webrtc';

const API_BASE = '/api';

interface SceneInfo {
  loaded: boolean;
  scene?: string;
  camera?: string;
  render_product?: string;
  prims?: string[];
}

interface PhysicsStatus {
  running: boolean;
  ready: boolean;
  playing: boolean;
  time: number;
  bodies: string[];
  error?: string | null;
}

interface SelectedTransform {
  path: string;
  translation: number[];
  rotation: number[];
  scale: number[];
  rigid_body: boolean;
}

type TransformTool = 'translate-x' | 'translate-y' | 'translate-z' | 'rotate-x' | 'rotate-y' | 'rotate-z';

interface PackageUpload {
  path: string;
  scenes?: string[];
  package?: string;
  detail?: string;
}

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const archiveInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const streamStartingRef = useRef(false);
  const [scenePath, setScenePath] = useState('');
  const [scene, setScene] = useState<SceneInfo | null>(null);
  const [webrtcPort, setWebrtcPort] = useState(49100);
  const [connected, setConnected] = useState(false);
  const [streamSize, setStreamSize] = useState({ width: 1280, height: 720 });
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedTransform, setSelectedTransform] = useState<SelectedTransform | null>(null);
  const [translation, setTranslation] = useState<string[]>(['0', '0', '0']);
  const [rotation, setRotation] = useState<string[]>(['0', '0', '0']);
  const [transformBusy, setTransformBusy] = useState(false);
  const [activeTransformTool, setActiveTransformTool] = useState<TransformTool | null>(null);
  const [translationDragSpeed, setTranslationDragSpeed] = useState(0.1);
  const [rotationDragSpeed, setRotationDragSpeed] = useState(0.05);
  const [physics, setPhysics] = useState<PhysicsStatus | null>(null);
  const [physicsBusy, setPhysicsBusy] = useState(false);
  const [sceneBusy, setSceneBusy] = useState(false);
  const [packageScenes, setPackageScenes] = useState<string[]>([]);
  const [initializePhysicsOnLoad, setInitializePhysicsOnLoad] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const disconnectRef = useRef<(() => Promise<void>) | null>(null);
  const transformTimerRef = useRef<number | null>(null);
  const transformRequestRef = useRef(0);
  const transformRequestInFlightRef = useRef(false);
  const transformPendingRef = useRef<{ translation: string[]; rotation: string[] } | null>(null);
  const translationRef = useRef(translation);
  const rotationRef = useRef(rotation);
  const transformDragRef = useRef<{
    tool: TransformTool;
    x: number;
    y: number;
    translation: string[];
    rotation: string[];
  } | null>(null);
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
    folderInputRef.current?.setAttribute('webkitdirectory', '');
  }, []);

  useEffect(() => () => {
    if (transformTimerRef.current !== null) window.clearTimeout(transformTimerRef.current);
  }, []);

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

  const loadScene = async (path = scenePath) => {
    const requestedPath = path.trim();
    if (!requestedPath) return;
    setSceneBusy(true);
    try {
      const res = await fetch(`${API_BASE}/scene/load`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: requestedPath }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Load failed');
      setScenePath(data.scene);
      setScene({
        loaded: true,
        scene: data.scene,
        camera: data.camera,
        render_product: data.render_product,
        prims: data.prims,
      });
      setSelectedPath(null);
      setSelectedTransform(null);
      setActiveTransformTool(null);
      setPhysics(null);
      log(`Loaded ${data.scene} with ${data.prim_count} prims`);
      await restartStream();
      if (initializePhysicsOnLoad) {
        await runPhysics('initialize');
      }
    } catch (err) {
      log(`Load error: ${String(err)}`);
    } finally {
      setSceneBusy(false);
    }
  };

  const finishPackageUpload = async (data: PackageUpload, label: string) => {
    if (!data.path) throw new Error(data.detail || 'Upload failed');
    const scenes = data.scenes ?? [data.path];
    setPackageScenes(scenes);
    setScenePath(data.path);
    log(`Uploaded ${label}; found ${scenes.length} USD scene${scenes.length === 1 ? '' : 's'}`);
    await loadScene(data.path);
  };

  const browseAndLoadLocalScene = async () => {
    setSceneBusy(true);
    try {
      const response = await fetch(`${API_BASE}/scene/browse`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Unable to open the scene picker');
      if (data.cancelled || !data.path) return;
      setPackageScenes([]);
      await loadScene(data.path);
    } catch (err) {
      log(`Browse error: ${String(err)}`);
    } finally {
      setSceneBusy(false);
    }
  };

  const uploadAndLoadScene = async (file: File) => {
    setSceneBusy(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const endpoint = file.name.toLowerCase().endsWith('.zip')
        ? `${API_BASE}/scene/package/archive`
        : `${API_BASE}/scene/upload`;
      const response = await fetch(endpoint, { method: 'POST', body: formData });
      const data: PackageUpload = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Upload failed');
      await finishPackageUpload(data, file.name);
    } catch (err) {
      log(`Upload error: ${String(err)}`);
      setSceneBusy(false);
    } finally {
      if (archiveInputRef.current) archiveInputRef.current.value = '';
    }
  };

  const uploadAndLoadFolder = async (fileList: FileList) => {
    const files = Array.from(fileList);
    if (!files.length) return;
    setSceneBusy(true);
    try {
      const relativePaths = files.map((file) => file.webkitRelativePath || file.name);
      const formData = new FormData();
      files.forEach((file) => formData.append('files', file));
      formData.append('relative_paths_json', JSON.stringify(relativePaths));
      const response = await fetch(`${API_BASE}/scene/package/folder`, { method: 'POST', body: formData });
      const data: PackageUpload = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Folder upload failed');
      await finishPackageUpload(data, relativePaths[0].split('/')[0]);
    } catch (err) {
      log(`Folder upload error: ${String(err)}`);
      setSceneBusy(false);
    } finally {
      if (folderInputRef.current) folderInputRef.current.value = '';
    }
  };

  const startStream = async (force = false) => {
    if (!videoRef.current || (!force && connected) || streamStartingRef.current) return;
    streamStartingRef.current = true;
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
    } finally {
      streamStartingRef.current = false;
    }
  };

  const stopStream = async () => {
    const disconnect = disconnectRef.current;
    disconnectRef.current = null;
    try {
      await disconnect?.();
    } catch (err) {
      log(`WebRTC disconnect error: ${String(err)}`);
    } finally {
      if (videoRef.current) videoRef.current.srcObject = null;
      setConnected(false);
      log('WebRTC disconnected');
    }
  };

  const restartStream = async () => {
    if (disconnectRef.current || connected) {
      await stopStream();
      await new Promise((resolve) => window.setTimeout(resolve, 250));
    }
    await startStream(true);
  };

  useEffect(() => {
    if (scene?.loaded && !connected) {
      void startStream();
    }
  }, [scene?.loaded]);

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
      if (action === 'initialize' || action === 'reset') {
        void refreshSelectedTransformAfterPhysicsReady();
      } else if (action === 'pause' || action === 'step') {
        window.setTimeout(() => void loadSelectedTransform().catch((err) => log(`Transform refresh error: ${String(err)}`)), 100);
      }
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

  const loadSelectedTransform = async () => {
    const response = await fetch(`${API_BASE}/selected/transform`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to inspect selected prim');
    const selected = data.selected as SelectedTransform | null;
    setSelectedTransform(selected);
    if (selected) {
      const nextTranslation = selected.translation.map((value) => String(value));
      const nextRotation = selected.rotation.map((value) => String(value));
      translationRef.current = nextTranslation;
      rotationRef.current = nextRotation;
      setTranslation(nextTranslation);
      setRotation(nextRotation);
    }
  };

  const refreshSelectedTransformAfterPhysicsReady = async () => {
    if (!selectedPath) return;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 100));
      const response = await fetch(`${API_BASE}/physics/status`);
      const status = await response.json() as PhysicsStatus;
      setPhysics(status);
      if (status.ready) {
        await new Promise((resolve) => window.setTimeout(resolve, 100));
        await loadSelectedTransform();
        return;
      }
    }
  };

  const canEditTransform = () => !physicsBusy
    && !physics?.playing
    && !(physics?.running && !physics.ready);

  const flushTransformUpdate = async () => {
    if (transformRequestInFlightRef.current) return;
    const pending = transformPendingRef.current;
    if (!pending) return;
    transformPendingRef.current = null;
    if ([...pending.translation, ...pending.rotation].some((value) => value.trim() === '')) return;
    const translationValues = pending.translation.map(Number);
    const rotationValues = pending.rotation.map(Number);
    if ([...translationValues, ...rotationValues].some((value) => !Number.isFinite(value))) return;
    const requestId = transformRequestRef.current;
    transformRequestInFlightRef.current = true;
    setTransformBusy(true);
    try {
      const response = await fetch(`${API_BASE}/selected/transform`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ translation: translationValues, rotation: rotationValues }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Transform update failed');
      if (requestId !== transformRequestRef.current) return;
      setSelectedTransform(data.selected as SelectedTransform);
      if (data.physics) setPhysics(data.physics as PhysicsStatus);
    } catch (err) {
      if (requestId === transformRequestRef.current) log(`Transform error: ${String(err)}`);
    } finally {
      transformRequestInFlightRef.current = false;
      setTransformBusy(false);
      if (transformPendingRef.current) void flushTransformUpdate();
    }
  };

  const scheduleTransformUpdate = (nextTranslation: string[], nextRotation: string[]) => {
    transformPendingRef.current = { translation: nextTranslation, rotation: nextRotation };
    if (transformTimerRef.current !== null || transformRequestInFlightRef.current) return;
    transformTimerRef.current = window.setTimeout(() => {
      transformTimerRef.current = null;
      void flushTransformUpdate();
    }, 33);
  };

  const updateTransformComponent = (kind: 'translation' | 'rotation', index: number, value: string) => {
    const nextTranslation = [...translationRef.current];
    const nextRotation = [...rotationRef.current];
    if (kind === 'translation') nextTranslation[index] = value;
    else nextRotation[index] = value;
    translationRef.current = nextTranslation;
    rotationRef.current = nextRotation;
    setTranslation(nextTranslation);
    setRotation(nextRotation);
    scheduleTransformUpdate(nextTranslation, nextRotation);
  };

  const selectPrim = async (path: string | null) => {
    if (transformTimerRef.current !== null) window.clearTimeout(transformTimerRef.current);
    transformRequestRef.current += 1;
    transformPendingRef.current = null;
    setTransformBusy(false);
    setSelectedPath(path);
    try {
      const response = await fetch(`${API_BASE}/select`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Selection failed');
      if (path) {
        await loadSelectedTransform();
      } else {
        setSelectedTransform(null);
        setActiveTransformTool(null);
      }
    } catch (err) {
      log(`Selection error: ${String(err)}`);
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
      log(path ? `Picked: ${path}` : 'Picked: nothing');
      await selectPrim(path);
    } catch (err) {
      console.warn('Pick failed:', err);
    }
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLVideoElement>) => {
    if (!connected) return;
    if (e.button === 0 && activeTransformTool && selectedTransform && canEditTransform()) {
      transformDragRef.current = {
        tool: activeTransformTool,
        x: e.clientX,
        y: e.clientY,
        translation: [...translationRef.current],
        rotation: [...rotationRef.current],
      };
      return;
    }
    mouseRef.current = {
      down: true,
      button: e.button,
      x: e.clientX,
      y: e.clientY,
      moved: false,
    };
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLVideoElement>) => {
    if (!connected) return;
    const transformDrag = transformDragRef.current;
    if (transformDrag) {
      const dx = e.clientX - transformDrag.x;
      const dy = e.clientY - transformDrag.y;
      const amount = transformDrag.tool.endsWith('-x') ? dx : -dy;
      const component = transformDrag.tool.endsWith('-x') ? 0 : transformDrag.tool.endsWith('-y') ? 1 : 2;
      const nextTranslation = [...transformDrag.translation];
      const nextRotation = [...transformDrag.rotation];
      if (transformDrag.tool.startsWith('translate')) {
        nextTranslation[component] = (Number(transformDrag.translation[component]) + amount * translationDragSpeed).toFixed(4);
      } else {
        nextRotation[component] = (Number(transformDrag.rotation[component]) + amount * rotationDragSpeed).toFixed(2);
      }
      translationRef.current = nextTranslation;
      rotationRef.current = nextRotation;
      setTranslation(nextTranslation);
      setRotation(nextRotation);
      scheduleTransformUpdate(nextTranslation, nextRotation);
      return;
    }
    if (!mouseRef.current.down) return;
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
    if (!connected) return;
    if (transformDragRef.current) {
      transformDragRef.current = null;
      void flushTransformUpdate();
      return;
    }
    if (!mouseRef.current.down) return;
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
            onChange={(event: React.ChangeEvent<HTMLInputElement>) => {
              setScenePath(event.target.value);
              setPackageScenes([]);
            }}
            placeholder="C:/path/to/scene.usda"
          />
          <input
            ref={archiveInputRef}
            type="file"
            accept=".zip"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void uploadAndLoadScene(file);
            }}
          />
          <input
            ref={folderInputRef}
            type="file"
            multiple
            hidden
            onChange={(event) => {
              const files = event.target.files;
              if (files) void uploadAndLoadFolder(files);
            }}
          />
          <button onClick={() => void browseAndLoadLocalScene()} disabled={sceneBusy}>
            Browse USD File
          </button>
          <button onClick={() => archiveInputRef.current?.click()} disabled={sceneBusy}>
            Browse ZIP
          </button>
          <button onClick={() => folderInputRef.current?.click()} disabled={sceneBusy}>
            Browse Folder
          </button>
          {packageScenes.length > 1 && (
            <>
              <label>Package scenes</label>
              <select value={scenePath} onChange={(event) => setScenePath(event.target.value)}>
                {packageScenes.map((path) => (
                  <option key={path} value={path}>{path.split(/[\\/]/).pop()}</option>
                ))}
              </select>
            </>
          )}
          <button onClick={() => void loadScene()} disabled={!scenePath || sceneBusy}>
            {sceneBusy ? 'Loading...' : 'Load Scene Path'}
          </button>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={initializePhysicsOnLoad}
              onChange={(event) => setInitializePhysicsOnLoad(event.target.checked)}
            />
            Initialize physics after load
          </label>
          <div className="hint">Streaming starts automatically. Initialize physics only when you are ready to simulate.</div>
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
          <label>Scene prim</label>
          <select
            value={selectedPath || ''}
            disabled={!scene?.loaded}
            onChange={(event) => void selectPrim(event.target.value || null)}
          >
            <option value="">Select a prim</option>
            {(scene?.prims || []).map((path) => (
              <option key={path} value={path}>{path}</option>
            ))}
          </select>
        </div>

        <div className="group">
          <label>Selected prim transform</label>
          {selectedTransform ? (
            <>
              <div className="status">
                {selectedTransform.path}
                <br />
                {selectedTransform.rigid_body ? 'Rigid body' : 'Static prim'}
                <br />
                Scale: {selectedTransform.scale.map((value) => value.toFixed(3)).join(', ')}
              </div>
              <label>Translate</label>
              <div className="vector-inputs">
                {translation.map((value, index) => (
                  <input
                    key={`translate-${index}`}
                    type="number"
                    step="any"
                    value={value}
                    aria-label={`Translate ${['X', 'Y', 'Z'][index]}`}
                    disabled={!canEditTransform()}
                    onChange={(event) => updateTransformComponent('translation', index, event.target.value)}
                  />
                ))}
              </div>
              <label>Rotate (degrees)</label>
              <div className="vector-inputs">
                {rotation.map((value, index) => (
                  <input
                    key={`rotate-${index}`}
                    type="number"
                    step="any"
                    value={value}
                    aria-label={`Rotate ${['X', 'Y', 'Z'][index]}`}
                    disabled={!canEditTransform()}
                    onChange={(event) => updateTransformComponent('rotation', index, event.target.value)}
                  />
                ))}
              </div>
              {selectedTransform.rigid_body && physics?.playing && (
                <div className="hint">Pause physics before repositioning this rigid body.</div>
              )}
              {selectedTransform.rigid_body && physics?.running && !physics.ready && (
                <div className="hint">Waiting for physics to synchronize the selected body.</div>
              )}
              {selectedTransform.rigid_body && physics?.ready && !physics.playing && (
                <div className="hint">Edits synchronize the paused body. Press Play to release it.</div>
              )}
              {transformBusy && <div className="hint">Updating transform...</div>}
            </>
          ) : (
            <div className="status">Click an object in the viewport to inspect it.</div>
          )}
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
            <br />
            Transform tool + left drag: edit selected axis
          </div>
        </div>

        <div className="group">
          <button onClick={() => void startStream()} disabled={connected || !scene?.loaded}>
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
        <div className="viewport-video-host">
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
            onMouseLeave={() => {
              mouseRef.current.down = false;
              transformDragRef.current = null;
              void flushTransformUpdate();
            }}
            onContextMenu={handleContextMenu}
          />
        </div>
        {selectedTransform && (
          <div className="transform-toolbar" aria-label="Viewport transform tools">
            {(['translate-x', 'translate-y', 'translate-z', 'rotate-x', 'rotate-y', 'rotate-z'] as TransformTool[]).map((tool) => (
              <button
                key={tool}
                className={`transform-tool ${tool.slice(-1)} ${activeTransformTool === tool ? 'active' : ''}`}
                onClick={() => setActiveTransformTool((current) => current === tool ? null : tool)}
                disabled={!canEditTransform()}
              >
                {tool.startsWith('translate') ? 'Move' : 'Rotate'} {tool.slice(-1).toUpperCase()}
              </button>
            ))}
            <label className="transform-tool-hint">
              Move speed: {translationDragSpeed.toFixed(2)} units/px
              <input
                type="range"
                min="0.01"
                max="1"
                step="0.01"
                value={translationDragSpeed}
                onChange={(event) => setTranslationDragSpeed(Number(event.target.value))}
              />
            </label>
            <label className="transform-tool-hint">
              Rotate speed: {rotationDragSpeed.toFixed(2)}°/px
              <input
                type="range"
                min="0.01"
                max="0.25"
                step="0.01"
                value={rotationDragSpeed}
                onChange={(event) => setRotationDragSpeed(Number(event.target.value))}
              />
            </label>
            {activeTransformTool && <div className="transform-tool-hint">Drag in the viewport to edit {activeTransformTool.replace('-', ' ').toUpperCase()}.</div>}
          </div>
        )}
        {!connected && <div className="status">Stream not connected</div>}
      </main>
    </div>
  );
}
