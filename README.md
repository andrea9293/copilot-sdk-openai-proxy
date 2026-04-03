# copilot-sdk-openai-proxy

A small Python project that provides an OpenAI-compatible proxy interface for use with the Copilot SDK. The repository contains the implementation under the `app/` package and tests to verify OpenAI-compatibility behavior.

Features
- Lightweight proxy to adapt Copilot SDK requests to OpenAI-compatible endpoints
- Test suite for API compatibility checks (see `test_openai_compat.py`)

Requirements
- Python 3.8+
- pip

Installation

1. Clone the repository:

   git clone https://github.com/andrea9293/copilot-sdk-openai-proxy.git
   cd copilot-sdk-openai-proxy

2. Install in editable / development mode:

   python3 -m venv .venv
   
   source .venv/bin/activate

   python -m pip install -e .

(If the project uses Poetry or another tool, run the tool-specific install instead.)

Usage

- Review the `app/` package for the proxy implementation and examples.
- To run the test suite:

   pytest -q

- To experiment interactively, import the package in a Python REPL or start any example scripts provided in `app/`.

Configuration

- Configuration options (API keys, target endpoints, ports) are expected to be provided via environment variables or configuration files. Check the source in `app/` for exact variable names and defaults.

Testing

- Tests are included in the repository (e.g., `test_openai_compat.py`). Run them with `pytest`.

Contributing

Contributions are welcome. Please open issues for bugs or feature requests and submit pull requests for changes. Follow these guidelines:

- Fork the repo and create a feature branch
- Add or update tests for any changes
- Keep changes focused and documented

Maintenance and Contact

- Maintainer: andrea9293 (see project repository on GitHub)

License

- No license file is included in this repository. Check the project for a LICENSE file or contact the maintainer to confirm licensing terms.

Notes

- This README is a general guide. Refer to the code in `app/` and `pyproject.toml` for implementation and dependency details.
