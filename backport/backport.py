"""
Put this file in a master checkout under .github/.
It should be next to backport-languages.py.

This assumes your git "origin" points to your fork, and "upstream" to upstream.
This will force-push to a branch called "release-backport".

Execute with:

$ python3 .github/backport.py

And follow the instructions. After the PR is merged, run:

$ python3 .github/backport.py --mark-done <PR-NUMBER>
"""

import json
import os
import subprocess
import sys

# NOTE: Replace this with your own token, which must be a classic token that
# has public_repo scope enabled to be able to mark the backported PRs as done.
BEARER_TOKEN = "ghp_???"
# NOTE: Replace this with your own GitHub username
USERNAME = "TrueBrain"
# NOTE: Replace with the version branch to backport to
RELEASE = "13"

pr_query = """
query ($number: Int!) {
  repository(owner: "OpenTTD", name: "OpenTTD") {
    pullRequest(number: $number) {
      body
    }
  }
}
"""

pr_search_query = """
query ($search: String!) {
  search(query: $search, type: ISSUE, first: 100) {
    issueCount
    edges {
      node {
        ... on PullRequest {
          number
          title
          commits(first: 100) {
            totalCount
            nodes {
              commit {
                messageHeadline
              }
            }
          }
          mergedAt
          mergeCommit {
            oid
          }
          labels(first: 10) {
            nodes {
              name
            }
          }
        }
      }
    }
  }
}
"""


def do_query(query, variables):
    query = query.replace("\n", "").replace("\\", "\\\\").replace('"', '\\"')
    variables = json.dumps(variables).replace("\\", "\\\\").replace('"', '\\"')
    res = subprocess.run(
        [
            "curl",
            "--fail",
            "-H",
            f"Authorization: bearer {BEARER_TOKEN}",
            "-X",
            "POST",
            "-d",
            f'{{"query": "{query}", "variables": "{variables}"}}',
            "https://api.github.com/graphql",
        ],
        capture_output=True,
    )
    if res.returncode != 0:
        return None
    return json.loads(res.stdout)


def do_remove_label(number):
    return subprocess.run(
        [
            "curl",
            "--fail",
            "-H",
            f"Authorization: bearer {BEARER_TOKEN}",
            "-X",
            "DELETE",
            f"https://api.github.com/repos/OpenTTD/OpenTTD/issues/{number}/labels/backport%20requested",
        ],
        capture_output=True,
    )


def do_add_label(number):
    return subprocess.run(
        [
            "curl",
            "--fail",
            "-H",
            f"Authorization: bearer {BEARER_TOKEN}",
            "-X",
            "POST",
            "-d",
            '{"labels": ["backported"]}',
            f"https://api.github.com/repos/OpenTTD/OpenTTD/issues/{number}/labels",
        ],
        capture_output=True,
    )


