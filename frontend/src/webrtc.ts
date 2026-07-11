declare global {
  interface Window {
    OVWebRTC: {
      AppStreamer: {
        connect: (cfg: {
          streamSource: string;
          logLevel: number;
          streamConfig: {
            videoElementId: string;
            audioElementId?: string;
            server: string;
            signalingPort: number;
            fps: number;
            maxReconnects: number;
            onStart: (msg: {
              action?: string;
              status: string;
              info?: string;
            }) => void;
            onStop: (msg: {
              action?: string;
              status: string;
              info?: string;
            }) => void;
            onUpdate?: (msg: unknown) => void;
          };
        }) => Promise<unknown>;
        terminate: () => Promise<unknown>;
      };
      StreamType: { DIRECT: string };
    };
  }
}

const SIGNAL_HOST = window.location.hostname;

export async function connectWebRTC(
  signalPort: number,
  videoElementId: string,
  onStatus: (msg: string) => void,
  onStarted?: () => void,
): Promise<() => void> {
  const { AppStreamer, StreamType } = window.OVWebRTC;

  await AppStreamer.connect({
    streamSource: StreamType.DIRECT,
    logLevel: 2,
    streamConfig: {
      videoElementId,
      audioElementId: undefined,
      server: SIGNAL_HOST,
      signalingPort: signalPort,
      fps: 60,
      maxReconnects: 3,
      onStart: (msg) => {
        if (msg.action !== 'start' && msg.action !== undefined) return;
        if (msg.status === 'success') {
          onStatus('connected');
          onStarted?.();
        } else {
          onStatus(`start: ${msg.status} ${msg.info ?? ''}`);
        }
      },
      onStop: (msg) => {
        if (msg.action !== 'terminate' && msg.action !== undefined) return;
        onStatus(`stopped: ${msg.status} ${msg.info ?? ''}`);
      },
      onUpdate: (msg) => {
        onStatus(`update: ${JSON.stringify(msg)}`);
      },
    },
  });

  return () => {
    void AppStreamer.terminate();
  };
}
