#!/usr/bin/env bash
# 174 部署与回滚脚本（agent-studio）
#
# 用法：
#   1) 推送镜像（在能访问 Harbor 的机器上）：
#        docker login 172.16.102.32:5000
#        docker push 172.16.102.32:5000/agent-studio/amd64/agent-studio-api:develop-fb472b2
#        docker push 172.16.102.32:5000/agent-studio/amd64/agent-studio-web:develop-fb472b2
#   2) 在 174 上执行本脚本：
#        bash scripts/deploy_174.sh upgrade develop-fb472b2
#      回滚：
#        bash scripts/deploy_174.sh rollback <旧标签，如 develop-20260805-04285be>
#
# 遵循 docs/plans/2026-08-02-user-agent-task-isolation.md §9 发布与回滚流程：
# 备份 compose env + 记录旧镜像标签 -> 先 migrate -> up --no-build --wait --scale worker=3
# -> 灰度验证 -> 失败恢复旧标签。

set -euo pipefail

ACTION="${1:-}"
NEW_TAG="${2:-}"
COMPOSE_DIR="${HARNESS_174_COMPOSE_DIR:-/opt/agent-studio/deploy/docker-compose}"
ENV_FILE="${COMPOSE_DIR}/.env.docker"
REGISTRY="172.16.102.32:5000"
PROJECT="agent-studio"
ARCH="amd64"
BACKUP_SUFFIX="$(date +%Y%m%d-%H%M%S)"

COMPOSE=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_DIR}/compose.yaml" -f "${COMPOSE_DIR}/compose.harbor.yaml")
export HARNESS_IMAGE_ARCH="${ARCH}"
export HARNESS_HARBOR_IMAGE_TAG="${NEW_TAG}"

log() { printf '[deploy-174] %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

[ -n "${ACTION}" ] && [ -n "${NEW_TAG}" ] || die "usage: deploy_174.sh upgrade|rollback <image-tag>"
[ -d "${COMPOSE_DIR}" ] || die "compose dir not found: ${COMPOSE_DIR}"
[ -f "${ENV_FILE}" ] || die "env file not found: ${ENV_FILE}"

case "${ACTION}" in
upgrade)
  log "=== 1/6 备份 compose env 与当前版本 ==="
  cp -a "${ENV_FILE}" "${ENV_FILE}.bak-${BACKUP_SUFFIX}"
  OLD_TAG="$(grep -E '^HARNESS_HARBOR_IMAGE_TAG=' "${ENV_FILE}" | tail -1 | cut -d= -f2- || echo develop)"
  log "old tag: ${OLD_TAG} -> new tag: ${NEW_TAG}"
  echo "${OLD_TAG}" > "${ENV_FILE}.old-tag-${BACKUP_SUFFIX}"
  cp -a "${ENV_FILE}.old-tag-${BACKUP_SUFFIX}" "${ENV_FILE}.old-tag"  # 回滚脚本读取
  log "备份完成: ${ENV_FILE}.bak-${BACKUP_SUFFIX} / .old-tag-${BACKUP_SUFFIX}"

  log "=== 2/6 拉取新镜像 ==="
  "${COMPOSE[@]}" pull api web worker migrate

  log "=== 3/6 写 .env.docker 的镜像标签 ==="
  if grep -q '^HARNESS_HARBOR_IMAGE_TAG=' "${ENV_FILE}"; then
    sed -i.bak "s|^HARNESS_HARBOR_IMAGE_TAG=.*|HARNESS_HARBOR_IMAGE_TAG=${NEW_TAG}|" "${ENV_FILE}"
  else
    echo "HARNESS_HARBOR_IMAGE_TAG=${NEW_TAG}" >> "${ENV_FILE}"
  fi

  log "=== 4/6 运行唯一 migrate 服务（串行迁移） ==="
  "${COMPOSE[@]}" up -d --no-build --wait migrate
  "${COMPOSE[@]}" logs --no-color migrate 2>&1 | tail -20 || true
  MIGRATE_EXIT=$("${COMPOSE[@]}" ps -q migrate >/dev/null && "${COMPOSE[@]}" inspect --format '{{.State.ExitCode}}' migrate 2>/dev/null || echo 1)
  # migrate 为一次性服务：等待其退出且 exit code 0
  for _ in $(seq 1 60); do
    CODE=$("${COMPOSE[@]}" ps -q migrate >/dev/null 2>&1 && "${COMPOSE[@]}" inspect --format '{{.State.ExitCode}}' migrate 2>/dev/null || echo "")
    [ "${CODE}" = "0" ] && break
    [ -n "${CODE}" ] && [ "${CODE}" != "0" ] && die "migrate 失败 exit=${CODE}；回滚: bash scripts/deploy_174.sh rollback ${OLD_TAG}"
    sleep 5
  done
  log "migrate 完成"

  log "=== 5/6 更新应用（3 个 Worker） ==="
  "${COMPOSE[@]}" up -d --no-build --wait --scale worker=3

  log "=== 6/6 灰度验证 ==="
  sleep 3
  curl -fsS http://127.0.0.1:8000/healthz >/dev/null && log "healthz OK"
  log "人工灰度顺序：登录 -> 智能体列表 -> 任务列表 -> 交叉 404 -> Echo Agent 运行 -> 3 Worker 竞争消费"
  log "升级完成 tag=${NEW_TAG}；如需回退: bash scripts/deploy_174.sh rollback ${OLD_TAG}"
  ;;
rollback)
  OLD_TAG="${NEW_TAG}"
  log "=== 回滚到 ${OLD_TAG} ==="
  [ -f "${ENV_FILE}.old-tag" ] && OLD_TAG="$(cat "${ENV_FILE}.old-tag")"
  log "实际回滚标签: ${OLD_TAG}"
  export HARNESS_HARBOR_IMAGE_TAG="${OLD_TAG}"
  "${COMPOSE[@]}" pull api web worker
  sed -i.bak "s|^HARNESS_HARBOR_IMAGE_TAG=.*|HARNESS_HARBOR_IMAGE_TAG=${OLD_TAG}|" "${ENV_FILE}"
  "${COMPOSE[@]}" up -d --no-build --wait --scale worker=3
  log "回滚完成 tag=${OLD_TAG}；数据库迁移保持兼容窗口，确认稳定后再清理"
  ;;
*)
  die "unknown action: ${ACTION}"
  ;;
esac
