# Contributing to Qingjiao Redact Community

Thank you for your interest in contributing!

## Development Setup

```bash
# 1. Backend
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
# Optional: install Alibaba ModelScope RaNER runtime
.venv/bin/pip install -r backend/requirements-ner.txt

# 2. Frontend
cd frontend && npm install && npm run build && cd ..

# 3. Run tests
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -v
```

## Guidelines

- Keep the recognition layer modular via the `EntityRecognizer` protocol in `backend/app/ner.py`.
- Keep all sample documents synthetic and free of real personal data.
- Follow conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- Ensure backend unit tests and `frontend` production build pass before opening a pull request.
