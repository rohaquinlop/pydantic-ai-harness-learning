from pydantic_ai import Agent
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai_harness.file_system import FileSystem
from pydantic_ai_harness.repo_context import RepoContext
from pydantic_ai_harness.tool_budgets import ToolBudgets
from pydantic_ai_harness.wrap_up_at_limits import WrapUpAtLimits

from pr_reviewer.agent import INSTRUCTIONS, check_result
from pr_reviewer.models import ReviewDeps, ReviewResult
from pr_reviewer.state import LIGHT_MODEL

READ_TOOLS = ("read_file", "list_directory", "find_files", "grep")

harness_reviewer = Agent(
    LIGHT_MODEL,
    deps_type=ReviewDeps,
    output_type=ReviewResult,
    instructions=INSTRUCTIONS,
    retries={"tools": 3},
    defer_model_check=True,
    capabilities=[
        FileSystem(read_only=True, tools=READ_TOOLS),
        RepoContext(),
        ToolBudgets(total=40, refuse_repeats=frozenset(READ_TOOLS)),
        WrapUpAtLimits(),
    ],
)
harness_reviewer.output_validator(check_result)


def policy_workspace(deps: ReviewDeps) -> LocalWorkspace[ReviewDeps]:
    """The run's workspace: the policy base, read-only. A new one per call, since its dir is fixed."""
    return LocalWorkspace(deps.policy_base, read_only=True)
