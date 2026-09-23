"""AGENTIC STAR Marketplace entrypoint — one-shot Pod process.

Referenced by this repo's Dockerfile as the image `CMD`. Compiles the agent,
provisions its secrets, then hands off to shared.bootstrap.marketplace_app
for the Marketplace lifecycle (identity, input, events, terminal delivery,
exit). Mirrors agentcore's own `agents/base/chat_agent/cli.py` (the pattern
this file was copied from).

`namespace=`/`agent_name=` here match `src/api/server.py`'s existing
`secrets_factory(namespace="EDU", agent_name="UniversityAcademicMisconductInvestigationReportDraftingAgent")`
call shape exactly -- one Marketplace Pod deploys exactly one template, so
there is no cross-template secret-path collision to guard against.

No `config["llm"]` seam to fill here: PreProcessNode/MainNode each build
their own secret-bound AzureOpenAIClient per invocation (see
`src/nodes/pre_process_node.py::_build_llm`) -- constructor/module-scope
injection would be structurally unreachable on this real Marketplace path
anyway (`run_agent_marketplace` never populates `config["llm"]`; it's the
caller's own seam to fill, and this template chooses not to use it at all).
"""

from pathlib import Path
from typing import Any

from framework.utils.config_loader import load_agent_config
from shared.bootstrap.marketplace_app import run_agent_marketplace
from src.graph.graph import UniversityAcademicMisconductInvestigationReportDraftingAgent

# Add config overrides here to set values without touching config/config.yaml.
extend_config: dict[str, Any] = {}

if __name__ == "__main__":
    run_agent_marketplace(
        UniversityAcademicMisconductInvestigationReportDraftingAgent,
        agent_name="UniversityAcademicMisconductInvestigationReportDraftingAgent",
        namespace="EDU",
        config={**load_agent_config(Path(__file__).resolve().parent), **extend_config},
    )
