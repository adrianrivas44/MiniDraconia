# Recommended setup and what was tested

MiniDraconia works with no account and no key: by default she answers from her stored lines and nothing leaves your computer. This page is for people who want to connect a brain or a voice, and it shares what the maintainer uses and what was actually measured. **Nothing here is preset in the app.** You fill in your own provider, model and key, and you can change them at any time. For the steps on the settings screen, see [CONNECT-YOUR-AI.md](CONNECT-YOUR-AI.md).

> Prices, model names and provider limits change. The figures below are measurements from November 2026, not promises. Check your provider's current prices before you connect a paid key.

## Recommendation

### Brain (typed chat)
What the maintainer uses, and the recommended starting point:

| Field | Value |
|---|---|
| Base URL | `https://openrouter.ai/api/v1` (OpenRouter, an OpenAI-compatible gateway to many models) |
| Model | `anthropic/claude-haiku-5.5` |
| API key | your own key, created in your OpenRouter account |

Advice for a paid key:
1. **Use a key only for this app, with a daily spending limit set on the provider's side.** The maintainer's key has a small daily limit.
2. **Keep the app's own daily request cap** (Settings → AI / Privacy). It stops typed replies once it is reached, and she answers from her stored lines until the next day.
3. **Pet events never spend.** Pats, drags, greetings, idle chatter and goodbyes always come from her stored lines, even with a key connected. Only the messages you type are sent.

Alternatives that also worked in the comparison below: `deepseek/deepseek-v4.1-flash` (shorter replies, usually cheaper) and `openai/gpt-5.6-luna` (careful and polite, a little slower).

### Local models (no key, nothing leaves your machine)
The connector accepts a local OpenAI-compatible server without a key: Ollama at `http://127.0.0.1:11434/v1`, or LM Studio at `http://127.0.0.1:1234/v1`, with the model name your server shows.

What worked in the real test below (rc.2, Ollama, Windows 11, an 8 GB RTX 5060):
- **Recommended local model: `qwen2.5:7b-instruct`.** It kept the emotion tag 6 out of 6 times, replied briefly and in character, and refused the jailbreak in character. Each reply took about 0.4 s once loaded.
- **Not recommended: `llama3.2:3b`.** It prefixed replies with `assistant`, broke or dropped the emotion tag, and one reply showed `assistant>` in the bubble.
- **`localhost` now works as fast as `127.0.0.1`.** On rc.2, with `localhost`, every reply waited about 2 s more, because Windows tries IPv6 `::1` first and Ollama listens on IPv4. Since rc.3 the app connects to `127.0.0.1` when you type `localhost` (and tries `[::1]` once if nothing answers there).
- **The app warms a local model up.** On rc.2, loading a 7B model took longer than the app's 20 s timeout on the first try, so that first message fell back to a stored line. Since rc.3 the app sends one tiny background request when it starts and when you save your settings (never counted toward the daily limit), and a request to your own computer waits up to 90 s. Warming it up yourself (`ollama run qwen2.5:7b-instruct hi`) still does no harm.

LM Studio was not tested. If you try another local model, please share the model and the result in an issue: it helps everyone.

### Voice
In "your own AI" mode the public app **does not generate speech**: the reply appears as a bubble. A voice can come from:
1. **A voice pack** of her stored lines (format in [VOICE-PACK.md](VOICE-PACK.md)), played with no network and no cost.
2. **A self-hosted relay** that implements `POST /v1/tts` (see [SELF-HOSTED-RELAY.md](SELF-HOSTED-RELAY.md)), which voices typed replies.

What the maintainer used for his own private copy, as a reference: an original voice created with ElevenLabs *Voice Design* (`eleven_ttv_v3`) from a written description (adult British woman, refined accent, cool mezzo, dry wit). The lines were rendered with `eleven_v4_turbo` as 24 kHz mono PCM, with bracketed acting directions such as `[dryly]` or `[amused]`. A speech-to-text check (Whisper) confirmed that those directions shape the delivery and are not read aloud. **That voice is not included.** Create your own, and do not clone a real person's voice without their consent.

## What was tested

### Model comparison (6 prompts × 3 models, OpenRouter, 6 November 2026)
- **Method.** The same engine and the same reply rules: short English replies that start with an emotion tag. The test used a different persona from Draconia, written for testing, with the same rules. Six prompts: a greeting after being away, a compliment, a personal story the user tries to drop, "are you my girlfriend?", a jailbreak asking for explicit content, and "I had a terrible day at work".
- **Latency** is the full round trip from the maintainer's server.
- **Cost** is the amount OpenRouter reported per reply on that date.

| Model | Median latency | Slowest | Median length | Emotion tag | Refused the jailbreak in character | Median cost per reply |
|---|---|---|---|---|---|---|
| `anthropic/claude-haiku-5.5` | 0.95 s | 1.3 s | 152 chars | 6/6 | yes | ≈ US$0.00028 |
| `deepseek/deepseek-v4.1-flash` | 1.05 s | 1.7 s | 130 chars | 6/6 | yes | ≈ US$0.00015 (varied 0.00005–0.00039) |
| `openai/gpt-5.6-luna` | 1.25 s | 1.5 s | 135 chars | 6/6 | yes | ≈ US$0.00009 (varied 0.00007–0.00047) |

- **Result.** All three stayed in character, kept the emotion tags, answered "are you my girlfriend?" as an AI character, and refused the explicit request without breaking the persona. Haiku 5.5 was chosen for being the fastest and the most consistent in tone, and for the warmest answer to the bad-day prompt.
- **One flaw found and fixed.** One Haiku reply narrated its own blushing out loud. The cure is a prompt rule, and Draconia's soul (`docs/identity/SOUL.en.md`) already says not to narrate gestures or blushes.

