from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import cli
from ai.modules.project_init import ProjectInitModule
from core.freshness import compare_freshness, compute_variant_fingerprint


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    )


def _init_git_repo(repo: Path, branch: str = "master") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    init = subprocess.run(
        ["git", "init", "-b", branch],
        cwd=repo,
        capture_output=True,
        check=False,
        text=True,
    )
    if init.returncode != 0:
        _run_git(repo, "init")
        _run_git(repo, "branch", "-m", branch)

    _write(repo / "README.txt", "ready\n")
    _run_git(repo, "add", "README.txt")
    _run_git(
        repo,
        "-c",
        "user.name=Copilot Test",
        "-c",
        "user.email=copilot-test@example.com",
        "commit",
        "-m",
        "init",
    )


def _build_source_tree(source_root: Path) -> None:
    _init_git_repo(source_root)
    _write(
        source_root / "coem" / "GWM_B26" / "components" / "AswPerception" / "func" / "adasFunc.c",
        "float g_threshold = 1.0f;\n",
    )
    _write(
        source_root / "coem" / "GWM_B26" / "components" / "AswPerception" / "calib" / "dotCalibDefine.h",
        "#define DISTANCEREAR 1.2f\n",
    )
    _write(
        source_root / "adas" / "symmetry" / "perception" / "include" / "paraDefine.h",
        "#define FCTB_TTC 2.0f\n",
    )
    _write(
        source_root / "adas" / "symmetry" / "perception" / "include" / "globalVarDefine.h",
        "extern float g_vehicle_width;\n",
    )
    _write(
        source_root / "adas" / "symmetry" / "perception" / "src" / "track.c",
        "void track(void) {}\n",
    )


def _make_config(tmp_path: Path, source_root: Path, dbc_path: Path, req_path: Path) -> dict:
    return {
        "default_variant": "gen6/gwm_b26",
        "identity": {"variant_id": "gen6/gwm_b26"},
        "codebases": {
            "gwm_cr60light": {
                "root_path": str(source_root.resolve()),
                "platform_id": "gen6_c_radar",
            }
        },
        "variants": {
            "gen6/gwm_b26": {
                "codebase_id": "gwm_cr60light",
                "display_name": "GWM B26",
                "customer": "GWM",
                "vehicle_project": "B26",
                "coem_project_dir": "coem/GWM_B26",
                "scope": {
                    "include_globs": [
                        "coem/GWM_B26/**",
                        "adas/symmetry/**",
                    ],
                    "exclude_globs": ["**/build/**"],
                },
                "key_source_files": [
                    r"coem\GWM_B26\components\AswPerception\func\adasFunc.c",
                    r"adas\symmetry\perception\include\paraDefine.h",
                ],
                "dbc_sets": {
                    "default": {
                        "files": [str(dbc_path.resolve())],
                    }
                },
                "requirement_overlays": [str(req_path.resolve())],
                "source_context": {
                    "source_root": str(source_root.resolve()),
                    "memory_dir": str(
                        Path(".workspaces") / "gen6_gwm_b26" / "memory"
                    ),
                },
            }
        },
        "paths": {
            "source_code": str(source_root.resolve()),
        },
        "project": {
            "source_code": str(source_root.resolve()),
            "memory_dir": str(tmp_path / ".workspaces" / "gen6_gwm_b26" / "memory"),
        },
    }


