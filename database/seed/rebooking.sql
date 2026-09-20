-- Vortex rebooking-queue seed: the pending callbacks the demo starts from,
-- one per slot database/seed/vortex_product.sql frees.
--
--   uv run python database/scripts/load_seed.py
--
-- Data only. The table comes from database/supabase/migrations/. Re-running
-- is safe: request_id is the primary key and a row already there is kept.

insert into public.rebooking_requests (
    request_id, call_id, intent, status, patient_id, policy_id,
    date_from, date_to, time_from, time_to,
    specialty_id, provider_id, location_id, appointment_id,
    source_reason, created_at, updated_at, matched_slot_json, draft_action_json
) values
    ('rq_258bcc699cee9b7f', 'WALLC-2518e3703b56', 'reschedule', 'pending',
     'P00005', 'privado', '2026-09-20', '2026-10-22', null, null,
     null, 'PR04', 'centro', null, 'wall_cancel',
     '2026-09-19T18:29:23.056050Z', '2026-09-19T18:29:23.056058Z', null, null),
    ('rq_1eb1b4fba931d7b5', 'WALLC-f546e6eb1663', 'reschedule', 'pending',
     'P00001', 'privado', '2026-09-20', '2026-10-23', null, null,
     null, 'PR04', 'centro', null, 'wall_cancel',
     '2026-09-19T18:29:23.311983Z', '2026-09-19T18:29:23.311990Z', null, null),
    ('rq_b8033d3d6bffe578', 'WALLC-c6a761e4c47f', 'reschedule', 'pending',
     'P00001', 'privado', '2026-09-20', '2026-10-24', null, null,
     null, 'PR04', 'centro', null, 'wall_cancel',
     '2026-09-19T18:29:23.573406Z', '2026-09-19T18:29:23.573413Z', null, null),
    ('rq_f946153cadece91b', 'WALLC-3562679aa541', 'reschedule', 'pending',
     'P00005', 'privado', '2026-09-20', '2026-10-21', null, null,
     null, 'PR03', 'sur', null, 'wall_cancel',
     '2026-09-19T18:29:52.933227Z', '2026-09-19T18:29:52.933325Z', null, null)
on conflict (request_id) do nothing;
