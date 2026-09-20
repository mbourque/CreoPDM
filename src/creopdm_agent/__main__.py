"""Allow ``python -m creopdm_agent`` without relying on the console script."""

from creopdm_agent.main import run_cli

if __name__ == "__main__":
    run_cli()
