## Summary

<!-- What does this PR do? One paragraph. Link the relevant issue or VISION.md phase if applicable. -->

Closes #<!-- issue number -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds capability)
- [ ] Breaking change (changes existing behavior or schema)
- [ ] Documentation update
- [ ] CI / DevOps change

## What was changed

<!-- List the files touched and why. Not a diff — explain the decision. -->

- `agents/` —
- `scrapers/` —
- `config/` —
- `database/schema.sql` —
- Other —

## Testing done

<!-- How did you verify this works? Include log snippets, DB query output, or report excerpt. -->

- [ ] Ran `docker compose exec agents python crews/market_intel_crew.py --market Yelahanka` end-to-end
- [ ] Checked `docker compose ps` — all 5 containers healthy after change
- [ ] Verified DB state with relevant `psql` query (paste output below if schema changed)
- [ ] CI passes (ruff lint + docker-compose validate + schema check)

```
# paste relevant log or query output here
```

## Checklist

- [ ] No API keys, `.env` values, or personal data committed
- [ ] `CHANGELOG.md` updated
- [ ] If schema changed: migration notes or `schema.sql` is backward-compatible
- [ ] If new dependency added: `requirements.txt` updated
