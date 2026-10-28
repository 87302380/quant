"""Map pinned X8 source using AST without importing/executing its strategy."""
import ast
from nfi_data import STUDY, read, write


def main():
    path=STUDY/'upstream/NostalgiaForInfinityX8.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NostalgiaForInfinityX8')
    constants={};methods=[]
    for node in cls.body:
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            names=node.targets if isinstance(node,ast.Assign) else [node.target]
            try:value=ast.literal_eval(node.value)
            except (ValueError,TypeError):continue
            for name in names:
                if isinstance(name,ast.Name):constants[name.id]=value
        elif isinstance(node,ast.FunctionDef):
            methods.append(dict(name=node.name,line=node.lineno,end_line=node.end_lineno))
    modes={k:v for k,v in constants.items() if k.endswith('_mode_tags') and isinstance(v,list)}
    settings={k:constants[k] for k in ('timeframe','info_timeframes','btc_info_timeframes','startup_candle_count',
              'stoploss','use_custom_stoploss','position_adjustment_enable','grinding_enable','derisk_enable',
              'futures_mode_leverage','futures_mode_leverage_rebuy_mode','futures_mode_leverage_grind_mode') if k in constants}
    result=dict(upstream=read(STUDY/'source_manifest.json'),settings=settings,mode_tags=modes,methods=methods,
                caveats=['Class defaults only; __init__ sets OKX startup_candle_count=480 and futures can_short=True.',
                         'Defined mode tags do not imply enabled entries; inspect config and populate_entry_trend.',
                         'Static source inventory is not proof of correctness or profitability.'])
    write(STUDY/'strategy_inventory.json',result)
    for item in methods:
        if item['name'] in ('informative_pairs','populate_indicators','populate_entry_trend','custom_stake_amount',
                            'adjust_trade_position','custom_exit','leverage','confirm_trade_entry'):
            print(item)
    print('Saved strategy_inventory.json (no strategy code executed)')


if __name__=='__main__':main()
