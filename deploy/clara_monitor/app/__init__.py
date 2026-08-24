"""The operational web application: the five tabs of section 3.

`ops` is the domain — Actions, Requests, the Agent, audit and provenance. This
package is what a person actually touches, and section 3 fixes its shape:

    Overview     freshness, coverage, unresolved work, movement, attention
    Products     the Clara catalogue and what each product faces
    Competitors  the directory, their products, sources and offers
    Actions      the work queue, resolved inline
    Requests     questions raised for a person, and their answers

Everything else named in 3.1 lives around those five rather than beside them: the
Agent is a header control opening a right-side panel, Send Request is a global and
contextual action, and Users, Request administration, Sources/Feeds and Audit
History sit in an Admin menu. The old Decisions tab is gone and the beauty Trends
experience is a separate optional module.

`router.handle` is the single entry point. `serve.py` and the serverless handler
are thin adapters over it, so the local site and the hosted one cannot drift into
two different applications.
"""

from .router import Request, Response, handle

__all__ = ["Request", "Response", "handle"]
