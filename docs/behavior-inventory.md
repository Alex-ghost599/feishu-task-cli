# Public behavior inventory

This inventory records abstract interoperability and safety behaviors derived only from public
Feishu documentation. It does not describe implementation lineage, private fixtures, internal
configuration, or repository comparisons.

| Public source | Abstract behavior covered by tests |
| --- | --- |
| [Task v2 overview](https://open.feishu.cn/document/task-v2/overview) | Task identifiers and Task/Tasklist mutation boundaries |
| [Create a Task](https://open.feishu.cn/document/task-v2/task/create) | Explicit Tasklist target, requested fields, returned identifier, then readback |
| [Get a Task](https://open.feishu.cn/document/task-v2/task/get) | Normalize an observed Task for preconditions and reconciliation |
| [Update a Task](https://open.feishu.cn/document/task-v2/task/patch) | Update/complete fields are planned before one guarded mutation |
| [Web app user authorization](https://open.feishu.cn/document/common-capabilities/sso/web-application-end-user-consent/guide) | Explicit browser authorization setup and callback validation |
| [Obtain an OAuth code](https://open.feishu.cn/document/authentication-management/access-token/obtain-oauth-code) | Pre-register the complete redirect URI and reuse it for authorization |
| [Authorization error 20029](https://open.feishu.cn/document/faq/trouble-shooting/how-to-resolve-the-authorization-page-20029-error) | Redirect allowlist matching includes the complete path |
| [Refresh user access token](https://open.feishu.cn/document/authentication-management/access-token/refresh-user-access-token?lang=en-US) | Refreshable user token lifecycle without exposing token material |

The project adds local safety behaviors around those public interfaces: immutable hashed
artifacts, declared Agent review, AuthContext binding, typed assignee identifiers, one-host replay
protection, no blind mutation retry, readback reconciliation, redaction, stable JSON, and safe
Markdown handoff. These are tested with synthetic responses. The inventory is not evidence of
live-tenant validation or a claim that Feishu provides distributed idempotency for these writes.
