"""Run inherited regression suites and new opportunity/risk/causality tests."""
import argparse,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SUITES=['study/test_deadline.py','study/test_audit.py','risk_study/test_controls.py','ytd_research/test_risk.py','return_search/test_optimize.py','short_search/test_short.py','rebound/test_rebound.py','atr_short/test_atr.py','fast_rs/test_fast_rs.py','portfolio_risk/test_portfolio.py','long_entry/test_long_entry.py','long_family/test_family.py','breadth/test_breadth.py','opportunities/test_opportunities.py']
def main():
    p=argparse.ArgumentParser();p.add_argument('--log',type=Path,required=True);a=p.parse_args()
    commands=[['-m','unittest','discover','-s','tests','-q']]+[[f'research/nfi/{n}'] for n in SUITES]
    with a.log.open('w') as f:
        for c in commands:
            f.write('COMMAND '+repr(c)+'\n');f.flush()
            subprocess.run([str(ROOT/'.venv/bin/python'),*c],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT)},stdout=f,stderr=subprocess.STDOUT,check=True)
if __name__=='__main__':main()
