# Optional local media services

FetchHarbor can add five bounded, locally processed media capabilities without a
database or public model server. They are disabled by default and use a separate
worker container.

| Service | Route | Default price (USDC) | Limit |
| --- | --- | ---: | --- |
| Speech synthesis | `POST /v1/audio/speech` | $0.040 | 2,000 characters |
| Audio transcription | `POST /audio/transcribe` | $0.025 | 25 MiB / 5 minutes |
| SRT or WebVTT subtitles | `POST /audio/subtitles` | $0.035 | 25 MiB / 5 minutes |
| Audio conversion | `POST /audio/convert` | $0.015 | 25 MiB / 5 minutes |
| Transcription and summary | `POST /audio/transcribe-summary` | $0.050 | media limits plus 20,000 transcript characters |

The summary route is registered only when both media and Ollama are enabled.
Operators can change every price through environment configuration or the
loopback-only admin panel; pricing changes take effect after restart.

These launch prices are intentionally below common hosted per-request media
offers while leaving room for electricity, failed work, model warm-up and x402
settlement overhead. Revisit them using observed completion time and demand. Do
not price below the operator's measured marginal cost.

## Install models and start

Create a unique worker credential with at least 32 random characters in
`secrets/media_worker_token.txt`. Never reuse the admin token.

The setup profile is the only media component with outbound access. It downloads
the pinned Whisper snapshot and SHA-256-verified Kokoro release assets into a
named volume:

```bash
docker compose -f compose.yaml -f compose.media.yaml \
  --profile media-setup run --rm media-model-download
```

Then start the normal internal-only stack:

```bash
docker compose -f compose.yaml -f compose.production.yaml \
  -f compose.media.yaml up --build -d
```

Add `--profile ollama` and the appropriate Ollama/GPU overlays if the summary
route is required. The first transcription loads Whisper and may take longer
than later calls. The default worker uses CPU int8 so an 8 GB NVIDIA GPU remains
available to Ollama.

Confirm `/health/ready`, `/services`, `/openapi.json` and
`/.well-known/x402.json`. When payment is enabled, an unpaid representative JSON
request to every media route must return `402` and a v2 `PAYMENT-REQUIRED` header.
Do not run a funded mainnet request as an automated setup step.

## Public contract

Audio is sent as base64 inside JSON. This is deliberate: x402 and Bazaar document
POST discovery using `bodyType: "json"` plus a JSON input schema. Clients should
always send `Content-Type: application/json` and a correct `Content-Length`.
Base64 increases request size by roughly one third and requires temporary memory
for both the encoded and decoded forms. FetchHarbor therefore caps decoded audio
at 25 MiB, caps the JSON request near 36 MiB, processes only one worker job at a
time and avoids creating a second encoded copy between the API and worker. For
substantially larger media, use a separately designed upload/object-storage flow
rather than increasing these limits on this synchronous paid endpoint.

Example transcription body:

```json
{
  "audio_base64": "UklGRg...",
  "language": "en"
}
```

`language` is optional. Subtitle requests add `format` as `srt` or `vtt`.
Conversion requests add `format` as `wav`, `mp3`, `opus` or `flac`. Speech accepts
`input`, one of the advertised voices, WAV output and speed from 0.75 to 1.25.
Successful binary outputs are returned as base64 JSON so paid agent clients have
a deterministic, discoverable response type.

## Security and privacy boundary

- The worker publishes no host port and joins an internal Docker network only.
- A per-install secret authenticates API-to-worker requests; it is never returned.
- The runtime worker has no outbound network, runs non-root, drops all
  capabilities, uses a read-only filesystem and permits one job at a time.
- PyAV validates that uploads contain audio and enforces decoded size and duration.
- FFmpeg receives fixed server-owned arguments without a shell; video, subtitle,
  data and metadata streams are discarded and the subprocess has a hard timeout.
- The API rejects absent, invalid or oversized media `Content-Length` values
  before reading the body. Cloudflare or another edge should also rate-limit all
  media paths.
- Audio, text, transcripts and outputs live only in memory or an ephemeral tmpfs;
  request bodies and query strings are not written to monitoring or audit logs.
- Filenames are not accepted, reducing unnecessary personal metadata.
- Transcript text is untrusted. The summary prompt explicitly delimits it and
  tells Ollama not to follow embedded instructions; model output must still be
  treated as untrusted content.

Kokoro's phonemizer requires an executable in-memory temporary mount to load a
private eSpeak shared-library copy. This does not change the read-only root,
non-root user, dropped capabilities, one-job limit or no-egress network boundary.

Malformed input can fail after payment verification because content decoding is
part of the paid operation. The Bazaar example and schema therefore need to be
representative, and clients should validate base64, format, size and duration
before signing a payment. Application errors use stable generic messages and do
not expose worker traces.

## Release checks

Before enabling paid traffic:

1. Verify model file hashes/revisions and review dependency/image scan results.
2. Exercise real speech, transcription, both subtitle formats and every conversion
   format through the internal worker.
3. Confirm missing/incorrect worker credentials return `401` and the worker has no
   published ports or outbound network.
4. Send invalid base64, non-audio, over-limit, unsupported-format and concurrent
   requests and confirm bounded `4xx` responses.
5. Validate each live 402 response with Agentic Market Seller Tools. Bazaar uses
   the declared JSON example when probing POST endpoints.
6. Validate verification and settlement for each paid route from an
   operator-controlled environment. Keep any mainnet value deliberately limited
   and require explicit operator approval.

References: [x402 v2 specification](https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md),
[Coinbase x402 FAQ](https://docs.cdp.coinbase.com/x402/support/faq),
[Agentic Market Seller Tools](https://agentic.market/validate),
[OWASP unrestricted resource consumption](https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), and
[Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx).
