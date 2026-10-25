"""Actionable fixed messages; never interpolate raw transport diagnostics."""
from security.network_policy import audit_code

_MESSAGES = {
    'domain_not_allowlisted': 'This website has not been approved. Review and approve its exact hostname before collection.',
    'invalid_url': 'Enter a complete HTTPS URL with no spaces or malformed percent encoding.',
    'invalid_scheme_or_host': 'Enter a complete https:// website URL. File and other URL schemes are unsupported.',
    'invalid_hostname': 'Use a public hostname, without IP addresses, wildcards, ports or credentials.',
    'userinfo_forbidden': 'URLs containing usernames or passwords are refused. Use a public URL or obtain an authorized export.',
    'query_urls_unsupported': 'Query URLs can contain credentials or signed access tokens and are unsupported. Use a query-free public page or an authorized export.',
    'nonstandard_port': 'Only standard HTTPS/HTTP ports are supported. Use a public HTTPS page or an authorized export.',
    'ambiguous_path': 'This URL has an ambiguous or unsafe path. Use the canonical public page URL.',
    'prohibited_destination': 'This hostname resolves to a private, local or otherwise prohibited address. Collection is blocked; use an authorized local export.',
    'dns_resolution_failed': 'The hostname could not be resolved. Check the spelling and your connection, then try again.',
    'tls_verification_failed': 'The HTTPS certificate could not be verified. Ask the site owner to fix its certificate or provide an authorized export.',
    'request_timeout': 'The site did not respond within the request limit. Retry later or obtain an authorized export.',
    'transport_failed': 'A secure connection could not be completed. Check connectivity or try an authorized export.',
    'new_origin_requires_approval': 'The site redirected to a different hostname or scheme. Nothing was approved there; start a new workflow for that URL.',
    'authorization_denied': 'The site denied access. Browser login does not authorize this collector; request an authorized export.',
    'access_restriction_detected': 'The page requires login, JavaScript, CAPTCHA or restricted access. Use an authorized export; no workaround will be attempted.',
    'interactive_document_requires_export': 'Interactive document viewers are unsupported. Ask the owner for an authorized CSV, XLSX or document export.',
    'robots_disallow': 'robots.txt disallows this page. Respect that rule and ask the owner for an authorized export.',
    'robots_unavailable': 'robots.txt could not be checked safely. Collection stopped; retry later or obtain an authorized export.',
    'page_robots_restriction': 'The page declares a robots restriction. Collection stopped; request an authorized export.',
    'rate_limited': 'The site requested a pause by rate-limiting access. Collection stopped without aggressive retries.',
    'response_too_large': 'The response exceeds the allowed size. Choose a smaller page or obtain an authorized export.',
    'unexpected_content_type': 'This is not a supported static HTML or public JSON page. Download an authorized document export and import it locally.',
    'insufficient_static_text': 'The response has insufficient static text. JavaScript/browser-session collection is unsupported; request an authorized export.',
    'storage_failed': 'Records could not be saved. Check output permissions, disk space and database locks; existing records remain intact.',
}
_BUDGETS = {'page_limit', 'frontier_limit', 'request_limit', 'duration_limit', 'record_limit', 'total_byte_limit'}


def collection_message(code: str) -> str:
    safe = audit_code(code)
    if safe in _BUDGETS:
        return 'A configured collection budget was reached. Narrow the scope or review the safe limits in Settings.'
    if safe == 'completed':
        return 'Collection complete.'
    if safe == 'cancelled':
        return 'Collection cancelled. Previously committed records remain saved.'
    return _MESSAGES.get(safe, 'The response could not be processed safely. Try a canonical public URL or obtain an authorized export.')
