# Security Policy

## Reporting a vulnerability

Email **vvuppala3030@gmail.com** with subject `[SECURITY] Crucible`. Please include
reproduction steps and impact. You should receive an acknowledgement within
72 hours. Please do not open public issues for suspected vulnerabilities.

Once the repository is hosted on GitHub, private vulnerability reporting
(Security Advisories) is the preferred channel.

## Scope and posture (v1)

- Model-generated code is treated as hostile until contained: production
  execution happens in an isolated microVM sandbox, never in the API process,
  a shared CI runner, or via a model-controlled Docker configuration (ADR-003).
- Uploaded dataset content is untrusted data everywhere, including inside LLM
  context (indirect prompt injection is in-scope threat T2).
- The full threat model, data classification, and control-to-test mapping live
  in [docs/security/threat-model.md](docs/security/threat-model.md).

## Non-claims

Crucible does not claim SOC 2 / HIPAA / GDPR certification. Useful controls
are adopted and evidenced; certification is out of scope for v1 (PRD §4).
