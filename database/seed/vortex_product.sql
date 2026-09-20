-- Vortex product-data seed: the hand-cancelled slots the demo starts from.
--
--   uv run python database/scripts/load_seed.py
--
-- Data only. The tables come from database/supabase/migrations/. Re-running
-- this is safe: every row is keyed on the diary slot it frees, and a slot
-- already freed is left alone.

insert into public.wall_cancellations
    (provider_id, site_id, slot_start, appointment_id, patient_name, provider_name, cancelled_at)
select v.provider_id, v.site_id, v.slot_start, v.appointment_id,
       v.patient_name, v.provider_name, v.cancelled_at
from (values
    ('PR04', 'centro', '2026-09-22T11:30:00+02:00', null,
     'Ignacio Vázquez Moreno', 'Dra. Iglesias', '2026-09-19T18:29:22.717+00:00'),
    ('PR04', 'centro', '2026-09-23T11:30:00+02:00', null,
     'Josefa Domínguez Navarro', 'Dra. Iglesias', '2026-09-19T18:29:22.718+00:00'),
    ('PR04', 'centro', '2026-09-24T11:30:00+02:00', null,
     'Josefa Domínguez Navarro', 'Dra. Iglesias', '2026-09-19T18:29:22.718+00:00'),
    ('PR03', 'sur', '2026-09-21T09:00:00+02:00', null,
     'Ignacio Vázquez Moreno', 'Dra. Sáenz', '2026-09-19T18:29:52.818+00:00')
) as v (provider_id, site_id, slot_start, appointment_id,
        patient_name, provider_name, cancelled_at)
where not exists (
    select 1 from public.wall_cancellations w
    where w.provider_id = v.provider_id
      and w.site_id = v.site_id
      and w.slot_start = v.slot_start
);
