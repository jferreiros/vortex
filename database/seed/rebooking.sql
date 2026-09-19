-- Vortex product-data seed.
-- Regenerate: run the board, cancel visits from Horarios, then dump again:
--   python -c "import sqlite3; print(chr(10).join(sqlite3.connect('logs/vortex_product.db').iterdump()))"
-- Load into place: python database/scripts/load_seed.py [--replace]

BEGIN TRANSACTION;
CREATE TABLE rebooking_requests (
                    request_id TEXT PRIMARY KEY,
                    call_id TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    date_from TEXT NOT NULL,
                    date_to TEXT NOT NULL,
                    time_from TEXT,
                    time_to TEXT,
                    specialty_id TEXT,
                    provider_id TEXT,
                    location_id TEXT,
                    appointment_id TEXT,
                    source_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    matched_slot_json TEXT,
                    draft_action_json TEXT
                );
INSERT INTO "rebooking_requests" VALUES('rq_258bcc699cee9b7f','WALLC-2518e3703b56','reschedule','pending','P00005','privado','2026-09-20','2026-10-22',NULL,NULL,NULL,'PR04','centro',NULL,'wall_cancel','2026-09-19T18:29:23.056050Z','2026-09-19T18:29:23.056058Z',NULL,NULL);
INSERT INTO "rebooking_requests" VALUES('rq_1eb1b4fba931d7b5','WALLC-f546e6eb1663','reschedule','pending','P00001','privado','2026-09-20','2026-10-23',NULL,NULL,NULL,'PR04','centro',NULL,'wall_cancel','2026-09-19T18:29:23.311983Z','2026-09-19T18:29:23.311990Z',NULL,NULL);
INSERT INTO "rebooking_requests" VALUES('rq_b8033d3d6bffe578','WALLC-c6a761e4c47f','reschedule','pending','P00001','privado','2026-09-20','2026-10-24',NULL,NULL,NULL,'PR04','centro',NULL,'wall_cancel','2026-09-19T18:29:23.573406Z','2026-09-19T18:29:23.573413Z',NULL,NULL);
INSERT INTO "rebooking_requests" VALUES('rq_f946153cadece91b','WALLC-3562679aa541','reschedule','pending','P00005','privado','2026-09-20','2026-10-21',NULL,NULL,NULL,'PR03','sur',NULL,'wall_cancel','2026-09-19T18:29:52.933227Z','2026-09-19T18:29:52.933325Z',NULL,NULL);
COMMIT;
