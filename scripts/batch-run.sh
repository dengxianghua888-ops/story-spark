#!/usr/bin/env bash
# batch-run.sh -- 批量驱动短篇仿写产线
#
# 场景 A:对 corpus/ 下的 pending 案例批跑 Phase 1 (建 few-shot 库)
# 场景 B:对 stories/ 下的多个项目批跑完整产线 (Phase 1-5)
#
# 用法:
#   # 对 corpus/ 下所有 pending 案例跑 Phase 1
#   ./scripts/batch-run.sh --mode corpus-phase1
#
#   # 对指定 story 列表跑完整产线
#   ./scripts/batch-run.sh --mode stories-full --stories stories/a stories/b
#
#   # Dry-run 预览
#   ./scripts/batch-run.sh --mode corpus-phase1 --dry-run
#
# 说明:
#   - 产线由 scripts/storyforge.py 主控, 本脚本为逐个案例触发 Python 状态机
#   - 每个案例跑完后会打印摘要,失败不中断后续案例(记录进 batch.log)
#   - 跑完 corpus phase 1 后,自动调用 update-corpus-index.py 更新索引

set -euo pipefail

MODE=""
DRY_RUN=false
STORIES=()
COUNT=10
SEED=""
RUNNER="manual-prompt-pack"
RUBRIC_THRESHOLD="8.0"
NO_RUBRIC=false
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORPUS_DIR="$ROOT/corpus"
MANIFEST="$CORPUS_DIR/_manifest.tsv"

while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)     MODE="$2"; shift 2 ;;
        --stories)  shift; while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do STORIES+=("$1"); shift; done ;;
        --count)    COUNT="$2"; shift 2 ;;
        --seed)     SEED="$2"; shift 2 ;;
        --runner)   RUNNER="$2"; shift 2 ;;
        --rubric-threshold) RUBRIC_THRESHOLD="$2"; shift 2 ;;
        --no-rubric) NO_RUBRIC=true; shift ;;
        --dry-run)  DRY_RUN=true; shift ;;
        -h|--help)
            echo "用法:"
            echo "  $0 --mode corpus-phase1 [--dry-run]"
            echo "  $0 --mode stories-full --stories <path1> [<path2> ...] [--dry-run]"
            echo "  $0 --mode random-batch --count N [--seed S] [--runner R] [--rubric-threshold 8.0] [--no-rubric] [--dry-run]"
            exit 0 ;;
        *)  echo "未知参数: $1" >&2; exit 10 ;;
    esac
done

if [[ -z "$MODE" ]]; then
    echo "错误: 必须指定 --mode (corpus-phase1 | stories-full | random-batch)" >&2
    exit 10
fi

BATCH_LOG="$ROOT/batch.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] [$1] $2" | tee -a "$BATCH_LOG"; }

# ---------- 场景 A: corpus phase1 ----------
run_corpus_phase1() {
    if [[ ! -f "$MANIFEST" ]]; then
        log "ERROR" "manifest 不存在: $MANIFEST, 先跑 build-corpus.sh"
        exit 11
    fi

    # 跳过表头
    local total=0 run=0 skipped=0
    while IFS=$'\t' read -r slug filename wc status; do
        [[ "$slug" == "slug" ]] && continue
        total=$((total + 1))

        local story_dir="$CORPUS_DIR/$slug"
        if [[ -f "$story_dir/dissection.md" ]]; then
            log "INFO" "跳过 $slug (已有 dissection.md)"
            skipped=$((skipped + 1))
            continue
        fi

        log "INFO" "处理 $slug ($filename, $wc 字)"

        if $DRY_RUN; then
            log "INFO" "  [DRY] 将运行: storyforge.py run --story $story_dir --from-phase 1 --to-phase 1 --runner $RUNNER"
        else
            if python3 "$ROOT/scripts/storyforge.py" run --story "$story_dir" --from-phase 1 --to-phase 1 --runner "$RUNNER" 2>&1 | tee -a "$BATCH_LOG"; then
                run=$((run + 1))
            else
                log "ERROR" "  $slug Phase 1 失败, 继续下一个"
            fi
        fi
    done < "$MANIFEST"

    log "INFO" "batch 完成: 总 $total / 跑 $run / 跳过 $skipped"

    # 跑完后刷新索引
    if ! $DRY_RUN && command -v python3 >/dev/null 2>&1; then
        log "INFO" "刷新 corpus/_index.json..."
        python3 "$ROOT/scripts/update-corpus-index.py" 2>&1 | tee -a "$BATCH_LOG"
    fi
}

