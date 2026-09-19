# Persona portraits

One SVG per receptionist persona, served by `GET /wall/personalities/{filename}`
and shown on the Clinic View's Personalities page. The three files here today
(`lucia.svg`, `mateo.svg`, `carla.svg`) are placeholders — the wall's animated
avatar in its three existing variants. To replace one, drop a self-contained
animated SVG in this folder: a tall portrait around 5:7 (the card's art box
uses `aspect-ratio: 5 / 7` and scales the image to its height), transparent
background, keyframes baked into the file, and no external references — no
fonts, no images, no scripts, because the page embeds it with `<img>` and
anything it does not carry itself will not load. Then open
`/wall#/clinic/personalities`, edit the persona and set its **Avatar** field to
the new filename; the name is stored on the persona, so the file does not have
to be called after the slug.
