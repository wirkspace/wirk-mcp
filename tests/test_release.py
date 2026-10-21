"""The release workflow and the package metadata: installable from PyPI or the release wheels, no stored token."""

import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent


def test_depends_on_the_wirk_package_by_name():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["name"] == "wirk-mcp"
    assert "wirk==0.4.23" in project["dependencies"]  # the CLI this server was tested with, published as wirk
    assert project["version"] == __import__("wirk_mcp").__version__ == "0.4.23"
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
    assert 'pip install ".[test]"' in ci


@pytest.mark.parametrize("public,main,private", [(False, True, "false"), (False, True, "true"),
                                                  (False, False, "true"), (True, True, "false")])
def test_ci_requires_its_declared_cli_before_tests(tmp_path, public, main, private):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert "wirk==0.4.23" in project["dependencies"]
    assert {"pytest>=8,<10", "pyyaml>=6"} <= set(project["optional-dependencies"]["test"])
    steps = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)["jobs"]["verify"]["steps"]
    script = next(step["run"] for step in steps if step.get("name", "").startswith("The 17+ MCP tests"))
    fake = tmp_path / "python"
    fake.write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_TRACE"
case "$*" in
  "-m pip install wirk==0.4.23"|"-m pip install .[test]") [ "$FAKE_PUBLIC_AVAILABLE" = 1 ] ;;
  "-m pip install wirk @ git+https://github.com/wirkspace/wirk-cli@main") [ "$FAKE_MAIN_AVAILABLE" = 1 ] ;;
  "-m pip install --no-deps ."|"-m pip install mcp>=2.2,<3 anyio>=4 pytest pyyaml"|"-m pytest tests -q -rs") exit 0 ;;
  *) exit 97 ;;
esac
""")
    fake.chmod(0o755)
    trace = tmp_path / "invocations.txt"
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "FAKE_TRACE": str(trace),
           "FAKE_PUBLIC_AVAILABLE": str(int(public)), "FAKE_MAIN_AVAILABLE": str(int(main)), "PRIVATE": private}
    result = subprocess.run(["bash", "-e", "-c", script], cwd=ROOT, env=env, capture_output=True, text=True)
    calls = trace.read_text().splitlines()
    assert (result.returncode == 0) is public, (result.stdout, result.stderr, calls)
    assert calls.count("-m pytest tests -q -rs") == int(public), calls
    assert not any("git+" in call for call in calls), calls


def test_the_readme_by_hand_path_works_beside_an_earlier_install():
    """The separate PyPI installs and earlier-server replacement are documented."""
    text = (ROOT / "README.md").read_text()
    assert "uv tool install wirk" in text
    assert "uv tool install wirk-mcp" in text
    assert text.index("uv tool install wirk") < text.index("wirk login") < text.index("mcp get wirk")
    assert "claude mcp remove --scope user wirk" in text
    assert text.index("mcp get wirk") < text.index("claude mcp add")
