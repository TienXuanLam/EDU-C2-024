# EDU-C2-024 — University Academic Misconduct Investigation Report Drafting Agent

> **Category**: Cat 2 (orchestrates multiple steps to accomplish a specific use case)
> **Industry**: EDU (education)

## Overview

Generates MEXT-guideline-compliant university academic misconduct investigation report
drafts from anonymized case facts (misconduct type, evidence description, subject role
category, case ID code). A seven-step pipeline ingests the case facts, classifies
misconduct taxonomy and severity, drafts an evidence review and intent analysis, looks
up sanction ranges, assembles the report, and validates the output — producing a
structured Markdown draft for academic integrity officer and legal counsel review
before official use.

**Case facts, whether typed as free text or submitted as JSON, must already be
anonymized** — no real names, student IDs, or department/affiliation detail. Input is
rejected before any LLM call if an identifier appears, so a leaked identifier in
free-form text never reaches the model. No subject-identifying information is held at
any stage.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |
| Azure OpenAI | A resource with a chat-capable deployment — `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` |

```bash
pip install -e .
```

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and operational documentation
```

See `docs/` for the design spec and test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
