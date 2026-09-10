@echo off
rem Rehearsal mode: opens the panel with dry_run enabled.
rem In this mode the app screenshots and recognizes, but NEVER clicks
rem and NEVER closes the ZCode client.
call "%~dp0run.bat" --dry-run %*
