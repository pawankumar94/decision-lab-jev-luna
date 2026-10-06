"""Deterministic warehouse simulator with real, traceable Jev action selection.

The model sees symbolic text state, never an image. No physical robot is involved.
"""
import argparse
import collections
import hashlib
import json
from client import JevClient, ROOT, key_from_prompt

DIRS = {"move_north": (0, -1), "move_east": (1, 0), "move_south": (0, 1), "move_west": (-1, 0)}
WORLD_INSTRUCTIONS = (
    "You control a simulated warehouse robot carrying one package. Choose one next action "
    "to reach the current delivery destination with as few actions as possible. "
    "Obey the package and aisle restrictions. Use the whole known map to navigate around barriers. "
    "Do not repeatedly reverse direction or wait when a valid route exists. "
    "Select finish only when at the current delivery destination. Coordinates: x increases east, y increases south. "
    "New door/destination updates in the current state override earlier states."
)


def rotate(pos, turns):
    x, y = pos
    for _ in range(turns):
        x, y = 6 - y, x
    return [x, y]


def prepare():
    directory = ROOT / "world"
    directory.mkdir(exist_ok=True)
    episodes = []
    for family in ["open_aisles", "barrier_detour", "fragile_cargo", "door_closure"]:
        for orientation in range(3):
            walls, rough, event = [], [], None
            if family == "open_aisles":
                walls = [[2, 1], [2, 2], [4, 4], [4, 5]]
            elif family == "barrier_detour":
                walls = [[3, y] for y in range(1, 6)]
            elif family == "fragile_cargo":
                walls = [[2, 1], [2, 5], [4, 1], [4, 5]]
                rough = [[x, 3] for x in range(2, 5)]
            else:
                walls = [[3, y] for y in [1, 2, 4, 5, 6]]
                event = {"at_action": 2, "close_cell": rotate([3, 3], orientation)}
            episodes.append({
                "id": f"{family}-{orientation}", "family": family, "orientation": orientation,
                "size": 7, "start": rotate([0, 3], orientation), "goal": rotate([6, 3], orientation),
                "walls": [rotate(p, orientation) for p in walls], "rough": [rotate(p, orientation) for p in rough],
                "cargo": "fragile" if family == "fragile_cargo" else "standard",
                "event": event, "max_actions": 32,
            })
    protocol = {
        "date": "2026-10-06", "model": "jev-1.13.0", "episodes": episodes,
        "instructions": WORLD_INSTRUCTIONS,
        "baselines": ["breadth_first_search_replanning", "manhattan_greedy"],
        "observation": "Full symbolic map, exact coordinates, cargo rules, adjacent destinations and computed Manhattan distances, previous six actions. No rendered image input; no future event disclosed until it occurs.",
        "finish": "Explicit finish action required at the destination. Incorrect finish terminates as false completion. Invalid moves rejected and count toward action budget; no physical action occurs.",
        "loop_stop": "Stop after robot visits same cell five times. Such failures count in completion rate.",
        "scope": "12 handcrafted toy worlds, three map rotations in each of four families; diagnostic experiment, not a validated robotics benchmark or deployment safety test.",
        "cost_cap": "Shared ledger with routing pilot; at most 1500 attempted requests and $0.10 estimated spend at published direct API price.",
    }
    path = directory / "protocol.json"
    path.write_text(json.dumps(protocol, indent=2) + "\n")
    (directory / "manifest.json").write_text(json.dumps({"protocol.json": hashlib.sha256(path.read_bytes()).hexdigest()}, indent=2) + "\n")
    print("Frozen warehouse protocol: 12 episodes, 32-action limit each.", flush=True)


class World:
    def __init__(self, episode):
        self.episode = episode
        self.position = tuple(episode["start"])
        self.goal = tuple(episode["goal"])
        self.walls = set(map(tuple, episode["walls"]))
        self.rough = set(map(tuple, episode["rough"]))
        self.history = []
        self.visits = collections.Counter([self.position])
        self.event_applied = False

    def update(self):
        event = self.episode["event"]
        if event and len(self.history) >= event["at_action"] and not self.event_applied:
            if self.position == tuple(event["close_cell"]):
                raise RuntimeError("Door event would overlap the robot; invalid episode design.")
            self.walls.add(tuple(event["close_cell"]))
            self.event_applied = True

    def status(self, p):
        if not all(0 <= n < 7 for n in p):
            return "outside_world"
        if p in self.walls:
            return "blocked_aisle"
        if p in self.rough and self.episode["cargo"] == "fragile":
            return "prohibited_for_fragile_cargo"
        return "allowed"

    def state(self):
        self.update()
        rows = []
        for y in range(7):
            rows.append("".join("#" if (x, y) in self.walls else "~" if (x, y) in self.rough else "." for x in range(7)))
        adjacent = {}
        for action, (dx, dy) in DIRS.items():
            p = self.position[0] + dx, self.position[1] + dy
            adjacent[action] = {"destination": list(p), "status": self.status(p), "manhattan_distance_to_goal": abs(p[0] - self.goal[0]) + abs(p[1] - self.goal[1])}
        return {"position": list(self.position), "delivery_destination": list(self.goal), "cargo": self.episode["cargo"],
            "rules": "Never enter blocked aisles or leave the world. Fragile cargo must never enter rough floor (~).",
            "map_rows_y_0_to_6": rows, "legend": {"#": "blocked", "~": "rough floor", ".": "normal floor"},
            "adjacent_actions": adjacent, "recent_actions": self.history[-6:], "door_update_applied": self.event_applied,
            "actions_remaining": self.episode["max_actions"] - len(self.history)}

    def step(self, action):
        before = self.position
        violation, terminal = None, None
        if action == "finish":
            terminal = "completed" if self.position == self.goal else "false_completion"
        elif action in DIRS:
            dx, dy = DIRS[action]
            target = self.position[0] + dx, self.position[1] + dy
            status = self.status(target)
            if status == "allowed":
                self.position = target
            else:
                violation = status
        elif action != "wait":
            raise RuntimeError("Unknown action.")
        self.history.append({"action": action, "from": list(before), "to": list(self.position), "rejected": violation})
        self.visits[self.position] += 1
        if not terminal and self.visits[self.position] >= 5:
            terminal = "loop_limit"
        if not terminal and len(self.history) >= self.episode["max_actions"]:
            terminal = "action_limit"
        return violation, terminal


