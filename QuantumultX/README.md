# QuantumultX Rules from ios_rule_script (aggregated)

These are direct copies of key aggregate rules from https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/QuantumultX

## Files
- Global.list : Broad foreign / GFW domains + keywords + UA + IPs (~35k). Use with a "Global" or "🚀 节点选择" policy.
- GlobalMedia.list : Streaming, AI, global video services.
- Mainland.list : Comprehensive China (ChinaMaxNoMedia) for direct.
- China.list : Lighter China direct option.

## QX Usage notes
QX rule lists in this format have the policy name embedded at the end of each line:
  HOST-SUFFIX,google.com,Global
  IP-CIDR,8.8.8.8/32,GlobalMedia

In your QX config (or [filter_remote] / [filter_local] via import), make sure you have matching policies/groups with those names, or batch-replace the policy names to match your setup (e.g. Global -> Proxy, GlobalMedia -> Media).

Example in QX .conf (remote):
; https://raw.githubusercontent.com/blackj-x/ACL4SSR/master/QuantumultX/Global.list

For best results combine with your existing [policy] groups for US / JP / HK / SG nodes, and use "server_check_url" or "resource_parser" as usual.

See the main ACL4SSR_Online_Full_self.ini (Clash side) for routing ideas that can be adapted (e.g. dedicated Bahamut -> TW node, AbemaTV -> JP node, Netflix -> US/JP node).

## Personal "Self" lists (regional direct supplements)
These are small, hand-maintained lists for the maintainer's own needs (Global + the ios aggregates weren't sufficient for certain sites).

- USSelfv1.list : Extra domains routed via US直连 group (e.g. claude.ai, vela).
- HKSelf.list   : Extra domains routed via HK直连 (e.g. okx/okex).
- JPSelf.list   : Extra domains routed via JP直连 (e.g. binance/bitget).
- ChinaSelf.list: Extra domains forced to 全球直连 / direct.

**How to keep in sync:**
- Edit the source of truth under `Clash/USSelfv1.list` (etc.).
- Run: `./Tool/generate_qx_self_lists.sh`
- The script converts `DOMAIN-SUFFIX` → `HOST-SUFFIX,... ,US直连` (and equivalent) and writes to QuantumultX/.

The generated lists use these policy names by default:
  HOST-SUFFIX,claude.ai,US直连
  HOST-SUFFIX,okx.com,HK直连
  ...

If your QX policies have different names (e.g. "🇺🇲 US直连" or "USProxy"), batch replace the trailing part or tweak the generator.

Example in QX .conf:
; https://raw.githubusercontent.com/blackj-x/ACL4SSR/master/QuantumultX/USSelfv1.list
; https://raw.githubusercontent.com/blackj-x/ACL4SSR/master/QuantumultX/HKSelf.list
; https://raw.githubusercontent.com/blackj-x/ACL4SSR/master/QuantumultX/JPSelf.list
; https://raw.githubusercontent.com/blackj-x/ACL4SSR/master/QuantumultX/ChinaSelf.list

Run Tool/sync_from_ios_rule_script.sh periodically for the large aggregates.
Run Tool/generate_qx_self_lists.sh after changing any Clash/*Self.list .

## QX Usage notes (repeated for convenience)
QX rule lists in this format have the policy name embedded at the end of each line:
  HOST-SUFFIX,google.com,Global
  IP-CIDR,8.8.8.8/32,GlobalMedia

In your QX config (or [filter_remote] / [filter_local] via import), make sure you have matching policies/groups with those names, or batch-replace the policy names to match your setup.
