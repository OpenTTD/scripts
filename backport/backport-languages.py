"""
Put this file in a master checkout under .github/.
It should be next to backport.py.
"""

import argparse
import glob
import subprocess
import shlex


def backport_language(language_file, blacklisted_ids, diff_to_stdout=False):
    result = subprocess.run(
        shlex.split("git diff HEAD..upstream/master -- %s" % language_file), check=True, stdout=subprocess.PIPE
    )

    input_lines = []
    chunk = []
    # We start with this set to True, to pick up any headers before the
    # patch really begins
    chunk_has_modification = True

    # Decode the result, skip the 4 line header
    for line in result.stdout.decode().split("\n"):
        if not line or line.startswith("@@") or line.startswith(("---", "+++")):
            # Only add the chunk if there was a modification to it.
            # 'git apply' cannot handle chunks with no modifications.
            if chunk_has_modification:
                input_lines.extend(chunk)
            chunk = []
            chunk_has_modification = False

            # Check for the start of a new chunk
            if line.startswith("@@"):
                chunk.append(line)
            else:
                input_lines.append(line)
            continue

        # Passthrough all the unmodified lines (they are just context)
        if not line.startswith(("-", "+")):
            chunk.append(line)
            continue

        id = line[1:].split(":")[0]
        if id not in blacklisted_ids:
            # Modification is not blacklisted; this is fine
            chunk_has_modification = True
            chunk.append(line)
            continue

        # A blacklisted id; skip the modification
        if line.startswith("+"):
            pass
        else:
            chunk.append(" " + line[1:])

    # No chunks found, so nothing to do
    if len(input_lines) < 6:
        return

    total_input = "\n".join(input_lines)
    if diff_to_stdout:
        print(total_input)
        return

    result = subprocess.run(shlex.split("git apply --recount"), check=True, input=total_input.encode())


def create_blacklisted_ids():
    # First check what changed in english.txt. Every change is blacklisted and
    # translations in these lines will not be backported
    result = subprocess.run(
        shlex.split("git diff HEAD..upstream/master -- src/lang/english.txt"), check=True, stdout=subprocess.PIPE
    )

    blacklisted_ids = []

    # Walk the diff line by line
    for line in result.stdout.decode().split("\n"):
        # Ignore headers
        if line.startswith(("---", "+++")) or not line:
            continue

        # Find all the lines that are modified
        if line.startswith(("-", "+")):
            # Store that id in a blacklist
            id = line[1:].split(":")[0]
            blacklisted_ids.append(id)

    return blacklisted_ids


def parse_command_line():
    parser = argparse.ArgumentParser(description="Backport languages from master to release branch")
    parser.add_argument(
        "languages", metavar="LANGUAGE", type=str, nargs="*", help="which languages to backport (empty for all)"
    )
    parser.add_argument("--diff", action="store_true", help="only show the diff; do not apply")
    return parser.parse_args()


def main():
    args = parse_command_line()

    blacklisted_ids = create_blacklisted_ids()

    if args.languages:
        language_files = ["src/lang/%s.txt" % language for language in args.languages]
    else:
        language_files = glob.glob("src/lang/*.txt") + glob.glob("src/lang/unfinished/*.txt")

    for language_file in language_files:
        print("Backporting %s ..." % language_file[len("src/lang/") :])
        backport_language(language_file, blacklisted_ids, diff_to_stdout=args.diff)


if __name__ == "__main__":
    main()
