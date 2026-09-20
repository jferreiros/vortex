-- The "Voz del agente" card's default row.
--
-- One row, ``id = 1`` -- a settings card has nothing to key on but itself.
-- The values are ``voice_config.DEFAULTS``: the female voice at the middle
-- of every slider, which is what a call sounds like when nobody has
-- touched the card.
--
-- Re-runnable: ``on conflict do nothing`` never overwrites a clinic's own
-- setting.

insert into public.voiceconfig (id, voice, tone, friendliness, speech_rate)
values (1, 'female', 50, 50, 50)
on conflict (id) do nothing;
