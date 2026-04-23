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
python run_replan_experiment_local.py --model Qwen/Qwen3-Coder-30B-A3B-Instruct --fv-guided
python run_replan_experiment_local.py --model Qwen/Qwen3-Coder-30B-A3B-Instruct --example --fv-guided
python run_replan_experiment_local.py --model Qwen/Qwen3-Coder-30B-A3B-Instruct --nl-critique
python run_replan_experiment_local.py --model Qwen/Qwen3-Coder-30B-A3B-Instruct --example --nl-critique
