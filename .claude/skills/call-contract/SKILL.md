---
name: call-contract
description: Use when you touch the WebSocket server, parse or emit Twilio Media Streams messages, handle audio frames, read call_id or from_number, or reason about concurrent sockets and the per-call time cap.
---

# The call contract — how a call reaches us

Frozen for the event. Only additive changes happen: new optional fields, new
`reason` values. Never a breaking one.

## The wire

We give the organisers one `wss://` URL. They connect and speak Twilio's Media
Streams wire format, playing the carrier. No Twilio account, no phone number.

Messages arrive in this order:

1. `connected`.
2. `start`. `start.callSid` is the id of this call. It is the `call_id` we submit.
   `start.customParameters` carries:
   - `call_id` — the same id again.
   - `from_number` — the caller's number in E.164 (`+34612345678`). Absent when
     the caller id is withheld, which is what a caller with no number on file
     looks like.
3. `media` — 20 ms frames of 8 kHz µ-law audio, base64, in real time. The caller's voice.
4. `stop` when the call ends on their side. Then they close the socket.

Two quirks that are easy to miss:

- `sequenceNumber`, `chunk` and `timestamp` are **strings** on the wire.
- Every key in the handshake is **camelCase**. The submit JSON is snake_case.

We talk back over the same socket with our own `media` messages, same format. We
may send `mark` and `clear`. `clear` has no effect on their side today. There is
no server-side barge-in: turn-taking and interruption are entirely ours.

## `call_id` and `from_number`

- `call_id` is exactly `start.callSid`. Never mint one. A `call_id` they never
  called us on is a 404 at submit time.
- `from_number` is a hint, never an identification. `GET /directory?phone=...`
  finds the chart before the caller speaks, but the caller is not always the
  patient (problem 9), and the number may be absent. Confirm on a second field.

## Concurrency

- One URL, many calls. `Run All` opens **ten** sockets at once, each with its own
  `start.callSid`, overlapping for the whole conversation.
- Problem 2's largest public burst opens **twenty**.
- Everything a call owns is per socket: conversation, `call_id`, submission. A
  fresh pipeline per connection. Sharing one session across sockets is the
  mistake the challenge looks for.
- A refused or dropped connection fails the case it carried. The other calls in
  the wave continue and are scored.

## Time caps

- Every call is capped at **three minutes**. An agent that cannot book in three
  minutes has failed.
- A call is also cut if it takes too long to connect or goes quiet. Streaming
  silence keeps the socket open but counts as saying nothing. The cut is
  attributed to our agent. The silence window length is not published.
- The submission window opens when they open the call and closes 30 s after they
  close the socket. See the `submit-action` skill.

## Exposing the socket

- `ngrok http 7860`. Endpoint is `wss://<host>/ws`: scheme `wss://`, path included.
  `https://` is not the endpoint.
- Claim a static domain: a free ngrok URL changes every restart.
- Pick a European region. Every 20 ms frame pays the round trip.
- Keep the tunnel up for the whole run.
- Set the endpoint on the dashboard: Settings -> Integration. Optional headers,
  one per line, values are write-only. Headers WebSocket owns (`Host`,
  `Connection`, `Upgrade`, `Sec-WebSocket-*`) are rejected.
- A run snapshots its endpoint when admitted. A queued run dials where it was queued.