def do_command(command):
    return subprocess.run(command, capture_output=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--mark-done":
        backport_pr = do_query(pr_query, {"number": int(sys.argv[2])})
        if backport_pr is None:
            print("ERROR: couldn't fetch backport PR")
            return

        for line in backport_pr["data"]["repository"]["pullRequest"]["body"].split("\n"):
            if line.startswith("<!-- Backported: "):
                prs = [int(pr) for pr in line.split(":")[1].split(" ")[1].split(",")]

        print("Update labels from backported PRs")
        for pr in prs:
            print(f"- #{pr} ..")
            res = do_remove_label(pr)
            if res.returncode != 0:
                print(f"ERROR: failed to remove label from {pr}")
            res = do_add_label(pr)
            if res.returncode != 0:
                print(f"ERROR: failed to add label to {pr}")

        print("All done")
        return

    dont_push = False
    if len(sys.argv) > 1 and sys.argv[1] == "--dont-push":
        dont_push = True

    resume = None
    resume_i = None
    if os.path.exists(".backport-resume"):
        with open(".backport-resume", "r") as fp:
            resume_str, _, resume_i_str = fp.read().partition(",")
            resume = int(resume_str)
            resume_i = int(resume_i_str)
        print(f"Resuming backporting from {resume}")

    all_prs = do_query(pr_search_query, {"search": 'is:closed is:pr label:"backport requested" repo:OpenTTD/OpenTTD'})
    if all_prs is None:
        print("ERROR: couldn't fetch all Pull Requests marked for 'backport requested'")
        return

    if not resume:
        do_command(["git", "fetch", "upstream"])
        do_command(["git", "checkout", f"upstream/release/{RELEASE}", "-B", "release-backport"])

    for pr in sorted(all_prs["data"]["search"]["edges"], key=lambda x: x["node"]["mergedAt"]):
        if resume:
            if resume != pr["node"]["number"]:
                continue
            resume = None
            print(f"Merging #{pr['node']['number']}: {pr['node']['title']} (resuming)")
        else:
            print(f"Merging #{pr['node']['number']}: {pr['node']['title']}")

        # In case of multiple commits, check if it was squashed or rebased.
        # We do this by comparing commit titles. As if you rebased, they have
        # to be identical.
        if pr["node"]["commits"]["totalCount"] > 1:
            for i in range(pr["node"]["commits"]["totalCount"]):
                commit = pr["node"]["commits"]["totalCount"] - i - 1
                commit_str = f'{pr["node"]["mergeCommit"]["oid"]}' + "".join(["^"] * commit)

                res = do_command(["git", "log", "--pretty=format:%s", f"{commit_str}^..{commit_str}"])
                if res.stdout.decode() != pr["node"]["commits"]["nodes"][i]["commit"]["messageHeadline"]:
                    print("  -> was squashed")
                    pr["node"]["commits"]["totalCount"] = 1
                    break

        for i in range(pr["node"]["commits"]["totalCount"]):
            if resume_i is not None:
                if resume_i != i:
                    continue
                resume_i = None
                continue

            commit = pr["node"]["commits"]["totalCount"] - i - 1
            commit_str = f'{pr["node"]["mergeCommit"]["oid"]}' + "".join(["^"] * commit)

            print(f"  Commit #{i}: {commit_str} ...")

            res = do_command(["git", "cherry-pick", commit_str])
            if res.returncode != 0:
                with open(".backport-resume", "w") as fp:
                    fp.write(str(pr["node"]["number"]) + "," + str(i))
                print(res.stdout.decode())
                print("")
                print("Cherry-pick failed: please fix the issue manually and run script again.")
                return

    if os.path.exists(".backport-resume"):
        os.unlink(".backport-resume")

    print("")
    print("Done cherry-picking")
    print("Backporting language changes")
    res = do_command(["python3", ".github/backport-languages.py"])
    if res.returncode != 0:
        print("ERROR: backporting language changes failed")
        return
    do_command(["git", "add", "src/lang/*.txt"])
    do_command(["git", "commit", "-m", "Update: Backport language changes"])
    print("Done backporting language changes")
    print("")

    print("Your commit message:")
    print("")

    marker = []

    print("## Description")
    print(f"Backport of all closed Pull Requests labeled as 'backport requested' into `release/{RELEASE}`.")
    for pr in sorted(all_prs["data"]["search"]["edges"], key=lambda x: x["node"]["mergedAt"]):
        print(f"- https://github.com/OpenTTD/OpenTTD/pull/{pr['node']['number']}")
        marker.append(str(pr["node"]["number"]))
    print("- All language changes")
    print(f"<!-- Backported: {','.join(marker)} -->")

    print("")

    if dont_push:
        print("Done with backport; you can now push this branch to remote:")
        print(" git push -f --set-upstream origin release-backport")
        print("After that, go to this URL:")
    else:
        res = do_command(["git", "push", "-f", "--set-upstream", "origin", "release-backport"])
        if res.returncode != 0:
            print("ERROR: failed to push to remote")
        else:
            print("Pushed to remote")
            print("You can create the PR here:")

    print(
        f"https://github.com/OpenTTD/OpenTTD/compare/release/{RELEASE}...{USERNAME}"
        f":release-backport?expand=1&title=Backport%20master%20into%20release%2f{RELEASE}"
    )


if __name__ == "__main__":
    main()
