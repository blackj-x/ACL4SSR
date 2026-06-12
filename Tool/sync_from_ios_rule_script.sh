#!/bin/zsh
# sync_from_ios_rule_script.sh
# 用于从 https://github.com/blackmatrix7/ios_rule_script 同步聚合规则到本项目
# 目标：保持 Global / GlobalMedia / Mainland (ChinaMaxNoMedia) 等集中文件最新
# 用法：./Tool/sync_from_ios_rule_script.sh
# 之后 git diff / commit 审查变更

set -e

BASE="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule"
DATE=$(date '+%Y-%m-%d')

echo "==> Syncing key aggregates from ios_rule_script ($DATE)"

# Clash
mkdir -p Clash

echo "-> Global.list"
curl -sL "$BASE/Clash/Global/Global.list" > /tmp/Global.list
echo "# NAME: Global (Aggregated from ios_rule_script for ACL4SSR self)
# SOURCE: https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Clash/Global
# NOTE: Updated periodically from upstream for fresher rules. Review diffs before use.
# SYNC: $DATE
" | cat - /tmp/Global.list > Clash/Global.list

echo "-> GlobalMedia.list"
curl -sL "$BASE/Clash/GlobalMedia/GlobalMedia.list" > /tmp/GlobalMedia.list
echo "# NAME: GlobalMedia (Aggregated from ios_rule_script for ACL4SSR self)
# SOURCE: https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Clash/GlobalMedia
# NOTE: Global streaming / AI / etc. Route via good nodes (US/JP/HK/SG split as needed).
# SYNC: $DATE
" | cat - /tmp/GlobalMedia.list > Clash/GlobalMedia.list

echo "-> Mainland.list (ChinaMaxNoMedia - large but comprehensive CN direct)"
curl -sL "$BASE/Clash/ChinaMaxNoMedia/ChinaMaxNoMedia.list" > /tmp/Mainland.list
echo "# NAME: Mainland (from ChinaMaxNoMedia, Aggregated from ios_rule_script for ACL4SSR self)
# SOURCE: https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Clash/ChinaMaxNoMedia
# NOTE: Very large (~125k lines). Use for thorough CN direct. Alternative: China.list (smaller).
# SYNC: $DATE
" | cat - /tmp/Mainland.list > Clash/Mainland.list

echo "-> China.list (lighter Mainland option)"
curl -sL "$BASE/Clash/China/China.list" > /tmp/China.list
echo "# NAME: China (lighter, Aggregated from ios_rule_script)
# SOURCE: https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Clash/China
# SYNC: $DATE
" | cat - /tmp/China.list > Clash/China.list

# Optional region/geo media (small, good for split)
for svc in Bahamut AbemaTV ViuTV HuluJP USMedia Netflix; do
  echo "-> $svc.list (region specific)"
  curl -sL "$BASE/Clash/$svc/$svc.list" > /tmp/$svc.list
  echo "# NAME: $svc (from ios_rule_script, for regional split)
# SOURCE: https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Clash/$svc
# SYNC: $DATE
" | cat - /tmp/$svc.list > Clash/$svc.list
done

# QuantumultX
echo "==> QuantumultX side"
mkdir -p QuantumultX

echo "-> QX Global.list"
curl -sL "$BASE/QuantumultX/Global/Global.list" > /tmp/qxglobal.list
echo "# NAME: Global (QX format, Aggregated from ios_rule_script)
# SOURCE: https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/QuantumultX/Global
# NOTE: Lines end with ,PolicyName (e.g. ,Global). Adjust to your QX policy names.
# SYNC: $DATE
" | cat - /tmp/qxglobal.list > QuantumultX/Global.list

echo "-> QX GlobalMedia.list"
curl -sL "$BASE/QuantumultX/GlobalMedia/GlobalMedia.list" > /tmp/qxgm.list
echo "# NAME: GlobalMedia (QX format)
# SOURCE: https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/QuantumultX/GlobalMedia
# SYNC: $DATE
" | cat - /tmp/qxgm.list > QuantumultX/GlobalMedia.list

echo "-> QX Mainland.list (ChinaMaxNoMedia) + China.list"
curl -sL "$BASE/QuantumultX/ChinaMaxNoMedia/ChinaMaxNoMedia.list" > /tmp/qxmain.list
echo "# NAME: Mainland (QX, from ChinaMaxNoMedia)
# SOURCE: https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/QuantumultX/ChinaMaxNoMedia
# SYNC: $DATE
" | cat - /tmp/qxmain.list > QuantumultX/Mainland.list

curl -sL "$BASE/QuantumultX/China/China.list" > /tmp/qxchina.list
echo "# NAME: China (QX lighter)
# SOURCE: https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/QuantumultX/China
# SYNC: $DATE
" | cat - /tmp/qxchina.list > QuantumultX/China.list

echo "==> Done. Review with: git diff --stat Clash/ QuantumultX/"
echo "    Then commit the updates to your fork for self use."
echo "Tip: Mainland files are large; consider using China.list in ini for lighter setups."