#!/bin/sh  
#SBATCH --job-name=webmall_plan_only_qwen2_5_coder_7b
#SBATCH -p batch  
#SBATCH --nodes=1
#SBATCH -A marlowe-m000186-pm05
#SBATCH -G 1
#SBATCH -c 2
#SBATCH --mem-per-gpu=64G
#SBATCH --time=1:00:00
#SBATCH --output=webmall_replan_qwen2.5-coder-7b-instruct_%A.out
#SBATCH --error=webmall_replan_qwen2.5-coder-7b-instruct_error_%A.out
#SBATCH --export=ALL

module load conda
CONDA_BASE="/marlowe/apps/Mambaforge/24.3.0-0"
eval "$($CONDA_BASE/bin/conda shell.bash hook)"
conda activate /scratch/m000186/esoroka/

python run_replan_experiment_local.py --prompts=webmall_prompts.jsonl  --model Qwen/Qwen2.5-Coder-7B-Instruct --condition nl-critique --max-iterations 3 --outdir results/experiments/Qwen2.5-Coder-7B-Instruct_nl-critique --example --gpus 1
