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
            onStart: (msg: { status: string; info?: string }) => void;
            onStop: (msg: { status: string; info?: string }) => void;
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
        onStatus(msg.status === 'success' ? 'connected' : `start: ${msg.status} ${msg.info ?? ''}`);
      },
      onStop: (msg) => {
        onStatus(`stopped: ${msg.status} ${msg.info ?? ''}`);
      },
    },
  });

  return () => {
    void AppStreamer.terminate();
  };
}
