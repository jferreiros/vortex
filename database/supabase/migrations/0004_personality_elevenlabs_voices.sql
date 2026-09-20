-- Per-persona ElevenLabs voices, separate from the Google fallback map.
--
-- 0001 gave personalities one voices_json map. That map is now the Google
-- HTTP adapter's fallback; stock launched calls need their own provider ids
-- so every agent keeps its own ElevenLabs voice instead of one global id.

alter table public.personalities
    add column if not exists elevenlabs_voices_json text not null default '{}';

update public.personalities
set elevenlabs_voices_json = case slug
    when 'lucia' then '{"es":"eZxqQzb5CuYo3Kl6EXfZ","en":"eZxqQzb5CuYo3Kl6EXfZ","ca":"eZxqQzb5CuYo3Kl6EXfZ","gl":"eZxqQzb5CuYo3Kl6EXfZ","eu":"eZxqQzb5CuYo3Kl6EXfZ"}'
    when 'mateo' then '{"es":"JngPf0lmRkKhY3qSJz0f","en":"JngPf0lmRkKhY3qSJz0f","ca":"JngPf0lmRkKhY3qSJz0f","gl":"JngPf0lmRkKhY3qSJz0f","eu":"JngPf0lmRkKhY3qSJz0f"}'
    when 'carla' then '{"es":"eZxqQzb5CuYo3Kl6EXfZ","en":"eZxqQzb5CuYo3Kl6EXfZ","ca":"eZxqQzb5CuYo3Kl6EXfZ","gl":"eZxqQzb5CuYo3Kl6EXfZ","eu":"eZxqQzb5CuYo3Kl6EXfZ"}'
    else elevenlabs_voices_json
end;
