# Contributing

*[Deutsche Version](CONTRIBUTING.md)*

Thanks for your interest in hoerbox-feeder! This is a small hobby project,
so contributing is correspondingly informal.

## Setup

See [DEVELOPER.en.md](DEVELOPER.en.md) for architecture, local setup, and
environment variables.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Pull requests

- Small, focused changes are easier to review than large ones.
- Run the tests before opening a PR.
- Briefly describe *why* the change is needed, not just *what* it does.

## Issues

Found a bug or have a feature idea? Feel free to open an issue –
reproduction steps or the concrete use case help the most.
