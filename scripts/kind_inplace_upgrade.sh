#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${1:?cluster name required}"
TARGET_RAW="${2:?target version required}"
TARGET_VER="${TARGET_RAW#v}"
IFS='.' read -r T_MAJOR T_MINOR T_PATCH <<<"$TARGET_VER"
T_PATCH="${T_PATCH:-0}"
TARGET_VER="${T_MAJOR}.${T_MINOR}.${T_PATCH}"
TARGET_MINOR_NUM=$((10#${T_MINOR}))

if ! command -v kind >/dev/null 2>&1; then echo "kind CLI not found" >&2; exit 1; fi
if ! command -v docker >/dev/null 2>&1; then echo "docker not found" >&2; exit 1; fi
if ! command -v kubectl >/dev/null 2>&1; then echo "kubectl not found" >&2; exit 1; fi

log() { echo "==> $*"; }
banner() { echo ""; echo "========================================"; echo "$*"; echo "========================================"; }

wait_for_api() {
  local tries="${1:-60}" i
  for (( i=1; i<=tries; i++ )); do
    if kubectl get --raw=/readyz >/dev/null 2>&1 || kubectl get nodes >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "ERROR: API server did not become ready in time" >&2
  return 1
}

# Discover nodes from kubectl roles (workers = not control-plane/master).
discover_nodes() {
  CP_NODES=()
  WORKER_NODES=()
  local name status roles age version
  # kubectl get nodes --no-headers → NAME STATUS ROLES AGE VERSION
  while read -r name status roles age version; do
    [[ -z "${name:-}" ]] && continue
    if [[ "$roles" == *control-plane* || "$roles" == *master* || "$name" == *control-plane* ]]; then
      CP_NODES+=("$name")
    else
      WORKER_NODES+=("$name")
    fi
  done < <(kubectl get nodes --no-headers 2>/dev/null || true)

  # Fallback via kind CLI
  if [[ ${#CP_NODES[@]} -eq 0 ]]; then
    local n
    while read -r n; do
      [[ -z "$n" ]] && continue
      if [[ "$n" == *control-plane* ]]; then CP_NODES+=("$n"); else WORKER_NODES+=("$n"); fi
    done < <(kind get nodes --name "$CLUSTER_NAME")
  fi

  if [[ ${#CP_NODES[@]} -eq 0 ]]; then
    echo "ERROR: no control-plane nodes found" >&2
    exit 1
  fi
  FIRST_CP="${CP_NODES[0]}"
}

node_kubelet_version() {
  local node="$1"
  kubectl get node "$node" -o jsonpath='{.status.nodeInfo.kubeletVersion}' 2>/dev/null | sed 's/^v//' || true
}

# Lowest kubelet minor across the cluster (workers may lag CPs).
cluster_min_version() {
  local min="" v
  local n
  for n in "${CP_NODES[@]}" "${WORKER_NODES[@]}"; do
    v="$(node_kubelet_version "$n")"
    [[ -z "$v" ]] && continue
    if [[ -z "$min" ]] || printf '%s\n%s\n' "$v" "$min" | sort -V | head -1 | grep -qx "$v"; then
      min="$v"
    fi
  done
  echo "$min"
}

all_nodes_on_minor() {
  local expect_minor="$1" n v
  for n in "${CP_NODES[@]}" "${WORKER_NODES[@]}"; do
    v="$(node_kubelet_version "$n")"
    case "$v" in
      ${expect_minor}.*) ;;
      *)
        echo "NODE_NOT_READY:$n:v${v:-unknown}"
        return 1
        ;;
    esac
  done
  return 0
}

print_node_matrix() {
  log "Node version matrix:"
  kubectl get nodes -o custom-columns='NAME:.metadata.name,ROLES:.metadata.labels.node-role\.kubernetes\.io/control-plane,VERSION:.status.nodeInfo.kubeletVersion,STATUS:.status.conditions[-1].type' 2>/dev/null \
    || kubectl get nodes -o wide
}

verify_success() {
  local expect_minor="$1"
  banner "POST-UPGRADE VERIFICATION"
  wait_for_api 90
  print_node_matrix

  if ! all_nodes_on_minor "$expect_minor"; then
    echo "ERROR: not all nodes are on v${expect_minor}.x" >&2
    print_node_matrix
    return 1
  fi

  if ! kubectl get nodes | grep -q Ready; then
    echo "ERROR: no Ready nodes" >&2
    return 1
  fi

  log "Workloads (pods/pvc sample):"
  kubectl get pods -A --field-selector=status.phase!=Succeeded 2>/dev/null | head -40 || true
  kubectl get pvc -A 2>/dev/null | head -40 || true

  local bad
  bad="$(kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "${bad}" != "0" ]]; then
    log "WARNING: ${bad} non-running pod(s) present (may be restarting after upgrade)"
  fi

  local ver
  ver="$(node_kubelet_version "$FIRST_CP")"
  banner "UPGRADED SUCCESSFULLY → v${ver}"
  echo "All control-plane and worker nodes are on v${expect_minor}.x."
  echo "Cluster '${CLUSTER_NAME}' workloads/PVCs were preserved (in-place kubeadm)."
  return 0
}

install_kube_packages() {
  local node="$1"
  local hop_minor="$2"
  local also_kubelet="${3:-0}"

  if ! docker inspect "$node" >/dev/null 2>&1; then
    echo "ERROR: docker container for node '$node' not found (kind node name mismatch?)" >&2
    docker ps --format '{{.Names}}' | grep -E "$CLUSTER_NAME" || true
    exit 1
  fi

  log "[$node] install kubeadm pinned to v${hop_minor}.*"
  docker exec -e DEBIAN_FRONTEND=noninteractive "$node" bash -ceu "
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    export NEEDRESTART_MODE=a
    APT_OPTS=(-y -qq -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

    apt-get update -qq
    apt-get \"\${APT_OPTS[@]}\" install apt-transport-https ca-certificates curl gpg >/dev/null
    install -m 0755 -d /etc/apt/keyrings
    rm -f /etc/apt/sources.list.d/kubernetes*.list /etc/apt/sources.list.d/pkgs.k8s.io*.list || true

    curl -fsSL \"https://pkgs.k8s.io/core:/stable:/v${hop_minor}/deb/Release.key\" \
      | gpg --batch --yes --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    echo \"deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v${hop_minor}/deb/ /\" \
      > /etc/apt/sources.list.d/kubernetes.list

    apt-get update -qq
    apt-mark unhold kubeadm kubelet kubectl 2>/dev/null || true
    KVER=\$(apt-cache madison kubeadm | awk -v m=\"^${hop_minor}\\.\" '\$3 ~ m { print \$3; exit }')
    if [[ -z \"\${KVER}\" ]]; then
      echo \"ERROR: no kubeadm package found for minor ${hop_minor}\" >&2
      exit 1
    fi
    echo \"Resolved kubeadm package version: \${KVER}\"
    apt-get \"\${APT_OPTS[@]}\" --allow-change-held-packages --allow-downgrades install \"kubeadm=\${KVER}\"
    apt-mark hold kubeadm
    INSTALLED=\$(kubeadm version -o short)
    echo \"Installed kubeadm: \${INSTALLED}\"
    case \"\${INSTALLED}\" in
      v${hop_minor}.*|${hop_minor}.*) ;;
      *) echo \"ERROR: expected kubeadm v${hop_minor}.x but got \${INSTALLED}\" >&2; exit 1 ;;
    esac
  "
  if [[ "$also_kubelet" == "1" ]]; then
    log "[$node] install kubelet/kubectl pinned to v${hop_minor}.* + restart"
    docker exec -e DEBIAN_FRONTEND=noninteractive "$node" bash -ceu "
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
      export NEEDRESTART_MODE=a
      APT_OPTS=(-y -qq -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
      dpkg --configure -a || true
      apt-mark unhold kubelet kubectl 2>/dev/null || true
      KVER=\$(apt-cache madison kubelet | awk -v m=\"^${hop_minor}\\.\" '\$3 ~ m { print \$3; exit }')
      if [[ -z \"\${KVER}\" ]]; then
        echo \"ERROR: no kubelet package found for minor ${hop_minor}\" >&2
        exit 1
      fi
      echo \"Resolved kubelet/kubectl package version: \${KVER}\"
      apt-get \"\${APT_OPTS[@]}\" --allow-change-held-packages --allow-downgrades install \
        \"kubelet=\${KVER}\" \"kubectl=\${KVER}\"
      apt-mark hold kubelet kubectl
      systemctl daemon-reload
      systemctl restart kubelet
      sleep 3
      systemctl is-active kubelet
      kubelet --version || true
    "
  fi
}

upgrade_secondary_cp() {
  local cp="$1"
  local hop_minor="$2"
  local cur
  cur="$(node_kubelet_version "$cp")"
  case "$cur" in
    ${hop_minor}.*)
      log "[$cp] already on v${cur} — skip secondary CP upgrade for this hop"
      return 0
      ;;
  esac
  banner "SECONDARY CONTROL-PLANE: $cp → v${hop_minor}.x"
  install_kube_packages "$cp" "$hop_minor" 0
  log "[$cp] kubeadm upgrade node"
  docker exec "$cp" bash -ceu "
    set -euo pipefail
    if ! kubeadm upgrade node; then
      kubeadm upgrade node --ignore-preflight-errors=CreateJob,ImagePull,SystemVerification
    fi
  "
  install_kube_packages "$cp" "$hop_minor" 1
  wait_for_api 60
}

upgrade_worker() {
  local w="$1"
  local hop_minor="$2"
  local cur
  cur="$(node_kubelet_version "$w")"
  case "$cur" in
    ${hop_minor}.*)
      log "[$w] already on v${cur} — skip worker for this hop"
      return 0
      ;;
  esac

  banner "WORKER NODE: $w → v${hop_minor}.x"
  log "drain $w"
  kubectl drain "$w" --ignore-daemonsets --delete-emptydir-data --force --timeout=300s || true

  install_kube_packages "$w" "$hop_minor" 0
  log "[$w] pre-pull pause:3.10"
  docker exec "$w" bash -ceu "crictl pull registry.k8s.io/pause:3.10 || true" || true

  log "[$w] kubeadm upgrade node"
  docker exec "$w" bash -ceu "
    set -euo pipefail
    if ! kubeadm upgrade node; then
      kubeadm upgrade node --ignore-preflight-errors=CreateJob,ImagePull,SystemVerification
    fi
  "
  install_kube_packages "$w" "$hop_minor" 1

  log "uncordon $w"
  kubectl uncordon "$w"
  wait_for_api 60

  cur="$(node_kubelet_version "$w")"
  case "$cur" in
    ${hop_minor}.*) log "[$w] worker OK — now v${cur}" ;;
    *)
      echo "ERROR: worker $w expected v${hop_minor}.x but got v${cur:-unknown}" >&2
      exit 1
      ;;
  esac
}

upgrade_one_hop() {
  local hop_minor="$1"
  local hop_index="$2"
  local hop_total="$3"

  banner "HOP ${hop_index}/${hop_total}: cluster → v${hop_minor}.x (CP first, then workers)"
  print_node_matrix

  # --- First control plane ---
  local first_ver
  first_ver="$(node_kubelet_version "$FIRST_CP")"
  if [[ "$first_ver" == ${hop_minor}.* ]]; then
    log "[$FIRST_CP] already on v${first_ver} — skip kubeadm apply for this hop"
  else
    log "[$FIRST_CP] best-effort etcd snapshot"
    docker exec "$FIRST_CP" bash -ceu "
      set -euo pipefail
      mkdir -p /root/etcd-backup
      if command -v etcdctl >/dev/null 2>&1; then
        ETCDCTL_API=3 etcdctl \
          --endpoints=https://127.0.0.1:2379 \
          --cacert=/etc/kubernetes/pki/etcd/ca.crt \
          --cert=/etc/kubernetes/pki/etcd/server.crt \
          --key=/etc/kubernetes/pki/etcd/server.key \
          snapshot save /root/etcd-backup/snapshot-${hop_minor}.db || true
      else
        echo 'etcdctl not present; skipping snapshot'
      fi
    " || true

    install_kube_packages "$FIRST_CP" "$hop_minor" 0
    local hop_tag
    hop_tag="$(docker exec "$FIRST_CP" kubeadm version -o short)"
    log "[$FIRST_CP] pre-pull pause:3.10"
    docker exec "$FIRST_CP" bash -ceu "crictl pull registry.k8s.io/pause:3.10 || true" || true

    log "[$FIRST_CP] kubeadm upgrade plan/apply ${hop_tag}"
    docker exec "$FIRST_CP" bash -ceu "
      set -euo pipefail
      set -x
      kubeadm upgrade plan \"${hop_tag}\" || kubeadm upgrade plan || true
      if ! kubeadm upgrade apply \"${hop_tag}\" --yes --force; then
        echo '==> retry apply with --ignore-preflight-errors=CreateJob (common on kind)'
        kubeadm upgrade apply \"${hop_tag}\" --yes --force \
          --ignore-preflight-errors=CreateJob,ImagePull,SystemVerification
      fi
    "
    install_kube_packages "$FIRST_CP" "$hop_minor" 1
    wait_for_api 90
  fi

  # --- Other control planes (HA) ---
  if ((${#CP_NODES[@]} > 1)); then
    banner "MULTI-NODE: upgrading ${#CP_NODES[@]} control-plane nodes"
    for cp in "${CP_NODES[@]:1}"; do
      upgrade_secondary_cp "$cp" "$hop_minor"
    done
  fi

  # --- Workers ---
  if ((${#WORKER_NODES[@]} > 0)); then
    banner "MULTI-NODE: upgrading ${#WORKER_NODES[@]} worker node(s)"
    log "Workers: ${WORKER_NODES[*]}"
    local w
    for w in "${WORKER_NODES[@]}"; do
      upgrade_worker "$w" "$hop_minor"
    done
  else
    log "Single-node / no workers detected — skipping worker phase"
  fi

  log "Waiting for API after hop v${hop_minor}.x ..."
  wait_for_api 90
  print_node_matrix

  if ! all_nodes_on_minor "$hop_minor"; then
    echo "ERROR: hop v${hop_minor}.x incomplete — some nodes still lagging:" >&2
    print_node_matrix
    exit 1
  fi
  log "Hop OK — ALL nodes (control-plane + workers) are on v${hop_minor}.x"
}

# --- main ---
discover_nodes
CUR_VER="$(cluster_min_version)"
IFS='.' read -r C_MAJOR C_MINOR C_PATCH <<<"${CUR_VER}"
C_MINOR_NUM=$((10#${C_MINOR:-0}))

banner "KIND IN-PLACE UPGRADE PLAN"
log "Cluster:            ${CLUSTER_NAME}"
log "Lowest node version: v${CUR_VER}  (used for hop planning — workers may lag)"
log "Target:              v${TARGET_VER}"
log "Control-plane (${#CP_NODES[@]}): ${CP_NODES[*]}"
if ((${#WORKER_NODES[@]} > 0)); then
  log "Workers (${#WORKER_NODES[@]}):       ${WORKER_NODES[*]}"
  banner "MULTINODE CLUSTER DETECTED"
  echo "Upgrade order each hop:"
  echo "  1) first control-plane (kubeadm upgrade apply)"
  echo "  2) other control-planes (kubeadm upgrade node)"
  echo "  3) each worker: drain → kubeadm upgrade node → kubelet → uncordon"
else
  log "Workers:             (none — single-node)"
fi
print_node_matrix

if (( C_MINOR_NUM >= TARGET_MINOR_NUM && C_MAJOR == T_MAJOR )); then
  log "Already at/beyond target minor on all nodes — verifying only"
  verify_success "${T_MAJOR}.${T_MINOR}"
  exit 0
fi

if (( T_MAJOR != C_MAJOR )); then
  echo "Refusing major-version jump (${C_MAJOR} → ${T_MAJOR})." >&2
  exit 1
fi

HOPS=()
for (( m=C_MINOR_NUM+1; m<=TARGET_MINOR_NUM; m++ )); do
  HOPS+=("${T_MAJOR}.${m}")
done
HOP_TOTAL=${#HOPS[@]}

if (( HOP_TOTAL > 1 )); then
  banner "HOPPING REQUIRED"
  echo "Kubernetes allows only ONE minor version per kubeadm upgrade."
  local_path="v${CUR_VER}"
  for h in "${HOPS[@]}"; do local_path="${local_path} → v${h}.x"; done
  echo "  ${local_path}"
else
  banner "SINGLE HOP"
  echo "Upgrading from lowest node v${CUR_VER} → v${HOPS[0]}.x (all nodes)."
fi

idx=1
for h in "${HOPS[@]}"; do
  # Re-discover in case membership changed
  discover_nodes
  upgrade_one_hop "$h" "$idx" "$HOP_TOTAL"
  idx=$((idx + 1))
done

verify_success "${T_MAJOR}.${T_MINOR}"
exit 0
