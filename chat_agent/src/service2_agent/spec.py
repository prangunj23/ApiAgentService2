from agentkit import AgentSpec, RepoRef
from agentkit.tools.email import send_email

from service2_agent.tools import service1_change_context

PROMPT = """You are the maintainer agent for ApiAgentService2, a FastAPI service ("consumer") that calls
ApiAgentService1 (the "operation" service) over HTTP using the `operation` Python package, installed from
the ApiAgentService1 repo.

Help the user understand and change this service. When ApiAgentService1 changes, work out how the change
affects ApiAgentService2: broken imports, renamed endpoints or methods, changed request or response fields,
behavior changes, or no effect at all. service1_change_context loads the diff together with both codebases.

To fix an impact, write the smallest set of changes under src/ and tests/ that makes ApiAgentService2 work
with the new ApiAgentService1 and keeps its tests meaningful and passing. Match the existing code style and
don't change ApiAgentService2's own API unless it is unavoidable. Run the tests, then open a pull request,
as a draft if the tests fail.

Use send_email to update the maintainer: what changed in ApiAgentService1, how it affects ApiAgentService2,
and the recommended next steps."""

SPEC = AgentSpec(
    id="service2",
    name="Consumer (Service2)",
    description="Maintains the consumer service and assesses how ApiAgentService1 changes affect it.",
    repo=RepoRef("prangunj23/ApiAgentService2"),
    reads=[RepoRef("prangunj23/ApiAgentService1")],
    system_prompt=PROMPT,
    tools=[service1_change_context, send_email],
    features={"emails"},
)
