# Humble Bundle Scrapper AGENTS.md file

## Dev environment setup
- Always use PIP as package manager.
- Create a virtual environment using `python -m venv venv` and activate it.
- Install dependencies using `pip install -r requirements.txt`.
- Use `pip freeze > requirements.txt` to update dependencies.
- Make sure to use Python 3.11 or higher.
- Use `black .` to format your code before committing.

## Testing instructions
- Tests are located in the `tests` directory.
- All new code must include corresponding tests.
- Run tests using `pytest tests/`.
- Ensure all tests pass before submitting a PR.
- Use `coverage run -m pytest` and `coverage report` to check test coverage. Right now is not mandatory but highly recommended.

## Coding standards
- Follow PEP 8 coding standards.
- Use meaningful variable and function names.
- Write docstrings for all public modules, functions, classes, and methods.
- Keep functions and methods short and focused on a single task. (SOLID principles)

## Building docs
- Use Sphinx for documentation.
- Generate docs using `sphinx-build -b html docs/ docs/_build/html`.
- Ensure all new features and changes are documented.

## PR instructions
- Title format: [FEAT] (for feature), [FIX] for fixes - <Title>
- Main branch is `master`, feature branches should be named as `feat/<feature-name>` or `fix/<fix-name>`.
- Never make direct commits to the master branch. Always create a new branch and send PR to master.
- Always run `pnpm lint` and `pnpm test` before committing.
- Ensure your code follows the project's coding standards and conventions.