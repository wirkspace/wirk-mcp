"""The release workflow and the package metadata: installable from PyPI or the release wheels, no stored token."""

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


def test_depends_on_the_wirk_package_by_name():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["name"] == "wirk-mcp"
    assert "wirk==0.4.0" in project["dependencies"]  # the CLI this server was tested with, published as wirk
    assert project["version"] == __import__("wirk_mcp").__version__ == "0.4.0"
    assert not any("git+" in dependency for dependency in project["dependencies"])  # PyPI refuses direct references


def test_release_workflow():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert re.search(r"tags:\s*\[\s*['\"]v\*['\"]\s*\]", text)
    assert "secrets." not in text
    assert "SHA256SUMS" in text and "publish-release.yml@" in text
    assert "vars.PYPI_PUBLISH == 'true'" in text and "id-token: write" in text
    assert "pypa/gh-action-pypi-publish@" in text and "environment: pypi" in text
    assert "GITHUB_REF_NAME" in text and "pytest" in text
    for use in re.findall(r"uses: (\S+)", text):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+(?:/\.github/workflows/[\w.-]+)?@[0-9a-f]{40}", use), use


def test_every_workflow_parses_as_yaml():
    """GitHub rejects a workflow it cannot parse, and only says so once the workflow runs."""
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        assert "jobs" in yaml.safe_load(workflow.read_text()), workflow.name


def test_the_readme_gives_the_sites_install_command():
    assert "curl -fsSL https://wirk.life/install | sh" in (ROOT / "README.md").read_text()


def test_ci_installs_the_pinned_cli():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert 'pip install "wirk==0.4.0"' in ci


def test_the_readme_by_hand_path_works_beside_an_earlier_install():
    """wirk-mcp is not on PyPI, and Claude Code's add refuses while an earlier server named wirk is registered."""
    text = (ROOT / "README.md").read_text()
    assert "uv tool install wirk-mcp" not in text
    assert "uv tool install https://github.com/wirkspace/wirk-mcp/releases/download/v0.4.0/wirk_mcp-0.4.0-py3-none-any.whl" in text
    assert "claude mcp remove --scope user wirk" in text
    assert text.index("mcp get wirk") < text.index("claude mcp add")
