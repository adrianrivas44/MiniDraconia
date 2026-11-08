# Known issues and validation limits

- This is a release candidate, not a stable product.
- She talks offline by default. Free-form conversation needs your own OpenAI-compatible endpoint (Settings → AI / Privacy; nothing is preset): a hosted service with your API key, or a server on your own computer without one. That mode is text only. It was tested against fake endpoints on Linux and, for a local server, rc.2's client against a real Ollama on Windows (results in `docs/RECOMMENDED-SETUP.md`); the app's own client has not yet been run against a real hosted endpoint. Storing the key uses Windows DPAPI; its real round trip passed on Windows.
- The rc.3 fixes for a server on your own computer (`localhost` connected as `127.0.0.1`, the 90-second local timeout, the background warm-up, the thinking pose while a reply waits, and cleaner replies) were verified with automated tests and stand-in servers on Linux. Their check against a real local server on Windows, through the frozen Settings screen, is listed in `docs/RELEASE-CHECKLIST.md`.
- A server that takes longer than 90 seconds to load its model can still make that first message fall back to a stored line (the request is tried once more).
- Smaller local models may reply off character or without an emotion tag. The app removes stray role prefixes and bracket junk, but it cannot fix what the model says; `docs/RECOMMENDED-SETUP.md` lists what worked.
- Her walk speed (5.16 sprite px per frame) is a loop average measured from a 16-frame walk with held frames: on held frames the feet may slide slightly even though each loop travels exactly as far as her feet. Human review on a real display is pending.
- Her climb is a broom ride: its speed is a design choice (no hand holds to match).
- Only Windows 11 x64 is the initial target; wider platform support is not verified.
- An early test ZIP passed its selftest but failed normal startup because `run_DyberPet` was absent. The candidate must demonstrate the durable packaging fix, not rely on a companion file manually added to one laptop.
- Visual quality, animation transitions, native falling and scaling still need human review on real displays.
- The inherited voice manifest lists eleven clips but only one had individual listening approval at intake. Do not infer approval of the other ten from their existence or hashes.
- A complete redistribution review of character/art/audio/Qt and other dependency notices is a public-release gate. Attribution or an AI-generation label alone is not proof of permission.
- A dependency manifest and successful build using an existing developer environment do not prove a clean-machine install. Test provenance must say which environment was exercised.
- Release downloads are verified after each publication by an unauthenticated download and SHA256 check. Public GitHub CI is not active, and community installations have not been verified.
