# Roblox hat price alerts

## Automatic setup: run commands only

Download the ZIP to your Downloads folder. On Windows, paste these commands into **PowerShell**:

```powershell
$alertZip = Get-ChildItem "$env:USERPROFILE\Downloads\Roblox_Price_Alerts_Hosting*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$alertFolder = Join-Path $env:USERPROFILE "RobloxHatAlerts"
Expand-Archive -LiteralPath $alertZip.FullName -DestinationPath $alertFolder -Force
powershell -NoProfile -ExecutionPolicy Bypass -File "$alertFolder\setup_windows.ps1"
```

The Windows launcher installs GitHub CLI and Python through Windows Package Manager if they are missing. Sign in to GitHub when prompted, then paste your Discord webhook into the hidden prompt. Press Enter to skip the optional Discord user ID, or enter your numeric ID for a personal mention. The webhook is sent to GitHub's secret store; it is never written into the source or the local setup state.

Setup creates a dedicated public repository, enables Actions, sets the required write permission for alert history, uploads every required file, stores the webhook, starts a test embed, and waits for the first workflow result. The test embed can ping `@everyone` using the default settings. The installer will print the repository and test-run links. GitHub continues monitoring after your PC shuts down.

On **GitHub Codespaces, Linux, or macOS**, extract the ZIP into a new folder and run this from that folder:

```bash
python3 setup_github.py
```

Python 3.8+ and GitHub CLI must be available. Codespaces' built-in `GITHUB_TOKEN` is excluded from setup's subprocesses because it is usually limited to the current repository; setup uses a normal GitHub CLI login for the new repository. If `gh` is missing on an Ubuntu-based Codespace, install it and rerun:

```bash
sudo apt-get update
sudo apt-get install -y gh
python3 setup_github.py
```

Optional command flags:

| Windows launcher flag | Python installer flag | Effect |
| --- | --- | --- |
| `-NoEveryone` | `--no-everyone` | Disable `@everyone`; personal mentions still work with a user ID |
| `-Private` | `--private` | Create a private repository and use your private Actions allowance |
| `-RepoName my-alerts` | `--repo-name my-alerts` | Change the repository name |
| `-UpdateWebhook` | `--update-webhook` | Replace the webhook on a later setup run |
| `-NoWait` | `--no-wait` | Dispatch the test and exit before it finishes |

If setup stops, rerun the same command in the same folder. `.setup-state.json` records only the destination account/repository and setup progress. A rerun resumes that repository; an unrelated repository with the same name is preserved and a new name is used instead. Downloading/extracting into a new folder creates a separate setup. Keep the same folder for later updates.

The automated GitHub setup is complete once the installer reports a successful test workflow. If GitHub is still queued after the wait period, use the printed test-run link to inspect its eventual result. Existing account restrictions or installation failures are reported, and setup does not claim the test succeeded when it did not.

## Hosting choices

Choose one way to run the watcher:

| Host | Script to run | Checking frequency | Cost |
| --- | --- | --- | --- |
| GitHub Actions | `price_alert.py` | Scheduled every five minutes; GitHub can delay or drop runs | Standard hosted runners are free for public repositories; private repositories have a monthly allowance |
| Render Background Worker | `roblox_price_alert.py` | About every 30 seconds, with backoff when Roblox rate-limits requests | Paid worker; persistent disk is billed separately |

The GitHub schedule is suitable for occasional alerts. Choose the continuous worker if you want to react quickly to short-lived resale listings. Both stop monitoring when their host is stopped, suspended, or unable to reach Roblox.

## What is watched

| Hat | Asset ID | Send an alert below |
| --- | --- | --- |
| Gold Emperor of the Night | 878895806 | 80,000 Robux |
| Silver Emperor of the Night | 878899787 | 120,000 Robux |
| Stickmasterluke's Peanut Butter Sparkle Time | 169444294 | 80,000 Robux |

The check uses the lowest resale listing price, not RAP or an estimated trading value. An item at exactly the threshold does not qualify. Edit `WATCHLIST` in `price_alert.py` to change the asset IDs or thresholds; both hosting modes use that same list.

