from flask import Flask, render_template, request, jsonify, redirect, url_for
import requests
from collections import defaultdict
from datetime import datetime, timezone
import os

app = Flask(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def get_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def fetch_user(username):
    r = requests.get(f"{GITHUB_API}/users/{username}", headers=get_headers())
    if r.status_code == 404:
        return None, "User not found"
    if r.status_code == 403:
        return None, "GitHub API rate limit reached. Set GITHUB_TOKEN env var to increase limits."
    r.raise_for_status()
    return r.json(), None


def fetch_events(username):
    events = []
    for page in range(1, 4):  # up to 3 pages = 90 events
        r = requests.get(
            f"{GITHUB_API}/users/{username}/events/public",
            headers=get_headers(),
            params={"per_page": 30, "page": page}
        )
        if r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        events.extend(data)
    return events


def fetch_repos(username):
    r = requests.get(
        f"{GITHUB_API}/users/{username}/repos",
        headers=get_headers(),
        params={"per_page": 100, "sort": "pushed"}
    )
    if r.status_code != 200:
        return []
    return r.json()


def parse_activity(events, repos):
    commit_count = 0
    repo_activity = defaultdict(int)
    day_activity = defaultdict(int)
    pr_count = 0
    issue_count = 0
    recent_commits = []

    for event in events:
        etype = event.get("type")
        repo_name = event.get("repo", {}).get("name", "unknown")
        created_at = event.get("created_at", "")

        # Parse day of week
        if created_at:
            try:
                dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
                day = dt.strftime("%A")
                day_activity[day] += 1
            except Exception:
                pass

        if etype == "PushEvent":
            payload = event.get("payload", {})
            commits = payload.get("commits", [])
            commit_count += len(commits)
            repo_activity[repo_name] += len(commits)
            for c in commits[:2]:
                recent_commits.append({
                    "message": c.get("message", "").split("\n")[0][:80],
                    "repo": repo_name.split("/")[-1],
                    "date": created_at[:10] if created_at else ""
                })
        elif etype == "PullRequestEvent":
            pr_count += 1
            repo_activity[repo_name] += 1
        elif etype in ("IssuesEvent", "IssueCommentEvent"):
            issue_count += 1

    # Top repos by commit activity
    top_repos = sorted(repo_activity.items(), key=lambda x: x[1], reverse=True)[:5]
    top_repos = [{"name": r.split("/")[-1], "full_name": r, "commits": c} for r, c in top_repos]

    # Most active day
    most_active_day = max(day_activity, key=day_activity.get) if day_activity else "N/A"
    ordered_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_chart = {d: day_activity.get(d, 0) for d in ordered_days}

    # Top repos by stars from profile
    star_repos = sorted(repos, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:3]
    star_repos = [{"name": r["name"], "stars": r["stargazers_count"], "lang": r.get("language") or "—", "description": (r.get("description") or "")[:80]} for r in star_repos]

    return {
        "commit_count": commit_count,
        "pr_count": pr_count,
        "issue_count": issue_count,
        "top_repos": top_repos,
        "star_repos": star_repos,
        "most_active_day": most_active_day,
        "day_chart": day_chart,
        "recent_commits": recent_commits[:6],
        "total_public_repos": len(repos),
    }


def build_summary(username):
    user, err = fetch_user(username)
    if err:
        return None, err

    events = fetch_events(username)
    repos = fetch_repos(username)
    activity = parse_activity(events, repos)

    return {
        "user": {
            "login": user["login"],
            "name": user.get("name") or user["login"],
            "avatar_url": user.get("avatar_url", ""),
            "bio": user.get("bio") or "",
            "location": user.get("location") or "",
            "followers": user.get("followers", 0),
            "following": user.get("following", 0),
            "public_repos": user.get("public_repos", 0),
            "html_url": user.get("html_url", ""),
            "created_at": user.get("created_at", "")[:10],
        },
        "activity": activity,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }, None


# ── Routes ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/user/<username>")
def dashboard(username):
    summary, err = build_summary(username)
    if err:
        return render_template("index.html", error=err, query=username)
    return render_template("dashboard.html", data=summary)


@app.route("/", methods=["POST"])
def search():
    username = request.form.get("username", "").strip()
    if not username:
        return render_template("index.html", error="Please enter a GitHub username.")
    return redirect(url_for("dashboard", username=username))


@app.route("/api/user/<username>")
def api_user(username):
    summary, err = build_summary(username)
    if err:
        return jsonify({"error": err}), 404
    return jsonify(summary)


if __name__ == "__main__":
    app.run(debug=True)
