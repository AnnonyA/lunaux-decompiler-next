# Security policy

## Supported versions

Only the latest tagged release and the current `main` branch receive security fixes during early development.

## Reporting

Do not publish exploitable parser crashes, arbitrary file writes, command injection, unsafe native loading behavior, or denial-of-service inputs before maintainers have had a reasonable opportunity to respond. Use GitHub private vulnerability reporting when enabled.

Include:

- affected version or commit;
- operating system and Python version;
- minimal reproduction;
- impact and required attacker access;
- suggested remediation, when known.

## Security design

- The server binds to loopback by default.
- CORS is disabled by default.
- Request and bytecode sizes are bounded.
- The CLI does not invoke shell commands or external `curl` processes.
- The application does not automatically install packages or replace its own source.
- Native backends execute in-process and must be treated as trusted code.

For hostile bytecode at scale, run the service in a constrained container or worker process with CPU, memory, and wall-clock limits.
