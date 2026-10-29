"""Summarize only a fully verified YTD snapshot, with explicit current/frozen time."""
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import json
from zoneinfo import ZoneInfo

import nfi_data as old
import nfi_ytd as ytd
from nfi_ytd_verify import blob


def local(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')


def main():
    verified=old.read(ytd.STUDY/'verification.json')
    engine=old.read(ytd.STUDY/'engine_verification.json')
    if verified['status']!='success' or engine['status']!='success':
        raise ValueError('Do not summarize incomplete verification as ready')
    preserved=old.read(ytd.STUDY/'preserved_inputs.json')
    for name,expected in preserved.items():
        if old.sha((ytd.ROOT/name).read_bytes())!=expected:
            raise ValueError(f'Previously frozen input changed:{name}')
    manifest=old.read(ytd.ARCHIVE/'manifest.json')
    if verified['data_manifest_sha256']!=old.sha((ytd.ARCHIVE/'manifest.json').read_bytes()):
        raise ValueError('Verification stale')
    universe=old.read(ytd.STUDY/'universe.json');groups=defaultdict(list)
    for item in manifest['files']:
        groups['mark1h' if item['candle_type']=='mark' else item['timeframe']].append(item)
    coverage=[];index={(x['instrument'],x['candle_type'],x['timeframe']):x for x in manifest['files']}
    evaluation=old.millis(universe['evaluation_start'])
    for pair in universe['pairs']:
        daily=index[pair['instrument'],'futures','1d']
        rows=json.loads(gzip.decompress(blob(daily)))
        before=sum(int(r[0])+86400000<=evaluation for r in rows)
        coverage.append({'instrument':pair['instrument'],'pair':pair['pair'],
                         'daily_bars_before_evaluation':before,
                         'daily_first_open':old.iso(int(rows[0][0])),
                         '200_daily_available':old.iso(int(rows[199][0])+86400000) if len(rows)>=200 else None,
                         '480_daily_available':old.iso(int(rows[479][0])+86400000) if len(rows)>=480 else None})
    old.write(ytd.STUDY/'coverage.json',{'evaluation_start':universe['evaluation_start'],'pairs':coverage,
                                       'warning':'Indicator-specific readiness is not proven by candle count alone'})
    bundles=old.read(ytd.ARCHIVE/'bundles.json')['files']
    for item in bundles:
        packed=(ytd.ARCHIVE/item['file']).read_bytes()
        if len(packed)!=item['bytes'] or old.sha(packed)!=item['sha256']:
            raise ValueError('Bundle size/hash mismatch')
    text=f'''# 推荐57币：2026年初至今数据完成记录

保持现有推荐57币，不扩大或重新筛选币种。现有100币池及四个月研究全部保留，旧数据清单、币池与上游源码哈希未改变。

按既有UTC年界，评价从2026-01-01 00:00 UTC（北京时间{local(universe['evaluation_start'])}）开始。冻结截止为北京时间**{local(universe['end_exclusive'])}**，只包含截止前已经闭合的K线；不是声称完成了尚未发生的11–12月。

## 数据规模

| 原生数据 | 文件数 | 总K线数（含预热） | 最早数据北京时间 | 闭合边界北京时间 |
|---|---:|---:|---|---|
'''
    for tf in ytd.BARS:
        items=groups[tf]
        text+=f"| {tf} | {len(items)} | {sum(x['rows'] for x in items):,} | {local(min(x['start'] for x in items))} | {local(items[0]['end_exclusive'])} |\n"
    text+=f'''
共{len(manifest['files'])}份文件，交易行情{verified['ohlcv_rows']:,}根、真实标记价格{verified['mark_rows']:,}根。指标预热最早2024年，不使用2024年前行情。当前57币在年初前均有至少480根闭合日线（逐币实际计数见coverage.json）；不同指标的就绪条件仍须遵循原策略。

## 实际通过的检查

- 全部342份数据按时间戳、长度、价格、成交量、闭合状态逐行验证；未补造缺口或上市前数据。
- 校验原始gzip与解压内容的SHA256，复用的旧数据也验证来源哈希。
- {verified['checked_higher_bars']:,}根完整高周期K线对照原生5m聚合，核对价格和成交量；保留原生零成交K线的正确处理。
- Freqtrade2026.9逐一读取{engine['datasets']['futures']}份永续行情和{engine['datasets']['mark']}份标记价格，行数、起点与终点均匹配。
- 确定性ZIP按币种打包，共{len(bundles)}份、{sum(x['bytes'] for x in bundles):,}字节，并再次核对ZIP哈希。
- 旧币池、旧行情/标记价格/ZIP清单、旧配置与固定上游源码的保留哈希逐项核对通过。

## 使用与限制

数据归档位于datasets/nfi_ytd2026，Freqtrade数据目录为data/nfi_ytd2026/freqtrade。配置为research/nfi/ytd2026/config.backtest.json，后续回测继续使用NFI24Hour，首次入场起24小时上限，加仓不重置。

**本次完成的是扩充、校验与引擎读取，没有据此宣称已跑完全年策略回测或得到全年盈利结论。** 当前币池投射到年初仍有事后选币/存活者偏差，固定策略版本晚于部分历史，扩展历史不自动成为独立OOS；真实资金费按原约定仍未下载。低周期最新截止与高周期闭合边界不同，严格避免未闭合高周期数据。

复现命令：

```sh
python nfi_ytd.py download
python nfi_ytd_verify.py
.venv/bin/python nfi_ytd_engine_verify.py
python nfi_ytd_report.py
```

下载支持SQLite断点，并复用原四个月的已验证原生数据。固定窗口不会随运行日期偷偷滚动；下次更新需建立新版本清单，保留当前快照。没有下单、账户凭据、推送或环境发布。
'''
    (ytd.STUDY/'SUMMARY.md').write_text(text,encoding='utf-8')
    old.write(ytd.STUDY/'completion.json',{'status':'success','completed_at':datetime.now(timezone.utc).isoformat(),
              'pairs':len(universe['pairs']),'files':len(manifest['files']),'end_exclusive':universe['end_exclusive'],
              'verification':verified,'engine':engine,'preserved_inputs_unchanged':True})
    print('YTD data complete, native/engine/bundle verification passed; full-strategy backtest not claimed')


if __name__=='__main__':main()
