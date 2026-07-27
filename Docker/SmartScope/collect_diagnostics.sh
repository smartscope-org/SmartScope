#! /bin/bash
#
# collect_diagnostics.sh - bundle SmartScope logs, container state, config and
# host health for a developer to diagnose an issue. Run from this directory:
# Config is included; PASSWORD/SECRET/KEY/TOKEN values in *.conf are redacted.

# --- command resolution: reused verbatim from smartscope.sh (lines 3-15) ---
readonly cmd_file="dockerCmd.txt"
composeCmd="docker compose"
dockerCmd="docker"

if [ -e "$cmd_file" ]; then
    {
        read -r dockerCmd
        read -r composeCmd
    } < "$cmd_file"
    echo "Using docker command: $dockerCmd"
    echo "Using docker-compose command: $composeCmd"
fi

cd $(dirname "$(readlink -f "$0")")

compose="$composeCmd -f docker-compose.yml -f smartscope.yml"

out="diag-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$out/config" "$out/system"

# Logs + container state
[ -d ./logs ] && cp -R ./logs "$out/logs"
$compose logs --no-color --tail=1000 > "$out/compose_logs.txt" 2>&1
$compose ps -a                       > "$out/services.txt"     2>&1
$compose images                      > "$out/images.txt"       2>&1

# Config (whole folder; secrets in *.conf redacted)
for f in docker-compose.yml smartscope.yml smartscope.sh smartscope.ps1 shared/initialdb.sql; do
    [ -f "$f" ] && cp "$f" "$out/config/"
done
for f in smartscope.conf database.conf; do
    [ -f "$f" ] && sed -E 's/^([[:space:]]*[A-Za-z_][A-Za-z0-9_]*(PASSWORD|PASSWD|SECRET|_KEY|TOKEN|API_?KEY)[[:space:]]*=).*/\1 <hidden>/I' "$f" > "$out/config/$f"
done

# Host / system health
df -h                        > "$out/system/disk.txt"           2>&1
$dockerCmd stats --no-stream > "$out/system/docker_stats.txt"   2>&1
$compose top                 > "$out/system/compose_top.txt"    2>&1
$dockerCmd version           > "$out/system/docker_version.txt" 2>&1
uname -a                     > "$out/system/host.txt"           2>&1

tar -czf "$out.tar.gz" "$out" && rm -rf "$out"
echo "Created $out.tar.gz  (logs + config + system state; passwords redacted)"