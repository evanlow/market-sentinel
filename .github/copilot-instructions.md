# Copilot Repository Instructions

Follow `prime_directive.md` for all implementation and review work in this repository.

## Required Workflow

- Read and follow `prime_directive.md` before making code changes.
- Work on a feature branch, not directly on `main`.
- Inspect existing code before editing.
- Verify the project environment before running commands.
- For Python projects, use the existing virtual environment if present; do not create a duplicate venv.
- Run baseline tests before changes and post-change tests after (all must pass, zero warnings; N/A for doc-only changes).
- Add or update tests for backend logic changes.
- For UI changes, perform manual browser smoke testing and check browser console errors.
- Never commit secrets, `.env`, credentials, API keys, passwords, or tokens.
- Investigate anomalies instead of applying unexplained workarounds.

## Required Handoff Report

Before handoff, always report:

- files changed
- tests run
- test results
- manual checks performed
- known risks or follow-up actions
