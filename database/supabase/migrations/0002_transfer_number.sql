-- The clinic's human transfer number, edited on the wall's Call settings page.
-- Empty (the default) means transfers are off: ``transfer_call`` answers
-- ``unavailable`` and the call carries on with the agent.

alter table public.clinic_settings
    add column if not exists transfer_number text not null default '';
