"""Audit native trigger expressions and disjoint baseline signal-family attribution."""
import ast,hashlib,json,sys
from pathlib import Path
from nfi_analyze import load_result
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/long_family'
sys.path.insert(0,str(ROOT/'research/nfi/long_family'))
from NFIShortLongFamily import signal_family,TREND,DIP

def main():
    source=ROOT/'research/nfi/upstream/NostalgiaForInfinityX8.py';tree=ast.parse(source.read_text());triggers={}
    for node in ast.walk(tree):
        if not isinstance(node,ast.If) or not isinstance(node.test,ast.Compare):continue
        t=node.test
        if ast.unparse(t.left)!='long_entry_condition_index' or len(t.comparators)!=1 or not isinstance(t.comparators[0],ast.Constant):continue
        tag=str(t.comparators[0].value)
        if tag not in TREND|DIP:continue
        calls=[x for x in node.body if isinstance(x,ast.Expr) and isinstance(x.value,ast.Call) and ast.unparse(x.value.func)=='long_entry_logic.append']
        triggers[tag]={'family':signal_family(tag),'branch_line':node.lineno,'last_trigger_expression':ast.unparse(calls[-1].value.args[0])}
    archive=next((ROOT/'results/nfi/long_entry/control').glob('*.zip'));raw=load_result(archive)
    old=json.loads((ROOT/'results/nfi/long_entry/diagnosis.json').read_text());paths={(x['pair'],x['open_date']):x for x in old['campaigns']}
    groups={};records=[]
    for t in raw['trades']:
        if t['is_short']:continue
        family=signal_family(t['enter_tag']);r=paths[(t['pair'],t['open_date'])]
        records.append({'pair':t['pair'],'open_date':t['open_date'],'tag':t['enter_tag'],'family':family,'profit_usdt':t['profit_abs'],'profit_ratio':t['profit_ratio'],'at6h':r['at6h'],'max_sampled_pnl':r['max_sampled_pnl']})
    for family in ['trend','dip','mixed_or_unknown']:
        ts=[t for t in records if t['family']==family];wins=[t for t in ts if t['profit_usdt']>0];loss=[t for t in ts if t['profit_usdt']<0]
        groups[family]={'trades':len(ts),'wins':len(wins),'losses':len(loss),'profit_usdt':sum(t['profit_usdt'] for t in ts),'profit_factor':sum(t['profit_usdt'] for t in wins)/-sum(t['profit_usdt'] for t in loss) if loss else None}
    out={'warning':'Source-semantics hypothesis; not an official NFI taxonomy. Last trigger excludes extensive native protections, so expressions do not fully reproduce entry. Family profit attribution is descriptive, not causal return decomposition. Mixed/unknown unchanged.',
         'upstream_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'baseline_archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'triggers':triggers,'groups':groups,'baseline_campaigns':records}
    (OUT/'source_and_baseline_diagnosis.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(groups,indent=2))
def matched_exits():
    base=load_result(next((OUT/'control').glob('*.zip')))
    original={(t['pair'],t['open_date']):t for t in base['trades']};summary={}
    for name in ['trend_exit','trend_both']:
        native=load_result(next((OUT/name).glob('*.zip')));rows=[]
        for t in native['trades']:
            if t['exit_reason']!='research_long_trend_failure':continue
            old=original.get((t['pair'],t['open_date']))
            rows.append({'pair':t['pair'],'open_date':t['open_date'],'tag':t['enter_tag'],'new_margin_return_pct':100*t['profit_ratio'],'old_margin_return_pct':100*old['profit_ratio'] if old else None,'hours':t['trade_duration']/60,'original_winner':old['profit_abs']>0 if old else None,'new_winner':t['profit_abs']>0})
        summary[name]={'exits':len(rows),'matched_winners':sum(t['original_winner'] is True for t in rows),'winners_turned_into_losses':sum(t['original_winner'] is True and not t['new_winner'] for t in rows),'matched_losers_improved':sum(t['original_winner'] is False and t['new_margin_return_pct']>t['old_margin_return_pct'] for t in rows),'matched_losers_worsened':sum(t['original_winner'] is False and t['new_margin_return_pct']<t['old_margin_return_pct'] for t in rows),'records':rows}
    (OUT/'matched_exit_diagnosis.json').write_text(json.dumps({'warning':'Matched entry diagnostics using actual normalized campaign returns. Shared wallet and sizing change; do not add these differences as causal portfolio contribution.','variants':summary},indent=2)+'\n')
if __name__=='__main__':
    main()
    if list((OUT/'trend_both').glob('*.zip')):matched_exits()
