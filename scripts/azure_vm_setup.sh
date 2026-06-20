#!/usr/bin/env bash
# Provision an Azure Ubuntu VM that mimics the 4 GB target laptop, then run
# the agent setup inside it. Requires `az` CLI logged in to your subscription.
#
# Usage:
#   ./scripts/azure_vm_setup.sh                          # defaults
#   RG=rg-research VM=agent-vm SIZE=Standard_B2s ./scripts/azure_vm_setup.sh
#   ./scripts/azure_vm_setup.sh --destroy                # tear it down
#
# Defaults:
#   resource group: rg-ollama-agent
#   vm name:        ollama-agent-vm
#   region:         eastus
#   size:           Standard_B2s  (4 GB RAM, 2 vCPU)   ~$30/mo if always-on
#                   Standard_B2ms (8 GB RAM, 2 vCPU)   ~$60/mo if you want headroom
#   image:          Ubuntu2204
#
# Cost notes:
#   B-series is burstable; idle costs are small. ALWAYS deallocate when done:
#     az vm deallocate -g <rg> -n <vm>            # stops billing for compute
#     az vm start      -g <rg> -n <vm>            # bring back
#   To delete everything:
#     ./scripts/azure_vm_setup.sh --destroy

set -euo pipefail

RG="${RG:-rg-ollama-agent}"
VM="${VM:-ollama-agent-vm}"
LOCATION="${LOCATION:-eastus}"
SIZE="${SIZE:-Standard_B2s}"
IMAGE="${IMAGE:-Ubuntu2204}"
ADMIN="${ADMIN:-azureuser}"
REPO_URL="${REPO_URL:-https://github.com/hsancheti_microsoft/ollama-local-research-agent.git}"

say() { printf "\n\033[1;36m==>\033[0m %s\n" "$*"; }
ok()  { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }

if ! command -v az >/dev/null; then
  echo "az CLI not found. Install: https://learn.microsoft.com/cli/azure/install-azure-cli" >&2
  exit 1
fi

if [[ "${1:-}" == "--destroy" ]]; then
  say "Destroying $RG (all resources)"
  az group delete -n "$RG" --yes --no-wait
  ok "tear-down queued (no-wait)"
  exit 0
fi

if ! az account show >/dev/null 2>&1; then
  say "Not logged in — running 'az login'"
  az login
fi

say "Ensuring resource group $RG in $LOCATION"
az group create -n "$RG" -l "$LOCATION" --only-show-errors >/dev/null
ok "rg ready"

say "Creating VM $VM (size=$SIZE, image=$IMAGE)"
if az vm show -g "$RG" -n "$VM" >/dev/null 2>&1; then
  ok "vm already exists; ensuring it's running"
  az vm start -g "$RG" -n "$VM" >/dev/null
else
  az vm create \
    -g "$RG" -n "$VM" \
    --image "$IMAGE" \
    --size "$SIZE" \
    --admin-username "$ADMIN" \
    --generate-ssh-keys \
    --public-ip-sku Standard \
    --nsg-rule SSH \
    --only-show-errors >/dev/null
  ok "vm created"
fi

# Open dashboard port (5050) on the NSG
say "Opening port 5050 (dashboard) for your current public IP only"
MY_IP="$(curl -fsS https://api.ipify.org)"
NSG="$(az vm show -g "$RG" -n "$VM" --query "networkProfile.networkInterfaces[0].id" -o tsv \
  | xargs -I{} az network nic show --ids {} --query "networkSecurityGroup.id" -o tsv \
  | awk -F'/' '{print $NF}')" || NSG=""
if [[ -n "$NSG" ]]; then
  az network nsg rule create \
    -g "$RG" --nsg-name "$NSG" \
    -n allow-dashboard-from-me \
    --priority 1010 \
    --protocol Tcp --destination-port-ranges 5050 \
    --source-address-prefixes "$MY_IP/32" \
    --access Allow --direction Inbound \
    --only-show-errors >/dev/null || true
  ok "5050 allowed from $MY_IP"
fi

IP="$(az vm show -d -g "$RG" -n "$VM" --query publicIps -o tsv)"
say "VM ready at $IP"
ok "ssh ${ADMIN}@${IP}"

say "Running wsl_setup.sh remotely (downloads ollama, pulls models, installs repo)"
ssh -o StrictHostKeyChecking=accept-new "${ADMIN}@${IP}" \
  "curl -fsSL https://raw.githubusercontent.com/hsancheti_microsoft/ollama-local-research-agent/main/scripts/wsl_setup.sh | REPO_URL='$REPO_URL' bash"

cat <<EOF

\033[1;32m=== Azure VM ready ===\033[0m

  ssh ${ADMIN}@${IP}
  cd ollama-local-research-agent
  source venv/bin/activate
  python main.py --hours 0.2
  ./dashboard/run.sh --host 0.0.0.0
  # then open http://${IP}:5050 from THIS machine (NSG only allows your IP)

To stop billing for compute when you're done:
  az vm deallocate -g $RG -n $VM
To bring back:
  az vm start      -g $RG -n $VM
To delete EVERYTHING:
  ./scripts/azure_vm_setup.sh --destroy

EOF
