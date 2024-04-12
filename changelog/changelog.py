"""
Put this file in a master checkout under .github/.

This assumes your git "origin" points to your fork, and "upstream" to upstream.
This script will overwrite the branch "changelog".

The GITHUB_TOKEN is a classic token you need to generate that has public_repo
scope enabled. This token is used to fetch information from the GitHub API.

Execute with:

$ export GITHUB_TOKEN=ghp_XXX
$ python3 .github/changelog.py <last-commit-of-previous-release>
"""

import json
import os
import subprocess
import sys

BEARER_TOKEN = os.getenv("GITHUB_TOKEN")

if not BEARER_TOKEN:
    print("Please set the GITHUB_TOKEN environment variable.")
    sys.exit(1)

PRIORITY = {
    "Feature": 1,
    "Add": 2,
    "Change": 3,
    "Fix": 4,
    "Remove": 5,
}

commit_pr_query = """
query ($hash: String) {
  repository(owner: "OpenTTD", name: "OpenTTD") {
    ref(qualifiedName: "master") {
      target {
        ... on Commit {
          history(first: 100, after: $hash) {
            pageInfo{
              endCursor
            }
            edges {
              node {
                oid
                associatedPullRequests(first: 1) {
                  edges {
                    node {
                      number
                      labels(first: 10) {
                        edges {
                          node {
                            name
                          }
                        }
                      }
                      closingIssuesReferences(first: 10) {
                        edges {
                          node {
                            number
                          }
                        }
                      }
                    }
                  }
                }
              }
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


def do_command(command):
    return subprocess.run(command, capture_output=True)


def main():
    last_commit = sys.argv[1]

    do_command(["git", "fetch", "upstream"])
    do_command(["git", "checkout", "upstream/master", "-B", "changelog"])

    commit_list = do_command(["git", "log", "--pretty=format:%ce|%H|%s", f"{last_commit}..HEAD"])
    commits = commit_list.stdout.decode().splitlines()

    commit_to_pr = {}
    backported = set()
    commits_seen = set()
    issues = {}

    cache_filename = f".changelog-cache-{last_commit}.{len(commits)}"

    if os.path.exists(cache_filename):
        with open(cache_filename, "r") as f:
            data = json.loads(f.read())
            commit_to_pr = data["commit_to_pr"]
            backported = set(data["backported"])
            commits_seen = set(data["commits_seen"])
            issues = data["issues"]
    else:
        print("Fetching commits and their associated PRs ... this might take a while ...")

        count = len(commits)
        variables = {}
        while count > 0:
            print(f"{count} commits left ...")

            res = do_query(commit_pr_query, variables)
            variables["hash"] = res["data"]["repository"]["ref"]["target"]["history"]["pageInfo"]["endCursor"]

            # Walk all commits.
            for edge in res["data"]["repository"]["ref"]["target"]["history"]["edges"]:
                count -= 1
                if count == 0:
                    break
                if not edge["node"]["associatedPullRequests"]["edges"]:
                    continue

                pr = edge["node"]["associatedPullRequests"]["edges"][0]["node"]

                # Links the commit to a PR.
                commit_to_pr[edge["node"]["oid"]] = pr["number"]
                # Link the hashes between 6 and 10 in size to the list of "seen commits".
                for i in range(6, 10):
                    commits_seen.add(edge["node"]["oid"][0:i])

                # Check if this PR was backported.
                for label in pr["labels"]["edges"]:
                    if label["node"]["name"] == "backported":
                        backported.add(pr["number"])

                # Track which issues were closed because of this PR.
                if pr["closingIssuesReferences"]["edges"]:
                    issues[pr["number"]] = []
                    for issue in pr["closingIssuesReferences"]["edges"]:
                        issues[pr["number"]].append(issue["node"]["number"])

        with open(cache_filename, "w") as f:
            f.write(
                json.dumps(
                    {
                        "commit_to_pr": commit_to_pr,
                        "backported": list(backported),
                        "commits_seen": list(commits_seen),
                        "issues": issues,
                    }
                )
            )

    messages = []

    for commit in commit_list.stdout.decode().splitlines():
        (email, hash, message) = commit.split("|", 2)

        if email in ("translators@openttd.org",):
            continue

        # Ignore all commit messages that don't change functionality.
        if message.startswith(("Codechange", "Codefix", "Doc", "Update", "Upgrade", "Cleanup", "Prepare", "Revert")):
            continue
        # Ignore everything related to the CI.
        if "[CI]" in message or "[Dependabot]" in message or "[DorpsGek]" in message:
            continue

        pr = commit_to_pr.get(hash)
        if pr is None:
            pr = -1

        # Skip everything already backported.
        if pr in backported:
            continue

        # Remove the PR number from the commit message.
        if message.endswith(f"(#{pr})"):
            message = message[: -len(f"(#{pr})")]

        commit_type, commit_message = message.strip().split(":", 1)
        subject = None

        # Remove trailing dots.
        commit_message = commit_message.strip().rstrip(".")
        commit_message = commit_message[0].upper() + commit_message[1:]
        # If the string starts with [, capitalize the first letter after the ].
        if commit_message.startswith("["):
            part1, part2 = commit_message.split("]", 1)
            part2 = part2.strip()
            commit_message = part1 + "] " + part2[0].upper() + part2[1:]

        if " " in commit_type:
            commit_type, subject = commit_type.split(" ", 1)

            if commit_type != "Fix":
                # Remove subject if not a fix.
                subject = None
            else:
                reference = False
                ticket = None

                # Check all parts of the subject for either a ticket or hash.
                for sub in subject.split(","):
                    sub = sub.strip()

                    # If we reference a ticket, that will be the subject.
                    if sub.startswith("#"):
                        ticket = sub
                        continue

                    # If the hash is in our set of commits, it is a fix for
                    # something unreleased; so don't mention it.
                    if sub in commits_seen:
                        reference = True
                        break

                if reference:
                    continue
                subject = ticket

        if commit_type == "Fix" and issues.get(str(pr)):
            issue_list = issues[str(pr)]

            # Check if any of the linked issues are mentioned in the commit.
            for issue in issue_list:
                if subject and f"#{issue}" in subject:
                    break
            else:
                # The linked issue is not mentioned. Create the link.
                issue = ", ".join([f"#{issue}" for issue in issue_list])

                if subject and subject != issue:
                    print(
                        f"WARNING: commit {hash} has a different references than the PR {pr}: '{subject}' vs '{issue}'"
                    )
                subject = issue

        message = commit_type
        if subject:
            message += f" {subject}"
        message += f": {commit_message}"
        if pr != -1:
            message += f" (#{pr})"

        messages.append((PRIORITY[commit_type], int(pr), message))

    for message in sorted(messages, key=lambda x: (x[0], -x[1])):
        print(message[2])


if __name__ == "__main__":
    main()