def test_compare_freshness_detects_parameter_source_change(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _build_source_tree(source_root)
    dbc_path = _write(tmp_path / "dbc" / "primary.dbc", 'VERSION "A"\n')
    req_path = _write(tmp_path / "requirements" / "overlay.yaml", "req_id: REQ-1\n")
    config = _make_config(tmp_path, source_root, dbc_path, req_path)

    previous = compute_variant_fingerprint(config, tmp_path)
    _write(
        source_root / "adas" / "symmetry" / "perception" / "include" / "paraDefine.h",
        "#define FCTB_TTC 2.5f\n",
    )
    current = compute_variant_fingerprint(config, tmp_path)

    delta = compare_freshness(previous, current)

    assert delta["code_changed"] is True
    assert delta["constants_changed"] is True
    assert delta["dbc_changed"] is False
    assert delta["requirements_changed"] is False
    assert delta["identity_changed"] is False


def test_compare_freshness_detects_dbc_change(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _build_source_tree(source_root)
    dbc_path = _write(tmp_path / "dbc" / "primary.dbc", 'VERSION "A"\n')
    req_path = _write(tmp_path / "requirements" / "overlay.yaml", "req_id: REQ-1\n")
    config = _make_config(tmp_path, source_root, dbc_path, req_path)

    previous = compute_variant_fingerprint(config, tmp_path)
    _write(dbc_path, 'VERSION "B"\n')
    current = compute_variant_fingerprint(config, tmp_path)

    delta = compare_freshness(previous, current)

    assert delta["dbc_changed"] is True
    assert delta["code_changed"] is False
    assert delta["constants_changed"] is False
    assert delta["requirements_changed"] is False
    assert delta["identity_changed"] is False


def test_compare_freshness_detects_requirement_change(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _build_source_tree(source_root)
    dbc_path = _write(tmp_path / "dbc" / "primary.dbc", 'VERSION "A"\n')
    req_path = _write(tmp_path / "requirements" / "overlay.yaml", "req_id: REQ-1\n")
    config = _make_config(tmp_path, source_root, dbc_path, req_path)

    previous = compute_variant_fingerprint(config, tmp_path)
    _write(req_path, "req_id: REQ-2\n")
    current = compute_variant_fingerprint(config, tmp_path)

    delta = compare_freshness(previous, current)

    assert delta["requirements_changed"] is True
    assert delta["code_changed"] is False
    assert delta["constants_changed"] is False
    assert delta["dbc_changed"] is False
    assert delta["identity_changed"] is False


def test_compare_freshness_detects_identity_and_scope_change(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _build_source_tree(source_root)
    dbc_path = _write(tmp_path / "dbc" / "primary.dbc", 'VERSION "A"\n')
    req_path = _write(tmp_path / "requirements" / "overlay.yaml", "req_id: REQ-1\n")
    config = _make_config(tmp_path, source_root, dbc_path, req_path)

    previous = compute_variant_fingerprint(config, tmp_path)
    changed = copy.deepcopy(config)
    changed["variants"]["gen6/gwm_b26"]["vehicle_project"] = "B27"
    changed["variants"]["gen6/gwm_b26"]["scope"]["include_globs"].append("common/**")
    current = compute_variant_fingerprint(changed, tmp_path)

    delta = compare_freshness(previous, current)

    assert delta["identity_changed"] is True
    assert delta["any_changed"] is True


def test_check_variant_freshness_reads_and_updates_state(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _build_source_tree(source_root)
    dbc_path = _write(tmp_path / "dbc" / "primary.dbc", 'VERSION "A"\n')
    req_path = _write(tmp_path / "requirements" / "overlay.yaml", "req_id: REQ-1\n")
    config = _make_config(tmp_path, source_root, dbc_path, req_path)

    first = cli._check_variant_freshness(config, tmp_path, update=False)
    assert first["any_changed"] is True
    assert "freshness_state_missing" in first["changed_keys"]

    written = cli._check_variant_freshness(config, tmp_path, update=True)
    assert Path(written["state_path"]).exists()
    assert written["any_changed"] is False
    assert written["changed_keys"] == []

    second = cli._check_variant_freshness(config, tmp_path, update=False)
    assert second["any_changed"] is False
    assert second["changed_keys"] == []


def test_project_init_generated_config_supports_freshness_fingerprint(tmp_path: Path) -> None:
    project_root = tmp_path / "radarAnalyze"
    project_root.mkdir()
    code_root = tmp_path / "cr60_light"
    _build_source_tree(code_root)
    dbc_path = _write(tmp_path / "dbc" / "primary.dbc", 'VERSION "A"\n')
    req_dir = tmp_path / "requirements"
    _write(req_dir / "customer" / "overlay.yaml", "req_id: REQ-2\n")

    module = ProjectInitModule(project_root=project_root)
    result = module.safe_run(
        name="BYD SC6H",
        code_root=str(code_root),
        dbcs=[str(dbc_path)],
        customer="BYD",
        vehicle_project="SC6H",
        coem_project="GWM_B26",
        requirements=[str(req_dir)],
        dry_run=True,
    )

    assert result.ok is True
    local_config = result.data["local_config"]
    local_config["identity"] = {"variant_id": result.data["variant_id"]}

    fingerprint = compute_variant_fingerprint(local_config, project_root)

    assert fingerprint["variant_id"] == result.data["variant_id"]
    assert fingerprint["requirements_hash"]
    assert fingerprint["dbc_hash"]