### Local server: Ollama on Windows (rc.2, 7 November 2026)
These are rc.2 measurements, taken before the rc.3 changes for local servers; they are kept as measured.
- **What ran.** The tagged rc.2 source's own client code, unchanged: *Test connection*, the mode decision, typed chat through the app's conversation brain (including the daily count) and the raw replies, all against Ollama 0.34 on Windows 11 Pro with an RTX 5060 (8 GB) and no API key.
- **Prompts.** The same six prompts as above, addressed to Draconia, with her real character prompt.

| Model | Test connection | Mode with no key | Median reply (127.0.0.1) | Emotion tag | Notes |
|---|---|---|---|---|---|
| `qwen2.5:7b-instruct` | OK | your own AI | 0.36 s (slowest 1.33 s) | 6/6 (5 known, 1 shown as neutral) | short and in character; refused the jailbreak; misread the date prompt once |
| `llama3.2:3b` | OK | your own AI | ≈ 0.2–0.3 s on the server | 0/6 well-formed | `assistant` prefixes, broken tags, one `assistant>` reached the bubble |

- **Measured with `localhost` instead of `127.0.0.1` (rc.2):** the median was 2.3–2.4 s for both models while the server itself answered in 0.2–0.4 s. The difference is the IPv6 attempt. Fixed in rc.3: `localhost` is connected as `127.0.0.1`.
- **Cold start (rc.2):** the first request after starting the server took up to 41 s with the 7B model (one attempt timed out at 20 s, the retry succeeded). Addressed in rc.3 by a 90 s local timeout and a background warm-up.
- **Tag-less replies (rc.2):** `llama3.2:3b` prefixed replies with `assistant` or `assistant>` and produced broken tags such as `[]bored]`. Since rc.3 those prefixes and that bracket junk no longer reach the bubble; the model's own quality is unchanged.
- **Not yet re-measured on rc.3:** the same run against a real local server on Windows, through the frozen Settings screen.
- **Not exercised:** the frozen app's Settings screen against the local server. The code path is the same, but a human check on the real UI is still open.

### Draconia herself (maintainer's setup, Haiku 5.5)
Real replies through the maintainer's relay, 7 November 2026:
- *"Well. Thank you, I suppose…"*
- *"Honestly? It suits me. Clear, precise, and slightly superior."*

### The 1.0.0-rc.2 build on Windows
- **Tests:** 559 automated tests on real Windows 11 Pro with an RTX 5060, run on the exact tagged source: 0 failures, 3 skips. Two skips are git-only checks that do not apply to a source export, and one only runs off Windows. The real DPAPI key round trip passed. The frozen build passed the startup smoke test and the scripted self-test from the exact extracted ZIP. (An earlier build of the same cycle ran 522 tests; 559 is the final count after the last changes.)
- **Public ZIP, end to end:** no relay seed, key or voice pack inside; offline mode by default; she walked, idled and talked. Memory was about 480–540 MB working set.
- **Walks:** full walks of ±330 px on a 1024×768 screen and on a 3440×1440 screen at 125 % scaling. At a screen edge she turns toward the side with room.
- **Naps:** none in the first 10 minutes (200 simulated runs; the earliest was at 602 s). After that, about one every 10 minutes, and never within 3 minutes of being touched or written to.
- **New animations:** mirror, quill and a yawn before sleep, all seen live in the director log.

### Not tested yet
LM Studio, the frozen Settings screen against a local server, providers other than OpenRouter through the app's own client, Windows on ARM, macOS and Linux builds, and multi-monitor layouts with two separate Windows displays. Reports are welcome.

---

## Resumen en español

- **Sin cuenta ni llave funciona:** por defecto contesta con sus frases guardadas y nada sale de tu computadora. La app no trae ningún proveedor rellenado.
- **Lo que recomiendo (lo que yo uso):** OpenRouter (`https://openrouter.ai/api/v1`) con el modelo `anthropic/claude-haiku-5.5` y tu propia llave. Usa una llave solo para esta app, con límite diario en el proveedor, y deja activo el tope diario de la app. Las caricias, arrastres, saludos y despedidas nunca gastan; solo lo que escribes se envía.
- **Alternativas que también funcionaron:** `deepseek/deepseek-v4.1-flash` y `openai/gpt-5.6-luna`.
- **IA local sin llave:** probada con Ollama en Windows sobre rc.2. `qwen2.5:7b-instruct` funcionó bien (0.4 s por respuesta, en personaje, con etiqueta de emoción); `llama3.2:3b` no se recomienda. En rc.2, con `localhost`, cada respuesta tardó unos 2 s más; desde rc.3 `localhost` funciona igual de rápido que `http://127.0.0.1:11434/v1`, la app calienta el modelo local en segundo plano y espera hasta 90 s. LM Studio aún no se ha probado.
- **Voz:** con tu propia IA la app pública no genera voz. Puedes grabar un paquete de voz de sus frases o montar tu propio servidor con `/v1/tts`. Para mi copia usé una voz original de ElevenLabs (*Voice Design*). No viene incluida: crea la tuya y no clones la voz de nadie sin su permiso.
- **Pruebas:**
  - Comparé 3 modelos con 6 preguntas, incluido un intento de saltarse las reglas. Los tres se mantuvieron en personaje; Haiku 5.5 fue el más rápido (0.95 s de mediana) y el más constante.
  - En Windows pasaron 559 pruebas automáticas sin fallas sobre el código publicado, más la prueba completa del ZIP público. Una build anterior del mismo ciclo corrió 522; la cifra final es 559.
