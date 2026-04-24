#!/bin/sh  
#SBATCH --job-name=webmall_plan_only
#SBATCH -p batch  
#SBATCH --nodes=1
#SBATCH -A marlowe-m000186-pm05
#SBATCH -G 4
#SBATCH -c 8
#SBATCH --mem-per-gpu=128G
#SBATCH --time=4:00:00
#SBATCH --output=webmall_replan_%A.out
#SBATCH --error=webmall_replan_error_%A.out
#SBATCH --export=ALL

module load conda
CONDA_BASE="/marlowe/apps/Mambaforge/24.3.0-0"
eval "$($CONDA_BASE/bin/conda shell.bash hook)"
conda activate /scratch/m000186/esoroka/
python run_replan_experiment_local.py --model Qwen/Qwen3-Coder-30B-A3B-Instruct --condition fv-guided --outdir=./outputs/Qwen3-coder-30B-A3B-Instruct_fv-guided_noexample --prompts=webmall_prompts.jsonl
python run_replan_experiment_local.py --model Qwen/Qwen3-Coder-30B-A3B-Instruct --example --condition fv-guided --outdir=./outputs/Qwen3-coder-30B-A3B-Instruct_fv-guided_example --prompts=webmall_prompts.jsonl

python run_replan_experiment_local.py --model Qwen/Qwen3-Coder-30B-A3B-Instruct --condition nl-critique --outdir=./outputs/Qwen3-coder-30B-A3B-Instruct_nl-critique_noexample --prompts=webmall_prompts.jsonl

python run_replan_experiment_local.py --model Qwen/Qwen3-Coder-30B-A3B-Instruct --example --condition nl-critique --outdir=./outputs/Qwen3-coder-30B-A3B-Instruct_nl-critique_example --prompts=webmall_prompts.jsonl

