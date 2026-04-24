#!/usr/bin/env bash
# GCP VM startup script.  Assumes Ubuntu 22.04 LTS base image on a VM with
# one or more NVIDIA A100 / L4 / H100 GPUs attached.  Installs:
#   - NVIDIA driver + CUDA 12.4 (via network installer)
#   - Python 3.10 + vLLM
#   - Serves an OpenAI-compatible API on 0.0.0.0:8000 with --api-key dummy-key
# Log: /var/log/vllm-startup.log
#
# Instance metadata keys consumed (set via gcloud --metadata):
#   MODEL           e.g. "Qwen/Qwen3.5-9B"
#   PORT            defaults to 8000
#   MAX_MODEL_LEN   defaults to 16384
#   TENSOR_PARALLEL defaults to 1  (raise to 2 if running a 30B model on 2x40GB)

set -euxo pipefail
exec > >(tee -a /var/log/vllm-startup.log) 2>&1

echo "=== vLLM startup: $(date) ==="

# --- Read metadata ---
get_meta() {
  curl -fs -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1" \
    2>/dev/null || echo "$2"
}
MODEL="$(get_meta MODEL 'Qwen/Qwen3.5-9B')"
PORT="$(get_meta PORT 8000)"
MAX_MODEL_LEN="$(get_meta MAX_MODEL_LEN 16384)"
TENSOR_PARALLEL="$(get_meta TENSOR_PARALLEL 1)"
echo "MODEL=${MODEL}  PORT=${PORT}  MAX_MODEL_LEN=${MAX_MODEL_LEN}  TP=${TENSOR_PARALLEL}"

# --- Basic tooling ---
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  git curl wget ca-certificates gnupg build-essential \
  python3.10 python3.10-venv python3-pip tmux pciutils

# --- NVIDIA driver (network installer, for CUDA 12.4 runtime) ---
# Only install if not already present.
if ! nvidia-smi >/dev/null 2>&1; then
  wget -q https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
  dpkg -i cuda-keyring_1.1-1_all.deb
  apt-get update -y
  # toolkit pulls in the driver on server SKUs
  apt-get install -y cuda-toolkit-12-4
  # reboot-less driver load — usually works on fresh Ubuntu VMs
  modprobe nvidia || true
fi

# --- Python env with vLLM ---
python3.10 -m venv /opt/vllm-venv
source /opt/vllm-venv/bin/activate
pip install --upgrade pip wheel
# Pin vllm to a version known to have the OpenAI server with --api-key support.
pip install "vllm>=0.6.0" "huggingface-hub[hf_transfer]"
export HF_HUB_ENABLE_HF_TRANSFER=1

# --- Pre-download model weights (hides first-call latency) ---
python - <<PYEOF
from huggingface_hub import snapshot_download
snapshot_download("${MODEL}", max_workers=8)
print("model weights downloaded")
PYEOF

# --- Serve in tmux so an SSH-in user can attach ---
tmux new-session -d -s vllm "\
  /opt/vllm-venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model ${MODEL} \
    --port ${PORT} \
    --host 0.0.0.0 \
    --max-model-len ${MAX_MODEL_LEN} \
    --tensor-parallel-size ${TENSOR_PARALLEL} \
    --dtype bfloat16 \
    --api-key dummy-key \
  2>&1 | tee /var/log/vllm-server.log"

echo "=== vLLM server started on port ${PORT}, tmux session 'vllm' ==="
echo "Tail /var/log/vllm-server.log to watch startup."
