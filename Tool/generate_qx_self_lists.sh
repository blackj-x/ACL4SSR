#!/bin/zsh
# generate_qx_self_lists.sh
# Convert personal "Self" regional direct lists from Clash/ format to QuantumultX/ format.
# Source of truth: Clash/USSelfv1.list, HKSelf.list, JPSelf.list, ChinaSelf.list
# These are hand-maintained additions that "Global" etc. didn't cover for the maintainer's setup.
#
# Usage (from repo root):
#   chmod +x Tool/generate_qx_self_lists.sh
#   ./Tool/generate_qx_self_lists.sh
#
# Then review the generated QuantumultX/*.list and commit if good.
# In QX, import the resulting lists (e.g. via filter_remote) and make sure you have policies
# named "US直连", "HK直连", "JP直连", "ChinaSelf" (or batch replace the trailing policy names).

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p QuantumultX

convert_self() {
  local src_clash="$1"
  local dst_qx="$2"
  local policy="$3"

  if [[ ! -f "$src_clash" ]]; then
    echo "WARN: $src_clash not found, skipping"
    return
  fi

  echo "==> Generating QuantumultX/$dst_qx (policy: $policy) from $src_clash"

  {
    echo "# NAME: $dst_qx (personal Self list for QX)"
    echo "# SOURCE: Converted from Clash/$(basename "$src_clash")"
    echo "# NOTE: Personal supplement lists (hand curated domains the maintainer routes specially, e.g. certain AI/exchange sites)."
    echo "#       Keep the Clash/ version as the single source of truth. Re-run this generator after editing Clash/ lists."
    echo "# POLICY: Lines end with ,$policy . If your QX policies use different names (e.g. with flags or English names),"
    echo "#         batch-replace in the generated file or edit the policy argument in this generator script."
    echo "# SYNC: MANUAL (not from ios_rule_script)"
    echo ""

    # Convert Clash DOMAIN-SUFFIX -> QX HOST-SUFFIX and append ,Policy
    # (These personal lists currently only contain DOMAIN-SUFFIX lines.)
    sed -E 's/^DOMAIN-SUFFIX,/HOST-SUFFIX,/' "$src_clash" \
      | sed -E "s/\$/,$policy/"
  } > "QuantumultX/$dst_qx"
}

convert_self Clash/USSelfv1.list  USSelfv1.list   "US直连"
convert_self Clash/HKSelf.list    HKSelf.list     "HK直连"
convert_self Clash/JPSelf.list    JPSelf.list     "JP直连"
convert_self Clash/ChinaSelf.list ChinaSelf.list  "ChinaSelf"

echo ""
echo "==> Done. Generated files:"
ls -l QuantumultX/USSelfv1.list QuantumultX/HKSelf.list QuantumultX/JPSelf.list QuantumultX/ChinaSelf.list 2>/dev/null || true
echo ""
echo "Review with: git diff --stat QuantumultX/"
echo "If the policy names don't match your QX setup, either adjust here or batch-edit the generated files."