def bfs_action(world):
    if world.position == world.goal:
        return "finish"
    queue = collections.deque([(world.position, None)])
    seen = {world.position}
    while queue:
        point, first = queue.popleft()
        for action, (dx, dy) in DIRS.items():
            nxt = point[0] + dx, point[1] + dy
            if nxt in seen or world.status(nxt) != "allowed":
                continue
            move = first or action
            if nxt == world.goal:
                return move
            seen.add(nxt)
            queue.append((nxt, move))
    return "wait"


def greedy_action(world):
    if world.position == world.goal:
        return "finish"
    actions = []
    for action, (dx, dy) in DIRS.items():
        nxt = world.position[0] + dx, world.position[1] + dy
        if world.status(nxt) == "allowed":
            actions.append((abs(nxt[0] - world.goal[0]) + abs(nxt[1] - world.goal[1]), action))
    return min(actions)[1] if actions else "wait"


def criteria():
    return {**{action: f"Move one cell {action[5:]}; consult this action's destination and status in adjacent_actions. Choose only an allowed destination." for action in DIRS},
        "wait": "Stay in place. Use only when no valid route exists.",
        "finish": "Declare delivery complete. Valid only at delivery_destination."}


def run(client=None):
    directory = ROOT / "world"
    protocol = json.loads((directory / "protocol.json").read_text())
    expected = json.loads((directory / "manifest.json").read_text())["protocol.json"]
    if hashlib.sha256((directory / "protocol.json").read_bytes()).hexdigest() != expected:
        raise RuntimeError("Frozen warehouse protocol changed.")
    result_path = ROOT / "results" / "warehouse.jsonl"
    raw_path = ROOT / "results" / "jev-world-requests.jsonl"
    (ROOT / "results").mkdir(exist_ok=True)
    done = {(r["method"], r["episode_id"]) for r in (json.loads(s) for s in result_path.read_text().splitlines())} if result_path.exists() else set()
    cache = {r["request_id"]: r for r in (json.loads(s) for s in raw_path.read_text().splitlines())} if raw_path.exists() else {}
    methods = ["jev-1.13.0"] if client else ["breadth_first_search_replanning", "manhattan_greedy"]
    for method in methods:
        for episode in protocol["episodes"]:
            if (method, episode["id"]) in done:
                continue
            world = World(episode)
            trace, violations = [], 0
            terminal = None
            while not terminal:
                state = world.state()
                response, latency = None, 0
                if method == "jev-1.13.0":
                    request_id = f"world-{episode['id']}-{len(trace)}"
                    payload = {"model": protocol["model"], "state": state, "questions": {"action": {"type": "choice", "instructions": protocol["instructions"], "criteria": criteria()}}}
                    if request_id in cache:
                        cached = cache[request_id]
                        if cached["request"] != payload:
                            raise RuntimeError("Resumed state differs from saved request.")
                        response, latency = cached["response"], cached["latency_seconds"]
                    else:
                        response, latency = client.decide(payload, request_id)
                        record = {"request_id": request_id, "request": payload, "response": response, "latency_seconds": latency}
                        with raw_path.open("a") as f:
                            f.write(json.dumps(record) + "\n")
                        cache[request_id] = record
                    action = response["answers"]["action"]["choice"]
                    if action not in criteria():
                        raise RuntimeError("Invalid model action.")
                elif method == "breadth_first_search_replanning":
                    action = bfs_action(world)
                else:
                    action = greedy_action(world)
                rejected, terminal = world.step(action)
                violations += bool(rejected)
                trace.append({"step": len(trace), "state": state, "action": action, "position_after": list(world.position), "rejected": rejected, "terminal": terminal, "latency_seconds": latency,
                    "confidence": response["answers"]["action"]["confidence"] if response else None,
                    "probabilities": response["answers"]["action"]["probabilities"] if response else None,
                    "usage": response["usage"] if response else None})
            result = {"method": method, "episode_id": episode["id"], "family": episode["family"], "episode": episode,
                "outcome": terminal, "completed": terminal == "completed", "action_count": len(trace),
                "movement_count": sum(t["state"]["position"] != t["position_after"] for t in trace),
                "rejected_actions": violations, "trace": trace}
            with result_path.open("a") as f:
                f.write(json.dumps(result) + "\n")
            print(method, episode["id"], terminal, "actions", len(trace), "rejected", violations, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "local", "live"])
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare()
    elif args.mode == "local":
        run()
    else:
        run(JevClient(key_from_prompt()))
