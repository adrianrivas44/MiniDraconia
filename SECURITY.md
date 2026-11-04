# Security reporting

MiniDraconia is an early Windows community candidate, not security-certified software. Do not use it to store secrets or sensitive conversations. No external model connection is implemented in this release line.

If you find a vulnerability, **do not post an exploit containing secrets or personal data in a public issue**. Use the repository's Security → Report a vulnerability option when it is enabled. If no private reporting route is available, request a private contact route from the maintainer without publishing the sensitive details. A specific contact address will be added only after the maintainer approves it.

A report should include the affected version, minimal reproduction, impact and a sanitized diagnostic. Do not attach live credentials, full user profiles, private messages or unrelated files. No bounty, response-time commitment or support guarantee is offered by this document.

Release maintainers: verify the exact source/binary manifest, normal startup, offline network behavior, dependency notices and archive paths before publishing. An unsigned executable's reputation warning is not evidence that the file is safe or malicious; never ask users to disable protection to work around it.
