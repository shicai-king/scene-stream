"""Run inside a worker image with only an explicitly authorized GPU visible."""
import json
import time

import torch
from flash_attn import flash_attn_func

assert torch.cuda.is_available(), "CUDA is unavailable"
assert torch.cuda.device_count() == 1, "Probe expects one explicitly selected GPU"
started = time.monotonic()
matrix = torch.randn(512, 512, dtype=torch.bfloat16, device="cuda")
result = matrix @ matrix.T
assert torch.isfinite(result).all()
q = torch.randn(1, 128, 8, 64, dtype=torch.bfloat16, device="cuda")
attention = flash_attn_func(q, q, q)
torch.cuda.synchronize()
assert torch.isfinite(attention).all()
print(json.dumps({"passed": True, "torch": torch.__version__, "cuda_runtime": torch.version.cuda,
                  "gpu": torch.cuda.get_device_name(0), "capability": torch.cuda.get_device_capability(0),
                  "bf16_matmul": True, "flash_attention_2": True, "elapsed_s": time.monotonic() - started}))
