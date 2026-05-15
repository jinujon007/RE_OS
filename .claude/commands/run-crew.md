Run the RE_OS market intel pipeline.

Market: $ARGUMENTS (default: Yelahanka if blank)

Steps:
1. Run: `docker compose exec agents python crews/market_intel_crew.py --market $ARGUMENTS`
2. After completion, read the last 40 lines of `logs/crew.log`
3. Report: run ID, stages completed, any errors, final output location
