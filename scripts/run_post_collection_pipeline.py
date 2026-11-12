"""Post-Collection Pipeline Orchestrator for APT WATCH 8th Directive.
Runs all analytical audits, calculates asking adjustments, price divergence matching,
representativeness checks, regenerates data.json, and produces the complete report.
"""
import subprocess
import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def run_step(name, script_path, args=None):
    cmd = [sys.executable, str(script_path)] + (args or [])
    print(f"\n>>> Running: {name} ({script_path.name})")
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    elapsed = time.time() - t0
    if res.returncode != 0:
        print(f"FAILED {name} in {elapsed:.2f}s:\n{res.stderr}\n{res.stdout}")
        raise RuntimeError(f"Step {name} failed")
    print(f"COMPLETED {name} in {elapsed:.2f}s")
    if res.stdout:
        print(res.stdout.strip())
    return res.stdout

def main():
    print("="*80)
    print("STARTING APT WATCH POST-COLLECTION PIPELINE")
    print("="*80)
    
    # 1. Consecutive Observation & Asking Adjustment
    run_step("1. Consecutive Observation Analysis", ROOT / 'scripts' / 'analyze_consecutive_observation.py')
    
    # 2. Expanded Price Divergence Matching
    run_step("2. Price Divergence Matching Waterfall", ROOT / 'scripts' / 'audit_price_divergence_expanded.py')
    
    # 3. Representativeness Audit
    run_step("3. Sample Representativeness Audit", ROOT / 'scripts' / 'audit_representativeness.py')
    
    # 4. Daily Operational Audit Log
    run_step("4. Daily Audit Log Generation", ROOT / 'scripts' / 'generate_daily_audit_log.py')
    
    # 5. Pipeline rebuild (apt_watch and nego_pressure)
    run_step("5. Rebuild apt_watch", ROOT / 'apt_watch.py')
    run_step("6. Rebuild nego_pressure", ROOT / 'nego_pressure.py')
    
    # 7. Run Unit Tests
    cmd = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']
    print(f"\n>>> Running: 7. Full Test Suite Verification")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr)
        raise RuntimeError("Unit tests failed")

    print("\nALL POST-COLLECTION PIPELINE STEPS COMPLETED SUCCESSFULLY!")

if __name__ == '__main__':
    main()
