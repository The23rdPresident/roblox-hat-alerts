#!/usr/bin/env python3
"""Create/configure a dedicated GitHub price-alert repository using gh, without Git."""

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".setup-state.json"
FILES = (
    "price_alert.py", "roblox_price_alert.py", "requirements.txt", "README.md",
    ".gitignore", ".env.example", ".github/workflows/price-alert.yml",
    "setup_github.py", "setup_windows.ps1",
)


class SetupError(Exception):
    pass


class GitHubError(SetupError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class GitHub:
    def __init__(self):
        self.executable = shutil.which("gh")
        if not self.executable:
            raise SetupError("GitHub CLI is missing. On Windows run setup_windows.ps1; on Codespaces install gh, then rerun this script.")
        self.environment = os.environ.copy()
        self.environment["GH_HOST"] = "github.com"
        self.environment["GH_PAGER"] = "cat"
        # Codespaces' built-in token is restricted to its current repository.
        # Use an existing full gh login or authenticate normally for the new repo.
        if self.environment.get("CODESPACES") == "true":
            self.environment.pop("GITHUB_TOKEN", None)

    def command(self, arguments, data=None, interactive=False, check=True):
        try:
            result = subprocess.run(
                [self.executable] + list(arguments), input=data,
                text=True, encoding="utf-8", errors="replace",
                capture_output=not interactive, env=self.environment,
                timeout=None if interactive else 90,
            )
        except subprocess.TimeoutExpired:
            raise SetupError("GitHub took too long to answer. Rerun the setup to resume.")
        if check and result.returncode:
            message = (result.stderr or result.stdout or "GitHub command failed").strip()
            match = re.search(r"HTTP\s+(\d{3})", message)
            raise GitHubError(message[:1500], int(match.group(1)) if match else None)
        return result

    def api(self, endpoint, method="GET", payload=None, missing_ok=False):
        arguments = ["api", endpoint, "--hostname", "github.com", "--method", method]
        data = None
        if payload is not None:
            arguments += ["--input", "-"]
            data = json.dumps(payload)
        try:
            result = self.command(arguments, data=data)
        except GitHubError as error:
            if missing_ok and error.status == 404:
                return None
            raise
        if not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            raise SetupError("GitHub returned an unexpected response. Rerun the setup to resume.")

    def authenticate(self):
        status = self.command(["auth", "status", "--hostname", "github.com"], check=False)
        if status.returncode:
            print("Sign in to GitHub when prompted. Complete the device-code login in your browser.", flush=True)
            self.command([
                "auth", "login", "--hostname", "github.com", "--git-protocol", "https",
                "--web", "--scopes", "repo,workflow",
            ], interactive=True)
        elif not (self.environment.get("GH_TOKEN") or self.environment.get("GITHUB_TOKEN")):
            scopes = (status.stdout or "") + (status.stderr or "")
            if "workflow" not in scopes:
                print("Adding the GitHub permission needed to upload a workflow. Complete the browser login if prompted.", flush=True)
                self.command(["auth", "refresh", "--hostname", "github.com", "--scopes", "workflow"], interactive=True)
        return self.api("user")


def load_setup_state():
    if not STATE_PATH.exists():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SetupError("The local .setup-state.json is damaged. Restore it before resuming, or extract the package into a new folder for a new repository.")
    if not isinstance(value, dict):
        raise SetupError("The local setup state has an invalid format.")
    return value


def save_setup_state(state):
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def validate_webhook(value):
    try:
        parts = urlsplit(value)
    except ValueError:
        raise SetupError("The webhook URL is invalid. Copy the full Discord webhook URL and rerun setup.")
    if (parts.scheme != "https" or parts.netloc != "discord.com"
            or not re.fullmatch(r"/api/(?:v[0-9]+/)?webhooks/[0-9]+/[A-Za-z0-9_-]+", parts.path)
            or parts.query or parts.fragment):
        raise SetupError("The webhook URL is invalid. Use the normal Discord URL containing the webhook ID and token; omit /github.")


def read_files(no_everyone):
    files = {}
    for name in FILES:
        path = ROOT / name
        if not path.is_file():
            raise SetupError("Required package file is missing: " + name + ". Extract the whole ZIP and rerun setup.")
        content = path.read_text(encoding="utf-8")
        if re.search(r"https://(?:discord\.com|discordapp\.com)/api/(?:v\d+/)?webhooks/\d+/[A-Za-z0-9_-]+", content):
            raise SetupError("A real Discord webhook URL was found in " + name + ". Remove it from the file; setup will store it as a GitHub secret.")
        if name.endswith("price-alert.yml") and no_everyone:
            content = content.replace("PING_EVERYONE: 'true'", "PING_EVERYONE: 'false'")
        files[name] = content
    return files


def resolve_repository(github, user, state, name, private):
    if state.get("repository"):
        if state.get("owner_id") != user["id"]:
            raise SetupError("This folder was set up under another GitHub account. Sign in to that account or extract the package into a fresh folder.")
        repository = github.api("repos/" + state["repository"])
        if repository.get("owner", {}).get("id") != user["id"]:
            raise SetupError("The saved repository is no longer owned by this account.")
        print("Resuming setup for " + repository["full_name"], flush=True)
        return repository

    repository_name = name
    if github.api("repos/" + user["login"] + "/" + repository_name, missing_ok=True):
        repository_name += "-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        print("That repository name already exists; creating a separate repository named " + repository_name, flush=True)
    print("Creating " + ("private" if private else "public") + " GitHub repository...", flush=True)
    repository = github.api("user/repos", "POST", {
        "name": repository_name, "private": private, "auto_init": True,
        "description": "Roblox limited-hat resale price alerts to Discord",
        "has_issues": False, "has_wiki": False,
    })
    state.update(repository=repository["full_name"], owner_id=user["id"])
    save_setup_state(state)
    return repository


def upload_files(github, repository, files):
    prefix = "repos/" + repository["full_name"]
    branch = repository["default_branch"]
    branch_info = None
    for attempt in range(20):
        branch_info = github.api(prefix + "/branches/" + quote(branch, safe=""), missing_ok=True)
        if branch_info:
            break
        time.sleep(2)
    if not branch_info:
        raise SetupError("GitHub has not finished initializing the repository. Rerun setup to resume.")
    head = branch_info["commit"]["sha"]
    commit = github.api(prefix + "/git/commits/" + head)
    tree = github.api(prefix + "/git/trees", "POST", {
        "base_tree": commit["tree"]["sha"],
        "tree": [{"path": name, "mode": "100644", "type": "blob", "content": content}
                 for name, content in files.items()],
    })
    if tree["sha"] != commit["tree"]["sha"]:
        new_commit = github.api(prefix + "/git/commits", "POST", {
            "message": "Set up Roblox price alerts", "tree": tree["sha"], "parents": [head],
        })
        # This is a normal fast-forward update. Existing files such as state.json are retained.
        github.api(prefix + "/git/refs/heads/" + quote(branch, safe=""), "PATCH", {
            "sha": new_commit["sha"], "force": False,
        })
    return branch


def dispatch_test(github, repository, branch):
    name = repository["full_name"]
    workflow = "repos/" + name + "/actions/workflows/price-alert.yml"
    registered = False
    for attempt in range(30):
        if github.api(workflow, missing_ok=True):
            registered = True
            break
        time.sleep(2)
    if not registered:
        raise SetupError("GitHub has not registered the workflow yet. Rerun setup in a minute to resume.")
    github.api(workflow + "/enable", "PUT")
    dispatched_at = datetime.now(timezone.utc)
    github.api(workflow + "/dispatches", "POST", {"ref": branch, "inputs": {"test_alert": True}})
    for attempt in range(30):
        runs = github.api(workflow + "/runs?event=workflow_dispatch&per_page=10")["workflow_runs"]
        for run in runs:
            created_at = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            if run.get("head_branch") == branch and (created_at - dispatched_at).total_seconds() >= -5:
                return run
        time.sleep(2)
    return None


def wait_for_test(github, repository, run):
    endpoint = "repos/" + repository["full_name"] + "/actions/runs/" + str(run["id"])
    print("Test run: " + run["html_url"], flush=True)
    print("Waiting for GitHub's test run to finish...", flush=True)
    last_status = None
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        result = github.api(endpoint)
        if result["status"] != last_status:
            print("  Status: " + result["status"], flush=True)
            last_status = result["status"]
        if result["status"] == "completed":
            if result.get("conclusion") == "success":
                return True
            github.command(["run", "view", str(run["id"]), "--repo", repository["full_name"], "--log-failed"], interactive=True, check=False)
            raise SetupError("The test workflow finished with " + str(result.get("conclusion")) + ". The repository is saved; fix the reported issue and rerun setup.")
        time.sleep(5)
    print("GitHub is still processing the run. The schedule is enabled; check the run URL above for the result.", flush=True)
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-name", default="roblox-hat-alerts")
    parser.add_argument("--private", action="store_true", help="Use a private repository; Actions uses your private allowance")
    parser.add_argument("--no-everyone", action="store_true", help="Disable @everyone; optionally provide your user ID")
    parser.add_argument("--update-webhook", action="store_true", help="Prompt for a replacement webhook on a later run")
    parser.add_argument("--no-wait", action="store_true", help="Start the test without waiting for its completion")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}", args.repo_name):
        raise SetupError("Use a repository name containing letters, numbers, periods, underscores, or hyphens.")
    state = load_setup_state()
    no_everyone = args.no_everyone or state.get("no_everyone", False)
    files = read_files(no_everyone)
    github = GitHub()
    user = github.authenticate()
    print("GitHub account: " + user["login"], flush=True)

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook and (not state.get("webhook_configured") or args.update_webhook):
        print("Paste your Discord webhook when prompted. Its value is hidden and is stored only as a GitHub secret.", flush=True)
        webhook = getpass.getpass("Discord webhook URL: ").strip()
    if webhook:
        validate_webhook(webhook)
    elif not state.get("webhook_configured"):
        raise SetupError("A Discord webhook URL is required.")

    user_id = os.environ.get("DISCORD_USER_ID", "").strip()
    if not state.get("repository") and not user_id:
        user_id = input("Your Discord user ID (optional; press Enter to skip): ").strip()
    if user_id and not user_id.isdigit():
        raise SetupError("Discord user ID must contain numbers only.")

    repository = resolve_repository(github, user, state, args.repo_name, args.private)
    state["no_everyone"] = no_everyone
    save_setup_state(state)
    prefix = "repos/" + repository["full_name"]
    print("Enabling Actions and permission to save alert history...", flush=True)
    github.api(prefix + "/actions/permissions", "PUT", {"enabled": True, "allowed_actions": "all"})
    github.api(prefix + "/actions/permissions/workflow", "PUT", {
        "default_workflow_permissions": "write", "can_approve_pull_request_reviews": False,
    })
    if webhook:
        print("Saving the Discord webhook as an encrypted repository secret...", flush=True)
        github.command(["secret", "set", "DISCORD_WEBHOOK_URL", "--repo", repository["full_name"]], data=webhook + "\n")
        state["webhook_configured"] = True
        save_setup_state(state)
        webhook = None
    if user_id:
        github.command(["secret", "set", "DISCORD_USER_ID", "--repo", repository["full_name"]], data=user_id + "\n")
    print("Uploading all scripts and the scheduled workflow...", flush=True)
    branch = upload_files(github, repository, files)
    print("Starting a labeled test embed and current-price check...", flush=True)
    run = dispatch_test(github, repository, branch)
    verified = False
    if run and not args.no_wait:
        verified = wait_for_test(github, repository, run)
    elif run:
        print("Test run: " + run["html_url"], flush=True)
    else:
        print("Test dispatched; its run has not appeared yet. Check " + repository["html_url"] + "/actions", flush=True)
    print("\n" + ("Setup complete and test workflow passed." if verified else "Repository setup complete; test completion is pending."), flush=True)
    print("Repository: " + repository["html_url"], flush=True)
    print("Checks are scheduled every five minutes. GitHub may delay scheduled runs.", flush=True)
    print("Your PC can be switched off. No source-file edits are required.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (SetupError, OSError) as error:
        print("\nSetup stopped: " + str(error), file=sys.stderr)
        print("Correct the reported issue and rerun the same command to resume.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nSetup interrupted. Rerun the same command to resume.", file=sys.stderr)
        sys.exit(130)
