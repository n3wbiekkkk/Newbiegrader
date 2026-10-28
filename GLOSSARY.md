# Newbiegrader

Domain language for submissions, judging attempts, feedback and account deletion. The
maintained rules are defined in [Submission feedback policy](docs/submission-feedback-policy.md)
and [Account data](docs/ACCOUNT_DATA.md), with queue behavior in
[Load handling](docs/load-handling.md) and catalog behavior in
[Problem loading](docs/problem-loading.md).

## Language

**Submission disclosure**:
The permitted extent of storing submission feedback or showing submission
information to a particular audience. Stored feedback and currently visible
information are distinct.

**Stored feedback**:
The judging feedback retained with a completed submission. Retaining a field does
not itself grant any audience permission to receive it later.

**Current disclosure**:
The submission information an audience may receive under the rules in effect
when it is requested, which can be narrower than the stored feedback.

**Account deletion**:
The recoverable erasure of an account's sign-in identity and owned data after
access has been revoked. A pending deletion is not completed erasure.

**Judge job**:
An admitted unit of submission, trial-run or rejudge work, tracked until it
completes or fails.

**Judging attempt**:
One worker's ownership of a judge job. A later attempt does not grant an earlier
worker permission to complete that job.

**Problem catalog**:
The observed collection of problem metadata, permanent IDs, catalog numbers and
versions. Inclusion in the catalog does not grant access under current publication
or contest rules.
