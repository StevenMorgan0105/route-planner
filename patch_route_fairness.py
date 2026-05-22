from pathlib import Path

p = Path("app.py")
s = p.read_text()

if "ROUTE_DRIVE_WEIGHT" not in s:
    s = s.replace(
        "HOME_PULL_BY_BLOCK_INDEX = [0.0, 0.2, 0.5, 1.25, 2.5, 4.0]\nPRIORITY_SCORE",
        "HOME_PULL_BY_BLOCK_INDEX = [0.0, 0.2, 0.5, 1.25, 2.5, 4.0]\n"
        "ROUTE_DRIVE_WEIGHT = 8\n"
        "FAIRNESS_STOP_PENALTY = 45\n"
        "ROTATION_TIEBREAKER_PENALTY = 2\n"
        "PRIORITY_SCORE",
    )

start = s.find("def choose_lead(")
end = s.find("\ndef maps_link", start)

if start == -1 or end == -1:
    raise SystemExit("Could not find the route functions to replace. app.py may have already changed.")

new_logic = '''
def route_choice_score(est: Estimator, lead: Lead, block_index: int, current: str, scheduled_counts, estimator_order, cache, client):
    drive_prev = drive_minutes(cache, client, current, lead.address)
    drive_home = drive_minutes(cache, client, lead.address, est.home_address)

    home_pull = HOME_PULL_BY_BLOCK_INDEX[min(block_index, len(HOME_PULL_BY_BLOCK_INDEX) - 1)]

    score = 0
    score += -PRIORITY_SCORE.get(lead.priority, 3) * 1000
    score += len(lead.available_blocks) * 40
    score += drive_prev * ROUTE_DRIVE_WEIGHT
    score += drive_home * home_pull
    score += scheduled_counts[est.name] * FAIRNESS_STOP_PENALTY

    if norm_estimator(lead.required_estimator) != "Any":
        score -= 150

    score += ((estimator_order[est.name] - block_index) % max(1, len(estimator_order))) * ROTATION_TIEBREAKER_PENALTY

    return score, drive_prev, drive_home


def build_routes(estimators: List[Estimator], leads: List[Lead], client):
    remaining = leads.copy()
    routes = {e.name: [] for e in estimators}
    current = {e.name: e.start_address for e in estimators}
    summaries = {}
    cache = {}

    scheduled_counts = {e.name: 0 for e in estimators}
    estimator_order = {e.name: idx for idx, e in enumerate(estimators)}

    for block_index, block in enumerate(ESTIMATE_BLOCKS):
        block_label = block["label"]
        used_estimators = set()

        while True:
            choices = []

            for est in estimators:
                if est.name in used_estimators:
                    continue

                for lead in remaining:
                    if not can_take(est, lead, block_label):
                        continue

                    score, drive_prev, drive_home = route_choice_score(
                        est,
                        lead,
                        block_index,
                        current[est.name],
                        scheduled_counts,
                        estimator_order,
                        cache,
                        client,
                    )

                    choices.append((score, est, lead, drive_prev, drive_home))

            if not choices:
                break

            choices.sort(key=lambda x: x[0])
            _, est, lead, drive_prev, drive_home = choices[0]

            routes[est.name].append({
                "Estimate Block": block_label,
                "Estimate Time": block_time(block),
                "Address": lead.address,
                "Priority": lead.priority,
                "Required Estimator": lead.required_estimator,
                "Drive From Previous (min)": drive_prev,
                "Drive From Stop To Home (min)": drive_home,
            })

            current[est.name] = lead.address
            remaining.remove(lead)
            used_estimators.add(est.name)
            scheduled_counts[est.name] += 1

    for est in estimators:
        rows = routes.get(est.name, [])
        final_home = drive_minutes(cache, client, rows[-1]["Address"], est.home_address) if rows else 0
        summaries[est.name] = {
            "home_address": est.home_address,
            "final_drive_home": final_home,
        }

    return routes, remaining, summaries
'''

s = s[:start] + new_logic + s[end:]
s = s.replace(
    "Add the address, select availability, and build the route.",
    "The planner keeps nearby stops together first, then balances work when route options are close.",
)
p.write_text(s)
print("Route-aware fairness logic added to app.py")
