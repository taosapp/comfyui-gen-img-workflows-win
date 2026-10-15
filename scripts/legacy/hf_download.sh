#!/usr/bin/env bash
# 分块并行下载 + 断点续传 + SHA256 校验。
# 用途：国内从 hf-mirror 拉大模型文件时，单连接容易中途停滞；本脚本用多个 curl 分块并行，
#       并靠 --speed-limit 自动掐掉停滞的连接重连。
#
# 用法: bash hf_download.sh <URL> <输出文件> [线程数=8] [期望SHA256]
#
# 注意：走 hf-mirror 时不要用 Python 的 urllib —— 它拿 resolve 重定向时会走 CDN，
#       而 CDN 对非 curl 的 TLS/HEAD 请求会拒绝或重置。curl 是可靠的。
set -u

URL="${1:?用法: hf_download.sh URL OUT [线程数] [SHA256]}"
OUT="${2:?缺少输出路径}"
N="${3:-8}"
SHA="${4:-}"

# 走不走代理由 PROXY 环境变量决定。国内直连 hf-mirror 时 302 会跳到 cas-bridge.xethub.hf.co（被墙，0 字节），
# 经代理则会跳到 us.aws.cdn.hf.co（可用）。所以拉 HF 大文件一律建议带上代理。
if [ -n "${PROXY:-}" ]; then
  NET=(-x "$PROXY")
  echo "使用代理 $PROXY"
else
  NET=(--noproxy '*')
fi

HDRS=$(curl -sIL "${NET[@]}" -m 60 "$URL" | tr -d '\r')
SZ=$(printf '%s\n' "$HDRS" | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')
if [ -z "${SZ:-}" ] || [ "$SZ" -le 0 ] 2>/dev/null; then
  echo "!! 无法获取文件大小"; exit 2
fi
echo "文件 $(( SZ / 1048576 )) MB，线程 $N"

PARTDIR="$OUT.parts"
mkdir -p "$PARTDIR"
CH=$(( SZ / N ))

idx=0
while [ $idx -lt $N ]; do
  s=$(( idx * CH ))
  if [ $idx -eq $(( N - 1 )) ]; then e=$(( SZ - 1 )); else e=$(( (idx + 1) * CH - 1 )); fi
  p="$PARTDIR/part$(printf '%02d' $idx)"
  (
    want=$(( e - s + 1 ))
    for attempt in $(seq 1 60); do
      have=0
      [ -f "$p" ] && have=$(stat -c %s "$p" 2>/dev/null || echo 0)
      [ "$have" -ge "$want" ] && exit 0
      need=$(( e - s - have + 1 ))
      tmp="$p.tmp"
      # 关键：必须校验响应码是 206 且长度合理，绝不把错误响应体追加进分块，否则总大小对得上但内容是坏的
      code=$(curl -sL "${NET[@]}" -f --speed-limit 30000 --speed-time 20 -m 900 \
             -r "$(( s + have ))-$e" -o "$tmp" -w '%{http_code}' "$URL" 2>/dev/null || echo 000)
      sz=$(stat -c %s "$tmp" 2>/dev/null || echo 0)
      if [ "$code" = "206" ] && [ "$sz" -gt 0 ] && [ "$sz" -le "$need" ]; then
        cat "$tmp" >> "$p"
      fi
    done
    have=$(stat -c %s "$p" 2>/dev/null || echo 0)
    [ "$have" -ge "$want" ] || echo "!! part$idx 未取完：$have/$want"
  ) &
  idx=$(( idx + 1 ))
done

echo "分块下载中（约每 20 秒报一次进度）..."
tick=0
while :; do
  sleep 20
  tot=0
  for f in "$PARTDIR"/part*; do
    [ -f "$f" ] && tot=$(( tot + $(stat -c %s "$f" 2>/dev/null || echo 0) ))
  done
  printf '  %6.1f / %6.1f MB\n' "$(awk "BEGIN{print $tot/1048576}")" "$(awk "BEGIN{print $SZ/1048576}")"
  [ "$tot" -ge "$SZ" ] && break
  tick=$(( tick + 1 ))
  if [ "$tick" -ge 180 ]; then echo "!! 等待超时（60 分钟）"; break; fi
done

wait
echo "合并 ..."
# 只合并 part00~partNN 本体；partNN.tmp 是 curl 的中间落盘文件，绝不能混进来（否则体积翻倍、内容错乱）
: > "$OUT"
for f in "$PARTDIR"/part[0-9][0-9]; do cat "$f" >> "$OUT"; done
GOT=$(stat -c %s "$OUT")
echo "完成 $(( GOT / 1048576 )) MB（期望 $(( SZ / 1048576 )) MB）"
if [ "$GOT" != "$SZ" ]; then echo "!! 大小不符"; exit 4; fi

if [ -n "$SHA" ]; then
  A=$(sha256sum "$OUT" | awk '{print $1}')
  if [ "$A" = "$SHA" ]; then echo "SHA256 校验通过"; else echo "!! SHA256 不符: $A"; exit 5; fi
fi

rm -f "$PARTDIR"/part*
rmdir "$PARTDIR" 2>/dev/null
echo "OK"
