#!/usr/bin/env bash
# Provision a single A100-40GB VM in us-central1-a running vLLM with Qwen3.5-9B.
#
# After this completes, tail /var/log/vllm-startup.log on the VM (~15 min) and
# once the server is up, open a tunnel from your laptop:
#
#   gcloud compute ssh vllm-qwen35-9b --zone=us-central1-a \
#       -- -NL 8000:localhost:8000
#
# Then locally:
#   python run_replan_experiment.py \
#     --base-url http://localhost:8000/v1 \
#     --api-key-env VLLM_API_KEY \   # export VLLM_API_KEY=dummy-key
#     --provider openai --model Qwen/Qwen3.5-9B \
#     --condition fv-guided --max-iterations 3 \
#     --prompts webmall_prompts.jsonl \
#     --outdir results/experiments/qwen35_9b_fv
#
# Tear down when done:
#   gcloud compute instances delete vllm-qwen35-9b --zone=us-central1-a

set -euxo pipefail

INSTANCE_NAME="${INSTANCE_NAME:-vllm-qwen35-9b}"
ZONE="${ZONE:-us-central1-a}"
MACHINE_TYPE="${MACHINE_TYPE:-a2-highgpu-1g}"   # 1x A100-40GB + 12 vCPU + 85GB RAM
MODEL="${MODEL:-Qwen/Qwen3.5-9B}"
DISK_GB="${DISK_GB:-200}"
HERE="$(cd "$(dirname "$0")" && pwd)"

gcloud compute instances create "${INSTANCE_NAME}" \
  --zone="${ZONE}" \
  --machine-type="${MACHINE_TYPE}" \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size="${DISK_GB}GB" \
  --boot-disk-type=pd-balanced \
  --accelerator="type=nvidia-tesla-a100,count=1" \
  --maintenance-policy=TERMINATE \
  --restart-on-failure \
  --metadata-from-file=startup-script="${HERE}/vllm_startup.sh" \
  --metadata="MODEL=${MODEL}"

echo
echo "✓ Instance created: ${INSTANCE_NAME} in ${ZONE}"
echo "Startup script is running; model download + vLLM warm-up takes ~10–15 min."
echo
echo "Watch progress:"
echo "  gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE} -- tail -f /var/log/vllm-startup.log"
echo
echo "Once you see 'Uvicorn running on http://0.0.0.0:8000' in /var/log/vllm-server.log,"
echo "open a port-forwarding tunnel from your laptop:"
echo "  gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE} -- -NL 8000:localhost:8000"
