#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Auto-retry script for creating Oracle Cloud A1.Flex instance
# when capacity is not available.
#
# Prerequisites:
#   1. Install OCI CLI: https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm
#   2. Configure OCI CLI: oci setup config
#   3. Fill in the variables below
#
# Usage:
#   chmod +x deploy/oracle-retry.sh
#   ./deploy/oracle-retry.sh
#
# The script will retry every 60 seconds until the instance
# is created or you press Ctrl+C.
# ═══════════════════════════════════════════════════════════

set -e

# ── FILL THESE IN ────────────────────────────────────────
# Find these values in the Oracle Cloud Console:

# Compartment OCID: Identity → Compartments → your compartment → OCID
COMPARTMENT_ID="ocid1.tenancy.oc1..aaaaaaaam7oftgrfuiqitp67vl7o5d75bj2ltjpaqsvhxw7275s3jypuhbea"

# Availability Domain: the AD name from your region
# Example: "Enoc:UK-LONDON-1-AD-1" or "Enoc:EU-FRANKFURT-1-AD-1"
AVAILABILITY_DOMAIN="Fvxe:CA-TORONTO-1-AD-1"

# Subnet OCID: Networking → VCNs → your VCN → Subnets → Public Subnet → OCID
SUBNET_ID="ocid1.subnet.oc1..subnet-renovation-bot"

# Image OCID for Ubuntu 22.04 ARM (find at: https://docs.oracle.com/en-us/iaas/images/)
# This is for Ubuntu 22.04 Minimal aarch64 — update if needed
IMAGE_ID="ocid1.image.oc1..PASTE_YOUR_IMAGE_OCID"

# SSH public key file path
SSH_KEY_FILE="$HOME/.ssh/id_rsa.pub"

# Instance settings
INSTANCE_NAME="renovation-bot"
OCPUS=4
MEMORY_GB=24
BOOT_VOLUME_GB=100

# Retry interval in seconds
RETRY_INTERVAL=60

# ── SCRIPT ───────────────────────────────────────────────

echo "═══════════════════════════════════════════"
echo "  Oracle Cloud A1.Flex — Auto-Retry"
echo "═══════════════════════════════════════════"
echo ""
echo "  Shape:    VM.Standard.A1.Flex"
echo "  OCPUs:    $OCPUS"
echo "  Memory:   ${MEMORY_GB} GB"
echo "  Boot:     ${BOOT_VOLUME_GB} GB"
echo "  Name:     $INSTANCE_NAME"
echo "  Retry:    every ${RETRY_INTERVAL}s"
echo ""
echo "  Press Ctrl+C to stop"
echo "═══════════════════════════════════════════"
echo ""

ATTEMPT=0

while true; do
    ATTEMPT=$((ATTEMPT + 1))
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

    echo "[$TIMESTAMP] Attempt #$ATTEMPT — Creating instance..."

    RESULT=$(oci compute instance launch \
        --compartment-id "$COMPARTMENT_ID" \
        --availability-domain "$AVAILABILITY_DOMAIN" \
        --shape "VM.Standard.A1.Flex" \
        --shape-config "{\"ocpus\": $OCPUS, \"memoryInGBs\": $MEMORY_GB}" \
        --display-name "$INSTANCE_NAME" \
        --image-id "$IMAGE_ID" \
        --subnet-id "$SUBNET_ID" \
        --assign-public-ip true \
        --boot-volume-size-in-gbs "$BOOT_VOLUME_GB" \
        --ssh-authorized-keys-file "$SSH_KEY_FILE" \
        --wait-for-state RUNNING \
        --max-wait-seconds 300 \
        2>&1) || true

    if echo "$RESULT" | grep -q '"lifecycle-state": "RUNNING"'; then
        echo ""
        echo "═══════════════════════════════════════════"
        echo "  ✅ Instance created successfully!"
        echo "═══════════════════════════════════════════"
        echo ""

        # Extract public IP
        INSTANCE_ID=$(echo "$RESULT" | grep '"id"' | head -1 | cut -d'"' -f4)
        echo "  Instance ID: $INSTANCE_ID"

        # Get VNIC attachments to find public IP
        sleep 10
        VNIC_ID=$(oci compute vnic-attachment list \
            --compartment-id "$COMPARTMENT_ID" \
            --instance-id "$INSTANCE_ID" \
            --query 'data[0]."vnic-id"' \
            --raw-output 2>/dev/null) || true

        if [ -n "$VNIC_ID" ]; then
            PUBLIC_IP=$(oci network vnic get \
                --vnic-id "$VNIC_ID" \
                --query 'data."public-ip"' \
                --raw-output 2>/dev/null) || true

            if [ -n "$PUBLIC_IP" ]; then
                echo "  Public IP:   $PUBLIC_IP"
                echo ""
                echo "  SSH into it:"
                echo "    ssh ubuntu@$PUBLIC_IP"
                echo ""
                echo "  Then follow deploy/ORACLE_CLOUD_DEPLOY.md Step 4"
            fi
        fi

        exit 0

    elif echo "$RESULT" | grep -qi "out of capacity"; then
        echo "[$TIMESTAMP] ⏳ Out of capacity. Retrying in ${RETRY_INTERVAL}s..."

    elif echo "$RESULT" | grep -qi "limit"; then
        echo "[$TIMESTAMP] ⚠️  Service limit reached. Check your tenancy limits."
        echo "$RESULT" | grep -i "limit" | head -3
        echo "Retrying in ${RETRY_INTERVAL}s..."

    else
        echo "[$TIMESTAMP] ❌ Unexpected error:"
        echo "$RESULT" | tail -5
        echo "Retrying in ${RETRY_INTERVAL}s..."
    fi

    sleep "$RETRY_INTERVAL"
done