# ---------- 场景 B: 多个 stories 的完整产线 ----------
run_stories_full() {
    if [[ ${#STORIES[@]} -eq 0 ]]; then
        log "ERROR" "必须用 --stories 指定至少一个 story 路径"
        exit 10
    fi

    local total=${#STORIES[@]}
    local ok=0 fail=0
    for st in "${STORIES[@]}"; do
        log "INFO" "处理 $st"
        if $DRY_RUN; then
            log "INFO" "  [DRY] 将运行: storyforge.py run --story $st --runner manual-prompt-pack"
        else
            if python3 "$ROOT/scripts/storyforge.py" run --story "$st" --runner manual-prompt-pack 2>&1 | tee -a "$BATCH_LOG"; then
                ok=$((ok + 1))
            else
                fail=$((fail + 1))
                log "ERROR" "  $st 失败, 继续"
            fi
        fi
    done

    log "INFO" "batch 完成: $ok/$total 成功, $fail 失败"
}

# ---------- 场景 C: 随机批量仿写 ----------
run_random_batch() {
    local picker_args=("--count" "$COUNT" "--json")
    if [[ -n "$SEED" ]]; then
        picker_args+=("--seed" "$SEED")
    fi

    if $DRY_RUN; then
        log "INFO" "[DRY] 将运行: corpus-picker.py ${picker_args[*]}"
        return 0
    fi

    local pick_json
    pick_json="$(python3 "$ROOT/scripts/corpus-picker.py" "${picker_args[@]}")"
    if [[ -z "$pick_json" ]]; then
        log "ERROR" "corpus-picker 没产出"
        exit 12
    fi

    local stories=()
    while IFS= read -r line; do
        stories+=("$line")
    done < <(python3 -c "import sys,json;d=json.loads(sys.stdin.read());[print(s) for s in d['stories']]" <<<"$pick_json")

    log "INFO" "随机选样 ${#stories[@]} 篇"
    local rubric_args=()
    if [[ "$NO_RUBRIC" == "true" ]]; then
        rubric_args+=(--skip-rubric)
    else
        rubric_args+=(--rubric-threshold "$RUBRIC_THRESHOLD")
    fi
    case "$RUNNER" in
        agent|codex|openclaw|claude)
            local preflight_status=0
            python3 - "$ROOT" "$RUNNER" "${#rubric_args[@]}" "${rubric_args[@]}" "${stories[@]}" <<'PY' 2>&1 | tee -a "$BATCH_LOG" || preflight_status=$?
import shlex
import sys
from pathlib import Path

root = Path(sys.argv[1])
runner = sys.argv[2]
rubric_count = int(sys.argv[3])
rubric_args = sys.argv[4:4 + rubric_count]
stories = [Path(value) for value in sys.argv[4 + rubric_count:]]
sys.path.insert(0, str(root / "scripts"))
from storyforge import story_source_access

denied = [story for story in stories if story_source_access(story) == "denied"]
if denied:
    print("等待人工批准原文访问; 本批次未启动任何 runner, 未生成质量完成报告。")
    for story in stories:
        print(f"固定选中故事: {story}")
    for story in denied:
        print(f"待批准 (source_policy.access=denied): {story}")
    print("请先人工核查并批准待批故事; 批准后对固定路径逐个运行以下命令, 不要重新随机选样:")
    for story in stories:
        print(shlex.join(["python3", str(root / "scripts/storyforge.py"), "run",
                          "--story", str(story), "--runner", runner, "--mode", "production", *rubric_args]))
    sys.exit(30)
PY
            if [[ "$preflight_status" -ne 0 ]]; then
                return "$preflight_status"
            fi
            ;;
    esac

    local ok=0 fail=0
    for st in "${stories[@]}"; do
        log "INFO" "处理 $st (runner=$RUNNER)"
        local sf_args=(run --story "$st" --runner "$RUNNER" --mode production --no-human-gates "${rubric_args[@]}")
        if python3 "$ROOT/scripts/storyforge.py" "${sf_args[@]}" 2>&1 | tee -a "$BATCH_LOG"; then
            ok=$((ok + 1))
        else
            fail=$((fail + 1))
            log "WARN" "  $st 未通过完整链路, 继续"
        fi
    done

    log "INFO" "汇总批次报告"
    python3 "$ROOT/scripts/batch-quality-report.py" --stories "${stories[@]}" \
        --title "Random Batch ${COUNT} (runner=${RUNNER})" 2>&1 | tee -a "$BATCH_LOG"

    log "INFO" "random-batch 完成: $ok/${#stories[@]} 通过"
}

# ---------- 主流程 ----------
log "INFO" "batch-run 启动, mode=$MODE, dry-run=$DRY_RUN"

case "$MODE" in
    corpus-phase1)  run_corpus_phase1 ;;
    stories-full)   run_stories_full ;;
    random-batch)   run_random_batch ;;
    *)  log "ERROR" "未知 mode: $MODE"; exit 10 ;;
esac

log "INFO" "batch-run 结束"
