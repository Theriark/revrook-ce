# Quick start

From nothing to an exported quarterly security review in about ten minutes, on one
machine, with invented demo data. Nothing here touches a real customer or a real
Microsoft tenant.

revrook is pre-release: there is no released version and no published image yet, so you
build the image from the repository. What the output is, and is not, is in the
[README](../README.md): a configuration evidence summary, not a certification.

## What you need

- Docker with the compose plugin (`docker compose version` works) and about 1 GB of
  free memory.
- `git`, `curl`, `jq` and Python 3.11 or newer on the same machine. Python only makes
  the demo files and uses the standard library; nothing is installed with it.
- Port 8080 free on the machine.

## 1. Get the code and start it

```bash
git clone --branch development https://github.com/Theriark/revrook-ce
cd revrook-ce
cp .env.example .env
docker compose up --build --wait
```

Until a release exists the code is on the `development` branch. `.env.example` holds
throwaway keys that are fine for this page and never for a real installation
([install.md](install.md) shows how to make your own). The first build takes a few
minutes; `--wait` returns when the database, the web role and the worker are healthy.
Check it:

```bash
curl -fsS http://localhost:8080/readyz
```

## 2. Make the first account

Open <http://localhost:8080>. It sends you to the first-run page, where you choose a
user name and a password of 12 to 256 characters. The page works only until the first
account exists; whoever reaches a new installation first can claim it, so do this
before you put the installation on a network others can reach.

Then open **Settings** and type the name of your business. It is printed on the cover
of every report, and a report cannot be exported while it is empty.

## 3. Load the demo client

```bash
bash scripts/demo.sh YOUR-USER-NAME
```

Use the name you chose in step 2. The script makes one client, **Demo Client (synthetic
data)**, and uploads six invented example files for it (device inventory, backup jobs,
network, training, leavers and a mail export), captured now. It prints the address of
the client. It never prints the API token it uses, and every name inside the files is a
placeholder.

## 4. Look around

Open the client page that the script printed. The **Overview** shows where the client
stands: the score, the controls by status, the score of each domain and how fresh each
export is. The **Checklist** lists the 51 controls with a status that is always an icon
and words, never a colour alone. **Evidence and imports** lists what was imported and
which export to refresh next. The **Glossary** in the top bar explains the words. How a
score is made is in [scoring.md](scoring.md).

## 5. Make and export the report

1. Open the client's **Reports** page. The period is the last full quarter; change it if
   you like and press **Use this period**.
2. Add who prepared the report and a line or two of plan for next quarter if you want
   to; everything is saved as you type.
3. Press **Make the report for this period**. This stores the state of the client today.
4. On the next page (**Preview and export**), open **Preview** to read the report, then
   press **Export the quarterly security review**.
5. The file is in the **Export history** of the client, with its SHA-256. It is one
   HTML file: print it to PDF from the browser if you need a PDF.

If **Before you export** lists things to fix, each line says what is missing. The usual
first one is the business name of step 2.

## 6. Clean up

Delete the demo client on the **System** page: type its exact name and press the button.
Its evidence, reports and exports go with it. To stop the stack and keep its data:

```bash
docker compose down
```

To stop it and delete the database and the evidence volume as well, add `-v`.

## Real data

The six demo files are the same shape as real exports. Write your own with the guides
in [importers.md](importers.md), and upload them through the API (an API token is made
the way `scripts/demo.sh` makes one) or, for a file whose columns have other names, with
the **Profile editor** in the top bar. Plan the installation first: [install.md](install.md),
[configuration.md](configuration.md), [operations.md](operations.md) for backups.

## If something goes wrong

| Symptom | Cause and fix |
| --- | --- |
| `docker compose up` stops with `copy .env.example to .env` | Step 1: the `.env` file is missing. |
| Port 8080 is in use | Stop what uses it and run step 1 again. To publish another port, see [install.md](install.md). |
| `scripts/demo.sh` says there is no account of that name | Use the name you made in step 2; names are case sensitive. |
| `scripts/demo.sh` says the example files could not be made | Python 3.11 or newer is needed on this machine. |
| The page says the background worker has not reported | The worker container is not running: `docker compose ps`, then `docker compose logs worker`. |

## Not for your installation

`scripts/e2e/phase_11.sh` repeats steps 3 to 6 for the compose smoke test of the merge
gate, and CI is the only place that runs it. Do not run it against a stack you keep: it
creates an administrator account whose password is written in the repository, never
removes it, and replaces the business name in **Settings**.
