import argparse, sys, logging, os
sys.path.append("../")
from dotenv import load_dotenv

from WebMall.webmall_overrides.study import WebMallStudy
from WebMall.webmall_overrides.benchmark import WebMallBenchmark
sys.path.append("../WebMall/AgentLab/src")
import bgym

from agentlab.llm.llm_configs import CHAT_MODEL_ARGS_DICT
from agentlab.agents import dynamic_prompting as dp
from agentlab.agents.generic_agent.generic_agent import (
    GenericAgentArgs, GenericPromptFlags, GenericAgentArgs
)
from WebMall.analyze_agentlab_results.aggregate_log_statistics import process_study_directory
from WebMall.analyze_agentlab_results.summarize_study import summarize_all_tasks_in_subdirs

FLAGS_default = GenericPromptFlags(
    obs=dp.ObsFlags(
        use_html=False,
        use_ax_tree=True,
        use_focused_element=True,
        use_error_logs=True,
        use_history=True,
        use_past_error_logs=False,
        use_action_history=True,
        use_think_history=True,
        use_diff=False,
        html_type="pruned_html",
        use_screenshot=False,
        use_som=False,
        extract_visible_tag=True,
        extract_clickable_tag=True,
        extract_coords="False",
        filter_visible_elements_only=False,
    ),
    action=dp.ActionFlags(
        action_set=bgym.HighLevelActionSetArgs(
            subsets=["bid"],
            multiaction=False,
        ),
        long_description=False,
        individual_examples=False,
    ),
    use_plan=False,
    use_criticise=False,
    use_thinking=True,
    use_memory=False,
    use_concrete_example=True,
    use_abstract_example=True,
    use_hints=True,
    enable_chat=False,
    max_prompt_tokens=60_000,
    be_cautious=True,
    extra_instructions=None,
)


if __name__ == "__main__":
    load_dotenv()
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=str, default="webmall_action_and_transaction_v1.0")
    parser.add_argument("--agent", type=str, default="openai/gpt-5-2025-08-07")
    parser.add_argument("--n_jobs", type=int, default=1)
    parser.add_argument("--parallel_backend", type=str, default="sequential")
    parser.add_argument("--reproducibility_mode", type=bool, default=False)
    parser.add_argument("--relaunch", type=bool, default=False)
    parser.add_argument('--use_memory', type=bool, default=False)
    parser.add_argument('--use_screenshot', type=bool, default=True)
    parser.add_argument('--use_som', type=bool, default=True)
    parser.add_argument('--experiment_name', type=str, default="gpt5")

    args = parser.parse_args()

    extra_instructions = None
    if args.use_memory:
        extra_instructions = "Use your memory to note down important information like the URLs of potential solutions and corresponding pricing information."

    flags = FLAGS_default.copy()
    flags.extra_instructions = extra_instructions
    flags.use_memory = args.use_memory
    flags.use_screenshot = args.use_screenshot
    flags.use_som = args.use_som

    agent_args = GenericAgentArgs(
        chat_model_args=CHAT_MODEL_ARGS_DICT[args.agent],
        flags=flags,
    )

    study = WebMallStudy(
        [agent_args],
        args.benchmark,
        logging_level_stdout=logging.INFO,
        suffix=args.experiment_name,
    )

    # make the study in the results directory
    # if results does not exist in the current directory, create it
    if not os.path.exists('results'):
        os.makedirs('results')
    
    study_dir = f"{os.getenv('AGENTLAB_EXP_ROOT')}/{args.experiment_name}/"
    if os.path.exists(study_dir):
        print(f"WARNING: cannot run over existing directory {study_dir}. Exiting.")
        sys.exit()

    study.run(
        n_jobs=args.n_jobs,
        parallel_backend=args.parallel_backend,
        strict_reproducibility=args.reproducibility_mode,
        n_relaunch=1,
    )

    if args.reproducibility_mode:
        study.append_to_journal(strict_reproducibility=True)

    summarize_all_tasks_in_subdirs(study_dir)
    process_study_directory(study_dir)