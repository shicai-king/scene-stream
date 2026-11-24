"""Small, documented compatibility layer for the pinned Scope release."""
import json
import time

from aiortc import RTCConfiguration
import scope.server.webrtc as webrtc

# Both peers are on the project Docker network; no public STUN/TURN is needed.
webrtc.create_rtc_config = lambda: RTCConfiguration(iceServers=[])

# Record raw production batches, before Scope's playback-rate clamping.
from scope.server.pipeline_processor import PipelineProcessor
original_track_batch = PipelineProcessor._track_output_batch


def track_batch(self, num_frames, processing_time):
    now = time.monotonic()
    previous = getattr(self, "_longlive_last_batch", None)
    self._longlive_last_batch = now
    print(json.dumps({"event": "model_output_batch", "num_frames": num_frames,
                      "processing_s": processing_time, "interval_s": now - previous if previous else None,
                      "monotonic_s": now}), flush=True)
    return original_track_batch(self, num_frames, processing_time)


PipelineProcessor._track_output_batch = track_batch

from scope.server.app import main

if __name__ == "__main__":
    print(json.dumps({"event": "scope_bootstrap", "ice_servers": [], "monotonic_s": time.monotonic()}), flush=True)
    main()
