"""Login and user-management pages.

Built on the same tokens and type as `site.py`, so signing in does not look like a
different application. Messages are written for the person reading them: what
happened and what to do, not an error code.
"""

from __future__ import annotations

import html

from .site import CSS

SHELL_CSS = """
.authwrap{min-height:100dvh;display:flex;align-items:center;justify-content:center;
          padding:28px}
.authbox{width:100%;max-width:420px;background:var(--card);border:1px solid var(--line);
         border-radius:8px;box-shadow:var(--shadow);padding:30px 28px}
.authbox h1{font-size:26px;margin-bottom:6px}
.authbox .sub{color:var(--ink2);font-size:13.5px;margin-bottom:22px;line-height:1.6}
.field{display:flex;flex-direction:column;gap:6px;margin-bottom:15px}
.field label{font-size:13px;color:var(--ink2);font-weight:600}
.field input,.field select{font-family:inherit;font-size:14.5px;padding:10px 12px;
  background:var(--bg);color:var(--ink);border:1px solid var(--line2);border-radius:5px}
.btn{width:100%;font-family:inherit;font-size:15px;font-weight:700;padding:11px 14px;
     background:var(--clara);color:#fff;border:0;border-radius:5px;cursor:pointer}
.btn:hover{filter:brightness(1.08)}
.btn.sec{background:var(--card2);color:var(--ink);border:1px solid var(--line2);
         font-weight:600;width:auto;padding:7px 13px;font-size:13px}
.msg{border-radius:5px;padding:11px 13px;font-size:13.5px;margin-bottom:18px;
     line-height:1.6}
.msg.err{background:var(--bad-wash);color:var(--bad)}
.msg.ok{background:var(--ok-wash);color:var(--ok)}
.authfoot{margin-top:20px;font-size:12px;color:var(--ink3);text-align:center}

.topbar{background:var(--card);border-bottom:1px solid var(--line);padding:11px 0}
.topbar .wrap{display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.topbar .who{font-size:13px;color:var(--ink2)}
.topbar .who b{color:var(--ink)}
.topbar .sp{margin-inline-start:auto;display:flex;gap:8px;align-items:center}
.topbar a{font-size:13px;color:var(--ink2);text-decoration:none;padding:6px 11px;
          border:1px solid var(--line2);border-radius:5px;font-weight:600}
.topbar a:hover{color:var(--clara);border-color:var(--clara)}
.adminwrap{max-width:1080px;margin:0 auto;padding:30px 22px 60px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:7px;
       box-shadow:var(--shadow);padding:22px 24px;margin-bottom:20px}
.panel h2{font-size:20px;margin-bottom:5px}
.panel .ph{color:var(--ink2);font-size:13.5px;margin-bottom:18px}
.frow{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;
      align-items:end}
.utable{width:100%;border-collapse:collapse;font-size:13.5px}
.utable th{text-align:left;font-size:12px;color:var(--ink3);font-weight:600;
           padding:10px 12px;background:var(--card2);border-bottom:1px solid var(--line2)}
.utable td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:middle}
.utable tbody tr:last-child td{border-bottom:0}
.utable form{display:inline}
.rolepill{font-size:11px;padding:2px 8px;border-radius:3px;font-weight:600}
.r-admin{background:var(--clara-wash);color:var(--clara)}
.r-viewer{background:var(--card3);color:var(--ink2)}
.st-on{color:var(--ok);font-weight:600;font-size:12.5px}
.st-off{color:var(--ink4);font-size:12.5px}
.actions-cell{display:flex;gap:6px;flex-wrap:wrap}
.pwbox{background:var(--ok-wash);border:1px solid var(--ok);border-radius:6px;
       padding:14px 16px;margin-bottom:18px}
.pwbox .lbl{font-size:12.5px;color:var(--ok);font-weight:700;margin-bottom:7px}
.pwbox code{font-family:var(--mono);font-size:16px;background:var(--card);
            padding:6px 11px;border-radius:4px;display:inline-block;
            border:1px solid var(--line2)}
.pwbox .hint{font-size:12px;color:var(--ink2);margin-top:9px;line-height:1.6}
"""


