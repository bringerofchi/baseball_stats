-- Migration: add provenance columns to edges table
--
-- The edges table was created before the orchestrator's provenance-stamping
-- convention (data_source, timestamp_collected, collection_stage,
-- data_version, collection_status) was applied project-wide. odds and
-- starters already carry these columns; this brings edges in line so
-- rows written by the new automated edge_computation / edge_recomputation_final
-- stages are traceable the same way everything else is.
--
-- SQLite ALTER TABLE only supports adding one column per statement, so
-- these are five separate ALTERs rather than a single multi-column ALTER.
--
-- Safe to run once against an existing mlb_edge_lab.db. Existing edges
-- rows will have NULL in these five columns until the next time
-- compute_edges() runs for their date and re-stamps them.

ALTER TABLE edges ADD COLUMN data_source TEXT;
ALTER TABLE edges ADD COLUMN timestamp_collected TEXT;
ALTER TABLE edges ADD COLUMN collection_stage TEXT;
ALTER TABLE edges ADD COLUMN data_version TEXT;
ALTER TABLE edges ADD COLUMN collection_status TEXT;
