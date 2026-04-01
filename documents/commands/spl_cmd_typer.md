---
 command: typer
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/typer
 title: typer
 download_date: 2026-02-03 09:20:34
---

 # typer

Creates an eventtype field for search results that match known event types. You must create event types to use this command. See About event types in the Knowledge Manager Manual.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The typer command is a distributable streaming command. See Command types.

#### Changing the default for maxlen

Users with file system access, such as system administrators, can change the default setting for maxlen.

- Open or create a local limits.conf file for the Search app at $SPLUNK_HOME/etc/apps/search/local.
- Under the [typer] stanza, specify the default for the maxlen setting.

#### Example 1:

Returns a field called eventtype which lists the names of the event types associated with the search results.
 