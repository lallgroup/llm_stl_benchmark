# https://github.com/wbsg-uni-mannheim/AgentLab/tree/3c70b919c8b5c68ebcbb9825bf0684663d410561/src/agentlab/agents
from dataclasses import dataclass
from typing import Any
import sys
sys.path.append("../BrowserGym")
from browsergym.experiment.loop import AbstractActionSet, DEFAULT_ACTION_SET
from browsergym.experiment.agent import Agent, AgentArgs
from agentlab.llm.base_api import BaseModelArgs
from agentlab.llm.llm_utils import Discussion, ParseError, SystemMessage, retry
from agentlab.llm.tracking import cost_tracker_decorator

from .generic_agent_prompt import GenericPromptFlags, MainPrompt

from .system_prompts_webmall import planner_system_prompt

@dataclass
class CustomAgentArgs(AgentArgs):
    planner_model: str = "gpt-5"
    planner_temperature: float = 0.5

    executor_model: str = "gpt-5-mini"
    executor_temperature: float = 0.5

    max_retry: int = 1

    def make_agent(self) -> Agent:
        return CustomAgent(self.args)


class CustomAgent(Agent):
    def __init__(self, args: CustomAgentArgs):
        super().__init__()

        # define which action set your agent will be using
        self.action_set = DEFAULT_ACTION_SET

        self.args = args
        planner_model_args = BaseModelArgs(model_name=args.planner_model,
                                           temperature=args.planner_temperature,
        )
        self.planner_llm = planner_model_args.make_model()
        executor_model_args = BaseModelArgs(model_name=args.executor_model,
                                            temperature=args.executor_temperature,
        )
        self.executor_llm = executor_model_args.make_model()

        self.planner_system_prompt = SystemMessage(content=planner_system_prompt)
        self.reset()


    def reset(self, seed=None):
        self.seed = seed
        self.task = "No task yet"
        self.plan = "No plan yet"
        self.plan_step = -1
        self.memories = []
        self.thoughts = []
        self.actions = []
        self.obs_history = []
        self.plan_history = []
    

    def executor_system_prompt(self)->SystemMessage:

        executor_system_prompt_str = f"""You are an expert web shopper following a plan to accomplish the final task '{self.task}'.and
You are currently on this step: {self.plan[self.plan_step]}.
ONLY do this step. Return the requested output.""" 

        return SystemMessage(content=executor_system_prompt_str)

    def obs_preprocessor(self, obs: dict) -> Any:
        # Optionally override this method to customize observation preprocessing
        # The output of this method will be fed to the get_action method and also saved on disk.
        return super().obs_preprocessor(obs)

    @cost_tracker_decorator
    def get_action(self, obs: Any) -> tuple[str, dict]:
        # Implement your custom logic here
        action = "your_action"
        info = {"custom_info": "details"}
        return action, info