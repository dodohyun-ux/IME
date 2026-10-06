"""Bounded Yen loopless paths on a directed multigraph, preserving edge IDs.

Candidate generation only: optimal MILP results are conditional on this pool.
No straight-line substitute when the graph is disconnected.
"""
from heapq import heappop, heappush
from itertools import count
from collections import defaultdict
import math

from backend.optimization import InputValidationError


def shortest_paths(edges, adjacency, start, end, permitted, weight, k, max_relaxations=2000000):
    serial = count()
    remaining = max_relaxations
    costs, reverse = {}, defaultdict(list)
    for eid,e in edges.items():
        if not permitted(e): continue
        value = weight(e)
        if not math.isfinite(value) or value < 0:
            raise InputValidationError('Road path weights must be finite and nonnegative')
        costs[eid] = value
        reverse[e['to_node']].append(eid)
    # Exact distances in the original permitted graph are admissible/consistent
    # lower bounds after Yen removes root nodes/edges. Reuse them for A* spur
    # searches; this preserves exact k-path ranking, not a geometric shortcut.
    lower = {end: 0.}
    queue = [(0., next(serial), end)]
    while queue:
        value,_,node = heappop(queue)
        if value != lower[node]: continue
        for eid in reverse.get(node, ()):
            remaining -= 1
            if remaining < 0:
                raise InputValidationError('Road candidate search work limit exceeded; reduce area or k')
            target = edges[eid]['from_node']
            new = value + costs[eid]
            if new < lower.get(target,float('inf')):
                lower[target] = new
                heappush(queue,(new,next(serial),target))

    def dijkstra(origin, banned_nodes, banned_edges):
        nonlocal remaining
        if origin not in lower: return None
        queue = [(lower[origin], next(serial), 0., origin)]
        distances = {origin: 0.}
        previous = {}
        while queue:
            _, _, cost, node = heappop(queue)
            if cost != distances[node]:
                continue
            if node == end:
                path = []
                while node != origin:
                    eid = previous[node]
                    path.append(eid)
                    node = edges[eid]['from_node']
                return tuple(reversed(path))
            for eid in adjacency.get(node, ()):
                remaining -= 1
                if remaining < 0:
                    raise InputValidationError('Road candidate search work limit exceeded; reduce area or k')
                e = edges[eid]
                target = e['to_node']
                if eid in banned_edges or target in banned_nodes or eid not in costs or target not in lower:
                    continue
                value = cost + costs[eid]
                if value < distances.get(target, float('inf')):
                    distances[target] = value
                    previous[target] = eid
                    heappush(queue, (value+lower[target], next(serial), value, target))
        return None

    first = dijkstra(start, set(), set())
    if first is None:
        return []
    accepted, pending, seen = [first], [], {first}
    for _ in range(1, k):
        last = accepted[-1]
        nodes = [start] + [edges[e]['to_node'] for e in last]
        for j, node in enumerate(nodes[:-1]):
            root = last[:j]
            banned = {p[j] for p in accepted if len(p) > j and p[:j] == root}
            spur = dijkstra(node, set(nodes[:j]), banned)
            if spur is None:
                continue
            path = root + spur
            if path not in seen:
                seen.add(path)
                heappush(pending, (sum(costs[e] for e in path), path))
        if not pending:
            break
        accepted.append(heappop(pending)[1])
    return accepted
