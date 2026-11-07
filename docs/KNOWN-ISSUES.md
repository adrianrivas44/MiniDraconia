# Known issues and validation limits

- This is a release candidate, not a stable product.
- She talks offline by default. Free-form conversation needs your own OpenAI-compatible endpoint (Settings → AI / Privacy; nothing is preset): a hosted service with your API key, or a server on your own computer without one. That mode is text only and was tested against fake endpoints on Linux, not yet against a real hosted or local server. Storing the key uses Windows DPAPI; its Windows run is a release gate.- Her walk speed (5.16 sprite px per frame) is a loop average measured from a 16-frame walk with held frames: on held frames the feet may slide slightly even though each loop travels exactly as far as her feet. Human review on a real display is pending.
- Her climb is a broom ride: its speed is a design choice (no hand holds to match).
- Only Windows 11 x64 is the initial target; wider platform support is not verified.
- An early test ZIP passed its selftest but failed normal startup because `run_DyberPet` was absent. The candidate must demonstrate the durable packaging fix, not rely on a companion file manually added to one laptop.
- Visual quality, animation transitions, native falling and scaling still need human review on real displays.
- The inherited voice manifest lists eleven clips but only one had individual listening approval at intake. Do not infer approval of the other ten from their existence or hashes.
- A complete redistribution review of character/art/audio/Qt and other dependency notices is a public-release gate. Attribution or an AI-generation label alone is not proof of permission.
- A dependency manifest and successful build using an existing developer environment do not prove a clean-machine install. Test provenance must say which environment was exercised.
- Public GitHub CI, release downloads and community installation cannot be verified before the repository/release actually exists.
