"""The release workflow and the package metadata: installable from PyPI or the release wheels, no stored token."""

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


def test_depends_on_the_wirk_package_by_name():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["name"] == "wirk-mcp"
    assert "wirk==0.4.1" in project["dependencies"]  # the CLI this server was tested with, published as wirk
    assert project["version"] == __import__("wirk_mcp").__version__ == "0.4.1"
    assert not any("git+" in dependency for dependency in project["dependencies"])  # PyPI refuses direct references


def test_release_workflow():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert re.search(r"tags:\s*\[\s*['\"]v\*['\"]\s*\]", text)
    assert "secrets." not in text
    assert "SHA256SUMS" in text and "gh release create" in text and "--verify-tag" in text
    assert re.search(r"if: \$\{\{ vars\.PYPI_PUBLISH == 'true' \}\}", text) and "id-token: write" in text
    assert "pypa/gh-action-pypi-publish@" in text and "environment: pypi" in text
    assert "GITHUB_REF_NAME" in text and "pytest" in text
    for use in re.findall(r"uses: (\S+)", text):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", use), use


def test_every_workflow_parses_as_yaml():
    """GitHub rejects a workflow it cannot parse, and only says so once the workflow runs."""
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        assert "jobs" in yaml.safe_load(workflow.read_text()), workflow.name


def test_the_readme_leads_with_uv_install():
    assert "uv tool install wirk" in (ROOT / "README.md").read_text().split("## Use", 1)[0]


def test_ci_installs_the_pinned_cli():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert 'pip install "wirk==0.4.1"' in ci
    assert "wirk-cli@e509e24164a4cd374b6bae5fdf793626e69c9b5d" in ci


def test_release_attaches_the_managed_launcher():
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    assert "cp scripts/managed_client.py dist/" in workflow
    assert (ROOT / "scripts/managed_client.py").is_file()


def test_the_readme_by_hand_path_replaces_an_earlier_install():
    text = (ROOT / "README.md").read_text()
    assert "uv tool install wirk-mcp" not in text
    assert "uv tool install https://github.com/wirkspace/wirk-mcp/releases/download/v0.4.1/wirk_mcp-0.4.1-py3-none-any.whl" in text
    assert "claude mcp remove --scope user wirk" in text
    assert text.index("mcp get wirk") < text.index("claude mcp add")
