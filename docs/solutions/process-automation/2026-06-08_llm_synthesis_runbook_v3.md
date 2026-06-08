# Runbook — llm_synthesis Bottleneck

_Generated: 2026-06-08_
_Module: process-automation/runbook-documenter_

## Problem Type
llm_synthesis

## Tags
`process-automation`, `runbook`, `llm_synthesis`

## Description
LLM synthesis dominating runtime. Stage3 avg 1055.2s exceeds Stage1+Stage2 (942.3s). Consider caching or faster model.

## Recommended Action
LLM synthesis dominating runtime. Stage3 avg 1055.2s exceeds Stage1+Stage2 (942.3s). Consider caching or faster model. Investigate the 11 failed runs first.

## Target File
crews/evaluate_pipeline.py

## Priority
HIGH

## Estimated Token Saving
60.0%

## Solution
1. Review the bottleneck stage identified above.
2. Implement the recommended action.
3. Monitor the next 10 pipeline runs for improvement.
4. If no improvement, re-run the Log Analyst and Efficiency Optimizer.
