"""What `gh` prints when GitHub refuses a call under a rate limit. The GraphQL text is the one
recorded on 19.11.2026; the REST and secondary texts follow GitHub's documentation and are not
recorded."""

GRAPHQL_REFUSAL = (
    '{"errors":[{"type":"RATE_LIMIT","code":"graphql_rate_limit",'
    '"message":"API rate limit already exceeded for user ID 1."}]}'
    "gh: API rate limit already exceeded for user ID 1."
)
REST_REFUSAL = (
    '{"message":"API rate limit exceeded for user ID 1.","documentation_url":"https://docs.github.com"}'
    "gh: API rate limit exceeded for user ID 1. If you reach out to GitHub Support for help, "
    "please include the request ID 8A1B:2C3D and timestamp 2026-11-19 20:00:00 UTC. (HTTP 403)"
)
SECONDARY_REFUSAL = (
    "gh: You have exceeded a secondary rate limit. Please wait a few minutes before "
    "you try again. If you reach out to GitHub Support for help, please include "
    "the request ID 8A1B:2C3D. (HTTP 403)"
)
