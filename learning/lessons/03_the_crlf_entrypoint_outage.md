# 03 — The CRLF Entrypoint Outage

> Source: `Frontend/nidhi-brand-forge/Dockerfile`, `.gitattributes` (root,
> storefront and admin panel), `docker-entrypoint.d/40-runtime-config.sh`
> Happened: 2026-10-02 · the site was down for about 90 seconds

---

## The symptom

A new storefront image was deployed. The container started, exited at once with
**code 127**, was restarted by Docker, exited again, and so on. The shop was
unreachable until a working image was running again.

Exit code 127 means "command not found".

---

## The root cause: one invisible character per line

Text files end each line with an invisible marker.

| System | Line ending | Characters |
|---|---|---|
| Linux, macOS | LF | `\n` |
| Windows | CRLF | `\r\n` |

The images are built on a Windows machine. The start-up script,
`40-runtime-config.sh`, had been saved with Windows endings. Its first line is:

```sh
#!/bin/sh
```

That line tells Linux which program runs the script. With a Windows ending the
kernel reads the program's name as `/bin/sh\r`: the letters, plus a carriage
return. No such program exists. So: "not found", exit 127.

Nothing about this is visible in an editor. The file looks perfect.

### Why it restarted forever

The base image (`nginx:alpine`) runs every script in `/docker-entrypoint.d/`
before starting nginx. A failing script stops the start. The container's
restart policy then starts it again, and it fails the same way.

### Why git made it more likely

Git on Windows usually has `core.autocrlf=true`. That setting converts LF to
CRLF when it writes files to your disk and back to LF when you commit. So the
file in the repository can be correct while the file on disk, the one Docker
copies into the image, is not.

---

## The fix: two guards and a check

**Guard 1 — tell git these files are always LF.** `.gitattributes`:

```gitattributes
*.sh text eol=lf
nginx.conf text eol=lf
Dockerfile text eol=lf
```

`eol=lf` overrides `autocrlf` for those files. They are LF on disk on every
machine.

**Guard 2 — strip the character while building.** In the Dockerfile:

```dockerfile
RUN sed -i 's/\r$//' /docker-entrypoint.d/40-runtime-config.sh \
    && chmod +x /docker-entrypoint.d/40-runtime-config.sh
```

`sed` removes a carriage return at the end of every line. Even if Guard 1 is
removed one day, the image is still correct.

**The check — try the image before switching.** Start the new image in a
throwaway container and confirm it stays `running`. Only then replace the live
one. The images that were live before a deploy are also kept on the server
under a `rollback-` tag, so going back is one command.

Two guards may look like one too many. They protect against different mistakes:
Guard 1 against a wrong checkout, Guard 2 against a file that arrives some other
way (a zip, an editor setting). Each is one line.

---

## The general lesson

> **A deploy step that can fail should be tried somewhere harmless first.**

The build succeeded. The push succeeded. The image was broken, and the first
place that found out was production. A 10-second trial run of the container
would have caught it.

Three more ideas this incident teaches:

1. **"It works on my machine" is often about the machine.** The same file is
   different bytes on Windows and Linux.
2. **Keep the last good version ready.** Rolling back should be one command,
   which it is when the old image is still on the server under its own tag.
3. **Fix the cause in more than one layer when each layer is cheap.** This is
   called defence in depth.

---

## Interview questions

1. *A container exits with code 127 right after starting. What do you check?*
   → "Command not found." Look at the entrypoint and the first line of any
   script it runs. Check for Windows line endings and for a missing program.

2. *What does `core.autocrlf` do, and how do you override it for some files?*
   → It converts line endings on checkout and commit. A `.gitattributes` rule
   such as `*.sh text eol=lf` forces LF for matching files.

3. *How do you make a deploy safer without a second server?*
   → Run the new image in a throwaway container first. Keep the old image
   tagged for rollback. Back up the database before running migrations.

4. *The build passed and the image is broken. What does that tell you about
   your pipeline?*
   → Building proves the files were assembled. It does not prove the container
   starts. Add a smoke test: start it and call its health endpoint.

5. *Tell me about a production incident you caused.*
   → Use this one. Say what broke, how long, how it was restored, the cause,
   and the three changes made afterwards.
