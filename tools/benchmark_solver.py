"""Repeatable local solver samples; bounded heuristics, not an optimality proof.

Compare revisions by saving this JSON and using --solver-source with a trusted
previous search.py. Both runs use the current bundled knowledge data and corpus.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thaum_nexus import KnowledgeBase
from thaum_nexus.data_model import BoardState
from thaum_nexus.resources import plan_resource_usage
from thaum_nexus.solver import search


def sample_boards(kb, generated, seed):
    for path in sorted((ROOT / 'tests/fixtures/boards').glob('*.json')):
        yield BoardState.from_dict(json.loads(path.read_text(encoding='utf-8')))
    rng = random.Random(seed)
    coords = [(q, r) for q in range(-2, 3) for r in range(-2, 3) if abs(q+r) <= 2]
    for index in range(generated):
        roots = dict(zip(rng.sample(coords, 4), rng.choices(sorted(kb.aspects), k=4)))
        cells = [dict(q=q, r=r, kind='root', aspect=roots[q, r]) if (q, r) in roots
                 else dict(q=q, r=r, kind='empty') for q, r in coords]
        yield BoardState.from_dict({'name': f'generated-{index}', 'cells': cells})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated', type=int, default=20)
    parser.add_argument('--seed', type=int, default=30930)
    parser.add_argument('--mode', choices=('minimal', 'inventory'), default='minimal')
    parser.add_argument('--solver-source', type=Path, help='Trusted previous search.py to compare')
    args = parser.parse_args()
    if args.generated < 0:
        parser.error('--generated must be nonnegative')
    solver = search
    if args.solver_source:
        spec = importlib.util.spec_from_file_location('benchmark_previous_solver', args.solver_source)
        solver = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = solver
        spec.loader.exec_module(solver)
    kb = KnowledgeBase.load(ROOT)
    # Sparse inventory deliberately exercises synthesis and missing primal stock.
    inventory = {aspect: (2 if aspect in kb.primal else 0) for aspect in kb.aspects}
    rows = []
    for board in sample_boards(kb, args.generated, args.seed):
        started = time.perf_counter()
        row = {'name': board.name, 'valid': False}
        try:
            solution = solver.solve(board, kb, solver.SearchConfig(
                minimize_placements=args.mode == 'minimal', aspect_inventory=inventory))
            search.validate_solution(board, kb, solution)
            resources = plan_resource_usage(kb, solution.placements.values(), inventory)
            row.update(valid=True, placements=len(solution.placements),
                       shortages=sum(resources.shortages.values()),
                       synthesis_steps=len(resources.synthesis), warnings=list(solution.warnings))
        except (RuntimeError, ValueError) as exc:
            row['error'] = f'{type(exc).__name__}: {exc}'
        row['seconds'] = round(time.perf_counter() - started, 6)
        rows.append(row)
    valid = [row for row in rows if row['valid']]
    print(json.dumps({'seed': args.seed, 'mode': args.mode,
                      'solver_source': str(args.solver_source or 'current'),
                      'scope': 'Deterministic local samples; no global optimality claim.',
                      'summary': {'valid': len(valid), 'failed': len(rows)-len(valid),
                                  'placements': sum(row['placements'] for row in valid),
                                  'shortages': sum(row['shortages'] for row in valid),
                                  'synthesis_steps': sum(row['synthesis_steps'] for row in valid),
                                  'seconds': round(sum(row['seconds'] for row in rows), 6)},
                      'cases': rows}, indent=2))


if __name__ == '__main__':
    main()