Each qualifying alert contains a green Discord embed with the item name, lowest price, threshold, amount under the threshold, thumbnail when available, timestamp, and a clickable Roblox catalog link. The same notification includes the catalog URL as text. The first check also sends a status embed showing all available prices.

Repeated checks of an unchanged cheap listing do not immediately send more alerts. A new lowest listing, a lower price, or a 30-minute reminder can send another alert while the price remains below target. A price at or above target resets that item's alert state, so its next drop below target alerts again. Prices may change before you click the link.

## 1. Set up Discord

The original uploaded `roblox_price_alert.py` contains a real webhook URL. Delete that webhook and create a replacement before publishing the original file anywhere. The scripts in this package contain no webhook credentials.

1. In Discord, open your server's **Server Settings → Integrations → Webhooks**.
2. Delete the webhook whose URL was included in the uploaded script, if it is still active.
3. Select **New Webhook** or **Create Webhook**, choose the alert channel, and give it a name such as `Hat Price Alerts`.
4. Select **Copy Webhook URL**. Save this URL in the host's secret or environment settings described below.

This uses an incoming Discord webhook. You do not need a Discord bot token, a bot login, or a Roblox cookie. Keep the copied URL out of source files and public screenshots. Use the normal URL without adding `/github` to it.

By default, qualifying alerts and the optional test alert include `@everyone`. To ping only yourself, set `PING_EVERYONE` to `false` and set `DISCORD_USER_ID` to your numeric user ID. Discord's **User Settings → Advanced → Developer Mode** lets you copy your user ID by right-clicking your name. Discord notification settings can still affect whether you receive a notification.

## 2A. GitHub Actions setup

1. Create a repository at <https://github.com/new>, named for example `roblox-hat-alerts`. A **public** repository uses free standard GitHub Actions runners. You may choose private, but scheduled checks will use your private Actions allowance.
2. Extract this ZIP on your computer. Upload the extracted contents to the repository's default branch, normally `main`. Upload the files, rather than the ZIP. Put `price_alert.py` at the repository root.
3. Check that the repository also contains **`.github/workflows/price-alert.yml`**. The workflow must be at that exact path and on the default branch. If the folder was omitted by the uploader, use **Add file → Create new file**, enter `.github/workflows/price-alert.yml` as the filename, and paste the supplied workflow's complete contents.
4. Open **Settings → Secrets and variables → Actions → New repository secret**. Name it exactly **`DISCORD_WEBHOOK_URL`**, paste the replacement Discord webhook URL as the value, and save it. Optionally add another repository secret named **`DISCORD_USER_ID`** with your numeric Discord user ID.
5. Open **Actions → Roblox Price Alerts → Run workflow**. If GitHub asks you to enable Actions first, do so. Select the default branch. Check the optional test-embed checkbox if you want a clearly labeled simulated price-drop embed, then select **Run workflow**.
6. Open the run and inspect **Check prices and send qualifying embeds**. You should see each hat's current price. Discord should receive a startup/status embed and, if selected, the test embed. The test is labeled as simulated and does not alter the actual watchlist or alert history.
7. Leave the workflow enabled. It is scheduled every five minutes, offset to minute 2, 7, 12, and so on. Your PC can be switched off.

The last workflow step commits `state.json` when alert state changes. Keep that file: it prevents repeat alerts on every check and preserves the reminder timer across runs. A missing file is created automatically; do not upload an empty `state.json`. `requirements.txt` is included for other hosts, but GitHub does not need to install packages.

To disable `@everyone` on GitHub, change `PING_EVERYONE: 'true'` to `PING_EVERYONE: 'false'` in the workflow. Change `REMIND_AFTER` in `price_alert.py` if you want a different reminder interval.

### GitHub troubleshooting

