# Known issues and validation limits

- This is a release candidate, not a stable product.
- The app is a scripted desktop companion. Free-form AI chat and Claude/xAI connectors are not implemented.
- Only Windows 11 x64 is the initial target; wider platform support is not verified.
- An early test ZIP passed its selftest but failed normal startup because `run_DyberPet` was absent. The candidate must demonstrate the durable packaging fix, not rely on a companion file manually added to one laptop.
- Visual quality, animation transitions, native falling and scaling still need human review on real displays.
- The inherited voice manifest lists eleven clips but only one had individual listening approval at intake. Do not infer approval of the other ten from their existence or hashes.
- A complete redistribution review of character/art/audio/Qt and other dependency notices is a public-release gate. Attribution or an AI-generation label alone is not proof of permission.
- A dependency manifest and successful build using an existing developer environment do not prove a clean-machine install. Test provenance must say which environment was exercised.
- Public GitHub CI, release downloads and community installation cannot be verified before the repository/release actually exists.
