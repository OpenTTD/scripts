# Scripts

A random collection of scripts we use from time to time to manage OpenTTD.

## Backport

The [backport](backport/) folder contains two scripts to handle backports:

- [backport-languages.py](backport/backport-languages.py) backports all languages from the `master` branch into the requested `release` branch.
  It only backports those entries that are unmodified in `english.txt`.
- [backport.py](backport/backport.py) backports Pull Requests marked with `backport requested` into a release branch, and creates a single Pull Request out of that.
  After the Pull Request is merged, it can mark the `backport requested` Pull Requests as `backported`, as the backport Pull Request contains information about what Pull Requests were backported.

In both cases, see the header of the file what to change to make it work for your case.

NOTE: they are both NOT meant to be run from this repository, but you have to copy it into the [OpenTTD](https://github.com/OpenTTD/OpenTTD) repository first.
