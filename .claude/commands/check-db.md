Show current RE_OS database state using the postgres MCP tool.

Run these queries and report findings:

1. Record counts per key table:
   SELECT 'rera_projects' as tbl, COUNT(*) FROM rera_projects
   UNION ALL SELECT 'kaveri_registrations', COUNT(*) FROM kaveri_registrations
   UNION ALL SELECT 'guidance_values', COUNT(*) FROM guidance_values
   UNION ALL SELECT 'listings', COUNT(*) FROM listings;

2. Market inventory summary:
   SELECT * FROM v_market_inventory ORDER BY market_name;

3. Data quality — orphaned RERA rows:
   SELECT COUNT(*) as total, COUNT(micro_market_id) as linked,
   COUNT(*) - COUNT(micro_market_id) as orphaned FROM rera_projects;

4. Last 5 agent runs:
   SELECT market_name, status, records_inserted, records_updated, error_type, started_at
   FROM agent_runs ORDER BY started_at DESC LIMIT 5;

Report: summary of what's in the DB, any data quality issues, last run outcome.
