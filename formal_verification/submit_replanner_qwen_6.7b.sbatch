#!/bin/sh  
#SBATCH --job-name=webmall_plan_only_qwen2_5_coder_7b
#SBATCH -p batch  
#SBATCH --nodes=1
#SBATCH -A marlowe-m000186-pm05
#SBATCH -G 1
#SBATCH -c 2
#SBATCH --mem-per-gpu=64G
#SBATCH --time=4:00:00
#SBATCH --output=webmall_replan_qwen2.5-coder-7b-instruct_%A.out
#SBATCH --error=webmall_replan_qwen2.5-coder-7b-instruct_error_%A.out
#SBATCH --export=ALL

module load conda
CONDA_BASE="/marlowe/apps/Mambaforge/24.3.0-0"
eval "$($CONDA_BASE/bin/conda shell.bash hook)"
conda activate /scratch/m000186/esoroka/

python run_replan_experiment_local.py --model Qwen/Qwen2.5-Coder-7B-Instruct --condition fv-guided --outdir=./outputs/Qwen2.5-coder-7B-Instruct_fv-guided_noexample --prompts=webmall_prompts.jsonl

python run_replan_experiment_local.py --model Qwen/Qwen2.5-Coder-7B-Instruct --example --condition fv-guided --outdir=./outputs/Qwen2.5-coder-7B-Instruct_fv-guided_example --prompts=webmall_prompts.jsonl

python run_replan_experiment_local.py --model Qwen/Qwen2.5-Coder-7B-Instruct --condition nl-critique --outdir=./outputs/Qwen2.5-coder-7B-Instruct_nl-critique_noexample --prompts=webmall_prompts.jsonl

python run_replan_experiment_local.py --model Qwen/Qwen2.5-Coder-7B-Instruct --example --condition nl-critique --outdir=./outputs/Qwen2.5-coder-7B-Instruct_nl-critique_example --prompts=webmall_prompts.jsonl