def _head(title: str) -> str:
    return (f'<title>{html.escape(title)}</title>'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<style>{CSS}{SHELL_CSS}</style>')


def login_page(error: str = "", notice: str = "", next_url: str = "/") -> str:
    P = [_head("Sign in — Clara Report")]
    P.append('<div class="authwrap"><div class="authbox">')
    P.append('<h1>Clara Report</h1>')
    P.append('<p class="sub">' + html.escape(
        "Clara prices against the competition. "
        "For the authorised team only.") + '</p>')
    if error:
        P.append(f'<div class="msg err">{html.escape(error)}</div>')
    if notice:
        P.append(f'<div class="msg ok">{html.escape(notice)}</div>')
    P.append('<form method="post" action="/login">')
    P.append(f'<input type="hidden" name="next" value="{html.escape(next_url)}">')
    P.append('<div class="field"><label for="u">'
             + html.escape("Username") + '</label>'
             '<input id="u" name="username" autocomplete="username" required '
             'autofocus></div>')
    P.append('<div class="field"><label for="p">'
             + html.escape("Password") + '</label>'
             '<input id="p" name="password" type="password" '
             'autocomplete="current-password" required></div>')
    P.append('<button class="btn" type="submit">'
             + html.escape("Sign in") + '</button>')
    P.append('</form>')
    P.append('<p class="authfoot">'
             + html.escape("No account? Ask an admin to add you.")
             + '</p>')
    P.append('</div></div>')
    return "\n".join(P)


def _topbar(user: dict, active: str = "") -> str:
    P = ['<div class="topbar"><div class="wrap">']
    P.append(f'<span class="who">Signed in as <b>{html.escape(user["display_name"])}</b>'
             + (' &middot; admin' if user["is_admin"] else '') + '</span>')
    P.append('<span class="sp">')
    P.append('<a href="/">Report</a>')
    if user["is_admin"]:
        P.append('<a href="/admin">Users</a>')
    P.append('<form method="post" action="/logout" style="display:inline">'
             '<button class="btn sec" type="submit">Sign out</button></form>')
    P.append('</span></div></div>')
    return "\n".join(P)


def admin_page(user: dict, users: list[dict], error: str = "", notice: str = "",
               new_password: tuple[str, str] | None = None,
               read_only: str = "") -> str:
    """Render the Users page.

    `read_only` carries the reason writes are impossible in this deployment (the
    hosted snapshot has no shared, durable store). When set, the add form and the
    per-row buttons are replaced by that reason. Rendering controls that would
    silently discard the change would be worse than not offering them.
    """
    P = [_head("Users — Clara Report")]
    P.append(_topbar(user, "admin"))
    P.append('<div class="adminwrap">')

    if new_password:
        who, pw = new_password
        P.append('<div class="pwbox">')
        P.append(f'<div class="lbl">Password for {html.escape(who)}</div>')
        P.append(f'<code>{html.escape(pw)}</code>')
        P.append('<div class="hint">Copy it now and send it to the user over a secure '
                 'channel. It will not be shown again and is not stored in readable '
                 'form — if it is lost, reset it from the table below.</div>')
        P.append('</div>')
    if error:
        P.append(f'<div class="msg err">{html.escape(error)}</div>')
    if notice:
        P.append(f'<div class="msg ok">{html.escape(notice)}</div>')

    # --- add user ---
    P.append('<div class="panel">')
    P.append('<h2>Add a user</h2>')
    if read_only:
        P.append(f'<p class="ph">{html.escape(read_only)}</p>')
        P.append('</div>')
    else:
        P.append('<p class="ph">Leave the password blank and the system will generate a '
                 'strong one and show it to you once.</p>')
        P.append('<form method="post" action="/admin/add"><div class="frow">')
        P.append('<div class="field"><label for="nu">Username</label>'
                 '<input id="nu" name="username" required placeholder="sara.a"></div>')
        P.append('<div class="field"><label for="nd">Display name</label>'
                 '<input id="nd" name="display_name" placeholder="Sara Ahmed"></div>')
        P.append('<div class="field"><label for="np">Password (optional)</label>'
                 '<input id="np" name="password" type="password" '
                 'placeholder="8 characters minimum"></div>')
        P.append('<div class="field"><label for="nr">Role</label>'
                 '<select id="nr" name="role">'
                 '<option value="viewer">Viewer</option>'
                 '<option value="admin">Admin</option></select></div>')
        P.append('<div class="field"><label>&nbsp;</label>'
                 '<button class="btn" type="submit">Add</button></div>')
        P.append('</div></form></div>')

    # --- users table ---
    P.append('<div class="panel">')
    P.append(f'<h2>Users ({len(users)})</h2>')
    P.append('<p class="ph">' + (html.escape(read_only) if read_only else
             'Disabling an account ends its sessions immediately. The last '
             'remaining admin cannot be disabled or deleted.') + '</p>')
    P.append('<div class="scroller"><table class="utable"><thead><tr>'
             '<th>Username</th><th>Name</th><th>Role</th><th>Status</th>'
             '<th>Last sign-in</th><th>'
             + ('Management' if read_only else 'Actions')
             + '</th></tr></thead><tbody>')
    for u in users:
        me = u["username"] == user["username"]
        P.append('<tr>')
        P.append(f'<td><b>{html.escape(u["username"])}</b>'
                 + (' <span class="rolepill r-viewer">you</span>' if me else '')
                 + '</td>')
        P.append(f'<td>{html.escape(u["display_name"] or "")}</td>')
        role = u["role"]
        P.append(f'<td><span class="rolepill r-{html.escape(role)}">'
                 + ("Admin" if role == "admin" else "Viewer") + '</span></td>')
        P.append('<td>' + ('<span class="st-on">active</span>' if u["is_active"]
                           else '<span class="st-off">disabled</span>') + '</td>')
        last = (u.get("last_login_at") or "")[:16].replace("T", " ")
        P.append('<td>' + (html.escape(last) if last
                           else '<span class="np">never</span>') + '</td>')

        if read_only:
            P.append('<td><span class="st-off">managed locally</span></td></tr>')
            continue

        P.append('<td><div class="actions-cell">')

        def form(action: str, label: str, extra: str = "") -> str:
            return (f'<form method="post" action="{action}">'
                    f'<input type="hidden" name="username" value="{html.escape(u["username"])}">'
                    f'{extra}<button class="btn sec" type="submit">{label}</button></form>')

        if u["is_active"]:
            P.append(form("/admin/disable", "Disable"))
        else:
            P.append(form("/admin/enable", "Enable"))
        if role == "admin":
            P.append(form("/admin/role", "Make viewer",
                          '<input type="hidden" name="role" value="viewer">'))
        else:
            P.append(form("/admin/role", "Make admin",
                          '<input type="hidden" name="role" value="admin">'))
        P.append(form("/admin/reset", "New password"))
        if not me:
            P.append(form("/admin/delete", "Delete"))
        P.append('</div></td></tr>')
    P.append('</tbody></table></div></div>')

    P.append('</div>')
    return "\n".join(P)
