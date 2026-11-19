# Security & Privacy Policy

## Local-First Guarantee

Qingjiao Redact Community processes all text, documents, NER inference, and reversible placeholder mappings strictly on your local machine:

- Document contents are never sent to external cloud APIs by this project.
- The open-source ModelScope RaNER model (`iic/nlp_raner_named-entity-recognition_chinese-base-news`) is downloaded once to your local `.model_cache/` and runs offline thereafter.
- Reversible placeholder mapping tables are stored locally under `data/` (configurable via `QINGJIAO_DATA_DIR`).

## Limitations of Community Edition

Automatic NER models cannot achieve 100% recall on arbitrary documents. Because Community Edition uses a standalone general-domain open-source NER model (3 entity types: Person, Organization, Location) without commercial structured rules, OCR, or domain-tuned models:

- **Always review detected entities before sharing redacted documents or sending them to external LLMs.**
- Do not rely on Community Edition alone for structured identifiers (ID cards, phone numbers, bank accounts, case numbers, amounts, seals/signatures, or scanned PDFs). For production compliance workloads, consider Qingjiao Redact Pro (`https://qingjiaolab.com`).

## Reporting a Vulnerability

Please report security issues privately via the contact channels listed on https://qingjiaolab.com rather than opening a public issue with sensitive reproduction data.
