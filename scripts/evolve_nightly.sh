#!/bin/bash
# 每晚自主进化：转换当日 traecli 会话 → evolve import（2026-11-13 起）
# 证据源：当日 traecli 会话（含 bot 会话）+ 当日直播档案 + 当日推送
# 手工确认铁律不适用 cron：apply 永不自动执行，仅 import（只上传证据）
set -euo pipefail
ROOT=/home/zxh/projects/14.fupange
SESSION_BASE=/home/zxh/.trae/cli/sessions
OUT=/tmp/evolve_sessions/$(date +%Y%m%d)
mkdir -p "$OUT"

# 转换器：traecli rollout JSONL → evolve 兼容 JSONL（user/assistant 轮次，滤环境噪声）
convert() {
python3 - "$1" "$2" <<'PYEOF'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
turns=[]
for line in open(src, errors='ignore'):
    try: rec=json.loads(line)
    except: continue
    if rec.get('type')!='history_mutation': continue
    for item in rec['payload'].get('items',[]):
        if item.get('type')!='message': continue
        role=item.get('role')
        if role not in ('user','assistant'): continue
        blocks=item.get('content',[])
        if isinstance(blocks,str): blocks=[{'type':'text','text':blocks}]
        for b in blocks:
            t=b.get('type'); txt=b.get('text','')
            if t in ('text','input_text','output_text') and txt:
                s=txt.strip()
                if s.startswith(('<system-reminder','# AGENTS.md instructions','<environment_context>','<skill>','You are a coding agent','# Environment','The following is the TRAE agent history')):
                    continue
                turns.append({'role':role,'text':txt[:1500]})
            if len(turns)>=60: break
        if len(turns)>=60: break
    if len(turns)>=60: break
if not turns: sys.exit(1)
with open(dst,'w') as f:
    for t in turns:
        f.write(json.dumps({'type':t['role'],'message':{'role':t['role'],'content':[{'type':'text','text':t['text']}]}}, ensure_ascii=False)+'\n')
PYEOF
}

# 1) 当日 traecli 会话 → 转换目录（当日无会话目录时回退最近一天）
D=$(date +%Y/%m/%d)
[ -d "$SESSION_BASE/$D" ] || D="2026/$(cd "$SESSION_BASE/2026" && find . -mindepth 2 -maxdepth 2 -type d | sort -r | head -1 | sed 's|^\./||')"
n=0
for f in $(ls -t "$SESSION_BASE/$D"/*.jsonl 2>/dev/null | grep -v lock || true); do
    base=$(basename "$f" .jsonl)
    if convert "$f" "$OUT/${base}.jsonl"; then n=$((n+1)); fi
    [ "$n" -ge 10 ] && break
done
echo "converted sessions: $n" >> "$ROOT/直播智能体/runtime/logs/evolve_nightly.log"

# 2) 直播档案 + 推送 → 转成伪会话（assistant 角色承载当日全部直播内容与推送）
TODAY=$(date +%Y%m%d)
ARCHIVE="$ROOT/直播智能体/runtime/messages/${TODAY}.jsonl"
PUSH="$ROOT/直播智能体/runtime/pushes/${TODAY}.jsonl"
[ -f "$ARCHIVE" ] && python3 - "$ARCHIVE" "$OUT/${TODAY}_live_archive.jsonl" <<'PYEOF'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
out=open(dst,'w')
buf=[]
for line in open(src, errors='ignore'):
    m=json.loads(line)
    buf.append(m.get('text',''))
text='\n\n'.join(buf)[:120000]
out.write(json.dumps({'type':'assistant','message':{'role':'assistant','content':[{'type':'text','text':'当日直播原文档案（主讲人全天观点，供情绪周期/题材分析）：\n'+text}]}}, ensure_ascii=False)+'\n')
out.close()
PYEOF
[ -f "$PUSH" ] && python3 - "$PUSH" "$OUT/${TODAY}_pushes.jsonl" <<'PYEOF'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
out=open(dst,'w')
buf=[]
for line in open(src, errors='ignore'):
    try: p=json.loads(line)
    except: continue
    buf.append(str(p.get('content') or p))
text='\n\n'.join(buf)[:60000]
out.write(json.dumps({'type':'assistant','message':{'role':'assistant','content':[{'type':'text','text':'当日盯盘智能体推送成品（盘中提炼与判断）：\n'+text}]}}, ensure_ascii=False)+'\n')
out.close()
PYEOF

# 3) 双 agent 导入（2026-11-13 起：本机三个连接器需显式消歧）
#    trae → fupange 根 agent（bot 路由大脑，evidence=当日全部会话）
#    openclaw → 直播智能体 agent（evidence=编辑任务会话 + 直播档案 + 推送成品）
source ~/.evolve-skill.env
cd "$ROOT"

# 3a) 根 agent（trae）：除编辑任务外的全部会话
export EVOLVE_CONNECTOR=trae
export EVOLVE_RUNTIME_ROOT="$ROOT"
mkdir -p "$OUT/editor"
for f in "$OUT"/*.jsonl; do
    base=$(basename "$f")
    [ "$base" = "${TODAY}_live_archive.jsonl" ] && continue
    [ "$base" = "${TODAY}_pushes.jsonl" ] && continue
    if grep -q "直播盯盘推送编辑" "$f" 2>/dev/null; then
        mv "$f" "$OUT/editor/$base"
    fi
done
cp "$OUT/${TODAY}_live_archive.jsonl" "$OUT/editor/" 2>/dev/null || true
cp "$OUT/${TODAY}_pushes.jsonl" "$OUT/editor/" 2>/dev/null || true
python3 -m evolve_cli import --from "$OUT" --limit 10 --no-wait 2>&1 | tee -a "$ROOT/直播智能体/runtime/logs/evolve_nightly.log"

# 3b) 直播智能体 agent（openclaw）：编辑任务会话 + 直播档案 + 推送成品
export EVOLVE_CONNECTOR=openclaw
export EVOLVE_RUNTIME_ROOT="$ROOT/直播智能体"
mkdir -p "$OUT/editor"
[ -d "$OUT/editor" ] && python3 -m evolve_cli import --from "$OUT/editor" --limit 10 --no-wait 2>&1 | tee -a "$ROOT/直播智能体/runtime/logs/evolve_nightly.log"
