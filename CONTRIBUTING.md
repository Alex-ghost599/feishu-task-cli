# Contributing

All post-bootstrap changes follow this workflow:

1. Open an Issue with acceptance criteria.
2. Branch from current `develop` as `<kind>--<slug>`.
3. Add a failing behavior test before implementation.
4. Push the branch and open a pull request to `develop`.
5. Pass quality, tests, build, secret, privacy, and feature checks.
6. Squash merge. Remote branches are retained unless the repository owner requests deletion.

Bugs use an Issue and `fix--<slug>` branch. Releases use a pull request from `develop` to
`main`, followed by an annotated semantic-version tag on the merged `main` commit.

Every pull request must state that it does not copy private predecessor code, fixtures,
comments, names, error strings, configuration, identifiers, or Git history.
