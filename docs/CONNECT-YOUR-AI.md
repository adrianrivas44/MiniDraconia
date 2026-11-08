# Connect your own AI

Draconia talks offline by default: she answers from her stored English lines and sends nothing anywhere. If you want her to answer your typed messages with a language model, you can connect **your own** AI in *Settings → AI / Privacy → Connect your own AI*. Nothing is preset: the app does not point at any provider, and you decide where your messages go. If you want a starting point, [RECOMMENDED-SETUP.md](RECOMMENDED-SETUP.md) shares what the maintainer uses and what was measured.

## What works

Any endpoint that speaks the OpenAI-compatible chat completions API: `POST <base URL>/chat/completions`. That covers many hosted services and most local model servers.

You fill in three fields:

| Field | What to enter | Example (placeholder) |
| --- | --- | --- |
| Base URL | The API base address your service or server documents, without `/chat/completions` | `https://your-endpoint.example/v1` |
| Model | The model name exactly as your service or server lists it | `provider/model-name` |
| API key | Your key, if the endpoint needs one | — |

*Test connection* and *Save and use my AI* refuse an empty base URL or model, and tell you so in plain words. Until all the required fields are filled in and saved, she stays offline.

### A hosted service

Open your service's API documentation, copy its OpenAI-compatible base URL and the name of the model you want, create an API key in your account there, and paste the three into Settings. A chat subscription on a website is usually not the same thing as an API key. A hosted service may charge your account for each request under its own terms; check them before you connect it.

A key is required for any endpoint that is not on your own computer, and **an API key is never sent over plain http:// to another computer**: such an address is refused. Use the `https://` address your service documents.

### A server on your own computer (no key)

A local OpenAI-compatible server works too, and needs no key. Typical base URLs:

- Ollama: `http://127.0.0.1:11434/v1`
- LM Studio: `http://127.0.0.1:1234/v1`

Start the server, load or pull a model in it, then enter that base URL and the model's name as the server lists it. Leave the API key empty.

Two tips from a real test with Ollama on Windows (see [RECOMMENDED-SETUP.md](RECOMMENDED-SETUP.md)):

- **Prefer `127.0.0.1` to `localhost`.** On Windows `localhost` resolves to the IPv6 address `::1` first; Ollama listens on IPv4 only, so every request waited about 2 seconds before falling back. With `127.0.0.1` the same replies took about 0.4 s.
- **Warm the model up first** (for example `ollama run <model> hi`). The first request after the server starts has to load the model; a 7B model took longer than the app's timeout on the first try, so that first message falls back to a stored line. Only `localhost`, `127.0.0.1` and `::1` count as your own computer; any other address needs a key and `https://`. If you do enter a key for a local server, it is sent to that local server only.

## Test connection

*Test connection* sends one tiny request (`Reply with the single word OK.`, at most 5 tokens) with the key you just typed, or the stored one. It shows `Connection OK.` or the error (for example the HTTP status), never the key. The test does not count toward the daily limit.

## The daily request limit

Every request she sends to your endpoint, including a second attempt after a timeout or a server error, counts toward a local **daily request limit**: 200 by default, editable in Settings (0 stops all requests). The count resets on your computer's local date. Past the limit she answers from her stored lines until the next day and says so once in her bubble. The count is kept in your profile as `own_key_usage.json`.

## Your key

- It is typed into a masked field and stored **encrypted with Windows DPAPI** for your Windows user, in your profile as `own_key.dpapi`. It is never written in plain text: not in settings, logs, crash reports or diagnostics, and it is never shown again.
- *Forget key* deletes the stored key and switches her back to offline lines.
- *Use offline lines* switches her back to offline and keeps the key until you forget it.
- Where Windows encryption is not available, no key is stored at all; only a server on your own computer, which needs no key, can be used there.
- Your base URL, model and daily limit are kept in `ai.json` in your profile (never the key). Values you saved once stay until you change them.

## What is sent

Only when you send a typed message in *Talk to Draconia*, and only to the base URL you entered:

- your typed message (up to 500 characters);
- the recent typed conversation (up to the last 16 messages, kept in memory only and cleared with *Clear current chat history* or when the app quits);
- her character prompt: the bundled `docs/identity/SOUL.en.md` plus a short desktop addendum (`full-engine/data/draconia_desktop_prompt_en.txt`), and a one-line rule for the reply.

Nothing else: no touches, greetings, chatter or other desktop events (those always use her stored lines and never send anything), no files, screenshots, keystrokes, clipboard, your Windows user name or her mood files. The request looks like this:

```json
{
  "model": "provider/model-name",
  "messages": [
    {"role": "system", "content": "<her character prompt>"},
    {"role": "user", "content": "<an earlier typed message>"},
    {"role": "assistant", "content": "<her earlier reply>"},
    {"role": "user", "content": "<your typed message>"},
    {"role": "system", "content": "<the one-line reply rule>"}
  ],
  "max_tokens": 140,
  "reasoning": {"enabled": false}
}
```

with the headers `Content-Type: application/json` and, when you entered a key, `Authorization: Bearer <your key>`. She reads the first choice's message, takes a leading emotion tag such as `[happy]` as her pose, and shows the rest in her bubble (text only; this mode has no voice). Each request waits up to 20 seconds; a timeout, a network error or a server error (5xx) is tried once more. Any failure, a rejected key or the limit makes her answer from her stored lines: the bubble always works.

See [privacy](PRIVACY.md) for everything she keeps on your computer.

## En español

*Connect your own AI* no apunta a ningún proveedor: la URL base y el modelo empiezan vacíos y tú los escribes. Funciona con cualquier servicio compatible con OpenAI (`/chat/completions`): pega la URL base y el nombre del modelo que documenta tu servicio, y tu clave API. Un servidor en tu propio equipo no necesita clave: por ejemplo Ollama en `http://127.0.0.1:11434/v1` o LM Studio en `http://127.0.0.1:1234/v1`. En Windows usa `127.0.0.1` y no `localhost` (con `localhost` cada respuesta tardó unos 2 segundos más), y carga el modelo antes de hablarle (`ollama run <modelo> hi`). Cualquier otra dirección necesita clave y `https://`; la clave nunca se envía por `http://` sin cifrar a otro equipo.

*Test connection* hace una sola petición mínima y no cuenta para el límite. Un límite diario de peticiones (200 por defecto, editable) la detiene; al pasarlo responde con sus frases guardadas hasta el día siguiente. Tu clave se guarda cifrada con Windows DPAPI y nunca se muestra ni se registra; *Forget key* la borra y vuelve al modo sin conexión. Solo se envía lo que escribes en *Talk to Draconia*, la conversación escrita reciente y el prompt del personaje; los toques y demás eventos del escritorio nunca se envían.
