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
; https://raw.githubusercontent.com/gouzhiyuan/ACL4SSR/master/QuantumultX/Global.list

For best results combine with your existing [policy] groups for US / JP / HK / SG nodes, and use "server_check_url" or "resource_parser" as usual.

See the main ACL4SSR_Online_Full_self.ini (Clash side) for routing ideas that can be adapted (e.g. dedicated Bahamut -> TW node, AbemaTV -> JP node, Netflix -> US/JP node).

Run Tool/sync_from_ios_rule_script.sh (from repo root) periodically to refresh these.