- **No workflow appears:** ensure `.github/workflows/price-alert.yml` is present on the default branch, with that exact filename and extension.
- **Missing/invalid webhook:** add `DISCORD_WEBHOOK_URL` as an Actions repository secret, not as an Actions variable. Confirm the copied URL contains the webhook's ID and token.
- **Discord HTTP 401/403/404:** confirm the replacement webhook still exists, points to the intended channel, and was copied correctly.
- **Save-state step reports permission denied:** the workflow already requests `contents: write`. In **Settings → Actions → General → Workflow permissions**, allow **Read and write permissions**, then rerun. Organization policies or branch protection can also prevent direct state commits; use a repository that permits these commits.
- **Same cheap listing alerts on every run:** check that the save-state step succeeds and that `state.json` is committed.
- **Checks are late or a short-lived listing is missed:** GitHub's scheduler is best effort, with a minimum scheduled interval of five minutes. Use the continuous worker for faster checks.
- **Public repository stops scheduling after a long period:** GitHub disables scheduled workflows after 60 days without repository activity. This version records the date of the last attempted and successful checks in `state.json`, causing a daily health update while the workflow runs. If the workflow is disabled or blocked long enough, re-enable it from the Actions tab or rerun setup.

## 2B. Render Background Worker setup

Use this alternative when checks about every 30 seconds are preferable to GitHub's scheduled checks.

1. Upload the extracted package to a GitHub repository as described above. The repository can be private because Render, rather than GitHub Actions, will run the watcher.
2. Disable **Actions → Roblox Price Alerts** if it is already enabled. Run only one watcher so two hosts do not send duplicate alerts.
3. Sign in at <https://dashboard.render.com/> and connect your GitHub account/repository. Select **New → Background Worker**, then choose this repository and its default branch.
4. Select **Python 3** as the language/runtime if Render asks. Leave Root Directory blank when the supplied files are at the repository root. Set these commands:

   | Setting | Value |
   | --- | --- |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `python -u roblox_price_alert.py` |

5. Select a paid worker instance. Render background workers do not have a free instance plan. Check the current price in the creation screen before deploying. Use one worker instance.
6. Add these environment variables:

   | Name | Value |
   | --- | --- |
   | `DISCORD_WEBHOOK_URL` | The replacement Discord webhook URL |
   | `CHECK_EVERY` | `30` |
   | `PING_EVERYONE` | `true`, or `false` for personal-only/no pings |
   | `DISCORD_USER_ID` | Optional: your numeric Discord user ID |
   | `PRICE_ALERT_STATE_FILE` | `/var/data/price-alert/state.json` |

7. Add a persistent disk mounted at **`/var/data/price-alert`**. The watcher creates `state.json` there. Disk storage has its own charge. Without a disk, local alert history is lost on restarts/redeploys and an existing cheap listing may alert again; if you skip the disk, omit `PRICE_ALERT_STATE_FILE` to use the writable default `state.json` in the project directory.
8. Create/deploy the worker. Open **Logs** and verify that all three current prices appear. The first successful run sends a Discord startup/status embed. Your PC can be switched off.

To test a full price-drop embed on Render, temporarily set `TEST_ALERT=true` and restart/deploy the worker. It sends one simulated embed at startup. Remove the setting or set it to `false` after testing so a future restart does not send another test.

`CHECK_EVERY` specifies the approximate time between polling rounds; slow API responses can lengthen it. Roblox HTTP 429 responses pause the worker for at least two minutes. The watcher alerts on observed prices, so a listing that appears and disappears between checks can still be missed.

## Files

| File | Purpose |
| --- | --- |
| `price_alert.py` | Shared watchlist, one price-check round, Discord embeds, persistent alert state |
| `roblox_price_alert.py` | Continuous worker that runs the shared checker |
| `.github/workflows/price-alert.yml` | Five-minute scheduled GitHub workflow and manual/test run button |
| `requirements.txt` | Standard-library-only dependency file for hosting builds |
| `.env.example` | Reference environment variable names; not automatically loaded |
| `.gitignore` | Prevents local secrets and Python cache files from being committed |
| `setup_github.py` | Automatic GitHub repository, secrets, permissions, upload, and test setup |
| `setup_windows.ps1` | Windows launcher that installs missing dependencies and runs automatic setup |

## Official documentation

- GitHub schedule limits, delays, default-branch requirement, and inactivity: <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule>
- GitHub Actions public/private billing: <https://docs.github.com/en/actions/concepts/billing-and-usage>
- GitHub repository secrets: <https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets>
- Discord webhook creation: <https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks>
- Render background workers: <https://render.com/docs/background-workers>
- Render free-plan service types: <https://render.com/docs/free>
- Render persistent disks: <https://render.com/docs/disks>
- Render current pricing: <https://render.com/pricing>
