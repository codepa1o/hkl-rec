# Guardian Content API structured-body extension

## Official contract

- Base URL: `https://content.guardianapis.com/`
- Authentication: `api-key` query parameter from `NEWSREC_GUARDIAN_API_KEY`
- Mode: synchronous single-item GET
- Documentation: `https://open-platform.theguardian.com/documentation/item`

The integration requests `show-fields=body,headline,standfirst,thumbnail,byline`,
`show-blocks=all`, `show-elements=image`, and `show-rights=all`. The returned
`webUrl` must match the configured Guardian domain before content is accepted.

## Resources and safety

- A Guardian API key is required and is never logged or persisted.
- Developer access is suitable for this non-commercial research project, but
  image display/cache permission remains an independent source-policy decision.
- Requests use the existing `SafeFetcher`: HTTPS only, public IP validation,
  redirect revalidation, response-size limits, timeouts, and JSON content type.

## Real verification

`tests/test_guardian_content_api_real.py` performs one bounded, credential-aware
request for the Lloyd's building article. It is skipped when the key is absent and
contains no mock transport.
