#!/bin/sh
set -eu

command_name="${1:-}"
case "${command_name}" in
  "api")
    shift
    exec uvicorn scalescore.api.main:app \
      --host "${SERVER_HOST:-0.0.0.0}" \
      --port "${SERVER_PORT:-8000}" \
      "$@"
    ;;
  "worker")
    shift
    exec scalescore-worker "$@"
    ;;
  *)
    echo "usage: scalescore-container {api|worker} [arguments...]" >&2
    exit 64
    ;;
esac
