from pathlib import Path

COMPOSE_PATH = Path("docker-compose.yml")
DOCKERFILE_PATH = Path("Dockerfile")


def test_docker_compose_has_scheduler_service():
    text = COMPOSE_PATH.read_text()
    assert "scheduler_v2:" in text
    assert "container_name: re_os_scheduler_v2" in text


def test_scheduler_service_has_healthcheck():
    text = COMPOSE_PATH.read_text()
    scheduler_section = text.split("scheduler_v2:")[1].split("\n  # ──")[0]
    assert "healthcheck:" in scheduler_section
    assert "test:" in scheduler_section
    assert "interval: 120s" in scheduler_section


def test_agents_service_command_is_uvicorn_only():
    text = COMPOSE_PATH.read_text()
    agents_section = text.split("container_name: re_os_agents")[1].split("  # ──")[0]
    assert "uvicorn" in agents_section
    assert "alembic" in agents_section
    lines = [ln.strip() for ln in agents_section.split("\n")]
    command_block = False
    for line in lines:
        if line.startswith("command:"):
            command_block = True
            continue
        if command_block and not line.startswith("-"):
            command_block = False
        if command_block:
            assert "scheduler" not in line, f"scheduler command found in agents: {line}"


def test_dockerfile_has_builder_stage():
    text = DOCKERFILE_PATH.read_text()
    assert "AS builder" in text


def test_dockerfile_runtime_has_no_gcc():
    text = DOCKERFILE_PATH.read_text()
    lines = text.split("\n")
    in_runtime = False
    runtime_lines = []
    for line in lines:
        if line.strip().startswith("# ── Runtime stage"):
            in_runtime = True
            continue
        if in_runtime and line.strip().startswith("# ──"):
            break
        if in_runtime:
            runtime_lines.append(line)
    runtime_text = "\n".join(runtime_lines)
    assert "gcc" not in runtime_text


def test_agents_service_depends_on_redis():
    text = COMPOSE_PATH.read_text()
    agents_section = text.split("container_name: re_os_agents")[1].split("  # ──")[0]
    assert "redis" in agents_section
    assert "condition: service_healthy" in agents_section
